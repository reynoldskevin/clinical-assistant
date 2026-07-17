/**
 * @jest-environment jsdom
 *
 * T71 acceptance test (LOCKED) — two enhancements to the T70 history accordions:
 *   1. Each accordion heading carries a caret/arrow element to the LEFT of the
 *      title (`.oe-ai-agent-turn-caret`, aria-hidden) plus a `.oe-ai-agent-turn-label`
 *      holding the heading text, and click-toggle still flips aria-expanded / hidden.
 *   2. When a rendered extraction is cleared by a SUBSEQUENT upload, it is archived
 *      into the same history stack — heading = the uploaded file's NAME, body = the
 *      previously-rendered facts panel.
 *
 * The widget (`agent-widget.js`) is a self-executing IIFE. We scaffold its DOM,
 * execute it, then drive the real submit handlers.
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

function loadWidget() {
    new Function(WIDGET_SRC)();
}

function el(sel, root) {
    return (root || document).querySelector(sel);
}

function flush() {
    // Drain all pending microtasks (the token → upload → token → extract → render
    // promise chain settles across several ticks).
    return new Promise(function (resolve) { setTimeout(resolve, 0); });
}

async function flushAll() {
    for (let i = 0; i < 8; i++) {
        await flush();
    }
}

function askQuestion(text) {
    el('.oe-ai-agent-question').value = text;
    el('.oe-ai-agent-form').dispatchEvent(new Event('submit', { cancelable: true }));
}

function answerArrives(text) {
    el('.oe-ai-agent-answer').textContent = text;
    el('.oe-ai-agent-submit').disabled = false;
}

function uploadNamed(name) {
    const fileInput = el('.oe-ai-agent-file');
    Object.defineProperty(fileInput, 'files', {
        configurable: true,
        value: [{ name: name, type: 'image/png' }],
    });
    el('.oe-ai-agent-upload-form').dispatchEvent(new Event('submit', { cancelable: true }));
}

describe('agent-widget: accordion caret indicator', () => {
    beforeEach(() => {
        document.body.innerHTML = SCAFFOLD;
        global.fetch = jest.fn(() => new Promise(() => {}));
        loadWidget();
    });

    test('archived Q&A heading has a caret as its first child, then a label with the question', () => {
        askQuestion('What are the active medications?');
        answerArrives('Metformin 500mg.');
        askQuestion('What is the latest A1c?');

        const heading = el('.oe-ai-agent-history .oe-ai-agent-turn-q');
        expect(heading).not.toBeNull();

        const caret = el('.oe-ai-agent-turn-caret', heading);
        expect(caret).not.toBeNull();
        expect(heading.firstChild).toBe(caret);
        expect(caret.getAttribute('aria-hidden')).toBe('true');

        const label = el('.oe-ai-agent-turn-label', heading);
        expect(label).not.toBeNull();
        expect(label.textContent).toContain('What are the active medications?');
    });

    test('clicking the caret-bearing heading still toggles aria-expanded and hidden', () => {
        askQuestion('Q1');
        answerArrives('A1');
        askQuestion('Q2');

        const heading = el('.oe-ai-agent-turn-q');
        const body = el('.oe-ai-agent-turn-a');
        expect(heading.getAttribute('aria-expanded')).toBe('false');
        expect(body.hasAttribute('hidden')).toBe(true);

        heading.dispatchEvent(new Event('click', { bubbles: true }));
        expect(heading.getAttribute('aria-expanded')).toBe('true');
        expect(body.hasAttribute('hidden')).toBe(false);

        heading.dispatchEvent(new Event('click', { bubbles: true }));
        expect(heading.getAttribute('aria-expanded')).toBe('false');
        expect(body.hasAttribute('hidden')).toBe(true);
    });
});

describe('agent-widget: archive cleared extractions as history items', () => {
    function resolvingFetch() {
        return jest.fn(function (url) {
            const u = String(url);
            function json(body, ok) {
                return Promise.resolve({
                    ok: ok !== false,
                    json: function () { return Promise.resolve(body); },
                });
            }
            if (u.indexOf('token.php') !== -1) {
                return json({ token: 'jwt-token' });
            }
            if (u.indexOf('upload.php') !== -1) {
                return json({ ok: true, id: 42, category: 'Patient Information' });
            }
            if (u.indexOf('/extract') !== -1) {
                return json({
                    ok: true,
                    doc_type: 'intake_form',
                    confidence: 0.9,
                    fact: { demographics: 'Jane Q Patient, DOB 1980-01-01' },
                });
            }
            return json({});
        });
    }

    beforeEach(() => {
        document.body.innerHTML = SCAFFOLD;
        global.fetch = resolvingFetch();
        loadWidget();
    });

    test('a subsequent upload archives the prior extraction keyed by its file name', async () => {
        uploadNamed('first.png');
        await flushAll();

        // The first extraction rendered a real facts panel in the live extract box.
        expect(el('.oe-ai-agent-extract .card')).not.toBeNull();
        expect(el('.oe-ai-agent-extract').textContent).toContain('Jane Q Patient');

        // A second upload clears the first extraction — it must be archived, not lost.
        uploadNamed('second.png');

        const turns = document.querySelectorAll('.oe-ai-agent-history .oe-ai-agent-turn');
        expect(turns.length).toBe(1);

        const heading = el('.oe-ai-agent-turn-q', turns[0]);
        const label = el('.oe-ai-agent-turn-label', heading);
        const body = el('.oe-ai-agent-turn-a', turns[0]);

        expect(label.textContent).toContain('first.png');
        expect(body.textContent).toContain('Jane Q Patient');

        // Collapsed by default; the live extract box no longer shows the first facts.
        expect(heading.getAttribute('aria-expanded')).toBe('false');
        expect(body.hasAttribute('hidden')).toBe(true);
        expect(el('.oe-ai-agent-extract').textContent).not.toContain('Jane Q Patient');

        // Expands on click.
        heading.dispatchEvent(new Event('click', { bubbles: true }));
        expect(heading.getAttribute('aria-expanded')).toBe('true');
        expect(body.hasAttribute('hidden')).toBe(false);
    });

    test('the first upload archives no extraction item', async () => {
        uploadNamed('only.png');
        await flushAll();
        expect(document.querySelectorAll('.oe-ai-agent-history .oe-ai-agent-turn').length).toBe(0);
    });

    test('asking a question does not archive or clear the extraction panel', async () => {
        uploadNamed('scan.png');
        await flushAll();
        expect(el('.oe-ai-agent-extract .card')).not.toBeNull();

        askQuestion('What meds is the patient on?');

        // The extraction stays put; no extraction accordion is created by a question.
        expect(el('.oe-ai-agent-extract .card')).not.toBeNull();
        const labels = Array.from(
            document.querySelectorAll('.oe-ai-agent-history .oe-ai-agent-turn-label')
        ).map(function (n) { return n.textContent; });
        expect(labels.some(function (t) { return t.indexOf('scan.png') !== -1; })).toBe(false);
    });
});
