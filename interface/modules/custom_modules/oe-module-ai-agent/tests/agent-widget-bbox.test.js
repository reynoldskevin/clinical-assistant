/**
 * @jest-environment jsdom
 *
 * T56d acceptance test (LOCKED) — click-to-reveal per-fact citation source.
 *
 * The overlay is NOT drawn all at once. The /extract response carries boxes keyed
 * PER FIELD (`citation_boxes = {field: [ {x,y,w,h} ]}`). Each cited fact is a
 * clickable control; clicking it reveals a document-image preview overlaying ONLY
 * that fact's box(es). Clicking the active fact again hides the preview. Facts with
 * no boxes are not clickable; no boxes / non-image upload => no preview.
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

// `boxes` is the per-field citation_boxes map (or null to omit it entirely).
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

// chief_concern has 1 box; current_medications has 2; allergies has NONE.
const BOXES = {
    chief_concern: [{ x: 10, y: 100, w: 100, h: 20 }],
    current_medications: [{ x: 10, y: 140, w: 80, h: 20 }, { x: 10, y: 180, w: 60, h: 20 }],
};

function click(elm) { elm.dispatchEvent(new Event('click', { bubbles: true })); }

function previewShown() {
    const p = el('.oe-ai-agent-extract .oe-ai-agent-doc-preview');
    return p !== null && p.style.display !== 'none';
}

beforeEach(() => {
    global.URL.createObjectURL = jest.fn(function () { return 'blob:preview-xyz'; });
});

describe('agent-widget: click-to-reveal per-fact citation source', () => {
    async function render(boxes) {
        document.body.innerHTML = SCAFFOLD;
        installFetch(boxes);
        loadWidget();
        upload('intake.png', 'image/png');
        await flushAll();
    }

    test('nothing is drawn until a fact is clicked', async () => {
        await render(BOXES);
        expect(all('.oe-ai-agent-citation-box').length).toBe(0);
        expect(previewShown()).toBe(false);
    });

    test('only cited facts are clickable controls', async () => {
        await render(BOXES);
        expect(el('[data-field="chief_concern"]')).not.toBeNull();
        expect(el('[data-field="chief_concern"]').className).toContain('oe-ai-agent-fact-cite');
        expect(el('[data-field="current_medications"]')).not.toBeNull();
        // allergies had no boxes -> not clickable
        expect(el('[data-field="allergies"]')).toBeNull();
    });

    test('clicking a fact reveals the preview with ONLY that fact\'s box', async () => {
        await render(BOXES);
        click(el('[data-field="chief_concern"]'));

        expect(previewShown()).toBe(true);
        expect(el('.oe-ai-agent-doc-image').getAttribute('src')).toBe('blob:preview-xyz');
        const drawn = all('.oe-ai-agent-citation-box');
        expect(drawn.length).toBe(1);
        expect(parseFloat(drawn[0].style.top)).toBeCloseTo(100 / 600 * 100, 3);
    });

    test('clicking another fact swaps to that fact\'s boxes only', async () => {
        await render(BOXES);
        click(el('[data-field="chief_concern"]'));
        click(el('[data-field="current_medications"]'));

        const drawn = all('.oe-ai-agent-citation-box');
        expect(drawn.length).toBe(2); // current_medications has two boxes
        const tops = drawn.map(function (b) { return parseFloat(b.style.top); }).sort();
        expect(tops[0]).toBeCloseTo(140 / 600 * 100, 3);
        expect(tops[1]).toBeCloseTo(180 / 600 * 100, 3);
        // the chief_concern box (top 16.667%) is gone
        expect(tops).not.toContain(100 / 600 * 100);
    });

    test('clicking the active fact again hides the preview (toggle)', async () => {
        await render(BOXES);
        click(el('[data-field="current_medications"]'));
        expect(previewShown()).toBe(true);
        click(el('[data-field="current_medications"]'));
        expect(previewShown()).toBe(false);
        expect(all('.oe-ai-agent-citation-box').length).toBe(0);
    });

    test('facts still render; no citation_boxes => no clickable facts, no preview', async () => {
        await render(null);
        expect(el('.oe-ai-agent-extract .card')).not.toBeNull();
        expect(el('.oe-ai-agent-extract').textContent.toLowerCase()).toContain('chest pain');
        expect(el('[data-field="chief_concern"]')).toBeNull();
        expect(el('.oe-ai-agent-doc-image')).toBeNull();
    });

    test('a non-image (PDF) upload has no clickable citations even with boxes', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch(BOXES);
        loadWidget();
        upload('report.pdf', 'application/pdf');
        await flushAll();
        expect(el('[data-field="chief_concern"]')).toBeNull();
        expect(global.URL.createObjectURL).not.toHaveBeenCalled();
    });
});
