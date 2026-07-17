<?php

/**
 * DerivedFactRef — immutable reference to one clinical record an extraction run
 * filed into the chart, as tracked by the `ai_derived_fact` provenance store.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Persistence;

final readonly class DerivedFactRef
{
    /**
     * @param string      $factType   e.g. lab_result | medication | allergy | condition | family_history | chief_concern
     * @param string      $targetTable where the clinical record lives (procedure_result, prescriptions, lists, …)
     * @param int         $targetId    the created record's numeric id
     * @param string|null $targetUuid  the created record's uuid as a lowercase 32-char hex string, or null
     * @param string      $factSummary human label for card/audit display
     */
    public function __construct(
        public string $factType,
        public string $targetTable,
        public int $targetId,
        public ?string $targetUuid,
        public string $factSummary,
    ) {
    }
}
