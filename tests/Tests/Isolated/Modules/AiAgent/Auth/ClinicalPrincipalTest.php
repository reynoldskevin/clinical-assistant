<?php

/**
 * T06 acceptance tests (LOCKED) — typed authorization principal for the AI agent.
 *
 * PatientId + ClinicalPrincipal value objects (custom-JWT auth model, ARCHITECTURE
 * §1a). Isolated (no DB): pure value-object behavior.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Auth;

use OpenEMR\Modules\AiAgent\Auth\ClinicalPrincipal;
use OpenEMR\Modules\AiAgent\Auth\PatientId;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Auth/PatientId.php';
require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Auth/ClinicalPrincipal.php';

#[Group('isolated')]
final class ClinicalPrincipalTest extends TestCase
{
    public function testPatientIdExposesPositiveValue(): void
    {
        $this->assertSame(42, (new PatientId(42))->value);
    }

    public function testPatientIdRejectsZero(): void
    {
        $this->expectException(\DomainException::class);
        new PatientId(0);
    }

    public function testPatientIdRejectsNegative(): void
    {
        $this->expectException(\DomainException::class);
        new PatientId(-5);
    }

    public function testPrincipalExposesClinicianAndPatientScope(): void
    {
        $p = new ClinicalPrincipal(7, 'dr_house', new PatientId(42), 'treatment');
        $this->assertSame(7, $p->clinicianId);
        $this->assertSame('dr_house', $p->clinicianUsername);
        $this->assertInstanceOf(PatientId::class, $p->patientId);
        $this->assertSame(42, $p->patientId->value);
        $this->assertSame('treatment', $p->purpose);
    }

    public function testPrincipalDefaultsPurposeToTreatment(): void
    {
        $p = new ClinicalPrincipal(7, 'dr_house', new PatientId(42));
        $this->assertSame('treatment', $p->purpose);
    }

    public function testPrincipalRejectsNonPositiveClinicianId(): void
    {
        $this->expectException(\DomainException::class);
        new ClinicalPrincipal(0, 'dr_house', new PatientId(42));
    }

    public function testPrincipalRejectsEmptyUsername(): void
    {
        $this->expectException(\DomainException::class);
        new ClinicalPrincipal(7, '', new PatientId(42));
    }

    public function testValueObjectsAreReadonlyAndFinal(): void
    {
        foreach ([PatientId::class, ClinicalPrincipal::class] as $class) {
            $ref = new \ReflectionClass($class);
            $this->assertTrue($ref->isFinal(), "{$class} must be final");
            $this->assertTrue($ref->isReadOnly(), "{$class} must be a readonly class");
        }
    }
}
