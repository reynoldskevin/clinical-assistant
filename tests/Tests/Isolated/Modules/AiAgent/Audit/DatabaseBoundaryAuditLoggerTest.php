<?php

/**
 * T10 acceptance tests (LOCKED) — DatabaseBoundaryAuditLogger writes real `log` rows.
 *
 * DB-backed but self-contained: a disposable throwaway schema with a cloned `log`
 * table via an injected PDO (the ETL/T09a pattern).
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
final class DatabaseBoundaryAuditLoggerTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_audit_test';

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

    public function testRecordGrantedWritesLogRow(): void
    {
        $logger = new DatabaseBoundaryAuditLogger($this->db, $this->clock());
        $logger->recordGranted(new ClinicalPrincipal(7, 'dr_house', new PatientId(42), 'treatment'));

        $rows = $this->db->query('SELECT patient_id, user, success, comments, event FROM `log`')->fetchAll();
        $this->assertCount(1, $rows);
        $this->assertSame(42, (int) $rows[0]['patient_id']);
        $this->assertSame('dr_house', $rows[0]['user']);
        $this->assertSame(1, (int) $rows[0]['success']);
        $this->assertStringContainsString('treatment', (string) $rows[0]['comments']);
        $this->assertNotSame('', (string) $rows[0]['event']);
    }

    public function testRecordDeniedWritesLogRow(): void
    {
        $logger = new DatabaseBoundaryAuditLogger($this->db, $this->clock());
        $logger->recordDenied(99, 'invalid or out-of-scope token');

        $rows = $this->db->query('SELECT patient_id, success, comments FROM `log`')->fetchAll();
        $this->assertCount(1, $rows);
        $this->assertSame(99, (int) $rows[0]['patient_id']);
        $this->assertSame(0, (int) $rows[0]['success']);
        $this->assertStringContainsString('out-of-scope', (string) $rows[0]['comments']);
    }
}
