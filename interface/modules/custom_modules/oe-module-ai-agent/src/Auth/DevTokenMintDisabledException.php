<?php

/**
 * DevTokenMintDisabledException — thrown when the dev token minter is asked to
 * mint while disabled.
 *
 * The dev-gated minter is fail-closed: unless explicitly enabled it refuses to
 * produce a token, raising this exception instead. This guarantees the dev
 * helper can never weaken the real (session + CSRF + ACL) auth model.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Auth;

final class DevTokenMintDisabledException extends \RuntimeException
{
}
