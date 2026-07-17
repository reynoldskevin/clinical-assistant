<?php

/**
 * LabFactPersister — files a validated LabFact into OpenEMR's native lab model
 * (procedure_order → procedure_report → procedure_result) as an agent-derived
 * lab result, tracks it via the T53a provenance store, and idempotently
 * supersedes a prior run on re-file by DELETING the agent-created chain it
 * created (the module's lab read is activity-blind, so a soft flag would not
 * hide a re-filed result). Only ever deletes rows the agent itself created and
 * recorded in provenance — never user-entered data.
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

final class LabFactPersister
{
    public function __construct(
        private \PDO $db,
        private DerivedFactProvenanceService $provenance,
    ) {
    }

    /**
     * File one validated LabFact into the chart, superseding any prior run for
     * the same (pid, documentId) lab_result first.
     *
     * @param array<string, string> $fact
     * @return array{fact_type: string, filed: int, superseded: int}
     */
    public function persist(int $pid, int $documentId, string $extractionRunId, int $createdBy, array $fact): array
    {
        // 1. Supersede any prior run's agent-created lab chain for this document.
        $priors = $this->provenance->supersedePriorRun($pid, $documentId, 'lab_result');
        $superseded = 0;
        foreach ($priors as $ref) {
            if ($ref->targetTable !== 'procedure_order') {
                continue;
            }
            $this->deleteOrderChain($ref->targetId);
            $superseded++;
        }

        // 2. Read fact fields defensively.
        $testName = $this->field($fact, 'test_name');
        $value = $this->field($fact, 'value');
        $unit = $this->field($fact, 'unit');
        $referenceRange = $this->field($fact, 'reference_range');
        $collectionDate = $this->field($fact, 'collection_date');
        $abnormalFlag = $this->field($fact, 'abnormal_flag');
        $sourceCitation = $this->field($fact, 'source_citation');
        $loinc = $this->field($fact, 'loinc');

        $dateOrDefault = $collectionDate !== '' ? $collectionDate : date('Y-m-d');

        // 3. Insert the new lab chain.
        $newOrderId = $this->insertOrder($pid, $createdBy, $collectionDate, $dateOrDefault);
        $newReportId = $this->insertReport($newOrderId, $collectionDate, $createdBy);
        $this->insertResult(
            $newReportId,
            $loinc,
            $testName,
            $value,
            $unit,
            $referenceRange,
            self::mapAbnormal($abnormalFlag),
            $sourceCitation,
            $documentId,
            $dateOrDefault,
        );

        // 4. Record provenance against the deletable order id.
        $summary = $this->summary($testName, $value, $unit);
        $this->provenance->record(
            $pid,
            $documentId,
            'lab_pdf',
            $extractionRunId,
            $createdBy,
            new DerivedFactRef('lab_result', 'procedure_order', $newOrderId, null, $summary),
        );

        return [
            'fact_type' => 'lab_result',
            'filed' => 1,
            'superseded' => $superseded,
        ];
    }

    /**
     * Delete an agent-created chain: results → report → order.
     */
    private function deleteOrderChain(int $orderId): void
    {
        $delResults = $this->db->prepare(
            'DELETE FROM procedure_result WHERE procedure_report_id IN '
            . '(SELECT procedure_report_id FROM procedure_report WHERE procedure_order_id = ?)'
        );
        $delResults->bindValue(1, $orderId, \PDO::PARAM_INT);
        $delResults->execute();

        $delReport = $this->db->prepare('DELETE FROM procedure_report WHERE procedure_order_id = ?');
        $delReport->bindValue(1, $orderId, \PDO::PARAM_INT);
        $delReport->execute();

        $delOrder = $this->db->prepare('DELETE FROM procedure_order WHERE procedure_order_id = ?');
        $delOrder->bindValue(1, $orderId, \PDO::PARAM_INT);
        $delOrder->execute();
    }

    private function insertOrder(int $pid, int $createdBy, string $collectionDate, string $dateOrDefault): int
    {
        $stmt = $this->db->prepare(
            'INSERT INTO procedure_order '
            . '(patient_id, provider_id, encounter_id, date_ordered, date_collected, order_status, activity) '
            . 'VALUES (?, ?, 0, ?, ?, ?, 1)'
        );
        $stmt->bindValue(1, $pid, \PDO::PARAM_INT);
        $stmt->bindValue(2, $createdBy, \PDO::PARAM_INT);
        $stmt->bindValue(3, $dateOrDefault, \PDO::PARAM_STR);
        $stmt->bindValue(4, $collectionDate, \PDO::PARAM_STR);
        $stmt->bindValue(5, 'completed', \PDO::PARAM_STR);
        $stmt->execute();

        return (int) $this->db->lastInsertId();
    }

    private function insertReport(int $orderId, string $collectionDate, int $createdBy): int
    {
        $stmt = $this->db->prepare(
            'INSERT INTO procedure_report '
            . '(procedure_order_id, date_collected, date_report, report_status, review_status, source) '
            . 'VALUES (?, ?, ?, ?, ?, ?)'
        );
        $stmt->bindValue(1, $orderId, \PDO::PARAM_INT);
        $stmt->bindValue(2, $collectionDate, \PDO::PARAM_STR);
        $stmt->bindValue(3, $collectionDate, \PDO::PARAM_STR);
        $stmt->bindValue(4, 'final', \PDO::PARAM_STR);
        $stmt->bindValue(5, 'received', \PDO::PARAM_STR);
        $stmt->bindValue(6, $createdBy, \PDO::PARAM_INT);
        $stmt->execute();

        return (int) $this->db->lastInsertId();
    }

    private function insertResult(
        int $reportId,
        string $loinc,
        string $testName,
        string $value,
        string $unit,
        string $referenceRange,
        string $abnormal,
        string $sourceCitation,
        int $documentId,
        string $dateOrDefault,
    ): int {
        $stmt = $this->db->prepare(
            'INSERT INTO procedure_result '
            . '(procedure_report_id, result_data_type, result_code, result_text, result, units, '
            . '`range`, abnormal, comments, document_id, result_status, date) '
            . 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
        );
        $stmt->bindValue(1, $reportId, \PDO::PARAM_INT);
        $stmt->bindValue(2, 'S', \PDO::PARAM_STR);
        $stmt->bindValue(3, $loinc, \PDO::PARAM_STR);
        $stmt->bindValue(4, $testName, \PDO::PARAM_STR);
        $stmt->bindValue(5, $value, \PDO::PARAM_STR);
        $stmt->bindValue(6, $unit, \PDO::PARAM_STR);
        $stmt->bindValue(7, $referenceRange, \PDO::PARAM_STR);
        $stmt->bindValue(8, $abnormal, \PDO::PARAM_STR);
        $stmt->bindValue(9, $sourceCitation, \PDO::PARAM_STR);
        $stmt->bindValue(10, $documentId, \PDO::PARAM_INT);
        $stmt->bindValue(11, 'final', \PDO::PARAM_STR);
        $stmt->bindValue(12, $dateOrDefault, \PDO::PARAM_STR);
        $stmt->execute();

        return (int) $this->db->lastInsertId();
    }

    /**
     * @param array<string, string> $fact
     */
    private function field(array $fact, string $key): string
    {
        return isset($fact[$key]) ? (string) $fact[$key] : '';
    }

    private function summary(string $testName, string $value, string $unit): string
    {
        $label = trim($testName . ' ' . $value . ' ' . $unit);

        return mb_substr($label, 0, 255);
    }

    /**
     * Normalize an extracted abnormal flag to OpenEMR's {no,yes,high,low} enum.
     */
    private static function mapAbnormal(string $flag): string
    {
        return match (strtolower(trim($flag))) {
            'high', 'h' => 'high',
            'low', 'l' => 'low',
            'abnormal', 'a', 'yes', 'positive', 'pos' => 'yes',
            default => 'no',
        };
    }
}
