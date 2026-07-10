<?php

/**
 * T19 acceptance tests (LOCKED) — PatientSummaryService::getMedications.
 *
 * DB-backed, self-contained disposable schema (cloned from `openemr`) via an
 * injected PDO. Proves get_medications is patient-scoped, unions prescriptions +
 * medication-type `lists` rows, honours active_only, and flags the "stale-active"
 * data-quality conflict: a row that is `active` yet whose `end_date` is already in
 * the past is marked `status_conflict = true` (per ARCHITECTURE.md §2.5).
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
final class ChartReadServiceMedicationsTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_meds_test';
    private const TABLES = ['prescriptions', 'lists'];

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

    private function rx(int $pid, string $drug, string $rxnorm, int $active, ?string $end): void
    {
        $endSql = $end === null ? 'NULL' : "'{$end}'";
        $this->db->exec(
            "INSERT INTO prescriptions
             (patient_id, drug, rxnorm_drugcode, active, date_added, start_date, end_date, txDate,
              usage_category_title, request_intent_title, provider_id)
             VALUES ({$pid}, '{$drug}', '{$rxnorm}', {$active}, '2018-01-01', '2018-01-01', {$endSql},
              '2018-01-01', '', '', 0)"
        );
    }

    private function listMed(int $pid, string $drug, int $activity, ?string $end): void
    {
        $endSql = $end === null ? 'NULL' : "'{$end}'";
        $this->db->exec(
            "INSERT INTO lists (pid, type, title, activity, begdate, enddate, date)
             VALUES ({$pid}, 'medication', '{$drug}', {$activity}, '2018-01-01', {$endSql}, '2018-01-01')"
        );
    }

    private function seed(): void
    {
        // Patient 1 — the stale-active matrix:
        $this->rx(1, 'Warfarin', '855332', 1, '2020-01-01');   // active + past end   -> conflict
        $this->rx(1, 'Metformin', '860975', 1, '2099-01-01');  // active + future end -> no conflict
        $this->rx(1, 'Aspirin', '1191', 1, null);              // active + no end     -> no conflict
        $this->rx(1, 'OldDrug', '111', 0, '2011-01-01');       // inactive + past end -> no conflict
        $this->listMed(1, 'Lisinopril', 1, '2019-01-01');      // list med, active + past end -> conflict

        // Patient 2 — must never leak into patient 1's medications.
        $this->rx(2, 'Digoxin', '3407', 1, '2020-01-01');
    }

    /**
     * @param list<array<string, mixed>> $meds
     * @return array<string, array<string, mixed>>
     */
    private function byDrug(array $meds): array
    {
        $out = [];
        foreach ($meds as $m) {
            $out[(string) $m['drug']] = $m;
        }
        return $out;
    }

    public function testReturnsPrescriptionsAndListMedsForThePatientOnly(): void
    {
        $meds = (new PatientSummaryService($this->db))->getMedications(1, false);

        $this->assertCount(5, $meds);                        // 4 prescriptions + 1 list med
        $drugs = array_keys($this->byDrug($meds));
        sort($drugs);
        $this->assertSame(['Aspirin', 'Lisinopril', 'Metformin', 'OldDrug', 'Warfarin'], $drugs);
        $this->assertArrayNotHasKey('Digoxin', $this->byDrug($meds)); // patient 2 excluded
    }

    public function testCarriesTheDocumentedFieldsAsTypedValues(): void
    {
        $warfarin = $this->byDrug((new PatientSummaryService($this->db))->getMedications(1, false))['Warfarin'];

        foreach (['ref', 'drug', 'rxnorm', 'active', 'start_date', 'end_date', 'status_conflict'] as $key) {
            $this->assertArrayHasKey($key, $warfarin);
        }
        $this->assertSame('Warfarin', $warfarin['drug']);
        $this->assertSame('855332', $warfarin['rxnorm']);
        $this->assertTrue($warfarin['active']);              // normalized to bool
        $this->assertIsBool($warfarin['status_conflict']);
    }

    public function testStaleActiveConflictFlag(): void
    {
        $meds = $this->byDrug((new PatientSummaryService($this->db))->getMedications(1, false));

        // active AND end_date in the past -> conflict (prescription and list med alike)
        $this->assertTrue($meds['Warfarin']['status_conflict']);
        $this->assertTrue($meds['Lisinopril']['status_conflict']);

        // active but end_date is in the future / absent -> NOT a conflict
        $this->assertFalse($meds['Metformin']['status_conflict']);
        $this->assertFalse($meds['Aspirin']['status_conflict']);

        // inactive -> never a conflict, even with a past end_date
        $this->assertFalse($meds['OldDrug']['status_conflict']);
        $this->assertFalse($meds['OldDrug']['active']);
    }

    public function testActiveOnlyExcludesInactiveButKeepsStaleActive(): void
    {
        $meds = $this->byDrug((new PatientSummaryService($this->db))->getMedications(1, true));

        $this->assertArrayNotHasKey('OldDrug', $meds);       // inactive dropped
        $this->assertArrayHasKey('Warfarin', $meds);         // stale-active is still active -> kept + flagged
        $this->assertTrue($meds['Warfarin']['status_conflict']);
        $this->assertCount(4, $meds);
    }
}
