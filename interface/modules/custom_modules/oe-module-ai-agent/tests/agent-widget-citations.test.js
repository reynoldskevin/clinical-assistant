/**
 * @jest-environment jsdom
 *
 * T72b acceptance test (LOCKED) — clickable [Sn] citations in the answer.
 *
 * The /ask/stream `done` frame carries a `citations` map (T72a:
 * {marker: {ref, type, section, text}}). After the answer renders, each [Sn]
 * marker whose number is in the map becomes a small clickable control; clicking
 * it opens a modal showing that citation's source (its text + section). Markers
 * with no matching source stay plain text.
 *
 * Deterministic: the streaming SSE response is mocked with a ReadableStream-like
 * reader; no live sidecar.
 */
/* global __dirname, setTimeout */
const fs = require('fs');
const path = require('path');
// jsdom's Jest env omits TextEncoder/TextDecoder; the widget's SSE reader uses
// TextDecoder, so provide Node's (the browser has these natively).
const { TextEncoder, TextDecoder } = require('util');
global.TextEncoder = global.TextEncoder || TextEncoder;
global.TextDecoder = global.TextDecoder || TextDecoder;

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
        (function tick() { if (n++ > 25) { return resolve(); } setTimeout(tick, 0); })();
    });
}

const CITATIONS = {
    '1': { ref: 'guideline:g1', type: 'guideline', section: 'ADA 2024 - Glycemic Targets', text: 'Target HbA1c below 7 percent for most adults.' },
    '2': { ref: 'prescription:1', type: 'record', section: 'Medications', text: 'Warfarin Sodium 5 MG' },
};

// A ReadableStream-like body that yields the given SSE frame strings.
function streamOf(frames) {
    const enc = new TextEncoder();
    const chunks = frames.map(function (f) { return enc.encode(f); });
    let i = 0;
    return {
        ok: true,
        body: {
            getReader: function () {
                return {
                    read: function () {
                        if (i < chunks.length) { return Promise.resolve({ value: chunks[i++], done: false }); }
                        return Promise.resolve({ value: undefined, done: true });
                    }
                };
            }
        }
    };
}

function installAskFetch(citations) {
    const answerFrame = 'event: answer\ndata: ' +
        JSON.stringify({ answer: 'Target is under 7 percent [S1]. Warfarin is active [S2]. Aspirin noted [S9].' }) + '\n\n';
    const doneData = { ok: true, correlation_id: 'c' };
    if (citations) { doneData.citations = citations; }
    const doneFrame = 'event: done\ndata: ' + JSON.stringify(doneData) + '\n\n';
    global.fetch = jest.fn(function (url) {
        const u = String(url);
        if (u.indexOf('token.php') !== -1) {
            return Promise.resolve({ ok: true, json: function () { return Promise.resolve({ token: 'jwt' }); } });
        }
        if (u.indexOf('/ask') !== -1) {
            return Promise.resolve(streamOf([answerFrame, doneFrame]));
        }
        return Promise.resolve({ ok: true, json: function () { return Promise.resolve({}); } });
    });
}

function ask(text) {
    el('.oe-ai-agent-question').value = text || 'how is the patient?';
    el('.oe-ai-agent-form').dispatchEvent(new Event('submit', { cancelable: true }));
}

function cite(n) { return el('.oe-ai-agent-answer .oe-ai-agent-cite[data-n="' + n + '"]'); }
function click(e) { e.dispatchEvent(new Event('click', { bubbles: true })); }
function modalShown() {
    const m = el('.oe-ai-agent-source-modal');
    return m !== null && m.style.display !== 'none';
}

describe('agent-widget: clickable [Sn] citations', () => {
    async function run(citations) {
        document.body.innerHTML = SCAFFOLD;
        installAskFetch(citations);
        loadWidget();
        ask();
        await flushAll();
    }

    test('markers with a matching source become clickable controls', async () => {
        await run(CITATIONS);
        expect(cite('1')).not.toBeNull();
        expect(cite('1').textContent).toContain('S1');
        expect(cite('2')).not.toBeNull();
        // [S9] has no entry in the citations map -> stays plain text (not a control)
        expect(cite('9')).toBeNull();
        expect(el('.oe-ai-agent-answer').textContent).toContain('[S9]');
    });

    test('clicking a citation opens a modal showing its source', async () => {
        await run(CITATIONS);
        expect(modalShown()).toBe(false);
        click(cite('1'));
        expect(modalShown()).toBe(true);
        const text = el('.oe-ai-agent-source-modal').textContent;
        expect(text).toContain('Target HbA1c below 7 percent');
        expect(text).toContain('ADA 2024 - Glycemic Targets');
    });

    test('clicking a different citation swaps the source', async () => {
        await run(CITATIONS);
        click(cite('1'));
        click(cite('2'));
        expect(modalShown()).toBe(true);
        expect(el('.oe-ai-agent-source-modal').textContent).toContain('Warfarin Sodium 5 MG');
    });

    test('the close button dismisses the citation modal', async () => {
        await run(CITATIONS);
        click(cite('1'));
        expect(modalShown()).toBe(true);
        click(el('.oe-ai-agent-source-close'));
        expect(modalShown()).toBe(false);
    });

    test('with no citations map, markers stay plain text', async () => {
        await run(null);
        expect(cite('1')).toBeNull();
        expect(el('.oe-ai-agent-answer').textContent).toContain('[S1]');
    });
});
