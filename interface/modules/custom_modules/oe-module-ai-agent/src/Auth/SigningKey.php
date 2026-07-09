<?php

/**
 * Typed HS256 signing-key value object for the AI agent token endpoint.
 *
 * Rejects a weak secret (< 32 bytes) at construction so a token can never be
 * signed with an insufficiently strong key.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Auth;

final readonly class SigningKey
{
    public function __construct(public string $value)
    {
        if (strlen($value) < 32) {
            throw new \DomainException('Signing key must be at least 32 bytes');
        }
    }
}
