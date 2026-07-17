/**
 * @jest-environment jsdom
 *
 * T56b acceptance test (LOCKED) — citation bounding-box overlay on the card.
 *
 * When the /extract response carries `citation_boxes` + `page_width`/`page_height`
 * (the T56a contract) and the upload was an IMAGE, the card renders a preview of
 * the document with one positioned overlay box per citation, so a clinician can
 * see exactly where each extracted fact came from. Boxes are positioned as
 * percentages of the page so they scale with the rendered image. No boxes (or a
 * non-image upload) => no overlay, and the existing facts panel is unchanged.
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

function el(sel, root) {
    return (root || document).querySelector(sel);
}

function all(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
}

function loadWidget() {
    new Function(WIDGET_SRC)();
}

function flushAll() {
    return new Promise(function (resolve) {
        let n = 0;
        (function tick() {
            if (n++ > 10) {
                return resolve();
            }
            setTimeout(tick, 0);
        })();
    });
}

// Resolves the upload -> extract flow. `boxes` (when provided) are echoed back on
// the extract response as citation_boxes with a fixed 400x600 page.
function installFetch(boxes) {
    global.fetch = jest.fn(function (url) {
        const u = String(url);
        function json(body, ok) {
            return Promise.resolve({ ok: ok !== false, json: function () { return Promise.resolve(body); } });
        }
        if (u.indexOf('token.php') !== -1) {
            return json({ token: 'jwt' });
        }
        if (u.indexOf('upload.php') !== -1) {
            return json({ ok: true, id: 42, category: 'Patient Information', duplicate: false });
        }
        if (u.indexOf('/extract') !== -1) {
            const body = {
                ok: true,
                doc_type: 'intake_form',
                confidence: 0.9,
                correlation_id: 'run-1',
                fact: { chief_concern: 'chest pain' },
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

beforeEach(() => {
    global.URL.createObjectURL = jest.fn(function () { return 'blob:preview-xyz'; });
});

describe('agent-widget: citation bounding-box overlay', () => {
    test('renders an image preview with one percentage-positioned box per citation', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch([{ x: 10, y: 100, w: 100, h: 20 }, { x: 10, y: 140, w: 80, h: 20 }]);
        loadWidget();

        upload('intake.png', 'image/png');
        await flushAll();

        const img = el('.oe-ai-agent-extract .oe-ai-agent-doc-image');
        expect(img).not.toBeNull();
        expect(img.getAttribute('src')).toBe('blob:preview-xyz');

        const drawn = all('.oe-ai-agent-extract .oe-ai-agent-citation-box');
        expect(drawn.length).toBe(2);

        // First box: x=10/400=2.5%, y=100/600≈16.667%, w=100/400=25%, h=20/600≈3.333%.
        expect(parseFloat(drawn[0].style.left)).toBeCloseTo(2.5, 3);
        expect(parseFloat(drawn[0].style.top)).toBeCloseTo(16.6667, 3);
        expect(parseFloat(drawn[0].style.width)).toBeCloseTo(25, 3);
        expect(parseFloat(drawn[0].style.height)).toBeCloseTo(3.3333, 3);
    });

    test('facts still render alongside the overlay', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch([{ x: 10, y: 100, w: 100, h: 20 }]);
        loadWidget();

        upload('intake.png', 'image/png');
        await flushAll();

        // The existing facts card is still present.
        expect(el('.oe-ai-agent-extract .card')).not.toBeNull();
        expect(el('.oe-ai-agent-extract').textContent.toLowerCase()).toContain('chest pain');
    });

    test('no citation_boxes => no overlay, facts panel unchanged', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch(null); // extract response without citation_boxes
        loadWidget();

        upload('intake.png', 'image/png');
        await flushAll();

        expect(el('.oe-ai-agent-extract .oe-ai-agent-doc-image')).toBeNull();
        expect(all('.oe-ai-agent-extract .oe-ai-agent-citation-box').length).toBe(0);
        // facts panel still rendered
        expect(el('.oe-ai-agent-extract .card')).not.toBeNull();
    });

    test('a non-image (PDF) upload renders no preview even when boxes are present', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch([{ x: 10, y: 100, w: 100, h: 20 }]);
        loadWidget();

        upload('report.pdf', 'application/pdf');
        await flushAll();

        expect(el('.oe-ai-agent-extract .oe-ai-agent-doc-image')).toBeNull();
        expect(global.URL.createObjectURL).not.toHaveBeenCalled();
    });
});
