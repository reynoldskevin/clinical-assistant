<?php

/**
 * T62 acceptance tests — DocumentUploadPolicy (invalid-type / oversized rejection).
 *
 * Pure, DB-free. The policy sniffs the uploaded bytes by MAGIC NUMBER (never the
 * browser-declared Content-Type, which is attacker-controlled) and enforces a
 * per-doc_type allow-list plus a maximum size, so upload.php can reject a bad
 * file BEFORE it ever reaches OpenEMR's document store.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Ingestion;

use OpenEMR\Modules\AiAgent\Ingestion\DocumentUploadPolicy;
use OpenEMR\Modules\AiAgent\Ingestion\UploadRejected;
use OpenEMR\Modules\AiAgent\Ingestion\UploadRejectionReason;
use PHPUnit\Framework\Attributes\DataProvider;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

$src = __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src';
require_once $src . '/Ingestion/UploadRejectionReason.php';
require_once $src . '/Ingestion/UploadRejected.php';
require_once $src . '/Ingestion/AcceptedUpload.php';
require_once $src . '/Ingestion/DocumentUploadPolicy.php';

#[Group('isolated')]
final class DocumentUploadPolicyTest extends TestCase
{
    private const PDF = "%PDF-1.4\n1 0 obj\n<<>>\nendobj\n";
    private const PNG = "\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR";
    private const JPEG = "\xFF\xD8\xFF\xE0\x00\x10JFIF";

    public function testAcceptsAPdfForALabPdfAndCanonicalizesTheMimetype(): void
    {
        $accepted = (new DocumentUploadPolicy())->inspect(self::PDF, 'lab_pdf');
        $this->assertSame('application/pdf', $accepted->canonicalMimetype);
    }

    public function testAcceptsAScannedImageForAnIntakeForm(): void
    {
        $policy = new DocumentUploadPolicy();
        $this->assertSame('image/png', $policy->inspect(self::PNG, 'intake_form')->canonicalMimetype);
        $this->assertSame('image/jpeg', $policy->inspect(self::JPEG, 'intake_form')->canonicalMimetype);
    }

    public function testAcceptsAPdfForAnIntakeForm(): void
    {
        $accepted = (new DocumentUploadPolicy())->inspect(self::PDF, 'intake_form');
        $this->assertSame('application/pdf', $accepted->canonicalMimetype);
    }

    public function testRejectsAnImageDeclaredAsALabPdf(): void
    {
        // Lab reports must be PDFs — an image is not an acceptable lab_pdf even
        // though it is a valid image for an intake form.
        $this->expectRejection(self::PNG, 'lab_pdf', UploadRejectionReason::UnsupportedType);
    }

    public function testAcceptsAPdfForAMedList(): void
    {
        // T76: a medication list is a PDF (like a lab report). Before the fix the
        // allow-list had no med_list entry, so every med-list PDF was refused.
        $accepted = (new DocumentUploadPolicy())->inspect(self::PDF, 'med_list');
        $this->assertSame('application/pdf', $accepted->canonicalMimetype);
    }

    public function testRejectsAnImageDeclaredAsAMedList(): void
    {
        // Med lists are PDF-only, exactly like lab reports — an image is refused.
        $this->expectRejection(self::PNG, 'med_list', UploadRejectionReason::UnsupportedType);
    }

    public function testRejectsAContentTypeSpoof(): void
    {
        // The bytes are a Windows executable ("MZ"); no declared mimetype can make
        // it acceptable because the policy sniffs the CONTENT, not the wire label.
        $this->expectRejection("MZ\x90\x00this is not a document", 'intake_form', UploadRejectionReason::UnsupportedType);
    }

    public function testRejectsPlainTextMasqueradingAsAPdf(): void
    {
        $this->expectRejection("Just some text, not a real PDF.", 'lab_pdf', UploadRejectionReason::UnsupportedType);
    }

    public function testRejectsAnEmptyFile(): void
    {
        $this->expectRejection('', 'lab_pdf', UploadRejectionReason::EmptyFile);
    }

    public function testRejectsAnOversizedFile(): void
    {
        // A valid PDF header followed by more than the byte cap of padding.
        $oversized = self::PDF . str_repeat('A', DocumentUploadPolicy::MAX_BYTES);
        $this->expectRejection($oversized, 'lab_pdf', UploadRejectionReason::TooLarge);
    }

    public function testAcceptsAFileAtExactlyTheSizeCap(): void
    {
        $pad = DocumentUploadPolicy::MAX_BYTES - strlen(self::PDF);
        $atCap = self::PDF . str_repeat('A', $pad);
        $accepted = (new DocumentUploadPolicy())->inspect($atCap, 'lab_pdf');
        $this->assertSame('application/pdf', $accepted->canonicalMimetype);
    }

    #[DataProvider('reasonHttpStatusProvider')]
    public function testEachRejectionReasonMapsToAClientErrorStatus(UploadRejectionReason $reason, int $status): void
    {
        $this->assertSame($status, $reason->httpStatus());
        $this->assertNotSame('', $reason->userMessage());
    }

    /**
     * @return array<string, array{UploadRejectionReason, int}>
     *
     * @codeCoverageIgnore Data providers run before coverage instrumentation starts.
     */
    public static function reasonHttpStatusProvider(): array
    {
        return [
            'empty' => [UploadRejectionReason::EmptyFile, 400],
            'too large' => [UploadRejectionReason::TooLarge, 413],
            'unsupported' => [UploadRejectionReason::UnsupportedType, 415],
        ];
    }

    private function expectRejection(string $bytes, string $docType, UploadRejectionReason $reason): void
    {
        try {
            (new DocumentUploadPolicy())->inspect($bytes, $docType);
            $this->fail('Expected UploadRejected for reason ' . $reason->value);
        } catch (UploadRejected $e) {
            $this->assertSame($reason, $e->reason);
        }
    }
}
