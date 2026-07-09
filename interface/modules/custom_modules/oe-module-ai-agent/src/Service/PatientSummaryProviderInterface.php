<?php

/**
 * PatientSummaryProviderInterface — the contract the boundary depends on to
 * fetch a single patient's "minimum necessary" clinical summary.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Service;

interface PatientSummaryProviderInterface
{
    /**
     * @return array<string, mixed>
     */
    public function getSummary(int $pid): array;
}
