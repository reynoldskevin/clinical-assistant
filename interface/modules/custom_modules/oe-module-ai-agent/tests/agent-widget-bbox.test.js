/**
 * @jest-environment jsdom
 *
 * T56h acceptance test (LOCKED) — citation source overlay.
 *
 * Two geometry sources feed the SAME [show source]/modal UX:
 *  - IMAGE uploads: per-field boxes from the /extract response (`citation_boxes`,
 *    server demo geometry).
 *  - PDF uploads: the render seam returns the rendered page URL PLUS word geometry
 *    from the PDF's own text layer (`{url, words, page_width, page_height}`); the
 *    widget locates each extracted fact value in those words CLIENT-SIDE, so it
 *    works for the actual page with no server geometry and no document mismatch.
 *
 * Each cited fact gets a small "show source" control; clicking opens a modal
 * showing only that fact's box(es). Deterministic — the PDF renderer/text-layer
 * seam is stubbed; no pdf.js, no live API.
 */
/* global __dirname, setTimeout */
const fs = require('fs');
const path = require('path');

const WIDGET_SRC = fs.readFileSync(
    path.join(__dirname, '..', 'public', 'agent-widget.js'),
    'utf8'
);

const SCAFFOLD = `
<div id="oe-ai-agent" data-pid="1" data-csrf="tok" data-sidecar-url="http://localhost:8900/ask">
  <form class="oe-ai-agent-form">
    <textarea class="oe-ai-agent-question"></textarea>
    <button type="submit" class="oe-ai-agent-submit">Ask</button>
  </form>
  <div class="oe-ai-agent-answer"></div>
  <form class="oe-ai-agent-upload-form">
    <input type="file" class="oe-ai-agent-file" />
    <select class="oe-ai-agent-doc-type"><option value="intake_form" selected>Intake</option></select>
    <button type="submit" class="oe-ai-agent-upload-submit">Upload</button>
    <div class="oe-ai-agent-upload-status"></div>
  </form>
  <div class="oe-ai-agent-extract"></div>
</div>
`;

function el(sel, root) { return (root || document).querySelector(sel); }
function all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
function loadWidget() { new Function(WIDGET_SRC)(); }

function flushAll() {
    return new Promise(function (resolve) {
        let n = 0;
        (function tick() { if (n++ > 10) { return resolve(); } setTimeout(tick, 0); })();
    });
}

function makeBody(overrides) {
    return Object.assign({
        ok: true,
        doc_type: 'intake_form',
        confidence: 0.9,
        correlation_id: 'run-1',
        fact: { chief_concern: 'chest pain', current_medications: 'lisinopril', allergies: 'none' },
        identity_check: { matches: true, mismatched_identifiers: [] }
    }, overrides || {});
}

function installFetch(bodyOverrides) {
    global.fetch = jest.fn(function (url) {
        const u = String(url);
        function json(body, ok) {
            return Promise.resolve({ ok: ok !== false, json: function () { return Promise.resolve(body); } });
        }
        if (u.indexOf('token.php') !== -1) { return json({ token: 'jwt' }); }
        if (u.indexOf('upload.php') !== -1) { return json({ ok: true, id: 42, category: 'X', duplicate: false }); }
        if (u.indexOf('/extract') !== -1) { return json(makeBody(bodyOverrides)); }
        return json({});
    });
}

function upload(name, type) {
    const fileInput = el('.oe-ai-agent-file');
    Object.defineProperty(fileInput, 'files', {
        configurable: true,
        value: [{ name: name, type: type || 'image/png' }],
    });
    el('.oe-ai-agent-upload-form').dispatchEvent(new Event('submit', { cancelable: true }));
}

// IMAGE server geometry: per-field map (chief_concern 1 box; current_medications 2; allergies none).
const IMG_BOXES = {
    chief_concern: [{ x: 10, y: 100, w: 100, h: 20 }],
    current_medications: [{ x: 10, y: 140, w: 80, h: 20 }, { x: 10, y: 180, w: 60, h: 20 }],
};

function click(elm) { elm.dispatchEvent(new Event('click', { bubbles: true })); }
function showSource(field) { return el('.oe-ai-agent-show-source[data-field="' + field + '"]'); }
function modalShown() {
    const m = el('.oe-ai-agent-source-modal');
    return m !== null && m.style.display !== 'none';
}

beforeEach(() => {
    global.URL.createObjectURL = jest.fn(function () { return 'blob:preview-xyz'; });
    delete global.window.OE_AI_AGENT_PDF_RENDER;
});

