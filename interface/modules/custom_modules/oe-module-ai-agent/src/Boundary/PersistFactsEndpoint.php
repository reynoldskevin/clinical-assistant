<?php

/**
 * PersistFactsEndpoint — the testable core of persist.php.
 *
 * Given a parsed, clinician-authorized request (pid + document + extraction-run
 * + doc_type + fact + clinician id), dispatch to the right persister
 * (LabFactPersister for lab_pdf, IntakeFactPersister for intake_form) and return
 * a normalized response. An unknown doc_type throws BEFORE any write, so the
 * boundary fails closed. Each persister already supersedes a prior run on
 * re-file, so re-posting the same document is idempotent.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Boundary;

use OpenEMR\Modules\AiAgent\Persistence\IntakeFactPersister;
use OpenEMR\Modules\AiAgent\Persistence\LabFactPersister;
use OpenEMR\Modules\AiAgent\Persistence\MedicationFactPersister;

final class PersistFactsEndpoint
{
    public function __construct(
        private LabFactPersister $lab,
        private IntakeFactPersister $intake,
        private MedicationFactPersister $medication,
    ) {
    }

    /**
     * Dispatch one validated fact envelope to the persister for its doc_type and
     * return a normalized response.
     *
     * @param array<string, mixed> $fact
     *
     * @return array{
     *     ok: bool,
     *     doc_type: string,
     *     filed: list<array{fact_type: string, count: int}>,
     *     superseded: int,
     *     total: int
     * }
     */
    public function handle(
        int $pid,
        int $documentId,
        string $extractionRunId,
        string $docType,
        array $fact,
        int $createdBy,
        ?string $createdByName = null,
    ): array {
        // Reject an unknown doc_type before any write (fail closed).
        if ($docType !== 'lab_pdf' && $docType !== 'intake_form' && $docType !== 'med_list') {
            throw new \DomainException('unsupported doc_type');
        }

        if ($docType === 'lab_pdf') {
            $result = $this->lab->persist($pid, $documentId, $extractionRunId, $createdBy, $fact);
            $filed = [];
            if ($result['filed'] > 0) {
                $filed[] = ['fact_type' => 'lab_result', 'count' => $result['filed']];
            }
            $superseded = $result['superseded'];
        } elseif ($docType === 'med_list') {
            $result = $this->medication->persist($pid, $documentId, $extractionRunId, $createdBy, $fact, $createdByName);
            $filed = $result['filed'] > 0
                ? [['fact_type' => 'medication', 'count' => $result['filed']]]
                : [];
            $superseded = $result['superseded'];
        } else {
            $result = $this->intake->persist($pid, $documentId, $extractionRunId, $createdBy, $fact, $createdByName);
            $filed = [];
            foreach ($result['filed'] as $factType => $count) {
                if ($count > 0) {
                    $filed[] = ['fact_type' => $factType, 'count' => $count];
                }
            }
            $superseded = $result['superseded'];
        }

        $total = 0;
        foreach ($filed as $entry) {
            $total += $entry['count'];
        }

        return [
            'ok' => true,
            'doc_type' => $docType,
            'filed' => $filed,
            'superseded' => $superseded,
            'total' => $total,
        ];
    }
}
