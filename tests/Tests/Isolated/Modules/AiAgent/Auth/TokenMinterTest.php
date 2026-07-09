<?php

/**
 * T16 acceptance tests (LOCKED) — TokenMinter composes the auth pieces into a JWT.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Auth;

use OpenEMR\Modules\AiAgent\Auth\InvalidScopedTokenException;
use OpenEMR\Modules\AiAgent\Auth\ScopedTokenService;
use OpenEMR\Modules\AiAgent\Auth\TokenMinter;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;
use Psr\Clock\ClockInterface;

$src = __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Auth';
require_once $src . '/PatientId.php';
require_once $src . '/ClinicalPrincipal.php';
require_once $src . '/InvalidScopedTokenException.php';
require_once $src . '/ScopedTokenService.php';
require_once $src . '/SigningKey.php';
require_once $src . '/TokenMinter.php';

#[Group('isolated')]
final class TokenMinterTest extends TestCase
{
    private const KEY = 'token-minter-signing-key-0123456789';

    private function clock(): ClockInterface
    {
        return new class implements ClockInterface {
            public function now(): \DateTimeImmutable
            {
                return new \DateTimeImmutable('2026-01-01T00:00:00+00:00');
            }
        };
    }

    public function testMintProducesATokenVerifiableForThePatient(): void
    {
        $clock = $this->clock();
        $token = TokenMinter::mint(7, 'dr_house', 42, self::KEY, $clock);

        $principal = (new ScopedTokenService(self::KEY, $clock))->verify($token, 42);
        $this->assertSame(7, $principal->clinicianId);
        $this->assertSame('dr_house', $principal->clinicianUsername);
        $this->assertSame(42, $principal->patientId->value);
    }

    public function testMintRejectsAWeakSigningKey(): void
    {
        $this->expectException(\DomainException::class);
        TokenMinter::mint(7, 'dr_house', 42, 'too-short', $this->clock());
    }

    public function testMintedTokenIsScopedToThePatient(): void
    {
        $clock = $this->clock();
        $token = TokenMinter::mint(7, 'dr_house', 42, self::KEY, $clock);

        $this->expectException(InvalidScopedTokenException::class);
        (new ScopedTokenService(self::KEY, $clock))->verify($token, 99); // wrong pid
    }
}
