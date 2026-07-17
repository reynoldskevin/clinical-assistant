<?php

/**
 * IntakeFactPersister — files a validated IntakeFact's narrative fields into
 * discrete OpenEMR clinical records, tracked via the T53a provenance store and
 * idempotently superseded on re-file.
 *
 * Narrative fields are split by NarrativeFieldSplitter (on `;`/newlines) into
 * line-items, each filed as one record with its text as the drug/title/body:
 *   - current_medications → prescriptions (active)
 *   - allergies           → lists type='allergy'
 *   - family_history      → lists type='medical_problem'
 *   - chief_concern       → one pnotes row (NOT split)
 *   - demographics        → never written (identity is the chart's own)
 *
 * Per fact_type, the prior run is superseded first (provenance rows flipped
 * active=0) and the underlying clinical records are SOFT-deactivated
 * (prescriptions.active=0 / lists.activity=0 / pnotes.activity=0), because the
 * module reads those tables filtered on active/activity=1.
 *
 * Raw prepared-statement SQL on the injected PDO — the OpenEMR service classes
 * need the full app bootstrap, unavailable in the module's isolated harness.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Persistence;

require_once __DIR__ . '/DerivedFactRef.php';
require_once __DIR__ . '/DerivedFactProvenanceService.php';
require_once __DIR__ . '/NarrativeFieldSplitter.php';

final class IntakeFactPersister
{
    private const DOC_TYPE = 'intake_form';

    /** prescriptions.drug is varchar(150). */
    private const DRUG_MAX = 150;

    /** lists.title / pnotes.title are varchar(255). */
    private const TITLE_MAX = 255;

    public function __construct(
        private \PDO $db,
        private DerivedFactProvenanceService $provenance,
        private NarrativeFieldSplitter $splitter,
    ) {
    }

    /**
     * @param array<string, mixed> $fact
     * @return array{filed: array{medication: int, allergy: int, family_history: int, chief_concern: int}, superseded: int}
     */
    public function persist(
        int $pid,
        int $documentId,
        string $extractionRunId,
        int $createdBy,
        array $fact,
    ): array {
        $medications = $this->splitter->split($this->field($fact, 'current_medications'));
        $allergies = $this->splitter->split($this->field($fact, 'allergies'));
        $familyHistory = $this->splitter->split($this->field($fact, 'family_history'));
        $chiefConcern = trim($this->field($fact, 'chief_concern'));

        $superseded = 0;

        $filedMedication = $this->fileMedications(
            $pid,
            $documentId,
            $extractionRunId,
            $createdBy,
            $medications,
            $superseded,
        );
        $filedAllergy = $this->fileList(
            $pid,
            $documentId,
            $extractionRunId,
            $createdBy,
            'allergy',
            'allergy',
            $allergies,
            $superseded,
        );
        $filedFamilyHistory = $this->fileList(
            $pid,
            $documentId,
            $extractionRunId,
            $createdBy,
            'family_history',
            'medical_problem',
            $familyHistory,
            $superseded,
        );
        $filedChiefConcern = $this->fileChiefConcern(
            $pid,
            $documentId,
            $extractionRunId,
            $createdBy,
            $chiefConcern,
            $superseded,
        );

        return [
            'filed' => [
                'medication' => $filedMedication,
                'allergy' => $filedAllergy,
                'family_history' => $filedFamilyHistory,
                'chief_concern' => $filedChiefConcern,
            ],
            'superseded' => $superseded,
        ];
    }

    /**
     * @param list<string> $lines
     */
    private function fileMedications(
        int $pid,
        int $documentId,
        string $extractionRunId,
        int $createdBy,
        array $lines,
        int &$superseded,
    ): int {
        $superseded += $this->supersede($pid, $documentId, 'medication');

        $today = date('Y-m-d');
        $insert = $this->db->prepare(
            'INSERT INTO prescriptions '
            . '(patient_id, drug, active, start_date, date_added, txDate, '
            . 'usage_category_title, request_intent_title, provider_id) '
            . 'VALUES (?, ?, 1, ?, NOW(), ?, ?, ?, ?)'
        );

        $filed = 0;
        foreach ($lines as $line) {
            $drug = $this->truncate($line, self::DRUG_MAX);
            $insert->bindValue(1, $pid, \PDO::PARAM_INT);
            $insert->bindValue(2, $drug, \PDO::PARAM_STR);
            $insert->bindValue(3, $today, \PDO::PARAM_STR);
            $insert->bindValue(4, $today, \PDO::PARAM_STR);
            $insert->bindValue(5, '', \PDO::PARAM_STR);
            $insert->bindValue(6, '', \PDO::PARAM_STR);
            $insert->bindValue(7, $createdBy, \PDO::PARAM_INT);
            $insert->execute();

            $targetId = (int) $this->db->lastInsertId();
            $this->provenance->record(
                $pid,
                $documentId,
                self::DOC_TYPE,
                $extractionRunId,
                $createdBy,
                new DerivedFactRef('medication', 'prescriptions', $targetId, null, $drug),
            );
            $filed++;
        }

        return $filed;
    }

    /**
     * @param list<string> $lines
     */
    private function fileList(
        int $pid,
        int $documentId,
        string $extractionRunId,
        int $createdBy,
        string $factType,
        string $listType,
        array $lines,
        int &$superseded,
    ): int {
        $superseded += $this->supersede($pid, $documentId, $factType);

        $today = date('Y-m-d');
        $insert = $this->db->prepare(
            'INSERT INTO lists (pid, type, title, activity, date, begdate) '
            . 'VALUES (?, ?, ?, 1, NOW(), ?)'
        );

        $filed = 0;
        foreach ($lines as $line) {
            $title = $this->truncate($line, self::TITLE_MAX);
            $insert->bindValue(1, $pid, \PDO::PARAM_INT);
            $insert->bindValue(2, $listType, \PDO::PARAM_STR);
            $insert->bindValue(3, $title, \PDO::PARAM_STR);
            $insert->bindValue(4, $today, \PDO::PARAM_STR);
            $insert->execute();

            $targetId = (int) $this->db->lastInsertId();
            $this->provenance->record(
                $pid,
                $documentId,
                self::DOC_TYPE,
                $extractionRunId,
                $createdBy,
                new DerivedFactRef($factType, 'lists', $targetId, null, $title),
            );
            $filed++;
        }

        return $filed;
    }

    private function fileChiefConcern(
        int $pid,
        int $documentId,
        string $extractionRunId,
        int $createdBy,
        string $concern,
        int &$superseded,
    ): int {
        $superseded += $this->supersede($pid, $documentId, 'chief_concern');

        if ($concern === '') {
            return 0;
        }

        $insert = $this->db->prepare(
            'INSERT INTO pnotes (pid, title, body, activity, date, deleted, user) '
            . 'VALUES (?, ?, ?, 1, NOW(), 0, ?)'
        );
        $insert->bindValue(1, $pid, \PDO::PARAM_INT);
        $insert->bindValue(2, 'AI intake: chief concern', \PDO::PARAM_STR);
        $insert->bindValue(3, $concern, \PDO::PARAM_STR);
        $insert->bindValue(4, (string) $createdBy, \PDO::PARAM_STR);
        $insert->execute();

        $targetId = (int) $this->db->lastInsertId();
        $this->provenance->record(
            $pid,
            $documentId,
            self::DOC_TYPE,
            $extractionRunId,
            $createdBy,
            new DerivedFactRef('chief_concern', 'pnotes', $targetId, null, $this->truncate($concern, self::TITLE_MAX)),
        );

        return 1;
    }

    /**
     * Supersede the prior run for one fact_type and soft-deactivate each returned
     * clinical record. Returns the number of records deactivated.
     */
    private function supersede(int $pid, int $documentId, string $factType): int
    {
        $refs = $this->provenance->supersedePriorRun($pid, $documentId, $factType);
        foreach ($refs as $ref) {
            $this->deactivate($ref);
        }

        return count($refs);
    }

    private function deactivate(DerivedFactRef $ref): void
    {
        $sql = match ($ref->targetTable) {
            'prescriptions' => 'UPDATE prescriptions SET active = 0 WHERE id = ?',
            'lists' => 'UPDATE lists SET activity = 0 WHERE id = ?',
            'pnotes' => 'UPDATE pnotes SET activity = 0 WHERE id = ?',
            default => null,
        };

        if ($sql === null) {
            return;
        }

        $stmt = $this->db->prepare($sql);
        $stmt->bindValue(1, $ref->targetId, \PDO::PARAM_INT);
        $stmt->execute();
    }

    /**
     * @param array<string, mixed> $fact
     */
    private function field(array $fact, string $key): string
    {
        $value = $fact[$key] ?? '';

        return is_string($value) ? $value : '';
    }

    private function truncate(string $value, int $max): string
    {
        if (mb_strlen($value) <= $max) {
            return $value;
        }

        return mb_substr($value, 0, $max);
    }
}
