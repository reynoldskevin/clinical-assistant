<?php

/**
 * BoundaryAuditLoggerInterface — audit sink for the AI agent access boundary.
 *
 * Every access decision at the patient-summary boundary is recorded: a granted
 * read captures the principal, a denied attempt captures the requested patient
 * id and a generic reason (never inner exception detail).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Audit;

use OpenEMR\Modules\AiAgent\Auth\ClinicalPrincipal;

interface BoundaryAuditLoggerInterface
{
    public function recordGranted(ClinicalPrincipal $principal): void;

    public function recordDenied(int $requestedPid, string $reason): void;
}
