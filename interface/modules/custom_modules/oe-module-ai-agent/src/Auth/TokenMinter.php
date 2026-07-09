<?php

/**
 * TokenMinter — composes the AI agent auth value objects into a signed, scoped JWT.
 *
 * A thin, static composition seam over the auth building blocks: it validates the
 * signing key (SigningKey), constructs the clinician/patient principal
 * (ClinicalPrincipal + PatientId), and delegates minting to ScopedTokenService.
 * Keeping the wiring here means callers (the token endpoint) never hand-assemble
 * the crypto pieces and can never sign with a weak key.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Auth;

use Psr\Clock\ClockInterface;

final class TokenMinter
{
    public static function mint(
        int $clinicianId,
        string $clinicianUsername,
        int $pid,
        string $signingKey,
        ClockInterface $clock,
    ): string {
        $key = new SigningKey($signingKey);

        return (new ScopedTokenService($key->value, $clock))
            ->mint(new ClinicalPrincipal($clinicianId, $clinicianUsername, new PatientId($pid)));
    }
}
