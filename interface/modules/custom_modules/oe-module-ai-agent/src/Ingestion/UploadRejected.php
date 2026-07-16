<?php

/**
 * UploadRejected — thrown by DocumentUploadPolicy when a file must not be stored.
 *
 * Carries the machine-readable {@see UploadRejectionReason} so the endpoint can
 * map it to an HTTP status and a specific message without string-matching.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Ingestion;

final class UploadRejected extends \RuntimeException
{
    public function __construct(public readonly UploadRejectionReason $reason)
    {
        parent::__construct($reason->value);
    }
}
