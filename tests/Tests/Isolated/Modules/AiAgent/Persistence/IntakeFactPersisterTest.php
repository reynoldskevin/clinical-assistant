<?php

/**
 * T53c acceptance tests (LOCKED) — IntakeFactPersister.
 *
 * DB-backed but self-contained: throwaway schema cloning prescriptions, lists,
 * pnotes + ai_derived_fact from `openemr` via an injected PDO. Mirrors
 * LabFactPersisterTest.
 *
 * Pins that a validated IntakeFact's narrative fields are split and filed as
 * discrete records (meds→prescriptions, allergies→lists/allergy,
 * family_history→lists/medical_problem, chief_concern→one pnotes), demographics is
 * never written, negations are skipped, each record is provenance-tracked, and a
 * re-file soft-supersedes the prior run per fact_type (reads filter active/activity).
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
use OpenEMR\Modules\AiAgent\Persistence\IntakeFactPersister;
use OpenEMR\Modules\AiAgent\Persistence\NarrativeFieldSplitter;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

$base = __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Persistence/';
require_once $base . 'DerivedFactRef.php';
require_once $base . 'DerivedFactProvenanceService.php';
require_once $base . 'NarrativeFieldSplitter.php';
require_once $base . 'IntakeFactPersister.php';

#[Group('isolated')]
final class IntakeFactPersisterTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_intake_test';
    private const TABLES = ['prescriptions', 'lists', 'pnotes', 'ai_derived_fact'];

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

    private function persister(): IntakeFactPersister
    {
        return new IntakeFactPersister(
            $this->db,
            new DerivedFactProvenanceService($this->db),
            new NarrativeFieldSplitter()
        );
    }

    /**
     * @param array<string, string> $over
     * @return array<string, string>
     */
    private function fact(array $over = []): array
    {
        return $over + [
            'demographics' => 'Name: Jane Doe; DOB: 1980-01-01; Sex: Female',
            'chief_concern' => '',
            'current_medications' => '',
            'allergies' => '',
            'family_history' => '',
            'source_citation' => 'Intake form p1',
        ];
    }

    private function countRows(string $sql): int
    {
        return (int) $this->db->query($sql)->fetch()['c'];
    }

    public function testFilesMedicationsAsActivePrescriptions(): void
    {
        $ret = $this->persister()->persist(1, 42, 'run-1', 7, $this->fact([
            'current_medications' => 'Lisinopril 10 mg once daily; Metformin 500 mg twice daily',
        ]));

        $this->assertSame(2, $this->countRows("SELECT COUNT(*) c FROM prescriptions WHERE patient_id = 1 AND active = 1"));
        $drugs = $this->db->query('SELECT drug FROM prescriptions ORDER BY id')->fetchAll();
        $this->assertStringContainsString('Lisinopril', $drugs[0]['drug']);
        $this->assertStringContainsString('Metformin', $drugs[1]['drug']);
        $this->assertSame(2, (int) $ret['filed']['medication']);

        $this->assertSame(2, $this->countRows("SELECT COUNT(*) c FROM ai_derived_fact WHERE fact_type = 'medication' AND target_table = 'prescriptions' AND active = 1"));
    }

    public function testFilesAllergiesAsActiveList(): void
    {
        $this->persister()->persist(1, 42, 'run-1', 7, $this->fact(['allergies' => 'Penicillin (rash)']));

        $row = $this->db->query("SELECT * FROM lists WHERE type = 'allergy'")->fetch();
        $this->assertStringContainsString('Penicillin', $row['title']);
        $this->assertSame(1, (int) $row['activity']);
        $this->assertSame(1, $this->countRows("SELECT COUNT(*) c FROM ai_derived_fact WHERE fact_type = 'allergy' AND target_table = 'lists' AND active = 1"));
    }

    public function testFilesFamilyHistoryAsProblemList(): void
    {
        $this->persister()->persist(1, 42, 'run-1', 7, $this->fact([
            'family_history' => 'Father: myocardial infarction at age 60; Mother: type 2 diabetes',
        ]));

        $this->assertSame(2, $this->countRows("SELECT COUNT(*) c FROM lists WHERE type = 'medical_problem' AND activity = 1"));
        $this->assertSame(2, $this->countRows("SELECT COUNT(*) c FROM ai_derived_fact WHERE fact_type = 'family_history' AND target_table = 'lists' AND active = 1"));
    }

    public function testFilesChiefConcernAsSinglePnote(): void
    {
        $this->persister()->persist(1, 42, 'run-1', 7, $this->fact([
            'chief_concern' => 'Intermittent chest tightness for 2 weeks',
        ]));

        $row = $this->db->query('SELECT * FROM pnotes')->fetch();
        $this->assertStringContainsString('chest tightness', $row['body']);
        $this->assertSame(1, (int) $row['activity']);
        $this->assertSame(1, $this->countRows("SELECT COUNT(*) c FROM ai_derived_fact WHERE fact_type = 'chief_concern' AND target_table = 'pnotes' AND active = 1"));
    }

    public function testDemographicsAreNeverWritten(): void
    {
        // Only demographics populated (default fact) -> nothing clinical is written.
        $ret = $this->persister()->persist(1, 42, 'run-1', 7, $this->fact());

        $this->assertSame(0, $this->countRows('SELECT COUNT(*) c FROM prescriptions'));
        $this->assertSame(0, $this->countRows('SELECT COUNT(*) c FROM lists'));
        $this->assertSame(0, $this->countRows('SELECT COUNT(*) c FROM pnotes'));
        $this->assertSame(0, $this->countRows('SELECT COUNT(*) c FROM ai_derived_fact'));
        $this->assertSame(0, (int) $ret['filed']['medication']);
    }

    public function testNegationAllergyIsSkipped(): void
    {
        $ret = $this->persister()->persist(1, 42, 'run-1', 7, $this->fact(['allergies' => 'No known drug allergies']));
        $this->assertSame(0, $this->countRows("SELECT COUNT(*) c FROM lists WHERE type = 'allergy'"));
        $this->assertSame(0, (int) $ret['filed']['allergy']);
    }

    public function testRefileSoftSupersedesMedicationsPerFactType(): void
    {
        $p = $this->persister();
        $p->persist(1, 42, 'run-1', 7, $this->fact(['current_medications' => 'DrugA 1 mg; DrugB 2 mg']));
        $ret = $p->persist(1, 42, 'run-2', 7, $this->fact(['current_medications' => 'DrugC 3 mg']));

        // Prior meds soft-deactivated; only the new one is active.
        $this->assertSame(1, $this->countRows('SELECT COUNT(*) c FROM prescriptions WHERE active = 1'));
        $this->assertSame(2, $this->countRows('SELECT COUNT(*) c FROM prescriptions WHERE active = 0'));
        $this->assertStringContainsString('DrugC', $this->db->query('SELECT drug FROM prescriptions WHERE active = 1')->fetch()['drug']);

        // Provenance: one active medication row, two superseded.
        $this->assertSame(1, $this->countRows("SELECT COUNT(*) c FROM ai_derived_fact WHERE fact_type = 'medication' AND active = 1"));
        $this->assertSame(2, $this->countRows("SELECT COUNT(*) c FROM ai_derived_fact WHERE fact_type = 'medication' AND active = 0"));
        $this->assertSame(2, (int) $ret['superseded']);
    }

    public function testFullEnvelopeFilesAcrossTablesAndSkipsDemographics(): void
    {
        $ret = $this->persister()->persist(1, 42, 'run-1', 7, [
            'demographics' => 'Name: Jane Doe; DOB: 1980-01-01; Sex: Female',
            'chief_concern' => 'Chest tightness',
            'current_medications' => 'Lisinopril 10 mg; Metformin 500 mg; Atorvastatin 20 mg',
            'allergies' => 'Penicillin (rash)',
            'family_history' => 'Father: MI; Mother: diabetes',
            'source_citation' => 'Intake p1',
        ]);

        $this->assertSame(3, (int) $ret['filed']['medication']);
        $this->assertSame(1, (int) $ret['filed']['allergy']);
        $this->assertSame(2, (int) $ret['filed']['family_history']);
        $this->assertSame(1, (int) $ret['filed']['chief_concern']);
        // 3 meds + 1 allergy + 2 problems + 1 note = 7 provenance rows; demographics wrote nothing extra.
        $this->assertSame(7, $this->countRows('SELECT COUNT(*) c FROM ai_derived_fact WHERE active = 1'));
    }

    public function testChiefConcernNoteStoresUsernameNotNumericId(): void
    {
        // OpenEMR's addPnote stores the USERNAME in pnotes.user, and the Patient
        // Notes view filters `pid != user`. If we stored the numeric clinician id
        // and it coincided with the pid (e.g. admin=id 1 filing to pid 1), the note
        // would be hidden. With a username supplied, pnotes.user must be the name.
        $this->persister()->persist(1, 42, 'run-1', 1, $this->fact([
            'chief_concern' => 'Chest tightness',
        ]), 'admin');

        $row = $this->db->query('SELECT user FROM pnotes')->fetch();
        $this->assertSame('admin', $row['user']);
    }
}
