<?php

/**
 * T09b acceptance tests (LOCKED) — PatientSummaryEndpoint boundary.
 *
 * Verify-before-read: the scoped token is validated (T08) before any chart data is
 * fetched. A denied request (cross-pid / invalid / expired) must NOT read data.
 * Isolated: real ScopedTokenService (fake clock) + a fake summary provider.
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
use OpenEMR\Modules\AiAgent\Boundary\PatientSummaryEndpoint;
use OpenEMR\Modules\AiAgent\Service\PatientSummaryProviderInterface;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;
use Psr\Clock\ClockInterface;

$src = __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src';
require_once $src . '/Auth/PatientId.php';
require_once $src . '/Auth/ClinicalPrincipal.php';
require_once $src . '/Auth/InvalidScopedTokenException.php';
require_once $src . '/Auth/ScopedTokenService.php';
require_once $src . '/Service/PatientSummaryProviderInterface.php';
require_once $src . '/Boundary/PatientSummaryEndpoint.php';

#[Group('isolated')]
final class PatientSummaryEndpointTest extends TestCase
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

    /** A fake provider that records whether it was called and with what pid. */
    private function provider(): PatientSummaryProviderInterface
    {
        return new class implements PatientSummaryProviderInterface {
            public bool $called = false;
            public int $lastPid = 0;
            public array $summary = ['demographics' => ['pid' => 42, 'fname' => 'Jane']];
            public function getSummary(int $pid): array
            {
                $this->called = true;
                $this->lastPid = $pid;
                return $this->summary;
            }
        };
    }

    private function principal(): ClinicalPrincipal
    {
        return new ClinicalPrincipal(7, 'dr_house', new PatientId(42), 'treatment');
    }

    public function testValidTokenReturnsSummaryAndReadsTheRightPatient(): void
    {
        $clock = $this->clock();
        $tokens = new ScopedTokenService(self::KEY, $clock);
        $provider = $this->provider();
        $endpoint = new PatientSummaryEndpoint($tokens, $provider);

        $token = $tokens->mint($this->principal());
        $result = $endpoint->handle($token, 42);

        $this->assertSame($provider->summary, $result);
        $this->assertTrue($provider->called);
        $this->assertSame(42, $provider->lastPid);
    }

    public function testCrossPidTokenIsDeniedAndNoDataIsRead(): void
    {
        $clock = $this->clock();
        $tokens = new ScopedTokenService(self::KEY, $clock);
        $provider = $this->provider();
        $endpoint = new PatientSummaryEndpoint($tokens, $provider);

        $token = $tokens->mint($this->principal()); // scoped to pid 42

        $this->denied(fn () => $endpoint->handle($token, 99));
        $this->assertFalse($provider->called, 'summary must NOT be read for a cross-pid request');
    }

    public function testGarbageTokenIsDeniedAndNoDataIsRead(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $provider = $this->provider();
        $endpoint = new PatientSummaryEndpoint($tokens, $provider);

        $this->denied(fn () => $endpoint->handle('not.a.valid.jwt', 42));
        $this->assertFalse($provider->called);
    }

    public function testExpiredTokenIsDeniedAndNoDataIsRead(): void
    {
        $clock = $this->clock();
        $tokens = new ScopedTokenService(self::KEY, $clock, 'oe-ai-agent-boundary', 300);
        $provider = $this->provider();
        $endpoint = new PatientSummaryEndpoint($tokens, $provider);

        $token = $tokens->mint($this->principal());
        $clock->now = $clock->now->modify('+301 seconds');

        $this->denied(fn () => $endpoint->handle($token, 42));
        $this->assertFalse($provider->called);
    }

    /** Assert the callable throws InvalidScopedTokenException (so we can also assert side effects after). */
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
