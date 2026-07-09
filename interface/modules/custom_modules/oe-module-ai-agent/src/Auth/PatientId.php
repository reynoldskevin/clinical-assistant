<?php

/**
 * Typed patient identifier value object for the AI agent authorization model.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Auth;

final readonly class PatientId
{
    public function __construct(public int $value)
    {
        if ($value <= 0) {
            throw new \DomainException('Patient ID must be positive');
        }
    }
}