describe('agent-widget: image citation source (server geometry)', () => {
    async function render(boxes) {
        document.body.innerHTML = SCAFFOLD;
        installFetch(boxes ? { citation_boxes: boxes, page_width: 400, page_height: 600 } : {});
        loadWidget();
        upload('intake.png', 'image/png');
        await flushAll();
    }

    test('only cited facts get a small "show source" control', async () => {
        await render(IMG_BOXES);
        expect(showSource('chief_concern')).not.toBeNull();
        expect(showSource('chief_concern').textContent.toLowerCase()).toContain('source');
        expect(showSource('current_medications')).not.toBeNull();
        expect(showSource('allergies')).toBeNull();
    });

    test('the whole fact row is not the click target', async () => {
        await render(IMG_BOXES);
        expect(el('.oe-ai-agent-extract dd[data-field]')).toBeNull();
        expect(el('.oe-ai-agent-extract dd[role="button"]')).toBeNull();
    });

    test('modal hidden until a source is opened', async () => {
        await render(IMG_BOXES);
        expect(modalShown()).toBe(false);
        expect(all('.oe-ai-agent-citation-box').length).toBe(0);
    });

    test('clicking [show source] opens the modal with only that fact\'s box', async () => {
        await render(IMG_BOXES);
        click(showSource('chief_concern'));
        expect(modalShown()).toBe(true);
        expect(el('.oe-ai-agent-source-modal .oe-ai-agent-doc-image').getAttribute('src')).toBe('blob:preview-xyz');
        const drawn = all('.oe-ai-agent-citation-box');
        expect(drawn.length).toBe(1);
        expect(parseFloat(drawn[0].style.top)).toBeCloseTo(100 / 600 * 100, 3);
    });

    test('another fact swaps to its boxes', async () => {
        await render(IMG_BOXES);
        click(showSource('chief_concern'));
        click(showSource('current_medications'));
        expect(all('.oe-ai-agent-citation-box').length).toBe(2);
    });

    test('close button and backdrop dismiss the modal', async () => {
        await render(IMG_BOXES);
        click(showSource('chief_concern'));
        click(el('.oe-ai-agent-source-close'));
        expect(modalShown()).toBe(false);
        click(showSource('chief_concern'));
        click(el('.oe-ai-agent-source-modal'));
        expect(modalShown()).toBe(false);
    });

    test('re-clicking the active control toggles the modal closed', async () => {
        await render(IMG_BOXES);
        click(showSource('current_medications'));
        expect(modalShown()).toBe(true);
        click(showSource('current_medications'));
        expect(modalShown()).toBe(false);
    });

    test('no citation geometry => no controls; facts still render', async () => {
        await render(null);
        expect(el('.oe-ai-agent-extract .card')).not.toBeNull();
        expect(el('.oe-ai-agent-extract').textContent.toLowerCase()).toContain('chest pain');
        expect(showSource('chief_concern')).toBeNull();
        expect(el('.oe-ai-agent-doc-image')).toBeNull();
    });
});

describe('agent-widget: PDF citation source (client-side text-layer geometry)', () => {
    // The render seam returns the rendered page URL + word geometry from the PDF
    // text layer; the widget locates each fact value in those words client-side.
    function installPdfRenderer() {
        global.window.OE_AI_AGENT_PDF_RENDER = jest.fn(function () {
            return Promise.resolve({
                url: 'blob:pdf-page',
                page_width: 2000,
                page_height: 2800,
                words: [
                    { text: 'Hemoglobin', x: 160, y: 496, w: 190, h: 30 },
                    { text: 'A1c', x: 360, y: 496, w: 80, h: 30 },
                ],
            });
        });
    }

    async function renderPdf() {
        document.body.innerHTML = SCAFFOLD;
        // lab fact; NO server citation_boxes — the PDF path locates client-side.
        installFetch({ doc_type: 'lab_pdf', fact: { test_name: 'Hemoglobin A1c', value: '7.4' } });
        loadWidget();
        upload('report.pdf', 'application/pdf');
        await flushAll();
    }

    test('locates a fact value in the PDF text layer and boxes it (client-side)', async () => {
        installPdfRenderer();
        await renderPdf();

        // test_name is found in the text layer -> gets a control; value "7.4" is not
        // present in the (stubbed) words -> no control.
        const ctl = showSource('test_name');
        expect(ctl).not.toBeNull();
        expect(showSource('value')).toBeNull();

        click(ctl);
        expect(modalShown()).toBe(true);
        expect(el('.oe-ai-agent-source-modal .oe-ai-agent-doc-image').getAttribute('src')).toBe('blob:pdf-page');

        const drawn = all('.oe-ai-agent-citation-box');
        expect(drawn.length).toBe(1);
        // union of Hemoglobin(160..350) + A1c(360..440) = x160..440 on a 2000x2800 page
        expect(parseFloat(drawn[0].style.left)).toBeCloseTo(160 / 2000 * 100, 2);
        expect(parseFloat(drawn[0].style.top)).toBeCloseTo(496 / 2800 * 100, 2);
        expect(parseFloat(drawn[0].style.width)).toBeCloseTo((440 - 160) / 2000 * 100, 2);
        // a PDF is rendered by the seam, not object-URL'd
        expect(global.URL.createObjectURL).not.toHaveBeenCalled();
    });

    test('no renderer available => PDF upload degrades to no controls', async () => {
        await renderPdf(); // no OE_AI_AGENT_PDF_RENDER installed
        expect(showSource('test_name')).toBeNull();
        expect(el('.oe-ai-agent-doc-image')).toBeNull();
    });
});
