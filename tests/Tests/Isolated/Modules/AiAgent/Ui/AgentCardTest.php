<?php

/**
 * T16 acceptance tests (LOCKED) — AgentCard renders the patient-summary widget.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Tests\Isolated\Modules\AiAgent\Ui;

use OpenEMR\Modules\AiAgent\Ui\AgentCard;
use PHPUnit\Framework\Attributes\Group;
use PHPUnit\Framework\TestCase;

require_once __DIR__ . '/../../../../../../interface/modules/custom_modules/oe-module-ai-agent/src/Ui/AgentCard.php';

#[Group('isolated')]
final class AgentCardTest extends TestCase
{
    public function testRenderCarriesPidContainerAndHeading(): void
    {
        $html = AgentCard::render(42);
        $this->assertStringContainsString('data-pid="42"', $html);
        // a stable container hook for the JS widget
        $this->assertStringContainsString('oe-ai-agent', $html);
        // an input for the clinician's question
        $this->assertMatchesRegularExpression('/<(input|textarea)\b/i', $html);
        // a heading identifying the assistant
        $this->assertMatchesRegularExpression('/AI|Co-?Pilot|assistant/i', $html);
    }

    public function testPidIsIntCastNotInterpolatedRaw(): void
    {
        // param is a native int, so the rendered pid is exactly the integer — no injection surface
        $html = AgentCard::render(7);
        $this->assertStringContainsString('data-pid="7"', $html);
        $this->assertStringNotContainsString('data-pid="7abc"', $html);
    }

    public function testUploadOffersTheThreeDocumentTypes(): void
    {
        // The doc-type <select> lets a clinician pick the document being uploaded;
        // the third type (medication list) is offered alongside lab + intake.
        $html = AgentCard::render(1);
        $this->assertStringContainsString('value="lab_pdf"', $html);
        $this->assertStringContainsString('value="intake_form"', $html);
        $this->assertStringContainsString('value="med_list"', $html);
        // the med_list option carries a human-readable label
        $this->assertMatchesRegularExpression('/value="med_list"[^>]*>\s*Medication List/i', $html);
    }
}
