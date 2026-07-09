<?php

/**
 * Raised when a scoped AI-agent token fails verification.
 *
 * Carries only a generic message; the underlying cause is preserved via the
 * exception chain ($previous) rather than embedded in the message, so internal
 * details never leak to callers.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Auth;

final class InvalidScopedTokenException extends \RuntimeException
{
}
