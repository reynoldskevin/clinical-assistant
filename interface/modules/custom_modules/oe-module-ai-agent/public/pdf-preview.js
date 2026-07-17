/**
 * pdf-preview.js — pdf.js glue for the AI Clinical Co-Pilot upload preview.
 *
 * Defines ``window.OE_AI_AGENT_PDF_RENDER``, the seam agent-widget.js consults
 * to preview a PDF upload for its [show source] citation modal. A PDF cannot be
 * rendered as an <img>, so this script rasterises page 1 to a PNG data URL using
 * the vendored ESM build of pdf.js. It is deliberately kept OUT of the widget
 * itself so the widget stays dependency-free and jsdom-testable — the widget
 * only ever calls this hook when it is present.
 *
 * Loaded as a plain <script> (no build step). The vendored pdf.js is resolved
 * relative to THIS script's own URL, and imported lazily the first time the
 * hook is invoked (and cached thereafter). Any failure rejects, and the widget
 * degrades to no preview.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */
(function () {
    'use strict';

    // Capture this script's own URL at load time so the vendored pdf.js ESM and
    // its worker can be resolved relative to it (document.currentScript is only
    // valid during synchronous top-level execution, not inside later callbacks).
    var THIS = document.currentScript && document.currentScript.src;

    // The loaded pdf.js module, cached across calls so repeated previews don't
    // re-import the (large) ESM bundle.
    var pdfjsLibPromise = null;

    function loadPdfjs() {
        if (pdfjsLibPromise) {
            return pdfjsLibPromise;
        }
        pdfjsLibPromise = import(new URL('vendor/pdfjs/pdf.min.mjs', THIS).href)
            .then(function (pdfjsLib) {
                pdfjsLib.GlobalWorkerOptions.workerSrc =
                    new URL('vendor/pdfjs/pdf.worker.min.mjs', THIS).href;
                return pdfjsLib;
            });
        return pdfjsLibPromise;
    }

    window.OE_AI_AGENT_PDF_RENDER = function (file) {
        return loadPdfjs().then(function (pdfjsLib) {
            return file.arrayBuffer().then(function (data) {
                return pdfjsLib.getDocument({ data: data }).promise;
            }).then(function (pdf) {
                return pdf.getPage(1);
            }).then(function (page) {
                var viewport = page.getViewport({ scale: 2 });
                var canvas = document.createElement('canvas');
                canvas.width = viewport.width;
                canvas.height = viewport.height;
                var ctx = canvas.getContext('2d');
                return page.render({ canvasContext: ctx, viewport: viewport }).promise
                    .then(function () {
                        return canvas.toDataURL('image/png');
                    });
            });
        });
    };
})();
