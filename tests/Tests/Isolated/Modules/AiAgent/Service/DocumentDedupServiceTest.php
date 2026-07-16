<?php

/**
 * T62 acceptance tests — PatientSummaryService::findDocumentIdByHash (idempotency).
 *
 * DB-backed and self-contained (mirrors ChartReadServiceDocumentsTest): manages a
 * throwaway schema cloned from `openemr` via an injected PDO. Proves the dedup
 * lookup the upload endpoint uses is patient-scoped and ignores deleted rows, so
 * re-uploading the same bytes to the same chart returns the existing document id
 * instead of storing a duplicate — while the same content on a DIFFERENT chart is
 * a distinct document.
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
final class DocumentDedupServiceTest extends TestCase
{
    private const SRC = 'openemr';
    private const TEST = 'openemr_ai_dedup_test';
    private const TABLES = ['documents'];

    // The upload endpoint stores hash('sha3-512', $bytes); the two fixtures use
    // distinct precomputed-style sentinels (any non-empty string works here).
    private const HASH_A = 'aaaa-hash-of-file-a';
    private const HASH_B = 'bbbb-hash-of-file-b';

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

    private function insertDoc(int $id, int $pid, string $hash, int $deleted = 0): void
    {
        $stmt = $this->db->prepare(
            'INSERT INTO documents (id, foreign_id, type, mimetype, name, docdate, date, revision, '
            . 'hash, deleted) '
            . "VALUES (?, ?, 'blob', 'application/pdf', 'doc.pdf', '2021-01-01', NOW(), NOW(), ?, ?)"
        );
        $stmt->execute([$id, $pid, $hash, $deleted]);
    }

    private function seed(): void
    {
        $this->insertDoc(501, 1, self::HASH_A);            // patient 1, file A
        $this->insertDoc(600, 2, self::HASH_A);            // patient 2, same bytes as A
        $this->insertDoc(700, 1, self::HASH_B, deleted: 1); // patient 1, file B but deleted
    }

    public function testReturnsTheExistingIdForTheSamePatientAndHash(): void
    {
        $id = (new PatientSummaryService($this->db))->findDocumentIdByHash(1, self::HASH_A);
        $this->assertSame(501, $id);
    }

    public function testReturnsNullForAHashThePatientHasNotUploaded(): void
    {
        $id = (new PatientSummaryService($this->db))->findDocumentIdByHash(1, 'never-seen-hash');
        $this->assertNull($id);
    }

    public function testIsPatientScopedSoTheSameBytesOnAnotherChartAreDistinct(): void
    {
        // Patient 2 has the same bytes (HASH_A) under a different id; patient 1's
        // lookup must never resolve to patient 2's document.
        $id = (new PatientSummaryService($this->db))->findDocumentIdByHash(2, self::HASH_A);
        $this->assertSame(600, $id);
    }

    public function testIgnoresDeletedDocuments(): void
    {
        // The only row with HASH_B is soft-deleted, so it must not count as a dup:
        // re-uploading file B should proceed to a fresh store.
        $id = (new PatientSummaryService($this->db))->findDocumentIdByHash(1, self::HASH_B);
        $this->assertNull($id);
    }
}
