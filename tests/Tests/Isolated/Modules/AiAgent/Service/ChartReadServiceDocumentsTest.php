<?php

/**
 * T46 acceptance tests (LOCKED) — PatientSummaryService document reads.
 *
 * DB-backed but self-contained: manages its own disposable throwaway schema
 * (cloned from `openemr`) via an injected PDO, mirroring the other ChartRead
 * service tests. Proves the two document reads are patient-scoped:
 * getDocuments returns ONLY the given patient's documents as metadata (never the
 * document_data blob), and getDocument refuses to return a document that belongs
 * to a DIFFERENT patient even when its id is supplied. doc_type is carried on the
 * `documentationOf` column (the upload endpoint records the chosen doc_type there).
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
final class ChartReadServiceDocumentsTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_doc_test';
    private const TABLES = ['documents'];

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

    private function insertDoc(int $id, int $pid, string $name, string $docType, string $date, string $data, int $deleted = 0): void
    {
        $stmt = $this->db->prepare(
            'INSERT INTO documents (id, foreign_id, type, mimetype, name, docdate, date, revision, '
            . 'documentationOf, document_data, deleted) '
            . "VALUES (?, ?, 'blob', 'application/pdf', ?, ?, ?, NOW(), ?, ?, ?)"
        );
        $stmt->execute([$id, $pid, $name, substr($date, 0, 10), $date, $docType, $data, $deleted]);
    }

    private function seed(): void
    {
        // Patient 1: two documents (a lab pdf and an intake form) + one deleted doc.
        $this->insertDoc(501, 1, 'labs-2021.pdf', 'lab_pdf', '2021-03-20 09:00:00', 'PID1-LAB-BLOB');
        $this->insertDoc(502, 1, 'intake.pdf', 'intake_form', '2021-06-01 09:00:00', 'PID1-INTAKE-BLOB');
        $this->insertDoc(503, 1, 'old-deleted.pdf', 'lab_pdf', '2020-01-01 09:00:00', 'PID1-DELETED', 1);
        // Patient 2: one document whose id (600) must never leak to patient 1.
        $this->insertDoc(600, 2, 'other-labs.pdf', 'lab_pdf', '2021-05-01 09:00:00', 'PID2-LAB-BLOB');
    }

    public function testGetDocumentsReturnsOnlyThatPatientMostRecentFirst(): void
    {
        $docs = (new PatientSummaryService($this->db))->getDocuments(1);

        // Patient 2's doc excluded; the deleted doc excluded.
        $this->assertCount(2, $docs);
        $ids = array_map(static fn (array $d): int => (int) $d['id'], $docs);
        $this->assertSame([502, 501], $ids); // most-recent-first by date
    }

    public function testGetDocumentsReturnsMetadataButNeverTheBlob(): void
    {
        $docs = (new PatientSummaryService($this->db))->getDocuments(1);

        $first = $docs[0];
        $this->assertArrayHasKey('id', $first);
        $this->assertArrayHasKey('name', $first);
        $this->assertArrayHasKey('mimetype', $first);
        $this->assertArrayHasKey('doc_type', $first);
        $this->assertSame('intake_form', $first['doc_type']);
        // Minimum-necessary: the document listing must NEVER carry the raw blob.
        $this->assertArrayNotHasKey('document_data', $first);
    }

    public function testGetDocumentReturnsOwnDocumentContent(): void
    {
        $doc = (new PatientSummaryService($this->db))->getDocument(1, 501);

        $this->assertNotSame([], $doc);
        $this->assertSame(501, (int) $doc['id']);
        $this->assertSame('lab_pdf', $doc['doc_type']);
        // getDocument (single, explicit fetch) DOES carry the content for extraction.
        $this->assertSame('PID1-LAB-BLOB', $doc['document_data']);
    }

    public function testGetDocumentForAnotherPatientsIdReturnsEmpty(): void
    {
        // Document 600 belongs to patient 2. Requesting it as patient 1 must
        // return nothing — a model cannot cross patients by guessing an id.
        $doc = (new PatientSummaryService($this->db))->getDocument(1, 600);

        $this->assertSame([], $doc);
    }

    public function testGetDocumentForMissingIdReturnsEmpty(): void
    {
        $doc = (new PatientSummaryService($this->db))->getDocument(1, 999999);

        $this->assertSame([], $doc);
    }

    public function testGetDocumentForDeletedDocumentReturnsEmpty(): void
    {
        $doc = (new PatientSummaryService($this->db))->getDocument(1, 503);

        $this->assertSame([], $doc);
    }
}
