<?php

/**
 * AgentCardRenderable — adapts AgentCard into the patient-summary RenderInterface.
 *
 * The patient-summary card render pipeline (see RenderEvent / card.macro.twig)
 * consumes objects exposing a template name plus a variables map. This adapter
 * renders the AI Co-Pilot widget once, at construction, and hands the resulting
 * markup to a tiny raw-output template.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Ui;

use OpenEMR\Events\Patient\Summary\Card\RenderInterface;

final class AgentCardRenderable implements RenderInterface
{
    private readonly string $html;

    public function __construct(int $pid)
    {
        $this->html = AgentCard::render($pid);
    }

    public function getTemplateFile(): string
    {
        return 'ai-agent/card.html.twig';
    }

    /**
     * @return array<string, string>
     */
    public function getVariables(): array
    {
        return ['cardHtml' => $this->html];
    }
}
