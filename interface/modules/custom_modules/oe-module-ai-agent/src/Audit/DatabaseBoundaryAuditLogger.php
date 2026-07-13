<?php

/**
 * DatabaseBoundaryAuditLogger — persists boundary access decisions to `log`.
 *
 * Writes one audit row per decision using prepared statements. A granted read
 * records the principal (clinician, patient scope, purpose); a denied attempt
 * records the requested patient id and a generic reason. When present, the
 * request's correlation id (forwarded from the sidecar as X-Correlation-ID) is
 * written to the dedicated `log.correlation_id` column so a trace can be
 * reconstructed by querying that column directly.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Audit;

use OpenEMR\Modules\AiAgent\Auth\ClinicalPrincipal;
use Psr\Clock\ClockInterface;

final class DatabaseBoundaryAuditLogger implements BoundaryAuditLoggerInterface
{
    public function __construct(
        private readonly \PDO $db,
        private readonly ClockInterface $clock,
        private readonly ?string $correlationId = null,
    ) {
    }

    private function bindCorrelationId(\PDOStatement $stmt, int $position): void
    {
        if ($this->correlationId !== null && $this->correlationId !== '') {
            $stmt->bindValue($position, $this->correlationId);
        } else {
            $stmt->bindValue($position, null, \PDO::PARAM_NULL);
        }
    }

    public function recordGranted(ClinicalPrincipal $principal): void
    {
        $stmt = $this->db->prepare(
            'INSERT INTO `log` (date, event, category, user, patient_id, success, comments, correlation_id)'
            . ' VALUES (?, ?, ?, ?, ?, ?, ?, ?)'
        );
        $stmt->bindValue(1, $this->clock->now()->format('Y-m-d H:i:s'));
        $stmt->bindValue(2, 'patient-summary');
        $stmt->bindValue(3, 'ai-agent');
        $stmt->bindValue(4, $principal->clinicianUsername);
        $stmt->bindValue(5, $principal->patientId->value, \PDO::PARAM_INT);
        $stmt->bindValue(6, 1, \PDO::PARAM_INT);
        $stmt->bindValue(7, $principal->purpose);
        $this->bindCorrelationId($stmt, 8);
        $stmt->execute();
    }

    public function recordDenied(int $requestedPid, string $reason): void
    {
        $stmt = $this->db->prepare(
            'INSERT INTO `log` (date, event, category, patient_id, success, comments, correlation_id)'
            . ' VALUES (?, ?, ?, ?, ?, ?, ?)'
        );
        $stmt->bindValue(1, $this->clock->now()->format('Y-m-d H:i:s'));
        $stmt->bindValue(2, 'patient-summary-denied');
        $stmt->bindValue(3, 'ai-agent');
        $stmt->bindValue(4, $requestedPid, \PDO::PARAM_INT);
        $stmt->bindValue(5, 0, \PDO::PARAM_INT);
        $stmt->bindValue(6, $reason);
        $this->bindCorrelationId($stmt, 7);
        $stmt->execute();
    }
}
