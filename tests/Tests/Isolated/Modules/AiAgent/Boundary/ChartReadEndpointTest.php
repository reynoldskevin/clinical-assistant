<?php

/**
 * T17 acceptance tests (LOCKED) — ChartReadEndpoint (multi-tool boundary).
 *
 * One operation-dispatched, verify-before-read boundary. The scoped token (T08)
 * is validated ONCE for the requested pid before any chart data is fetched, then
 * the request is dispatched to the provider by ChartOperation. A denied request
 * (cross-pid / invalid / expired) must read NO data for ANY operation — the same
 * fail-closed guarantee PatientSummaryEndpoint gives, now generalized.
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
final class ChartReadEndpointTest extends TestCase
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
                return ['demographics' => ['pid' => $pid]];
            }
            public function listEncounters(int $pid): array
            {
                $this->calls[] = ['list_encounters', $pid, 0];
                return [['encounter' => 5, 'pid' => $pid]];
            }
            public function getEncounter(int $pid, int $encounterId): array
            {
                $this->calls[] = ['get_encounter', $pid, $encounterId];
                return ['encounter' => $encounterId, 'pid' => $pid];
            }
            public function getResults(int $pid): array
            {
                $this->calls[] = ['get_results', $pid, 0];
                return [['result_code' => '2339-0', 'pid' => $pid]];
            }
            public function getMedications(int $pid, bool $activeOnly): array
            {
                $this->calls[] = ['get_medications', $pid, $activeOnly ? 1 : 0];
                return [['drug' => 'Metformin', 'pid' => $pid]];
            }
            public string $lastQuery = '';
            public function searchChart(int $pid, string $query, int $limit): array
            {
                $this->lastQuery = $query;
                $this->calls[] = ['search_chart', $pid, $limit];
                return [['ref' => 'pnote:1', 'source_type' => 'note', 'pid' => $pid]];
            }
        };
    }

    private function principal(): ClinicalPrincipal
    {
        return new ClinicalPrincipal(7, 'dr_house', new PatientId(42), 'treatment');
    }

    public function testValidTokenDispatchesSummary(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $result = $endpoint->handle($tokens->mint($this->principal()), 42, ChartOperation::Summary);

        $this->assertSame(['demographics' => ['pid' => 42]], $result);
        $this->assertSame([['summary', 42, 0]], $provider->calls);
    }

    public function testValidTokenDispatchesListEncounters(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $result = $endpoint->handle($tokens->mint($this->principal()), 42, ChartOperation::ListEncounters);

        $this->assertSame([['encounter' => 5, 'pid' => 42]], $result);
        $this->assertSame([['list_encounters', 42, 0]], $provider->calls);
    }

    public function testValidTokenDispatchesGetEncounterWithParam(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $result = $endpoint->handle(
            $tokens->mint($this->principal()),
            42,
            ChartOperation::GetEncounter,
            ['encounter_id' => 88],
        );

        $this->assertSame(['encounter' => 88, 'pid' => 42], $result);
        // The pid comes from the token (42), the encounter id from params (88).
        $this->assertSame([['get_encounter', 42, 88]], $provider->calls);
    }

    public function testValidTokenDispatchesGetResults(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $result = $endpoint->handle($tokens->mint($this->principal()), 42, ChartOperation::GetResults);

        $this->assertSame([['result_code' => '2339-0', 'pid' => 42]], $result);
        $this->assertSame([['get_results', 42, 0]], $provider->calls);
    }

    public function testValidTokenDispatchesGetMedicationsWithActiveOnlyParam(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $result = $endpoint->handle(
            $tokens->mint($this->principal()),
            42,
            ChartOperation::GetMedications,
            ['active_only' => true],
        );

        $this->assertSame([['drug' => 'Metformin', 'pid' => 42]], $result);
        // pid from the token (42); active_only from params (true -> 1).
        $this->assertSame([['get_medications', 42, 1]], $provider->calls);
    }

    public function testGetMedicationsDefaultsActiveOnlyToFalseWhenParamAbsent(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $endpoint->handle($tokens->mint($this->principal()), 42, ChartOperation::GetMedications);

        $this->assertSame([['get_medications', 42, 0]], $provider->calls);
    }

    public function testValidTokenDispatchesSearchChartWithQueryAndLimit(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $result = $endpoint->handle(
            $tokens->mint($this->principal()),
            42,
            ChartOperation::SearchChart,
            ['query' => 'chest pain', 'limit' => 5],
        );

        $this->assertSame([['ref' => 'pnote:1', 'source_type' => 'note', 'pid' => 42]], $result);
        // pid from the token (42); query + limit from params.
        $this->assertSame([['search_chart', 42, 5]], $provider->calls);
        $this->assertSame('chest pain', $provider->lastQuery);
    }

    public function testSearchChartDefaultsLimitWhenAbsent(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $endpoint->handle($tokens->mint($this->principal()), 42, ChartOperation::SearchChart, ['query' => 'x']);

        // Default limit is 20 when the model omits it.
        $this->assertSame([['search_chart', 42, 20]], $provider->calls);
    }

    public function testCrossPidTokenIsDeniedAndNoDataIsReadForEveryOperation(): void
    {
        foreach (ChartOperation::cases() as $op) {
            $tokens = new ScopedTokenService(self::KEY, $this->clock());
            $provider = $this->provider();
            $endpoint = new ChartReadEndpoint($tokens, $provider);

            $token = $tokens->mint($this->principal()); // scoped to pid 42

            $this->denied(fn () => $endpoint->handle($token, 99, $op, ['encounter_id' => 1]));
            $this->assertSame([], $provider->calls, "no read for a cross-pid {$op->value} request");
        }
    }

    public function testGarbageTokenIsDeniedAndNoDataIsRead(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $this->denied(fn () => $endpoint->handle('not.a.jwt', 42, ChartOperation::ListEncounters));
        $this->assertSame([], $provider->calls);
    }

    public function testExpiredTokenIsDeniedAndNoDataIsRead(): void
    {
        $clock = $this->clock();
        $tokens = new ScopedTokenService(self::KEY, $clock, 'oe-ai-agent-boundary', 300);
        $provider = $this->provider();
        $endpoint = new ChartReadEndpoint($tokens, $provider);

        $token = $tokens->mint($this->principal());
        $clock->now = $clock->now->modify('+301 seconds');

        $this->denied(fn () => $endpoint->handle($token, 42, ChartOperation::GetEncounter, ['encounter_id' => 1]));
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
