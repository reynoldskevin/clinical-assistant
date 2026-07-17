/**
 * @jest-environment jsdom
 *
 * T56e acceptance test (LOCKED) — [show source] control + modal overlay.
 *
 * Each cited fact renders a small "show source" control (not the whole row).
 * Clicking it opens a MODAL overlay showing the document image with ONLY that
 * fact's box(es). Another fact's control swaps the boxes; the close button, the
 * backdrop, or re-clicking the active control dismisses the modal. The per-field
 * `citation_boxes` contract (T56d) is unchanged.
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

function installFetch(boxes) {
    global.fetch = jest.fn(function (url) {
        const u = String(url);
        function json(body, ok) {
            return Promise.resolve({ ok: ok !== false, json: function () { return Promise.resolve(body); } });
        }
        if (u.indexOf('token.php') !== -1) { return json({ token: 'jwt' }); }
        if (u.indexOf('upload.php') !== -1) { return json({ ok: true, id: 42, category: 'Patient Information', duplicate: false }); }
        if (u.indexOf('/extract') !== -1) {
            const body = {
                ok: true,
                doc_type: 'intake_form',
                confidence: 0.9,
                correlation_id: 'run-1',
                fact: { chief_concern: 'chest pain', current_medications: 'lisinopril', allergies: 'none' },
                identity_check: { matches: true, mismatched_identifiers: [] }
            };
            if (boxes) {
                body.citation_boxes = boxes;
                body.page_width = 400;
                body.page_height = 600;
            }
            return json(body);
        }
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

const BOXES = {
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

describe('agent-widget: [show source] control + modal overlay', () => {
    async function render(boxes) {
        document.body.innerHTML = SCAFFOLD;
        installFetch(boxes);
        loadWidget();
        upload('intake.png', 'image/png');
        await flushAll();
    }

    test('each cited fact gets a small "show source" control; non-cited do not', async () => {
        await render(BOXES);
        const ctl = showSource('chief_concern');
        expect(ctl).not.toBeNull();
        expect(ctl.textContent.toLowerCase()).toContain('source');
        expect(showSource('current_medications')).not.toBeNull();
        expect(showSource('allergies')).toBeNull();
        // the value text is still shown for the fact
        expect(el('.oe-ai-agent-extract').textContent.toLowerCase()).toContain('chest pain');
    });

    test('the whole fact row is NOT the click target (only the small control)', async () => {
        await render(BOXES);
        // no dd carries the click affordance any more
        expect(el('.oe-ai-agent-extract dd[data-field]')).toBeNull();
        expect(el('.oe-ai-agent-extract dd[role="button"]')).toBeNull();
    });

    test('the modal is hidden until a source is opened', async () => {
        await render(BOXES);
        expect(modalShown()).toBe(false);
        expect(all('.oe-ai-agent-citation-box').length).toBe(0);
    });

    test('clicking [show source] opens the modal with ONLY that fact\'s box', async () => {
        await render(BOXES);
        click(showSource('chief_concern'));

        expect(modalShown()).toBe(true);
        expect(el('.oe-ai-agent-source-modal .oe-ai-agent-doc-image').getAttribute('src')).toBe('blob:preview-xyz');
        const drawn = all('.oe-ai-agent-citation-box');
        expect(drawn.length).toBe(1);
        expect(parseFloat(drawn[0].style.top)).toBeCloseTo(100 / 600 * 100, 3);
    });

    test('another fact\'s [show source] swaps to its boxes', async () => {
        await render(BOXES);
        click(showSource('chief_concern'));
        click(showSource('current_medications'));

        const drawn = all('.oe-ai-agent-citation-box');
        expect(drawn.length).toBe(2);
        const tops = drawn.map(function (b) { return parseFloat(b.style.top); }).sort();
        expect(tops[0]).toBeCloseTo(140 / 600 * 100, 3);
        expect(tops[1]).toBeCloseTo(180 / 600 * 100, 3);
    });

    test('the close button dismisses the modal and clears boxes', async () => {
        await render(BOXES);
        click(showSource('chief_concern'));
        expect(modalShown()).toBe(true);
        click(el('.oe-ai-agent-source-close'));
        expect(modalShown()).toBe(false);
        expect(all('.oe-ai-agent-citation-box').length).toBe(0);
    });

    test('clicking the backdrop dismisses the modal', async () => {
        await render(BOXES);
        click(showSource('chief_concern'));
        expect(modalShown()).toBe(true);
        // clicking the modal backdrop itself (not its inner content) closes it
        click(el('.oe-ai-agent-source-modal'));
        expect(modalShown()).toBe(false);
    });

    test('re-clicking the active fact\'s [show source] toggles the modal closed', async () => {
        await render(BOXES);
        click(showSource('current_medications'));
        expect(modalShown()).toBe(true);
        click(showSource('current_medications'));
        expect(modalShown()).toBe(false);
    });

    test('no citation_boxes => no controls and no modal; facts still render', async () => {
        await render(null);
        expect(el('.oe-ai-agent-extract .card')).not.toBeNull();
        expect(el('.oe-ai-agent-extract').textContent.toLowerCase()).toContain('chest pain');
        expect(showSource('chief_concern')).toBeNull();
        expect(el('.oe-ai-agent-doc-image')).toBeNull();
    });

    test('a PDF upload renders its page via the renderer seam and enables the source controls', async () => {
        const pdfRender = jest.fn(function () { return Promise.resolve('blob:pdf-page'); });
        global.window.OE_AI_AGENT_PDF_RENDER = pdfRender;

        document.body.innerHTML = SCAFFOLD;
        installFetch(BOXES);
        loadWidget();
        upload('report.pdf', 'application/pdf');
        await flushAll();

        expect(pdfRender).toHaveBeenCalled();
        const ctl = showSource('chief_concern');
        expect(ctl).not.toBeNull();
        click(ctl);
        expect(modalShown()).toBe(true);
        expect(el('.oe-ai-agent-source-modal .oe-ai-agent-doc-image').getAttribute('src')).toBe('blob:pdf-page');
        expect(all('.oe-ai-agent-citation-box').length).toBe(1);
        // a PDF is rendered, not object-URL'd
        expect(global.URL.createObjectURL).not.toHaveBeenCalled();
    });

    test('a PDF upload with no renderer available degrades to no controls', async () => {
        // no OE_AI_AGENT_PDF_RENDER hook present (cleared in beforeEach)
        document.body.innerHTML = SCAFFOLD;
        installFetch(BOXES);
        loadWidget();
        upload('report.pdf', 'application/pdf');
        await flushAll();
        expect(showSource('chief_concern')).toBeNull();
        expect(el('.oe-ai-agent-doc-image')).toBeNull();
    });
});
