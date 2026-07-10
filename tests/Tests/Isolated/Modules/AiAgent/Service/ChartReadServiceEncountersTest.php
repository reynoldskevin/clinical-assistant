<?php

/**
 * T17 acceptance tests (LOCKED) — PatientSummaryService encounter reads.
 *
 * DB-backed but self-contained: manages its own disposable throwaway schema
 * (cloned from `openemr`) via an injected PDO, mirroring PatientSummaryServiceTest.
 * Proves the two new chart-navigation reads are patient-scoped: listEncounters
 * returns only the given patient's encounters, and getEncounter refuses to return
 * an encounter that belongs to a DIFFERENT patient even when its id is supplied.
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
final class ChartReadServiceEncountersTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_enc_test';
    private const TABLES = ['form_encounter'];

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
        // Patient 1: three encounters (2019..2021).
        $db->exec("INSERT INTO form_encounter (pid, encounter, date, reason, provider_id)
                   VALUES (1, 10, '2019-01-01 10:00:00', 'Annual physical', 3)");
        $db->exec("INSERT INTO form_encounter (pid, encounter, date, reason, provider_id)
                   VALUES (1, 11, '2020-06-15 10:00:00', 'Follow-up visit', 7)");
        $db->exec("INSERT INTO form_encounter (pid, encounter, date, reason, provider_id)
                   VALUES (1, 12, '2021-03-20 10:00:00', 'Medication review', 7)");
        // Patient 2: a single encounter whose id (20) must never leak to patient 1.
        $db->exec("INSERT INTO form_encounter (pid, encounter, date, reason, provider_id)
                   VALUES (2, 20, '2021-05-01 10:00:00', 'Other patient visit', 9)");
    }

    public function testListEncountersReturnsOnlyThatPatientMostRecentFirst(): void
    {
        $encounters = (new PatientSummaryService($this->db))->listEncounters(1);

        $this->assertCount(3, $encounters);                       // patient 2's encounter excluded
        $ids = array_map(static fn (array $e): int => (int) $e['encounter'], $encounters);
        $this->assertSame([12, 11, 10], $ids);                    // most-recent-first

        $first = $encounters[0];
        $this->assertArrayHasKey('date', $first);
        $this->assertArrayHasKey('reason', $first);
        $this->assertSame('Medication review', $first['reason']);
    }

    public function testGetEncounterReturnsOwnEncounterDetail(): void
    {
        $encounter = (new PatientSummaryService($this->db))->getEncounter(1, 11);

        $this->assertNotSame([], $encounter);
        $this->assertSame(11, (int) $encounter['encounter']);
        $this->assertSame('Follow-up visit', $encounter['reason']);
    }

    public function testGetEncounterForAnotherPatientsIdReturnsEmpty(): void
    {
        // Encounter 20 belongs to patient 2. Requesting it as patient 1 must
        // return nothing — a model cannot cross patients by guessing an id.
        $encounter = (new PatientSummaryService($this->db))->getEncounter(1, 20);

        $this->assertSame([], $encounter);
    }

    public function testGetEncounterForMissingIdReturnsEmpty(): void
    {
        $encounter = (new PatientSummaryService($this->db))->getEncounter(1, 999);

        $this->assertSame([], $encounter);
    }
}
