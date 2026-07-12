<?php

/**
 * T39 acceptance tests (LOCKED) — dev-gated token mint helper.
 *
 * DevTokenMinter lets the Postman collection mint a pid-scoped JWT programmatically
 * on the synthetic demo, but it is fail-closed: disabled by default, it throws
 * rather than minting, so it can never weaken the real (session + CSRF + ACL)
 * auth model. When enabled it produces an ordinary pid-scoped token that the
 * boundary's ScopedTokenService accepts for that pid and rejects cross-pid.
 * Isolated (no DB): pure crypto over an injected gate boolean.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Auth;

use OpenEMR\Modules\AiAgent\Auth\DevTokenMintDisabledException;
use OpenEMR\Modules\AiAgent\Auth\DevTokenMinter;
use OpenEMR\Modules\AiAgent\Auth\InvalidScopedTokenException;
use OpenEMR\Modules\AiAgent\Auth\ScopedTokenService;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;
use Psr\Clock\ClockInterface;

$src = __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src';
require_once $src . '/Auth/PatientId.php';
require_once $src . '/Auth/ClinicalPrincipal.php';
require_once $src . '/Auth/InvalidScopedTokenException.php';
require_once $src . '/Auth/SigningKey.php';
require_once $src . '/Auth/ScopedTokenService.php';
require_once $src . '/Auth/TokenMinter.php';
require_once $src . '/Auth/DevTokenMintDisabledException.php';
require_once $src . '/Auth/DevTokenMinter.php';

#[Group('isolated')]
final class DevTokenMinterTest extends TestCase
{
    private const KEY = 'dev-mint-signing-key-0123456789-abcdef';

    private function clock(): ClockInterface
    {
        return new class implements ClockInterface {
            public function now(): \DateTimeImmutable
            {
                return new \DateTimeImmutable('2026-01-01T00:00:00+00:00');
            }
        };
    }

    public function testDisabledMinterRefusesToMint(): void
    {
        $minter = new DevTokenMinter(false, self::KEY, $this->clock());
        $this->expectException(DevTokenMintDisabledException::class);
        $minter->mintForPid(42);
    }

    public function testEnabledMinterMintsAVerifiableScopedToken(): void
    {
        $minter = new DevTokenMinter(true, self::KEY, $this->clock());
        $token = $minter->mintForPid(42, 7, 'grader');

        $principal = (new ScopedTokenService(self::KEY, $this->clock()))->verify($token, 42);
        $this->assertSame(42, $principal->patientId->value);
        $this->assertSame(7, $principal->clinicianId);
        $this->assertSame('grader', $principal->clinicianUsername);
    }

    public function testMintedTokenIsPidScopedAndRejectedCrossPid(): void
    {
        $minter = new DevTokenMinter(true, self::KEY, $this->clock());
        $token = $minter->mintForPid(42);

        $this->expectException(InvalidScopedTokenException::class);
        (new ScopedTokenService(self::KEY, $this->clock()))->verify($token, 99);
    }
}
