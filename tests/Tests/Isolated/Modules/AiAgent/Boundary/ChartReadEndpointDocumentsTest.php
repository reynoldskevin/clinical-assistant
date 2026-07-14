<?php

/**
 * T46 acceptance tests (LOCKED) — ChartReadEndpoint document operations.
 *
 * The two new read operations, get_documents (list this patient's documents,
 * metadata only) and get_document (one document's content by id), dispatch
 * through the SAME verify-before-read boundary as every other chart read: the
 * scoped token is validated once for the requested pid, the pid comes from the
 * token (never the wire), and a denied token reads NO document for either op.
 *
 * Isolated: real ScopedTokenService (fake clock) + a fake ChartRead provider.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Boundary;

use OpenEMR\Modules\AiAgent\Auth\ClinicalPrincipal;
use OpenEMR\Modules\AiAgent\Auth\InvalidScopedTokenException;
use OpenEMR\Modules\AiAgent\Auth\PatientId;
use OpenEMR\Modules\AiAgent\Auth\ScopedTokenService;
use OpenEMR\Modules\AiAgent\Boundary\ChartOperation;
use OpenEMR\Modules\AiAgent\Boundary\ChartReadEndpoint;
use OpenEMR\Modules\AiAgent\Service\ChartReadProviderInterface;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;
use Psr\Clock\ClockInterface;

$src = __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src';
require_once $src . '/Auth/PatientId.php';
require_once $src . '/Auth/ClinicalPrincipal.php';
require_once $src . '/Auth/InvalidScopedTokenException.php';
require_once $src . '/Auth/ScopedTokenService.php';
require_once $src . '/Service/PatientSummaryProviderInterface.php';
require_once $src . '/Service/ChartReadProviderInterface.php';
require_once $src . '/Boundary/ChartOperation.php';
require_once $src . '/Boundary/ChartReadEndpoint.php';

#[Group('isolated')]
final class ChartReadEndpointDocumentsTest extends TestCase
{
    private const KEY = 'test-signing-key-0123456789-abcdef';

    private function clock(string $iso = '2026-01-01T00:00:00+00:00'): ClockInterface
    {
        return new class ($iso) implements ClockInterface {
            public \DateTimeImmutable $now;
            public function __construct(string $iso)
            {
                $this->now = new \DateTimeImmutable($iso);
            }
            public function now(): \DateTimeImmutable
            {
                return $this->now;
            }
        };
    }

    /** A fake provider recording which method ran, with which pid + args. */
    private function provider(): ChartReadProviderInterface
    {
        return new class implements ChartReadProviderInterface {
            /** @var list<array{string, int, int}> */
            public array $calls = [];
            public function getSummary(int $pid): array
            {
                $this->calls[] = ['summary', $pid, 0];
                return [];
            }
            public function listEncounters(int $pid): array
            {
                $this->calls[] = ['list_encounters', $pid, 0];
                return [];
            }
            public function getEncounter(int $pid, int $encounterId): array
            {
                $this->calls[] = ['get_encounter', $pid, $encounterId];
                return [];
            }
            public function getResults(int $pid): array
            {
                $this->calls[] = ['get_results', $pid, 0];
                return [];
            }
            public function getMedications(int $pid, bool $activeOnly): array
            {
                $this->calls[] = ['get_medications', $pid, $activeOnly ? 1 : 0];
                return [];
            }
            public function searchChart(int $pid, string $query, int $limit): array
            {
                $this->calls[] = ['search_chart', $pid, $limit];
                return [];
            }
            public function getDocuments(int $pid): array
            {
                $this->calls[] = ['get_documents', $pid, 0];
                return [['id' => 501, 'name' => 'labs.pdf', 'mimetype' => 'application/pdf', 'pid' => $pid]];
            }
            public function getDocument(int $pid, int $documentId): array
            {
                $this->calls[] = ['get_document', $pid, $documentId];
                return ['id' => $documentId, 'mimetype' => 'application/pdf', 'content' => 'BASE64', 'pid' => $pid];
            }
        };
    }

    private function principal(): ClinicalPrincipal
    {
        return new ClinicalPrincipal(7, 'dr_house', new PatientId(42), 'treatment');
    }

    public function testGetDocumentsAndGetDocumentAreOnTheWhitelist(): void
    {
        // The two new operations parse from their wire strings into the enum.
        $this->assertSame(ChartOperation::GetDocuments, ChartOperation::tryFrom('get_documents'));
        $this->assertSame(ChartOperation::GetDocument, ChartOperation::tryFrom('get_document'));
    }

    public function testValidTokenDispatchesGetDocuments(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $result = $endpoint->handle($tokens->mint($this->principal()), 42, ChartOperation::GetDocuments);

        $this->assertSame(
            [['id' => 501, 'name' => 'labs.pdf', 'mimetype' => 'application/pdf', 'pid' => 42]],
            $result,
        );
        // pid comes from the token (42), not the wire.
        $this->assertSame([['get_documents', 42, 0]], $provider->calls);
    }

    public function testValidTokenDispatchesGetDocumentWithDocumentIdParam(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $result = $endpoint->handle(
            $tokens->mint($this->principal()),
            42,
            ChartOperation::GetDocument,
            ['document_id' => 501],
        );

        $this->assertSame(
            ['id' => 501, 'mimetype' => 'application/pdf', 'content' => 'BASE64', 'pid' => 42],
            $result,
        );
        // pid from the token (42); document id from params (501).
        $this->assertSame([['get_document', 42, 501]], $provider->calls);
    }

    public function testGetDocumentDefaultsMissingIdToZero(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $endpoint->handle($tokens->mint($this->principal()), 42, ChartOperation::GetDocument);

        $this->assertSame([['get_document', 42, 0]], $provider->calls);
    }

    public function testCrossPidTokenIsDeniedForBothDocumentOps(): void
    {
        foreach ([ChartOperation::GetDocuments, ChartOperation::GetDocument] as $op) {
            $tokens = new ScopedTokenService(self::KEY, $this->clock());
            $provider = $this->provider();
            $endpoint = new ChartReadEndpoint($tokens, $provider);

            $token = $tokens->mint($this->principal()); // scoped to pid 42

            $this->denied(fn () => $endpoint->handle($token, 99, $op, ['document_id' => 501]));
            $this->assertSame([], $provider->calls, "no read for a cross-pid {$op->value} request");
        }
    }

    public function testExpiredTokenIsDeniedForDocumentReads(): void
    {
        $clock = $this->clock();
        $tokens = new ScopedTokenService(self::KEY, $clock, 'oe-ai-agent-boundary', 300);
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $token = $tokens->mint($this->principal());
        $clock->now = $clock->now->modify('+301 seconds');

        $this->denied(fn () => $endpoint->handle($token, 42, ChartOperation::GetDocument, ['document_id' => 501]));
        $this->assertSame([], $provider->calls);
    }

    private function denied(callable $fn): void
    {
        try {
            $fn();
            $this->fail('expected InvalidScopedTokenException');
        } catch (InvalidScopedTokenException) {
            $this->addToAssertionCount(1);
        }
    }
}
