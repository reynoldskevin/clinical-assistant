<?php

/**
 * DevTokenMinter — dev/demo-only helper for programmatically minting a
 * pid-scoped JWT without an authenticated session.
 *
 * Fail-closed by construction: disabled by default, it throws
 * DevTokenMintDisabledException rather than minting, so it can never weaken the
 * real (session + CSRF + ACL) auth model. When explicitly enabled it delegates
 * to TokenMinter to produce an ordinary pid-scoped token that the boundary's
 * ScopedTokenService accepts for that pid and rejects cross-pid. Intended only
 * for the synthetic Postman demo — never for real PHI.
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

final class DevTokenMinter
{
    public function __construct(
        private readonly bool $enabled,
        private readonly string $signingKey,
        private readonly ClockInterface $clock,
    ) {
    }

    public function mintForPid(int $pid, int $clinicianId = 1, string $clinicianUsername = 'dev'): string
    {
        if (!$this->enabled) {
            throw new DevTokenMintDisabledException();
        }

        return TokenMinter::mint($clinicianId, $clinicianUsername, $pid, $this->signingKey, $this->clock);
    }
}
