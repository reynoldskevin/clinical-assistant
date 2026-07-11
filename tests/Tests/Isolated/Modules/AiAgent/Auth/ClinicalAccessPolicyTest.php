<?php

/**
 * T28 acceptance tests (LOCKED) — clinical-read authorization gate.
 *
 * The AI agent is a read-only overlay: it must never read more than the
 * logged-in human already could. ClinicalAccessPolicy is the single
 * authorization seam — it decides whether a session user may read clinical data
 * by delegating to OpenEMR's own ACL (section `patients`, value `med`), injected
 * as a check so this is unit-testable with no DB and no OpenEMR bootstrap.
 * token.php wires the real AclMain::aclCheckCore into it before minting.
 *
 * Isolated (no DB): pure policy behavior over an injected ACL check.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Auth;

use OpenEMR\Modules\AiAgent\Auth\ClinicalAccessPolicy;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Auth/ClinicalAccessPolicy.php';

#[Group('isolated')]
final class ClinicalAccessPolicyTest extends TestCase
{
    public function testGrantsWhenAclCheckReturnsTrue(): void
    {
        $policy = new ClinicalAccessPolicy(static fn(): bool => true);
        $this->assertTrue($policy->mayReadClinical('dr_house'));
    }

    public function testDeniesWhenAclCheckReturnsFalse(): void
    {
        $policy = new ClinicalAccessPolicy(static fn(): bool => false);
        $this->assertFalse($policy->mayReadClinical('front_desk'));
    }

    public function testDeniesEmptyUsernameWithoutConsultingAcl(): void
    {
        $consulted = false;
        $policy = new ClinicalAccessPolicy(static function () use (&$consulted): bool {
            $consulted = true;
            return true;
        });

        $this->assertFalse($policy->mayReadClinical(''));
        $this->assertFalse($consulted, 'ACL must not be consulted for a blank username');
    }

    public function testForwardsPatientsMedSectionAndUsernameToAclCheck(): void
    {
        $captured = [];
        $policy = new ClinicalAccessPolicy(
            static function (string $section, string $value, string $user) use (&$captured): bool {
                $captured = [$section, $value, $user];
                return true;
            }
        );

        $policy->mayReadClinical('dr_house');

        $this->assertSame(['patients', 'med', 'dr_house'], $captured);
    }
}
