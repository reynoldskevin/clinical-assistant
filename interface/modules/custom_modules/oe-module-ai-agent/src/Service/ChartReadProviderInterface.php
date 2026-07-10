<?php

/**
 * ChartReadProviderInterface — the contract the multi-tool read boundary depends
 * on. Extends the single-summary provider with the chart-navigation reads
 * (encounter list + one encounter's detail). All reads are patient-scoped.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Service;

interface ChartReadProviderInterface extends PatientSummaryProviderInterface
{
    /**
     * @return list<array<string, mixed>>
     */
    public function listEncounters(int $pid): array;

    /**
     * @return array<string, mixed>
     */
    public function getEncounter(int $pid, int $encounterId): array;

    /**
     * @return list<array<string, mixed>>
     */
    public function getResults(int $pid): array;

    /**
     * @return list<array<string, mixed>>
     */
    public function getMedications(int $pid, bool $activeOnly): array;
}
