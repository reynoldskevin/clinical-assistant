<?php

/**
 * T20 acceptance tests (LOCKED) — PatientSummaryService::searchChart.
 *
 * DB-backed, self-contained disposable schema (cloned from `openemr`) via an
 * injected PDO. Proves the free-text chart search is patient-scoped, spans the
 * note sources (`pnotes` + `form_soap`), returns snippet rows (never whole
 * documents), honours the result limit, and rejects an empty query.
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
final class ChartReadServiceSearchTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_search_test';
    private const TABLES = ['pnotes', 'form_soap'];

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

    private function pnote(int $pid, string $title, string $body, string $date): void
    {
        $stmt = $this->db->prepare(
            'INSERT INTO pnotes (pid, title, body, date, activity) VALUES (?, ?, ?, ?, 1)'
        );
        $stmt->execute([$pid, $title, $body, $date]);
    }

    private function soap(int $pid, string $s, string $o, string $a, string $p, string $date): void
    {
        $stmt = $this->db->prepare(
            'INSERT INTO form_soap (pid, subjective, objective, assessment, plan, date, activity)
             VALUES (?, ?, ?, ?, ?, ?, 1)'
        );
        $stmt->execute([$pid, $s, $o, $a, $p, $date]);
    }

    private function seed(): void
    {
        // Patient 1 — a note, a SOAP note, two "followup" notes, and a long note.
        $this->pnote(1, 'Cardiology visit', 'Patient reports chest pain and shortness of breath.', '2021-05-01 10:00:00');
        $this->soap(1, 'Complains of severe headache', 'BP 120/80', 'Tension headache', 'Rest and fluids', '2020-03-01 10:00:00');
        $this->pnote(1, 'Note one', 'Routine followup scheduled.', '2019-01-01 10:00:00');
        $this->pnote(1, 'Note two', 'Second followup completed.', '2018-01-01 10:00:00');
        $this->pnote(1, 'Long note', 'marker ' . str_repeat('x', 1000), '2017-01-01 10:00:00');

        // Patient 2 — must never surface for patient 1's searches.
        $this->pnote(2, 'Endocrine', 'Patient has diabetes mellitus, poorly controlled.', '2021-06-01 10:00:00');
    }

    public function testFindsANoteByBodyTextScopedToThePatient(): void
    {
        $hits = (new PatientSummaryService($this->db))->searchChart(1, 'chest pain', 20);

        $this->assertNotSame([], $hits);
        $hit = $hits[0];
        foreach (['ref', 'source_type', 'date', 'snippet'] as $key) {
            $this->assertArrayHasKey($key, $hit);
        }
        $this->assertSame('note', $hit['source_type']);
        $this->assertStringContainsStringIgnoringCase('chest pain', (string) $hit['snippet']);
    }

    public function testFindsASoapNote(): void
    {
        $hits = (new PatientSummaryService($this->db))->searchChart(1, 'headache', 20);

        $types = array_column($hits, 'source_type');
        $this->assertContains('soap', $types);
        $soap = null;
        foreach ($hits as $h) {
            if ($h['source_type'] === 'soap') {
                $soap = $h;
            }
        }
        $this->assertStringContainsStringIgnoringCase('headache', (string) $soap['snippet']);
    }

    public function testCrossPatientIsolation(): void
    {
        $service = new PatientSummaryService($this->db);

        // Patient 2's "diabetes" note must NOT be visible to patient 1.
        $this->assertSame([], $service->searchChart(1, 'diabetes', 20));
        // Patient 2 sees their own note.
        $this->assertNotSame([], $service->searchChart(2, 'diabetes', 20));
    }

    public function testLimitCapsTheNumberOfHits(): void
    {
        $hits = (new PatientSummaryService($this->db))->searchChart(1, 'followup', 1);

        $this->assertCount(1, $hits); // two "followup" notes seeded, capped to one
    }

    public function testEmptyQueryReturnsNoHits(): void
    {
        $this->assertSame([], (new PatientSummaryService($this->db))->searchChart(1, '   ', 20));
    }

    public function testSnippetIsTruncatedNotTheWholeDocument(): void
    {
        $hits = (new PatientSummaryService($this->db))->searchChart(1, 'marker', 20);

        $this->assertNotSame([], $hits);
        $snippet = (string) $hits[0]['snippet'];
        $this->assertStringContainsStringIgnoringCase('marker', $snippet);
        // Minimum-necessary: a snippet, never the full 1000+ char body.
        $this->assertLessThanOrEqual(300, strlen($snippet));
    }
}
