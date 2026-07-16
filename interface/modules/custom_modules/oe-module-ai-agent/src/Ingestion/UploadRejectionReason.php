<?php

/**
 * UploadRejectionReason — why an uploaded document was refused before storage.
 *
 * Backed so the reason can be surfaced on the JSON error contract the card reads,
 * letting the widget show a specific, actionable message instead of a generic
 * failure. Each case owns its HTTP status and user-facing message.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Ingestion;

enum UploadRejectionReason: string
{
    case EmptyFile = 'empty';
    case TooLarge = 'too_large';
    case UnsupportedType = 'unsupported_type';

    /**
     * The HTTP status the upload endpoint returns for this rejection. All are
     * 4xx client errors — a rejection is the caller's file, not a server fault.
     */
    public function httpStatus(): int
    {
        return match ($this) {
            self::EmptyFile => 400,
            self::TooLarge => 413,
            self::UnsupportedType => 415,
        };
    }

    /**
     * A safe, specific message for the clinician. Contains no internal detail.
     */
    public function userMessage(): string
    {
        return match ($this) {
            self::EmptyFile => 'That file is empty. Choose a document to upload.',
            self::TooLarge => 'That file is too large. The limit is '
                . (DocumentUploadPolicy::MAX_BYTES / (1024 * 1024)) . ' MB.',
            self::UnsupportedType => 'Unsupported file type. A lab report must be a PDF; '
                . 'an intake form may be a PDF or an image (PNG/JPEG).',
        };
    }
}
