<?php

/**
 * T18 acceptance tests (LOCKED) — PatientSummaryService::getResults.
 *
 * DB-backed, self-contained disposable schema (cloned from `openemr`) via an
 * injected PDO, mirroring the other AiAgent service tests. Proves the dedicated
 * lab/diagnostic results read is patient-scoped: only the given patient's results
 * are returned (via the procedure_order.patient_id join), most-recent-first, with
 * the value/units/range/abnormal/status fields a clinician would need.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Service;

use OpenEMR\Modules\AiAgent\Service\PatientSummaryService;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

$src = __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src';
require_once $src . '/Service/PatientSummaryProviderInterface.php';
require_once $src . '/Service/ChartReadProviderInterface.php';
require_once $src . '/Service/PatientSummaryService.php';

#[Group('isolated')]
final class ChartReadServiceResultsTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_results_test';
    private const TABLES = ['procedure_order', 'procedure_report', 'procedure_result'];

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
        $this->seed();
    }

    protected function tearDown(): void
    {
        $this->connect(null)->exec('DROP DATABASE IF EXISTS `' . self::TEST . '`');
    }

    /** Insert one order → report → result chain for a patient; returns nothing. */
    private function seedResult(
        int $pid,
        string $code,
        string $name,
        string $value,
        string $units,
        string $range,
        string $abnormal,
        string $date
    ): void {
        $db = $this->db;
        $db->exec("INSERT INTO procedure_order (patient_id, date_ordered, provider_id) VALUES ({$pid}, '{$date}', 0)");
        $orderId = (int) $db->lastInsertId();
        $db->exec("INSERT INTO procedure_report (procedure_order_id, date_collected, date_report, report_status)
                   VALUES ({$orderId}, '{$date}', '{$date}', 'final')");
        $reportId = (int) $db->lastInsertId();
        $db->exec("INSERT INTO procedure_result
                   (procedure_report_id, result_code, result_text, result, units, `range`, abnormal, date, result_status)
                   VALUES ({$reportId}, '{$code}', '{$name}', '{$value}', '{$units}', '{$range}', '{$abnormal}', '{$date}', 'final')");
    }

    private function seed(): void
    {
        // Patient 1: three results across 2019..2021.
        $this->seedResult(1, '2339-0', 'Glucose', '95', 'mg/dL', '70-99', 'no', '2019-06-01');
        $this->seedResult(1, '4548-4', 'HbA1c', '7.8', '%', '4.0-5.6', 'yes', '2020-06-01');
        $this->seedResult(1, '2093-3', 'Cholesterol', '180', 'mg/dL', '<200', 'no', '2021-06-01');
        // Patient 2: a result whose value must never appear for patient 1.
        $this->seedResult(2, '2823-3', 'Potassium', '9.9', 'mmol/L', '3.5-5.1', 'yes', '2021-07-01');
    }

    public function testGetResultsReturnsOnlyThatPatientMostRecentFirst(): void
    {
        $results = (new PatientSummaryService($this->db))->getResults(1);

        $this->assertCount(3, $results);                          // patient 2's result excluded
        $codes = array_column($results, 'result_code');
        $this->assertSame(['2093-3', '4548-4', '2339-0'], $codes); // most-recent-first
    }

    public function testGetResultsCarriesTheClinicalFields(): void
    {
        $results = (new PatientSummaryService($this->db))->getResults(1);

        $hba1c = null;
        foreach ($results as $row) {
            if ($row['result_code'] === '4548-4') {
                $hba1c = $row;
            }
        }
        $this->assertNotNull($hba1c);
        $this->assertSame('HbA1c', $hba1c['result_text']);
        $this->assertSame('7.8', $hba1c['result']);
        $this->assertSame('%', $hba1c['units']);
        $this->assertSame('4.0-5.6', $hba1c['range']);
        $this->assertSame('yes', $hba1c['abnormal']);
        // Each result carries a citable ref (result:<procedure_result_id>) so the
        // agent can ground a lab-value claim through the verification gate.
        $this->assertArrayHasKey('ref', $hba1c);
        $this->assertMatchesRegularExpression('/^result:\d+$/', $hba1c['ref']);
        $this->assertArrayHasKey('date', $hba1c);
        $this->assertArrayHasKey('result_status', $hba1c);
    }

    public function testGetResultsRowMatchesTheSharedLabTrendContract(): void
    {
        // T77 contract: the lab-trend chart widget (agent-widget.js) consumes
        // get_results over the browser→read.php wire using the SHARED fixture
        // tests/fixtures/get_results_contract.json. This pins the PRODUCER side —
        // every key the fixture (and therefore the JS consumer) relies on must be
        // present on a real getResults row, so a shape change here breaks the JS
        // consumer test rather than silently diverging.
        $fixturePath = __DIR__
            . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent'
            . '/tests/fixtures/get_results_contract.json';
        $fixture = json_decode((string) file_get_contents($fixturePath), true);
        $this->assertIsArray($fixture);
        $this->assertNotEmpty($fixture);

        $results = (new PatientSummaryService($this->db))->getResults(1);
        $this->assertNotEmpty($results);
        $realKeys = array_keys($results[0]);

        foreach (array_keys($fixture[0]) as $contractKey) {
            $this->assertContains(
                $contractKey,
                $realKeys,
                "getResults must expose the '{$contractKey}' key the lab-trend contract fixture relies on"
            );
        }
    }

    public function testGetResultsIsPatientScoped(): void
    {
        // Patient 2's abnormal potassium (9.9) must never surface for patient 1.
        $results = (new PatientSummaryService($this->db))->getResults(1);

        $values = array_column($results, 'result');
        $this->assertNotContains('9.9', $values);

        // And patient 2 sees their own single result.
        $p2 = (new PatientSummaryService($this->db))->getResults(2);
        $this->assertCount(1, $p2);
        $this->assertSame('2823-3', $p2[0]['result_code']);
    }
}
