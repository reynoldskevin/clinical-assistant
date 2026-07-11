<?php

/**
 * ClinicalAccessPolicy — clinical-read authorization gate for the AI agent.
 *
 * The AI agent is a read-only overlay: it must never read more than the
 * logged-in human already could. This is the single authorization seam — it
 * decides whether a session user may read clinical data by delegating to
 * OpenEMR's own ACL (section `patients`, value `med`), injected as a check so
 * it is unit-testable with no DB and no OpenEMR bootstrap. Fails closed for a
 * blank username without consulting the ACL.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Auth;

final readonly class ClinicalAccessPolicy
{
    private \Closure $aclCheck;

    public function __construct(callable $aclCheck)
    {
        $this->aclCheck = \Closure::fromCallable($aclCheck);
    }

    public function mayReadClinical(string $username): bool
    {
        if ($username === '') {
            return false;
        }

        return ($this->aclCheck)('patients', 'med', $username);
    }
}
