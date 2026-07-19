<?php

/**
 * T84 acceptance tests (LOCKED) — LabFactPersister files under STRICT SQL mode
 * when the extracted collection date is missing or unparseable.
 *
 * DB-backed and self-contained (mirrors LabFactPersisterTest): clones the
 * procedure_* + ai_derived_fact tables into a throwaway DB, then sets the
 * persister connection's sql_mode to Railway's strict set
 * (STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE...) so the test reproduces
 * production. The VLM commonly returns collection_date: null → the persister
 * sees '' → binding '' into a datetime column is REJECTED by strict mode, so
 * "Accept & file to chart" 500s on Railway while passing on non-strict local
 * MariaDB. These tests pin that a missing/unparseable date files as NULL rather
 * than throwing, and that a valid date is preserved.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Persistence;

use OpenEMR\Modules\AiAgent\Persistence\DerivedFactProvenanceService;
use OpenEMR\Modules\AiAgent\Persistence\LabFactPersister;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Persistence/DerivedFactRef.php';
require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Persistence/DerivedFactProvenanceService.php';
require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Persistence/LabFactPersister.php';

#[Group('isolated')]
final class LabFactPersisterStrictDateTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_lab_strict_test';
    private const TABLES = ['procedure_order', 'procedure_report', 'procedure_result', 'ai_derived_fact'];

    // Exactly the mode Railway MySQL reported (SELECT @@sql_mode).
    private const STRICT_MODE = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,'
        . 'NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

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

    protected function setUp(): void
    {
        $root = $this->connect(null);
        $root->exec('DROP DATABASE IF EXISTS `' . self::TEST . '`');
        $root->exec('CREATE DATABASE `' . self::TEST . '`');
        foreach (self::TABLES as $t) {
            $root->exec("CREATE TABLE `" . self::TEST . "`.`{$t}` LIKE `" . self::SRC . "`.`{$t}`");
        }
        $this->db = $this->connect(self::TEST);
        // Reproduce Railway: strict mode rejects '' in a datetime column.
        $this->db->exec("SET SESSION sql_mode='" . self::STRICT_MODE . "'");
    }

    protected function tearDown(): void
    {
        $this->connect(null)->exec('DROP DATABASE IF EXISTS `' . self::TEST . '`');
    }

    /**
     * @param array<string, string> $over
     * @return array<string, string>
     */
    private function fact(array $over = []): array
    {
        return $over + [
            'test_name' => 'Hemoglobin A1c',
            'value' => '5.4',
            'unit' => '%',
            'reference_range' => '4.0-5.6',
            'collection_date' => '2026-05-01',
            'abnormal_flag' => '',
            'source_citation' => 'Synthetic Lab Report - No PHI',
        ];
    }

    private function persister(): LabFactPersister
    {
        return new LabFactPersister($this->db, new DerivedFactProvenanceService($this->db));
    }

    // --- AC1: an empty collection date files (NULL dates), does not 500 ---------

    public function testFilesWithEmptyCollectionDateUnderStrictMode(): void
    {
        $result = $this->persister()->persist(1, 77, 'run-1', 7, $this->fact(['collection_date' => '']));

        $this->assertSame(1, (int) ($result['filed'] ?? 0));

        $order = $this->db->query('SELECT * FROM procedure_order')->fetch();
        $this->assertNull($order['date_collected'], 'order.date_collected must be NULL, never ""/zero-date');
        $this->assertNotNull($order['date_ordered'], 'order.date_ordered must fall back to a real date');

        $report = $this->db->query('SELECT * FROM procedure_report')->fetch();
        $this->assertNull($report['date_collected'], 'report.date_collected must be NULL');
        $this->assertNull($report['date_report'], 'report.date_report must be NULL');

        $res = $this->db->query('SELECT * FROM procedure_result')->fetch();
        $this->assertSame('Hemoglobin A1c', $res['result_text']);
        $this->assertSame('5.4', $res['result']);
        $this->assertNotNull($res['date'], 'result.date must fall back to a real date');
    }

    // --- AC2: a non-empty but unparseable date also files (NULL dates) ----------

    public function testFilesWithUnparseableCollectionDateUnderStrictMode(): void
    {
        $result = $this->persister()->persist(1, 78, 'run-1', 7, $this->fact(['collection_date' => 'May 2024']));

        $this->assertSame(1, (int) ($result['filed'] ?? 0));

        $order = $this->db->query('SELECT * FROM procedure_order')->fetch();
        $this->assertNull($order['date_collected']);
        $this->assertNotNull($order['date_ordered']);

        $report = $this->db->query('SELECT * FROM procedure_report')->fetch();
        $this->assertNull($report['date_collected']);
        $this->assertNull($report['date_report']);

        $res = $this->db->query('SELECT * FROM procedure_result')->fetch();
        $this->assertSame('Hemoglobin A1c', $res['result_text']);
        $this->assertNotNull($res['date']);
    }

    // --- AC3: a valid ISO date is preserved (regression) -----------------------

    public function testPreservesValidCollectionDateUnderStrictMode(): void
    {
        $this->persister()->persist(1, 79, 'run-1', 7, $this->fact(['collection_date' => '2026-05-01']));

        $order = $this->db->query('SELECT * FROM procedure_order')->fetch();
        $this->assertSame('2026-05-01', substr((string) $order['date_collected'], 0, 10));

        $report = $this->db->query('SELECT * FROM procedure_report')->fetch();
        $this->assertSame('2026-05-01', substr((string) $report['date_collected'], 0, 10));
        $this->assertSame('2026-05-01', substr((string) $report['date_report'], 0, 10));

        $res = $this->db->query('SELECT * FROM procedure_result')->fetch();
        $this->assertSame('2026-05-01', substr((string) $res['date'], 0, 10));
    }
}
