<?php

/**
 * T53b acceptance tests (LOCKED) — LabFactPersister.
 *
 * DB-backed but self-contained: manages its own disposable throwaway schema
 * (cloning the procedure_* tables + ai_derived_fact from `openemr`) via an
 * injected PDO. Mirrors PatientSummaryServiceTest / DerivedFactProvenanceServiceTest.
 *
 * Pins that a validated LabFact is filed as a linked procedure_order→report→result
 * (the module's native, FHIR-readable lab shape), tracked via T53a provenance, and
 * that re-filing the same document SUPERSEDES the prior run by DELETING its
 * agent-created rows (the lab read is activity-blind) while keeping the provenance
 * audit trail.
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
final class LabFactPersisterTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_lab_test';
    private const TABLES = ['procedure_order', 'procedure_report', 'procedure_result', 'ai_derived_fact'];

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
            'value' => '7.4',
            'unit' => '%',
            'reference_range' => '4.0-5.6',
            'collection_date' => '2026-05-01',
            'abnormal_flag' => 'High',
            'source_citation' => 'Lab report p1: "HbA1c 7.4 %"',
        ];
    }

    private function persister(): LabFactPersister
    {
        return new LabFactPersister($this->db, new DerivedFactProvenanceService($this->db));
    }

    public function testFilesLinkedProcedureOrderReportResult(): void
    {
        $this->persister()->persist(1, 42, 'run-1', 7, $this->fact());

        $order = $this->db->query('SELECT * FROM procedure_order')->fetch();
        $this->assertSame(1, (int) $order['patient_id']);

        $report = $this->db->query(
            'SELECT * FROM procedure_report WHERE procedure_order_id = ' . (int) $order['procedure_order_id']
        )->fetch();
        $this->assertIsArray($report);

        $result = $this->db->query(
            'SELECT * FROM procedure_result WHERE procedure_report_id = ' . (int) $report['procedure_report_id']
        )->fetch();
        $this->assertSame('Hemoglobin A1c', $result['result_text']);
        $this->assertSame('7.4', $result['result']);
        $this->assertSame('%', $result['units']);
        $this->assertSame('4.0-5.6', $result['range']);
        $this->assertSame('high', $result['abnormal']);
        $this->assertStringContainsString('HbA1c', (string) $result['comments']);
        $this->assertSame(42, (int) $result['document_id']);
        $this->assertSame('2026-05-01', substr((string) $result['date'], 0, 10));
    }

    public function testRecordsProvenanceForTheFiledLab(): void
    {
        $this->persister()->persist(1, 42, 'run-xyz', 7, $this->fact());

        $prov = $this->db->query('SELECT * FROM ai_derived_fact')->fetch();
        $this->assertSame('lab_result', $prov['fact_type']);
        $this->assertSame('procedure_order', $prov['target_table']);
        $this->assertSame(1, (int) $prov['active']);
        $this->assertSame(42, (int) $prov['source_document_id']);
        $this->assertSame('run-xyz', $prov['extraction_run_id']);
        // provenance target is the deletable order id
        $order = $this->db->query('SELECT procedure_order_id FROM procedure_order')->fetch();
        $this->assertSame((int) $order['procedure_order_id'], (int) $prov['target_id']);
        $this->assertStringContainsString('Hemoglobin A1c', (string) $prov['fact_summary']);
    }

    public function testRefileSupersedesPriorRunByDeletingItsRows(): void
    {
        $p = $this->persister();
        $p->persist(1, 42, 'run-1', 7, $this->fact(['value' => '7.4']));
        $result = $p->persist(1, 42, 'run-2', 7, $this->fact(['value' => '6.1']));

        // Exactly one active lab chain remains — the new value.
        $this->assertSame(1, (int) $this->db->query('SELECT COUNT(*) c FROM procedure_order')->fetch()['c']);
        $this->assertSame(1, (int) $this->db->query('SELECT COUNT(*) c FROM procedure_result')->fetch()['c']);
        $this->assertSame('6.1', $this->db->query('SELECT result FROM procedure_result')->fetch()['result']);

        // One active provenance row; the prior run is superseded (inactive), not gone.
        $this->assertSame(1, (int) $this->db->query('SELECT COUNT(*) c FROM ai_derived_fact WHERE active = 1')->fetch()['c']);
        $this->assertSame(1, (int) $this->db->query('SELECT COUNT(*) c FROM ai_derived_fact WHERE active = 0')->fetch()['c']);
        $this->assertSame(1, (int) ($result['superseded'] ?? 0));
    }

    public function testDoesNotTouchAnotherDocumentsLab(): void
    {
        $p = $this->persister();
        $p->persist(1, 42, 'run-1', 7, $this->fact());
        $p->persist(1, 99, 'run-1', 7, $this->fact()); // different document
        // Re-file document 42 only.
        $p->persist(1, 42, 'run-2', 7, $this->fact());

        // Document 99's lab is untouched; document 42 has exactly one active order → 2 orders total.
        $this->assertSame(2, (int) $this->db->query('SELECT COUNT(*) c FROM procedure_order')->fetch()['c']);
        $this->assertSame(2, (int) $this->db->query('SELECT COUNT(*) c FROM ai_derived_fact WHERE active = 1')->fetch()['c']);
    }

    /**
     * @return array<string, array{string, string}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function abnormalFlagProvider(): array
    {
        return [
            'High word' => ['High', 'high'],
            'H letter' => ['H', 'high'],
            'Low word' => ['Low', 'low'],
            'L letter' => ['L', 'low'],
            'abnormal generic' => ['abnormal', 'yes'],
            'normal' => ['Normal', 'no'],
            'blank' => ['', 'no'],
            'unknown' => ['weird', 'no'],
        ];
    }

    #[\PHPUnit\Framework\Attributes\DataProvider('abnormalFlagProvider')]
    public function testAbnormalFlagMapsToOpenEmrEnum(string $flag, string $expected): void
    {
        // Distinct document per case so supersede does not interfere.
        $doc = 100 + abs(crc32($flag)) % 1000;
        $this->persister()->persist(1, $doc, 'run-1', 7, $this->fact(['abnormal_flag' => $flag]));
        $row = $this->db->query(
            'SELECT abnormal FROM procedure_result pr JOIN procedure_report rp ON rp.procedure_report_id = pr.procedure_report_id '
            . 'JOIN procedure_order po ON po.procedure_order_id = rp.procedure_order_id WHERE po.encounter_id = 0 '
            . 'ORDER BY pr.procedure_result_id DESC LIMIT 1'
        )->fetch();
        $this->assertSame($expected, $row['abnormal']);
    }
}
