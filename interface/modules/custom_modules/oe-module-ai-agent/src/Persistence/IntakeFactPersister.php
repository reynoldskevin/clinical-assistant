<?php

/**
 * IntakeFactPersister — files a validated IntakeFact's narrative fields into
 * discrete OpenEMR clinical records, tracked via the T53a provenance store and
 * idempotently superseded on re-file.
 *
 * Narrative fields are split by NarrativeFieldSplitter (on `;`/newlines) into
 * line-items, each filed as one record with its text as the drug/title/body:
 *   - current_medications → lists type='medication' (the Medications panel)
 *   - allergies           → lists type='allergy'
 *   - family_history      → lists type='medical_problem'
 *   - chief_concern       → an encounter reason (form_encounter + forms), NOT split
 *   - demographics        → never written (identity is the chart's own)
 *
 * Per fact_type, the prior run is superseded first (provenance rows flipped
 * active=0) and the underlying agent-created records are retired: `lists` rows are
 * DELETED (the native Issues/Medications panels filter on enddate, not activity, so
 * a soft flag would leave a visible duplicate) and a chief-concern encounter is
 * removed (form_encounter + its forms registration).
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
        ?string $createdByName = null,
    ): array {
        $medications = $this->splitter->split($this->field($fact, 'current_medications'));
        $allergies = $this->splitter->split($this->field($fact, 'allergies'));
        $familyHistory = $this->splitter->split($this->field($fact, 'family_history'));
        $chiefConcern = trim($this->field($fact, 'chief_concern'));

        $superseded = 0;

        // Medications are filed to the Medications list (lists type='medication'),
        // which is where OpenEMR's Medications panel reads them — NOT the
        // prescriptions table (that surfaces under Prescriptions).
        $filedMedication = $this->fileList(
            $pid,
            $documentId,
            $extractionRunId,
            $createdBy,
            'medication',
            'medication',
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
            $createdByName,
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
        ?string $createdByName = null,
    ): int {
        $superseded += $this->supersede($pid, $documentId, 'chief_concern');

        if ($concern === '') {
            return 0;
        }

        // Chief concern is filed as an encounter's REASON. A real OpenEMR encounter
        // is a form_encounter row PLUS a `forms` registration (formdir='newpatient',
        // deleted=0) — the encounters history joins them and filters on that. The
        // encounter number is unique; MAX+1 is sufficient here (single-writer flow).
        $author = ($createdByName !== null && $createdByName !== '')
            ? $createdByName
            : (string) $createdBy;
        $encounterNo = (int) ($this->db->query(
            'SELECT COALESCE(MAX(encounter), 0) + 1 AS n FROM form_encounter'
        )->fetch()['n']);

        $enc = $this->db->prepare(
            'INSERT INTO form_encounter (pid, encounter, date, reason, provider_id) '
            . 'VALUES (?, ?, NOW(), ?, ?)'
        );
        $enc->bindValue(1, $pid, \PDO::PARAM_INT);
        $enc->bindValue(2, $encounterNo, \PDO::PARAM_INT);
        $enc->bindValue(3, $this->truncate($concern, self::TITLE_MAX), \PDO::PARAM_STR);
        $enc->bindValue(4, $createdBy, \PDO::PARAM_INT);
        $enc->execute();
        $formEncounterId = (int) $this->db->lastInsertId();

        $form = $this->db->prepare(
            'INSERT INTO forms (date, encounter, form_name, form_id, pid, user, groupname, formdir, deleted) '
            . "VALUES (NOW(), ?, 'New Patient Encounter', ?, ?, ?, 'Default', 'newpatient', 0)"
        );
        $form->bindValue(1, $encounterNo, \PDO::PARAM_INT);
        $form->bindValue(2, $formEncounterId, \PDO::PARAM_INT);
        $form->bindValue(3, $pid, \PDO::PARAM_INT);
        $form->bindValue(4, $author, \PDO::PARAM_STR);
        $form->execute();

        // Provenance target is the encounter NUMBER so supersede can retire both the
        // form_encounter row and its forms registration.
        $this->provenance->record(
            $pid,
            $documentId,
            self::DOC_TYPE,
            $extractionRunId,
            $createdBy,
            new DerivedFactRef('chief_concern', 'form_encounter', $encounterNo, null, $this->truncate($concern, self::TITLE_MAX)),
        );

        return 1;
    }

    /**
     * Supersede the prior run for one fact_type and retire each returned clinical
     * record so it no longer shows in the chart. Returns the number retired.
     */
    private function supersede(int $pid, int $documentId, string $factType): int
    {
        $refs = $this->provenance->supersedePriorRun($pid, $documentId, $factType);
        foreach ($refs as $ref) {
            $this->retirePriorRecord($ref);
        }

        return count($refs);
    }

    /**
     * Retire a superseded, agent-created record. The mechanism differs by table
     * because OpenEMR's native panels filter differently:
     *  - the Prescriptions panel and the pnotes/Messages views honor active/activity,
     *    so a soft flag (=0) hides a superseded row;
     *  - the native Issues panel (interface/patient_file/summary/stats.php) filters on
     *    `enddate`, NOT `activity`, so a soft-flagged `lists` row would still display
     *    as a duplicate — it must be DELETED.
     * A chief-concern encounter (target_table='form_encounter') is retired by
     * deleting BOTH the form_encounter row and its `forms` registration, keyed on the
     * encounter number (the provenance target id). The other tables retire by id.
     * We only ever touch rows the agent itself created (the provenance target),
     * never a clinician's own records; the superseded provenance row preserves history.
     */
    private function retirePriorRecord(DerivedFactRef $ref): void
    {
        if ($ref->targetTable === 'form_encounter') {
            foreach ([
                'DELETE FROM form_encounter WHERE encounter = ?',
                "DELETE FROM forms WHERE encounter = ? AND formdir = 'newpatient'",
            ] as $encSql) {
                $stmt = $this->db->prepare($encSql);
                $stmt->bindValue(1, $ref->targetId, \PDO::PARAM_INT);
                $stmt->execute();
            }
            return;
        }

        $sql = match ($ref->targetTable) {
            'prescriptions' => 'UPDATE prescriptions SET active = 0 WHERE id = ?',
            'lists' => 'DELETE FROM lists WHERE id = ?',
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
