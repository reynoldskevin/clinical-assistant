<?php

/**
 * T36 acceptance tests (LOCKED) — the boundary audit log records the correlation id.
 *
 * For a full trace reconstructable from logs alone, every `log` row the boundary
 * writes must carry the request's correlation id (forwarded from the sidecar as
 * the X-Correlation-ID header, T35). The id is a per-request property of the
 * logger (constructor), included in the `comments` column. DB-backed but
 * self-contained: a disposable throwaway schema with a cloned `log` table via an
 * injected PDO (the T10 pattern).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Audit;

use OpenEMR\Modules\AiAgent\Audit\DatabaseBoundaryAuditLogger;
use OpenEMR\Modules\AiAgent\Auth\ClinicalPrincipal;
use OpenEMR\Modules\AiAgent\Auth\PatientId;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;
use Psr\Clock\ClockInterface;

$src = __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src';
require_once $src . '/Auth/PatientId.php';
require_once $src . '/Auth/ClinicalPrincipal.php';
require_once $src . '/Audit/BoundaryAuditLoggerInterface.php';
require_once $src . '/Audit/DatabaseBoundaryAuditLogger.php';

#[Group('isolated')]
final class BoundaryAuditCorrelationTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_cid_test';

    private \PDO $db;

    private function connect(?string $dbName): \PDO
    {
        $host = getenv('AI_DB_HOST') ?: 'mysql';
        $port = getenv('AI_DB_PORT') ?: '3306';
        $dsn = "mysql:host={$host};port={$port}" . ($dbName ? ";dbname={$dbName}" : '');
        return new \PDO($dsn, getenv('AI_DB_USER') ?: 'root', getenv('AI_DB_PASS') ?: 'root', [
            \PDO::ATTR_ERRMODE => \PDO::ERRMODE_EXCEPTION,
            \PDO::ATTR_DEFAULT_FETCH_MODE => \PDO::FETCH_ASSOC,
        ]);
    }

    private function clock(): ClockInterface
    {
        return new class implements ClockInterface {
            public function now(): \DateTimeImmutable
            {
                return new \DateTimeImmutable('2026-01-01T12:00:00+00:00');
            }
        };
    }

    private function principal(): ClinicalPrincipal
    {
        return new ClinicalPrincipal(7, 'dr_house', new PatientId(42), 'treatment');
    }

    protected function setUp(): void
    {
        $root = $this->connect(null);
        $root->exec('DROP DATABASE IF EXISTS `' . self::TEST . '`');
        $root->exec('CREATE DATABASE `' . self::TEST . '`');
        $root->exec('CREATE TABLE `' . self::TEST . '`.`log` LIKE `' . self::SRC . '`.`log`');
        $this->db = $this->connect(self::TEST);
    }

    protected function tearDown(): void
    {
        $this->connect(null)->exec('DROP DATABASE IF EXISTS `' . self::TEST . '`');
    }

    private function comments(): string
    {
        return (string) $this->db->query('SELECT comments FROM `log`')->fetch()['comments'];
    }

    public function testGrantedRowRecordsTheCorrelationId(): void
    {
        $logger = new DatabaseBoundaryAuditLogger($this->db, $this->clock(), 'cid-abc123');
        $logger->recordGranted($this->principal());

        $comments = $this->comments();
        $this->assertStringContainsString('cid-abc123', $comments);
        $this->assertStringContainsString('treatment', $comments); // existing content preserved
    }

    public function testDeniedRowRecordsTheCorrelationId(): void
    {
        $logger = new DatabaseBoundaryAuditLogger($this->db, $this->clock(), 'cid-deny-9');
        $logger->recordDenied(99, 'invalid or out-of-scope token');

        $comments = $this->comments();
        $this->assertStringContainsString('cid-deny-9', $comments);
        $this->assertStringContainsString('out-of-scope', $comments);
    }

    public function testNoCorrelationIdMeansNoCidMarker(): void
    {
        // Backward compatible: constructed without a correlation id -> no cid= marker.
        $logger = new DatabaseBoundaryAuditLogger($this->db, $this->clock());
        $logger->recordGranted($this->principal());

        $this->assertStringNotContainsString('cid=', $this->comments());
    }
}
