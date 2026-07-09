<?php

/**
 * Typed authorization principal for the AI agent.
 *
 * Captures the initiating clinician, the patient scope, and the purpose of the
 * interaction as an immutable value object (custom-JWT auth model).
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Auth;

final readonly class ClinicalPrincipal
{
    public function __construct(
        public int $clinicianId,
        public string $clinicianUsername,
        public PatientId $patientId,
        public string $purpose = 'treatment',
    ) {
        if ($clinicianId <= 0) {
            throw new \DomainException('Clinician ID must be positive');
        }

        if ($clinicianUsername === '') {
            throw new \DomainException('Clinician username must not be empty');
        }
    }
}
