<?php

/**
 * AgentCard — renders the AI Clinical Co-Pilot widget for the patient summary.
 *
 * Produces a self-contained container the front-end JS (agent-widget.js) hooks
 * onto. The patient id is a native int and is emitted directly into the markup,
 * so there is no string-interpolation injection surface: the only value that can
 * ever reach the DOM is an integer.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */

declare(strict_types=1);

namespace OpenEMR\Modules\AiAgent\Ui;

final class AgentCard
{
    public static function render(int $pid, string $sidecarUrl = '', string $csrfToken = ''): string
    {
        // The sidecar URL is optional; when provided it is escaped and emitted as
        // a data attribute the front-end reads (falling back to its default path).
        $sidecarAttr = $sidecarUrl !== ''
            ? ' data-sidecar-url="' . htmlspecialchars($sidecarUrl, ENT_QUOTES) . '"'
            : '';

        // The CSRF token is embedded (escaped) so the widget can authenticate its
        // POST to token.php; the dashboard exposes no CSRF JS global.
        $csrfAttr = $csrfToken !== ''
            ? ' data-csrf="' . htmlspecialchars($csrfToken, ENT_QUOTES) . '"'
            : '';

        // Cache-bust the widget script by its mtime so a changed agent-widget.js
        // is always re-fetched rather than served stale from the browser cache.
        $mtime = @filemtime(__DIR__ . '/../../public/agent-widget.js');
        $version = (string) ($mtime !== false ? $mtime : '1');

        // The pdf.js glue defines window.OE_AI_AGENT_PDF_RENDER, which the widget
        // consults to preview PDF uploads. It is loaded (cache-busted) BEFORE the
        // widget so the hook is present by the time the widget runs.
        $pdfMtime = @filemtime(__DIR__ . '/../../public/pdf-preview.js');
        $pdfVersion = (string) ($pdfMtime !== false ? $pdfMtime : '1');

        // $pid is a native int; emitting it directly means the attribute value can
        // only ever be an integer — no untrusted string ever reaches the markup.
        return <<<HTML
<div id="oe-ai-agent" class="oe-ai-agent card mb-2" data-pid="{$pid}"{$sidecarAttr}{$csrfAttr}>
    <div class="card-body">
        <h5 class="card-title oe-ai-agent-title">AI Clinical Co-Pilot</h5>
        <div class="oe-ai-agent-answer" role="status" aria-live="polite"></div>
        <form class="oe-ai-agent-form">
            <textarea class="oe-ai-agent-question form-control" rows="2"
                placeholder="Ask about this patient..." aria-label="Question for the AI Clinical Co-Pilot"></textarea>
            <button type="submit" class="oe-ai-agent-submit btn btn-primary btn-sm mt-1">Ask</button>
        </form>
        <button type="button" class="oe-ai-agent-trends-btn btn btn-outline-secondary btn-sm mt-2">Lab trends</button>
        <div class="oe-ai-agent-trends mt-2"></div>
        <form class="oe-ai-agent-upload-form d-flex flex-wrap align-items-center justify-content-end mt-2">
            <span class="oe-ai-agent-upload-status small mb-0 mr-2" role="status" aria-live="polite"></span>
            <label class="oe-ai-agent-upload-label small text-muted mb-0 mr-2">Upload a document</label>
            <select class="oe-ai-agent-doc-type custom-select custom-select-sm w-auto mr-1"
                aria-label="Document type">
                <option value="lab_pdf">Lab PDF</option>
                <option value="intake_form">Intake form</option>
                <option value="med_list">Medication List</option>
            </select>
            <input type="file" class="oe-ai-agent-file form-control-file form-control-sm w-auto mr-1"
                accept="application/pdf,image/*" aria-label="Upload a document">
            <button type="submit" class="oe-ai-agent-upload-submit btn btn-secondary btn-sm">Upload</button>
        </form>
        <div class="oe-ai-agent-extract mt-2" role="status" aria-live="polite"></div>
    </div>
    <script src="../../../interface/modules/custom_modules/oe-module-ai-agent/public/pdf-preview.js?v={$pdfVersion}"></script>
    <script src="../../../interface/modules/custom_modules/oe-module-ai-agent/public/agent-widget.js?v={$version}"></script>
</div>
HTML;
    }
}
