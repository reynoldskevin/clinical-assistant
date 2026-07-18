<?php

/**
 * DocumentUploadPolicy — decides whether an uploaded blob may be stored.
 *
 * The card lets a clinician attach a lab report, intake form, or medication list
 * to the open chart. T46 stored whatever was posted; T62 hardens that entry point.
 * This policy is the fail-closed gate that runs BEFORE OpenEMR's document store:
 *
 *  - it identifies the file by its MAGIC NUMBER, never the browser-supplied
 *    Content-Type (which the client controls and can spoof);
 *  - it enforces a per-doc_type allow-list — a lab report and a medication list
 *    must each be a PDF; an intake form may be a PDF or a scanned image (PNG/JPEG);
 *  - it caps the size so an oversized upload is refused up front.
 *
 * Anything outside the allow-list is refused with a typed {@see UploadRejected}
 * carrying the specific {@see UploadRejectionReason}. Pure and DB-free.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Ingestion;

final class DocumentUploadPolicy
{
    /** Maximum accepted upload size in bytes (10 MiB). */
    public const MAX_BYTES = 10 * 1024 * 1024;

    /**
     * Canonical mimetypes accepted for each doc_type. A lab report must be a
     * true PDF; an intake form may also be a scanned image.
     *
     * @var array<string, list<string>>
     */
    private const ALLOWED = [
        'lab_pdf' => ['application/pdf'],
        'intake_form' => ['application/pdf', 'image/png', 'image/jpeg'],
        'med_list' => ['application/pdf'],
    ];

    /**
     * Inspect the raw uploaded bytes for the chosen doc_type.
     *
     * @throws UploadRejected when the file is empty, too large, or not an
     *                        allowed type for this doc_type.
     */
    public function inspect(string $bytes, string $docType): AcceptedUpload
    {
        if ($bytes === '') {
            throw new UploadRejected(UploadRejectionReason::EmptyFile);
        }
        if (strlen($bytes) > self::MAX_BYTES) {
            throw new UploadRejected(UploadRejectionReason::TooLarge);
        }

        $sniffed = $this->sniff($bytes);
        $allowed = self::ALLOWED[$docType] ?? [];
        if ($sniffed === null || !in_array($sniffed, $allowed, true)) {
            throw new UploadRejected(UploadRejectionReason::UnsupportedType);
        }

        return new AcceptedUpload($sniffed);
    }

    /**
     * Identify a document by its leading magic bytes. Returns the canonical
     * mimetype, or null when the content is not a recognised document/image.
     */
    private function sniff(string $bytes): ?string
    {
        if (str_starts_with($bytes, "%PDF-")) {
            return 'application/pdf';
        }
        if (str_starts_with($bytes, "\x89PNG\r\n\x1a\n")) {
            return 'image/png';
        }
        if (str_starts_with($bytes, "\xFF\xD8\xFF")) {
            return 'image/jpeg';
        }
        return null;
    }
}
