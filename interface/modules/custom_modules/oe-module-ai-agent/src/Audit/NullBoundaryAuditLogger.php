<?php

/**
 * NullBoundaryAuditLogger — no-op audit sink (Null Object pattern).
 *
 * The default when no audit logger is supplied to the boundary, so that access
 * decisions can be exercised without a database while the interface remains the
 * single seam for real auditing.
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

final class NullBoundaryAuditLogger implements BoundaryAuditLoggerInterface
{
    public function recordGranted(ClinicalPrincipal $principal): void
    {
    }

    public function recordDenied(int $requestedPid, string $reason): void
    {
    }
}
