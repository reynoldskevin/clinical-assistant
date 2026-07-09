<?php

/**
 * T08 acceptance tests (LOCKED) — scoped-token mint/verify service.
 *
 * Short-lived, pid-scoped JWT (custom-JWT auth model, ARCHITECTURE §1a). Isolated:
 * a fake PSR-20 clock makes expiry deterministic; no DB, no HTTP.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Auth;

use OpenEMR\Modules\AiAgent\Auth\ClinicalPrincipal;
use OpenEMR\Modules\AiAgent\Auth\InvalidScopedTokenException;
use OpenEMR\Modules\AiAgent\Auth\PatientId;
use OpenEMR\Modules\AiAgent\Auth\ScopedTokenService;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;
use Psr\Clock\ClockInterface;

$moduleSrc = __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Auth';
require_once $moduleSrc . '/PatientId.php';
require_once $moduleSrc . '/ClinicalPrincipal.php';
require_once $moduleSrc . '/InvalidScopedTokenException.php';
require_once $moduleSrc . '/ScopedTokenService.php';

#[Group('isolated')]
final class ScopedTokenServiceTest extends TestCase
{
    private const KEY = 'test-signing-key-0123456789-abcdef';

    /** A mutable fake clock so we can advance past token expiry. */
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

    private function principal(): ClinicalPrincipal
    {
        return new ClinicalPrincipal(7, 'dr_house', new PatientId(42), 'treatment');
    }

    public function testMintThenVerifyRoundTripsThePrincipal(): void
    {
        $svc = new ScopedTokenService(self::KEY, $this->clock());
        $token = $svc->mint($this->principal());
        $this->assertIsString($token);
        $this->assertNotSame('', $token);

        $out = $svc->verify($token, 42);
        $this->assertSame(7, $out->clinicianId);
        $this->assertSame('dr_house', $out->clinicianUsername);
        $this->assertSame(42, $out->patientId->value);
        $this->assertSame('treatment', $out->purpose);
    }

    public function testVerifyRejectsExpiredToken(): void
    {
        $clock = $this->clock();
        $svc = new ScopedTokenService(self::KEY, $clock, 'oe-ai-agent-boundary', 300);
        $token = $svc->mint($this->principal());

        $clock->now = $clock->now->modify('+301 seconds'); // past the 5-min ttl

        $this->expectException(InvalidScopedTokenException::class);
        $svc->verify($token, 42);
    }

    public function testVerifyRejectsTamperedToken(): void
    {
        $svc = new ScopedTokenService(self::KEY, $this->clock());
        $token = $svc->mint($this->principal());

        $this->expectException(InvalidScopedTokenException::class);
        $svc->verify($token . 'x', 42); // corrupt the signature segment
    }

    public function testVerifyRejectsWrongPatientScope(): void
    {
        $svc = new ScopedTokenService(self::KEY, $this->clock());
        $token = $svc->mint($this->principal()); // scoped to pid 42

        $this->expectException(InvalidScopedTokenException::class);
        $svc->verify($token, 99);
    }

    public function testVerifyRejectsTokenSignedWithADifferentKey(): void
    {
        $clock = $this->clock();
        $minter = new ScopedTokenService('key-AAAAAAAAAAAAAAAAAAAAAAAAAAAA', $clock);
        $verifier = new ScopedTokenService('key-BBBBBBBBBBBBBBBBBBBBBBBBBBBB', $clock);
        $token = $minter->mint($this->principal());

        $this->expectException(InvalidScopedTokenException::class);
        $verifier->verify($token, 42);
    }
}
