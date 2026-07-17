<?php

/**
 * DerivedFactProvenanceService — the T53 provenance store. Every clinical record
 * the persist step files is recorded here against the source document + extraction
 * run it came from, so a re-extracted document can supersede a prior run's derived
 * records rather than duplicating them.
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

final class DerivedFactProvenanceService
{
    public function __construct(private \PDO $db)
    {
    }

    /**
     * Insert one provenance row, minting a fresh 16-byte uuid for the row.
     * Returns the new row id.
     */
    public function record(
        int $pid,
        int $documentId,
        string $docType,
        string $extractionRunId,
        int $createdBy,
        DerivedFactRef $ref,
    ): int {
        $stmt = $this->db->prepare(
            'INSERT INTO ai_derived_fact '
            . '(uuid, pid, source_document_id, extraction_run_id, doc_type, fact_type, '
            . 'target_table, target_id, target_uuid, fact_summary, created_by, created_at, active) '
            . 'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW(), 1)'
        );

        $targetUuidBin = $ref->targetUuid !== null ? hex2bin($ref->targetUuid) : null;

        $stmt->bindValue(1, random_bytes(16), \PDO::PARAM_LOB);
        $stmt->bindValue(2, $pid, \PDO::PARAM_INT);
        $stmt->bindValue(3, $documentId, \PDO::PARAM_INT);
        $stmt->bindValue(4, $extractionRunId, \PDO::PARAM_STR);
        $stmt->bindValue(5, $docType, \PDO::PARAM_STR);
        $stmt->bindValue(6, $ref->factType, \PDO::PARAM_STR);
        $stmt->bindValue(7, $ref->targetTable, \PDO::PARAM_STR);
        $stmt->bindValue(8, $ref->targetId, \PDO::PARAM_INT);
        if ($targetUuidBin === null) {
            $stmt->bindValue(9, null, \PDO::PARAM_NULL);
        } else {
            $stmt->bindValue(9, $targetUuidBin, \PDO::PARAM_LOB);
        }
        $stmt->bindValue(10, $ref->factSummary, \PDO::PARAM_STR);
        $stmt->bindValue(11, $createdBy, \PDO::PARAM_INT);
        $stmt->execute();

        return (int) $this->db->lastInsertId();
    }

    /**
     * Mark all currently-active rows for (pid, documentId, factType) as superseded
     * (active=0, superseded_at=NOW()) and return their target refs so the caller
     * can deactivate the underlying clinical records. Idempotent: a second call
     * returns [] and changes nothing.
     *
     * @return list<DerivedFactRef>
     */
    public function supersedePriorRun(int $pid, int $documentId, string $factType): array
    {
        $select = $this->db->prepare(
            'SELECT fact_type, target_table, target_id, target_uuid, fact_summary '
            . 'FROM ai_derived_fact '
            . 'WHERE pid = ? AND source_document_id = ? AND fact_type = ? AND active = 1'
        );
        $select->bindValue(1, $pid, \PDO::PARAM_INT);
        $select->bindValue(2, $documentId, \PDO::PARAM_INT);
        $select->bindValue(3, $factType, \PDO::PARAM_STR);
        $select->execute();

        $refs = [];
        foreach ($select->fetchAll(\PDO::FETCH_ASSOC) as $row) {
            $refs[] = $this->rowToRef($row);
        }

        if ($refs === []) {
            return [];
        }

        $update = $this->db->prepare(
            'UPDATE ai_derived_fact SET active = 0, superseded_at = NOW() '
            . 'WHERE pid = ? AND source_document_id = ? AND fact_type = ? AND active = 1'
        );
        $update->bindValue(1, $pid, \PDO::PARAM_INT);
        $update->bindValue(2, $documentId, \PDO::PARAM_INT);
        $update->bindValue(3, $factType, \PDO::PARAM_STR);
        $update->execute();

        return $refs;
    }

    /**
     * Active rows for (pid, documentId), for display/audit.
     *
     * @return list<DerivedFactRef>
     */
    public function activeFor(int $pid, int $documentId): array
    {
        $stmt = $this->db->prepare(
            'SELECT fact_type, target_table, target_id, target_uuid, fact_summary '
            . 'FROM ai_derived_fact '
            . 'WHERE pid = ? AND source_document_id = ? AND active = 1'
        );
        $stmt->bindValue(1, $pid, \PDO::PARAM_INT);
        $stmt->bindValue(2, $documentId, \PDO::PARAM_INT);
        $stmt->execute();

        $refs = [];
        foreach ($stmt->fetchAll(\PDO::FETCH_ASSOC) as $row) {
            $refs[] = $this->rowToRef($row);
        }

        return $refs;
    }

    /**
     * @param array<string, mixed> $row
     */
    private function rowToRef(array $row): DerivedFactRef
    {
        $targetUuid = $row['target_uuid'] !== null ? bin2hex((string) $row['target_uuid']) : null;

        return new DerivedFactRef(
            (string) $row['fact_type'],
            (string) $row['target_table'],
            (int) $row['target_id'],
            $targetUuid,
            (string) $row['fact_summary'],
        );
    }
}
