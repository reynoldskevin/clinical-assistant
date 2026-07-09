<?php

/**
 * T09a acceptance tests (LOCKED) — PatientSummaryService.
 *
 * DB-backed but self-contained: manages its own disposable throwaway schema
 * (cloned from `openemr`) via an injected PDO, so it has no dependency on the
 * OpenEMR app bootstrap. Mirrors the ETL throwaway-schema pattern, PHP side.
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

require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Service/PatientSummaryService.php';

#[Group('isolated')]
final class PatientSummaryServiceTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_test';
    private const TABLES = [
        'patient_data', 'lists', 'prescriptions', 'form_encounter',
        'form_vitals', 'procedure_order', 'procedure_report', 'procedure_result',
    ];

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

    private function seed(): void
    {
        $db = $this->db;
        $db->exec("INSERT INTO patient_data (pid, fname, lname, DOB, sex, race, ethnicity)
                   VALUES (1, 'Jane', 'Doe', '1980-01-01', 'Female', 'white', 'not_hisp_or_latin')");

        // active + inactive problem, + allergy
        $db->exec("INSERT INTO lists (pid, type, title, diagnosis, activity, begdate, date)
                   VALUES (1, 'medical_problem', 'Diabetes', 'SNOMED-CT:44054006', 1, '2010-01-01', '2010-01-01')");
        $db->exec("INSERT INTO lists (pid, type, title, diagnosis, activity, begdate, date)
                   VALUES (1, 'medical_problem', 'Resolved thing', 'SNOMED-CT:11111', 0, '2009-01-01', '2009-01-01')");
        $db->exec("INSERT INTO lists (pid, type, title, diagnosis, activity, begdate, date)
                   VALUES (1, 'allergy', 'Penicillin allergy', 'SNOMED-CT:91936005', 1, '2005-01-01', '2005-01-01')");

        // active + inactive medication (strict-mode NOT-NULL cols supplied)
        $db->exec("INSERT INTO prescriptions (patient_id, drug, rxnorm_drugcode, active, date_added, start_date, txDate, usage_category_title, request_intent_title, provider_id)
                   VALUES (1, 'Metformin', '860975', 1, '2012-01-01', '2012-01-01', '2012-01-01', '', '', 0)");
        $db->exec("INSERT INTO prescriptions (patient_id, drug, rxnorm_drugcode, active, date_added, start_date, txDate, usage_category_title, request_intent_title, provider_id)
                   VALUES (1, 'OldDrug', '111', 0, '2008-01-01', '2008-01-01', '2008-01-01', '', '', 0)");

        // 7 encounters (2015..2021) -> recent capped at 5, most-recent-first
        for ($y = 2015; $y <= 2021; $y++) {
            $enc = $y - 2014;
            $db->exec("INSERT INTO form_encounter (pid, encounter, date, reason)
                       VALUES (1, {$enc}, '{$y}-01-01 10:00:00', 'Visit {$y}')");
        }

        // 2 vitals
        $db->exec("INSERT INTO form_vitals (pid, date, bps, bpd, pulse, weight)
                   VALUES (1, '2020-01-01 10:00:00', '120', '80', 72, 70)");
        $db->exec("INSERT INTO form_vitals (pid, date, bps, bpd, pulse, weight)
                   VALUES (1, '2021-01-01 10:00:00', '118', '78', 70, 71)");

        // one lab result via order -> report -> result
        $db->exec("INSERT INTO procedure_order (patient_id, date_ordered, provider_id) VALUES (1, '2019-06-01', 0)");
        $orderId = (int) $db->lastInsertId();
        $db->exec("INSERT INTO procedure_report (procedure_order_id, date_collected, date_report, report_status)
                   VALUES ({$orderId}, '2019-06-01', '2019-06-01', 'final')");
        $reportId = (int) $db->lastInsertId();
        $db->exec("INSERT INTO procedure_result (procedure_report_id, result_code, result_text, result, units, date)
                   VALUES ({$reportId}, '2339-0', 'Glucose', '95', 'mg/dL', '2019-06-01')");
    }

    public function testDemographics(): void
    {
        $s = (new PatientSummaryService($this->db))->getSummary(1);
        $d = $s['demographics'];
        $this->assertSame(1, (int) $d['pid']);
        $this->assertSame('Jane', $d['fname']);
        $this->assertSame('Doe', $d['lname']);
        $this->assertSame('1980-01-01', $d['dob']);
        $this->assertSame('Female', $d['sex']);
        $this->assertSame('white', $d['race']);
        $this->assertSame('not_hisp_or_latin', $d['ethnicity']);
    }

    public function testActiveOnlyProblemsMedsAndAllergies(): void
    {
        $s = (new PatientSummaryService($this->db))->getSummary(1);

        $this->assertCount(1, $s['problems']);            // inactive excluded
        $this->assertSame('Diabetes', $s['problems'][0]['title']);
        $this->assertStringContainsString('44054006', $s['problems'][0]['diagnosis']);

        $this->assertCount(1, $s['medications']);         // inactive excluded
        $this->assertSame('Metformin', $s['medications'][0]['drug']);
        $this->assertSame('860975', $s['medications'][0]['rxnorm_drugcode']);

        $this->assertCount(1, $s['allergies']);
        $this->assertSame('Penicillin allergy', $s['allergies'][0]['title']);
    }

    public function testRecentSectionsAreBoundedAndMostRecentFirst(): void
    {
        $s = (new PatientSummaryService($this->db, 5))->getSummary(1);

        $this->assertCount(5, $s['recent_encounters']);   // 7 seeded, capped at 5
        $dates = array_column($s['recent_encounters'], 'date');
        $this->assertGreaterThan($dates[4], $dates[0]);   // descending (most recent first)
        $this->assertStringStartsWith('2021', (string) $dates[0]);

        $this->assertCount(2, $s['recent_vitals']);
        $this->assertArrayHasKey('bps', $s['recent_vitals'][0]);

        $this->assertCount(1, $s['recent_labs']);
        $lab = $s['recent_labs'][0];
        $this->assertStringContainsString('2339-0', $lab['result_code']);
        $this->assertSame('95', $lab['result']);
        $this->assertSame('mg/dL', $lab['units']);
    }
}
