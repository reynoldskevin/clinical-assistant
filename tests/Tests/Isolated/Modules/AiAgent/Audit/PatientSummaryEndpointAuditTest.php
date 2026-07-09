<?php

/**
 * T10 acceptance tests (LOCKED) — the boundary audits every access.
 *
 * A granted read records the principal; a denied attempt records the requested pid
 * and reason (and still reads no data). Isolated: real ScopedTokenService (fake clock),
 * a spy audit logger, a fake provider.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Audit;

use OpenEMR\Modules\AiAgent\Audit\BoundaryAuditLoggerInterface;
use OpenEMR\Modules\AiAgent\Auth\ClinicalPrincipal;
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
require_once $src . '/Audit/BoundaryAuditLoggerInterface.php';
require_once $src . '/Audit/NullBoundaryAuditLogger.php';
require_once $src . '/Boundary/PatientSummaryEndpoint.php';

#[Group('isolated')]
final class PatientSummaryEndpointAuditTest extends TestCase
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

    private function audit(): BoundaryAuditLoggerInterface
    {
        return new class implements BoundaryAuditLoggerInterface {
            public ?ClinicalPrincipal $granted = null;
            public int $grantedCount = 0;
            public int $deniedCount = 0;
            public int $deniedPid = 0;
            public string $deniedReason = '';
            public function recordGranted(ClinicalPrincipal $principal): void
            {
                $this->granted = $principal;
                $this->grantedCount++;
            }
            public function recordDenied(int $requestedPid, string $reason): void
            {
                $this->deniedCount++;
                $this->deniedPid = $requestedPid;
                $this->deniedReason = $reason;
            }
        };
    }

    private function provider(): PatientSummaryProviderInterface
    {
        return new class implements PatientSummaryProviderInterface {
            public bool $called = false;
            public function getSummary(int $pid): array
            {
                $this->called = true;
                return ['demographics' => ['pid' => $pid]];
            }
        };
    }

    private function principal(): ClinicalPrincipal
    {
        return new ClinicalPrincipal(7, 'dr_house', new PatientId(42), 'treatment');
    }

    public function testGrantedReadIsAudited(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $audit = $this->audit();
        $provider = $this->provider();
        $endpoint = new PatientSummaryEndpoint($tokens, $provider, $audit);

        $endpoint->handle($tokens->mint($this->principal()), 42);

        $this->assertSame(1, $audit->grantedCount);
        $this->assertSame(0, $audit->deniedCount);
        $this->assertNotNull($audit->granted);
        $this->assertSame(7, $audit->granted->clinicianId);
        $this->assertSame(42, $audit->granted->patientId->value);
        $this->assertTrue($provider->called);
    }

    public function testCrossPidDenialIsAuditedAndNoDataRead(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $audit = $this->audit();
        $provider = $this->provider();
        $endpoint = new PatientSummaryEndpoint($tokens, $provider, $audit);

        $token = $tokens->mint($this->principal()); // scoped to pid 42
        try {
            $endpoint->handle($token, 99);
            $this->fail('expected denial');
        } catch (\OpenEMR\Modules\AiAgent\Auth\InvalidScopedTokenException) {
            $this->addToAssertionCount(1);
        }

        $this->assertSame(1, $audit->deniedCount);
        $this->assertSame(99, $audit->deniedPid);
        $this->assertNotSame('', $audit->deniedReason);
        $this->assertSame(0, $audit->grantedCount);
        $this->assertFalse($provider->called, 'no data read on a denied request');
    }

    public function testGarbageTokenDenialIsAudited(): void
    {
        $tokens = new ScopedTokenService(self::KEY, $this->clock());
        $audit = $this->audit();
        $provider = $this->provider();
        $endpoint = new PatientSummaryEndpoint($tokens, $provider, $audit);

        try {
            $endpoint->handle('not.a.jwt', 42);
            $this->fail('expected denial');
        } catch (\OpenEMR\Modules\AiAgent\Auth\InvalidScopedTokenException) {
            $this->addToAssertionCount(1);
        }

        $this->assertSame(1, $audit->deniedCount);
        $this->assertSame(0, $audit->grantedCount);
        $this->assertFalse($provider->called);
    }
}
