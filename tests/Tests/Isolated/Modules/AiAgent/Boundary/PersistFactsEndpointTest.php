<?php

/**
 * T53d acceptance tests (LOCKED) — PersistFactsEndpoint.
 *
 * The testable core of persist.php: given a parsed, clinician-authorized request
 * (pid + document + extraction-run + doc_type + fact + clinician id), dispatch to
 * the right persister (LabFactPersister for lab_pdf, IntakeFactPersister for
 * intake_form) and return a normalized response. DB-backed via a throwaway schema
 * so the dispatch is proven end-to-end against the real persisters.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Boundary;

use OpenEMR\Modules\AiAgent\Boundary\PersistFactsEndpoint;
use OpenEMR\Modules\AiAgent\Persistence\DerivedFactProvenanceService;
use OpenEMR\Modules\AiAgent\Persistence\IntakeFactPersister;
use OpenEMR\Modules\AiAgent\Persistence\LabFactPersister;
use OpenEMR\Modules\AiAgent\Persistence\NarrativeFieldSplitter;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

$persist = __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Persistence/';
require_once $persist . 'DerivedFactRef.php';
require_once $persist . 'DerivedFactProvenanceService.php';
require_once $persist . 'NarrativeFieldSplitter.php';
require_once $persist . 'LabFactPersister.php';
require_once $persist . 'IntakeFactPersister.php';
require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Boundary/PersistFactsEndpoint.php';

#[Group('isolated')]
final class PersistFactsEndpointTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_persist_test';
    private const TABLES = [
        'procedure_order', 'procedure_report', 'procedure_result',
        'prescriptions', 'lists', 'pnotes', 'ai_derived_fact',
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
    }

    protected function tearDown(): void
    {
        $this->connect(null)->exec('DROP DATABASE IF EXISTS `' . self::TEST . '`');
    }

    private function endpoint(): PersistFactsEndpoint
    {
        $prov = new DerivedFactProvenanceService($this->db);
        return new PersistFactsEndpoint(
            new LabFactPersister($this->db, $prov),
            new IntakeFactPersister($this->db, $prov, new NarrativeFieldSplitter())
        );
    }

    private function countRows(string $sql): int
    {
        return (int) $this->db->query($sql)->fetch()['c'];
    }

    public function testDispatchesLabFactToLabPersister(): void
    {
        $fact = [
            'test_name' => 'Hemoglobin A1c', 'value' => '7.4', 'unit' => '%',
            'reference_range' => '4.0-5.6', 'collection_date' => '2026-05-01',
            'abnormal_flag' => 'High', 'source_citation' => 'p1',
        ];
        $resp = $this->endpoint()->handle(1, 42, 'run-1', 'lab_pdf', $fact, 7);

        // A real lab result row was written.
        $this->assertSame(1, $this->countRows('SELECT COUNT(*) c FROM procedure_result'));
        // Normalized response.
        $this->assertTrue($resp['ok']);
        $this->assertSame('lab_pdf', $resp['doc_type']);
        $this->assertSame(1, (int) $resp['total']);
        $factTypes = array_column($resp['filed'], 'count', 'fact_type');
        $this->assertSame(1, (int) $factTypes['lab_result']);
    }

    public function testDispatchesIntakeFactToIntakePersister(): void
    {
        $fact = [
            'demographics' => 'Name: Jane Doe',
            'chief_concern' => 'Chest tightness',
            'current_medications' => 'Lisinopril 10 mg; Metformin 500 mg',
            'allergies' => 'Penicillin (rash)',
            'family_history' => 'Father: MI',
            'source_citation' => 'p1',
        ];
        $resp = $this->endpoint()->handle(1, 42, 'run-1', 'intake_form', $fact, 7);

        $this->assertSame(2, $this->countRows('SELECT COUNT(*) c FROM prescriptions WHERE active = 1'));
        $this->assertSame(1, $this->countRows("SELECT COUNT(*) c FROM lists WHERE type = 'allergy'"));
        $this->assertSame(1, $this->countRows("SELECT COUNT(*) c FROM lists WHERE type = 'medical_problem'"));
        $this->assertSame(1, $this->countRows('SELECT COUNT(*) c FROM pnotes'));

        $this->assertTrue($resp['ok']);
        $this->assertSame('intake_form', $resp['doc_type']);
        $factTypes = array_column($resp['filed'], 'count', 'fact_type');
        $this->assertSame(2, (int) $factTypes['medication']);
        $this->assertSame(1, (int) $factTypes['allergy']);
        $this->assertSame(5, (int) $resp['total']); // 2 meds + 1 allergy + 1 problem + 1 concern
    }

    public function testUnknownDocTypeWritesNothingAndThrows(): void
    {
        $this->expectException(\DomainException::class);
        try {
            $this->endpoint()->handle(1, 42, 'run-1', 'not_a_type', ['x' => 'y'], 7);
        } finally {
            // No clinical rows written for an unknown doc_type.
            $this->assertSame(0, $this->countRows('SELECT COUNT(*) c FROM ai_derived_fact'));
            $this->assertSame(0, $this->countRows('SELECT COUNT(*) c FROM procedure_result'));
            $this->assertSame(0, $this->countRows('SELECT COUNT(*) c FROM prescriptions'));
        }
    }
}
