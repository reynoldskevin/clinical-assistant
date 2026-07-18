<?php

/**
 * MedicationFactPersister — files a validated med_list extraction's `medications`
 * narrative into the patient-dashboard Medications panel (`lists` rows with
 * type='medication'), tracked via the T53a provenance store and idempotently
 * superseded on re-file.
 *
 * The `medications` field is a single narrative string; NarrativeFieldSplitter
 * breaks it into line-items (on `;`/newlines, skipping "none"/negations/blank),
 * each filed as one `lists` row with its text as the title — the same store
 * IntakeFactPersister uses for current_medications.
 *
 * Per re-file, the prior run is superseded first (provenance rows flipped
 * active=0) and its agent-created `lists` rows are DELETED — the native
 * Medications/Issues panel filters on enddate, NOT activity, so a soft flag would
 * leave a visible duplicate. Only rows this module itself tracked in
 * `ai_derived_fact` are ever deleted; a clinician-entered medication is never
 * touched.
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

final class MedicationFactPersister
{
    private const DOC_TYPE = 'med_list';

    private const FACT_TYPE = 'medication';

    private const LIST_TYPE = 'medication';

    /** lists.title is varchar(255). */
    private const TITLE_MAX = 255;

    public function __construct(
        private \PDO $db,
        private DerivedFactProvenanceService $provenance,
        private NarrativeFieldSplitter $splitter,
    ) {
    }

    /**
     * @param array<string, mixed> $fact
     * @return array{filed: int, superseded: int}
     */
    public function persist(
        int $pid,
        int $documentId,
        string $extractionRunId,
        int $createdBy,
        array $fact,
        ?string $createdByName = null,
    ): array {
        $medications = $this->splitter->split($this->field($fact, 'medications'));

        // Supersede the prior run FIRST and retire (DELETE) its agent-created rows
        // so the panel never shows a ghost duplicate of the previous extraction.
        $superseded = $this->supersede($pid, $documentId);

        $today = date('Y-m-d');
        $insert = $this->db->prepare(
            'INSERT INTO lists (pid, type, title, activity, date, begdate) '
            . 'VALUES (?, ?, ?, 1, NOW(), ?)'
        );

        $filed = 0;
        foreach ($medications as $line) {
            $title = $this->truncate($line, self::TITLE_MAX);
            $insert->bindValue(1, $pid, \PDO::PARAM_INT);
            $insert->bindValue(2, self::LIST_TYPE, \PDO::PARAM_STR);
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
                new DerivedFactRef(self::FACT_TYPE, 'lists', $targetId, null, $title),
            );
            $filed++;
        }

        return [
            'filed' => $filed,
            'superseded' => $superseded,
        ];
    }

    /**
     * Supersede the prior run for medications and retire each returned clinical
     * record so it no longer shows in the chart. Returns the number retired.
     */
    private function supersede(int $pid, int $documentId): int
    {
        $refs = $this->provenance->supersedePriorRun($pid, $documentId, self::FACT_TYPE);
        foreach ($refs as $ref) {
            $this->retirePriorRecord($ref);
        }

        return count($refs);
    }

    /**
     * Retire a superseded, agent-created medication. The native Medications/Issues
     * panel (interface/patient_file/summary/stats.php) filters on `enddate`, NOT
     * `activity`, so a soft-flagged `lists` row would still display as a duplicate —
     * it must be DELETED. We only ever touch the row the agent itself created (the
     * provenance target), never a clinician's own record; the superseded provenance
     * row preserves history.
     */
    private function retirePriorRecord(DerivedFactRef $ref): void
    {
        if ($ref->targetTable !== 'lists') {
            return;
        }

        $stmt = $this->db->prepare('DELETE FROM lists WHERE id = ?');
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
