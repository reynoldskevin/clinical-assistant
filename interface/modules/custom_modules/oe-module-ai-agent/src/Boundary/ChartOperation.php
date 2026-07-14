<?php

/**
 * ChartOperation — the closed set of read operations the multi-tool boundary
 * dispatches to.
 *
 * A raw operation string from the wire is PARSED into this enum (parse, don't
 * validate); an unrecognized string must be rejected, not silently accepted.
 * The enum's case set is the boundary's whitelist.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Boundary;

enum ChartOperation: string
{
    case Summary = 'summary';
    case ListEncounters = 'list_encounters';
    case GetEncounter = 'get_encounter';
    case GetResults = 'get_results';
    case GetMedications = 'get_medications';
    case SearchChart = 'search_chart';
    case GetDocuments = 'get_documents';
    case GetDocument = 'get_document';
}
