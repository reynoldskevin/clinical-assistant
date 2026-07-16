<?php

/**
 * AcceptedUpload — the result of a passing DocumentUploadPolicy inspection.
 *
 * Immutable value object. Carries the CANONICAL mimetype derived from the file's
 * own magic number (not the browser-declared Content-Type), so the endpoint
 * stores a trustworthy mimetype on the document row.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Ingestion;

final readonly class AcceptedUpload
{
    public function __construct(public string $canonicalMimetype)
    {
    }
}
