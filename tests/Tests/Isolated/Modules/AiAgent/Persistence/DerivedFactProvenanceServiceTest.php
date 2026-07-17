<?php

/**
 * T53a acceptance tests (LOCKED) — DerivedFactProvenanceService.
 *
 * DB-backed but self-contained: manages its own disposable throwaway schema
 * (cloning `ai_derived_fact` from `openemr`, which the ticket's Doctrine migration
 * creates) via an injected PDO, so it has no dependency on the OpenEMR app
 * bootstrap. Mirrors PatientSummaryServiceTest.
 *
 * Pins the provenance contract T53b/T53c write against: record a derived-fact
 * row, list active rows for a document, and idempotently supersede a prior
 * extraction run's rows (returning their target refs so the caller can deactivate
 * the underlying clinical records).
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
use OpenEMR\Modules\AiAgent\Persistence\DerivedFactRef;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Persistence/DerivedFactRef.php';
require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Persistence/DerivedFactProvenanceService.php';

#[Group('isolated')]
final class DerivedFactProvenanceServiceTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_prov_test';
    private const TABLES = ['ai_derived_fact'];

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

    private function ref(string $factType, string $table, int $targetId, string $summary, ?string $uuidHex = null): DerivedFactRef
    {
        return new DerivedFactRef($factType, $table, $targetId, $uuidHex, $summary);
    }

    public function testRecordInsertsAndActiveForReadsItBack(): void
    {
        $svc = new DerivedFactProvenanceService($this->db);
        $id = $svc->record(1, 42, 'lab_pdf', 'run-abc', 7, $this->ref('lab_result', 'procedure_result', 100, 'Glucose 95 mg/dL'));

        $this->assertGreaterThan(0, $id);

        $active = $svc->activeFor(1, 42);
        $this->assertCount(1, $active);
        $this->assertSame('lab_result', $active[0]->factType);
        $this->assertSame('procedure_result', $active[0]->targetTable);
        $this->assertSame(100, $active[0]->targetId);
        $this->assertSame('Glucose 95 mg/dL', $active[0]->factSummary);

        // A uuid was minted (16 bytes) for the row.
        $row = $this->db->query('SELECT LENGTH(uuid) AS len FROM ai_derived_fact WHERE id = ' . $id)->fetch();
        $this->assertSame(16, (int) $row['len']);
    }

    public function testTargetUuidRoundTrips(): void
    {
        $svc = new DerivedFactProvenanceService($this->db);
        $uuidHex = '0123456789abcdef0123456789abcdef';
        $svc->record(1, 42, 'intake_form', 'run-x', 7, $this->ref('medication', 'prescriptions', 200, 'Metformin 500 mg', $uuidHex));

        $active = $svc->activeFor(1, 42);
        $this->assertSame($uuidHex, $active[0]->targetUuid);
    }

    public function testSupersedePriorRunFlipsOnlyMatchingFactTypeAndReturnsRefs(): void
    {
        $svc = new DerivedFactProvenanceService($this->db);
        // Run 1: a lab result AND a medication for the same document.
        $svc->record(1, 42, 'lab_pdf', 'run-1', 7, $this->ref('lab_result', 'procedure_result', 100, 'Glucose 95'));
        $svc->record(1, 42, 'lab_pdf', 'run-1', 7, $this->ref('medication', 'prescriptions', 200, 'Metformin'));

        // Superseding lab_result must return the prior lab ref and leave the med alone.
        $superseded = $svc->supersedePriorRun(1, 42, 'lab_result');
        $this->assertCount(1, $superseded);
        $this->assertSame('procedure_result', $superseded[0]->targetTable);
        $this->assertSame(100, $superseded[0]->targetId);

        // Run 2: the new lab result.
        $svc->record(1, 42, 'lab_pdf', 'run-2', 7, $this->ref('lab_result', 'procedure_result', 101, 'Glucose 110'));

        $active = $svc->activeFor(1, 42);
        $summaries = array_map(fn (DerivedFactRef $r) => $r->factSummary, $active);
        sort($summaries);
        // The old lab (100) is gone from active; the med (200) and new lab (101) remain.
        $this->assertSame(['Glucose 110', 'Metformin'], $summaries);
    }

    public function testSupersedeSetsSupersededAtTimestamp(): void
    {
        $svc = new DerivedFactProvenanceService($this->db);
        $svc->record(1, 42, 'lab_pdf', 'run-1', 7, $this->ref('lab_result', 'procedure_result', 100, 'Glucose 95'));
        $svc->supersedePriorRun(1, 42, 'lab_result');

        $row = $this->db->query(
            "SELECT active, superseded_at FROM ai_derived_fact WHERE target_id = 100"
        )->fetch();
        $this->assertSame(0, (int) $row['active']);
        $this->assertNotNull($row['superseded_at']);
    }

    public function testSupersedeIsIdempotent(): void
    {
        $svc = new DerivedFactProvenanceService($this->db);
        $svc->record(1, 42, 'lab_pdf', 'run-1', 7, $this->ref('lab_result', 'procedure_result', 100, 'Glucose 95'));

        $first = $svc->supersedePriorRun(1, 42, 'lab_result');
        $this->assertCount(1, $first);
        $second = $svc->supersedePriorRun(1, 42, 'lab_result');
        $this->assertCount(0, $second);
    }

    public function testSupersedeIsScopedToPidAndDocument(): void
    {
        $svc = new DerivedFactProvenanceService($this->db);
        $svc->record(1, 42, 'lab_pdf', 'run-1', 7, $this->ref('lab_result', 'procedure_result', 100, 'A'));
        $svc->record(2, 42, 'lab_pdf', 'run-1', 7, $this->ref('lab_result', 'procedure_result', 101, 'B')); // other pid
        $svc->record(1, 99, 'lab_pdf', 'run-1', 7, $this->ref('lab_result', 'procedure_result', 102, 'C')); // other doc

        $svc->supersedePriorRun(1, 42, 'lab_result');

        // Only pid=1/doc=42 was superseded; the other pid and other document stay active.
        $this->assertCount(0, $svc->activeFor(1, 42));
        $this->assertCount(1, $svc->activeFor(2, 42));
        $this->assertCount(1, $svc->activeFor(1, 99));
    }
}
