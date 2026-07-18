<?php

/**
 * T75b acceptance tests (LOCKED) — MedicationFactPersister.
 *
 * A `med_list` extraction's `medications` string is split and filed under the
 * patient-dashboard Medications panel — `lists` rows with `type='medication'`
 * (the same store IntakeFactPersister uses for current_medications). Each row is
 * provenance-tracked in `ai_derived_fact`, negations are skipped, and a re-file
 * DELETES the prior run's agent-created rows (the panel filters on enddate, so a
 * soft-flag would leave a ghost duplicate) while preserving provenance history.
 *
 * DB-backed but self-contained: a throwaway schema clones `lists` +
 * `ai_derived_fact` from `openemr` via an injected PDO. Mirrors
 * IntakeFactPersisterTest.
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
use OpenEMR\Modules\AiAgent\Persistence\MedicationFactPersister;
use OpenEMR\Modules\AiAgent\Persistence\NarrativeFieldSplitter;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

$base = __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Persistence/';
require_once $base . 'DerivedFactRef.php';
require_once $base . 'DerivedFactProvenanceService.php';
require_once $base . 'NarrativeFieldSplitter.php';
require_once $base . 'MedicationFactPersister.php';

#[Group('isolated')]
final class MedicationFactPersisterTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_medlist_test';
    private const TABLES = ['lists', 'ai_derived_fact'];

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

    private function persister(): MedicationFactPersister
    {
        return new MedicationFactPersister(
            $this->db,
            new DerivedFactProvenanceService($this->db),
            new NarrativeFieldSplitter()
        );
    }

    /**
     * @param array<string, string|null> $over
     * @return array<string, string|null>
     */
    private function fact(array $over = []): array
    {
        return $over + [
            'medications' => 'Lisinopril 10 mg PO once daily; Metformin 500 mg PO twice daily',
            'source_citation' => 'Medication list, page 1',
        ];
    }

    private function countRows(string $sql): int
    {
        return (int) $this->db->query($sql)->fetch()['c'];
    }

    public function testFilesEachMedicationToTheMedicationsPanel(): void
    {
        $ret = $this->persister()->persist(1, 42, 'run-1', 7, $this->fact());

        // The Medications panel reads lists WHERE type='medication' AND active.
        $this->assertSame(2, $this->countRows("SELECT COUNT(*) c FROM lists WHERE type = 'medication' AND activity = 1"));
        $rows = $this->db->query("SELECT title, pid FROM lists WHERE type = 'medication' ORDER BY id")->fetchAll();
        $this->assertStringContainsString('Lisinopril', $rows[0]['title']);
        $this->assertStringContainsString('Metformin', $rows[1]['title']);
        $this->assertSame(1, (int) $rows[0]['pid']);
        $this->assertSame(2, (int) $ret['filed']);
    }

    public function testEachMedicationIsProvenanceTracked(): void
    {
        $this->persister()->persist(1, 42, 'run-1', 7, $this->fact());

        $this->assertSame(
            2,
            $this->countRows(
                "SELECT COUNT(*) c FROM ai_derived_fact "
                . "WHERE fact_type = 'medication' AND target_table = 'lists' AND active = 1"
            )
        );
    }

    public function testNegationIsSkipped(): void
    {
        $ret = $this->persister()->persist(1, 42, 'run-1', 7, $this->fact(['medications' => 'None']));
        $this->assertSame(0, $this->countRows("SELECT COUNT(*) c FROM lists WHERE type = 'medication'"));
        $this->assertSame(0, (int) $ret['filed']);
    }

    public function testEmptyOrNullMedicationsFilesNothing(): void
    {
        $this->assertSame(0, (int) $this->persister()->persist(1, 42, 'run-1', 7, $this->fact(['medications' => '']))['filed']);
        $this->assertSame(0, (int) $this->persister()->persist(1, 42, 'run-2', 7, $this->fact(['medications' => null]))['filed']);
        $this->assertSame(0, $this->countRows("SELECT COUNT(*) c FROM lists"));
        $this->assertSame(0, $this->countRows("SELECT COUNT(*) c FROM ai_derived_fact"));
    }

    public function testRefileRemovesPriorMedicationsAndLeavesOnlyTheNewRun(): void
    {
        $p = $this->persister();
        $p->persist(1, 42, 'run-1', 7, $this->fact(['medications' => 'DrugA 1 mg; DrugB 2 mg']));
        $ret = $p->persist(1, 42, 'run-2', 7, $this->fact(['medications' => 'DrugC 3 mg']));

        // Prior meds removed from the Medications list; only the new one remains
        // (no ghost duplicate — the panel filters on enddate, not activity).
        $this->assertSame(1, $this->countRows("SELECT COUNT(*) c FROM lists WHERE type = 'medication'"));
        $this->assertStringContainsString(
            'DrugC',
            $this->db->query("SELECT title FROM lists WHERE type = 'medication'")->fetch()['title']
        );

        // Provenance preserves history: one active row, two superseded.
        $this->assertSame(1, $this->countRows("SELECT COUNT(*) c FROM ai_derived_fact WHERE fact_type = 'medication' AND active = 1"));
        $this->assertSame(2, $this->countRows("SELECT COUNT(*) c FROM ai_derived_fact WHERE fact_type = 'medication' AND active = 0"));
        $this->assertSame(2, (int) $ret['superseded']);
    }

    public function testRefileOnlyTouchesOwnProvenanceTrackedRows(): void
    {
        // A pre-existing NON-agent medication (e.g. entered by a clinician) must
        // survive a re-file — the persister only deletes rows it tracked itself.
        $this->db->exec(
            "INSERT INTO lists (pid, type, title, activity, date, begdate) "
            . "VALUES (1, 'medication', 'Clinician-entered Warfarin', 1, NOW(), CURDATE())"
        );

        $p = $this->persister();
        $p->persist(1, 42, 'run-1', 7, $this->fact(['medications' => 'DrugA 1 mg']));
        $p->persist(1, 42, 'run-2', 7, $this->fact(['medications' => 'DrugB 2 mg']));

        // The clinician's med + the new run's med remain (2); the prior run's is gone.
        $this->assertSame(2, $this->countRows("SELECT COUNT(*) c FROM lists WHERE type = 'medication'"));
        $this->assertSame(1, $this->countRows("SELECT COUNT(*) c FROM lists WHERE title = 'Clinician-entered Warfarin'"));
    }
}
