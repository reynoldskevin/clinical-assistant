/**
 * @jest-environment jsdom
 *
 * Guideline-evidence citations render as clickable chips.
 *
 * The live sidecar cites guideline evidence with the raw ref in brackets
 * (e.g. "[guideline:diabetes:glycemic-targets]") and carries that ref as a KEY
 * in the `done` frame's citations map (type: guideline). Record facts stay
 * numbered "[Sn]". This test pins that guideline markers become compact "[Gk]"
 * chips that open their source, record "[Sn]" chips still work, and internal
 * "[openemr:...]" sentinels are stripped from the visible text.
 *
 * Deterministic: the streaming SSE response is mocked; no live sidecar.
 */
/* global __dirname, setTimeout */
const fs = require('fs');
const path = require('path');
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
function loadWidget() { new Function(WIDGET_SRC)(); }
function flushAll() {
    return new Promise(function (resolve) {
        let n = 0;
        (function tick() { if (n++ > 25) { return resolve(); } setTimeout(tick, 0); })();
    });
}

const GREF = 'guideline:diabetes:glycemic-targets';
const CITATIONS = {
    '2': { ref: 'prescription:1', type: 'record', section: 'Medications', text: 'Warfarin Sodium 5 MG' },
    [GREF]: { ref: GREF, type: 'guideline', section: 'Diabetes - Glycemic Targets', text: 'A reasonable HbA1c goal is below 7 percent.' }
};

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
        JSON.stringify({
            answer: 'HbA1c below 7 percent [' + GREF + ']. Warfarin is active [S2]. No aspirin documented [openemr:_absence].'
        }) + '\n\n';
    const doneFrame = 'event: done\ndata: ' + JSON.stringify({ ok: true, correlation_id: 'c', citations: citations }) + '\n\n';
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

function ask() {
    el('.oe-ai-agent-question').value = 'guideline question';
    el('.oe-ai-agent-form').dispatchEvent(new Event('submit', { cancelable: true }));
}
function click(e) { e.dispatchEvent(new Event('click', { bubbles: true })); }
function modalShown() {
    const m = el('.oe-ai-agent-source-modal');
    return m !== null && m.style.display !== 'none';
}

describe('agent-widget: guideline-evidence citations', () => {
    async function run() {
        document.body.innerHTML = SCAFFOLD;
        installAskFetch(CITATIONS);
        loadWidget();
        ask();
        await flushAll();
    }

    test('a [guideline:...] marker becomes a compact [Gk] chip', async () => {
        await run();
        const chip = el('.oe-ai-agent-answer .oe-ai-agent-cite[data-n="' + GREF + '"]');
        expect(chip).not.toBeNull();
        expect(chip.textContent).toBe('[G1]');
        // the raw ref is no longer visible as text
        expect(el('.oe-ai-agent-answer').textContent).not.toContain(GREF);
    });

    test('clicking the guideline chip opens its source', async () => {
        await run();
        click(el('.oe-ai-agent-answer .oe-ai-agent-cite[data-n="' + GREF + '"]'));
        expect(modalShown()).toBe(true);
        const text = el('.oe-ai-agent-source-modal').textContent;
        expect(text).toContain('A reasonable HbA1c goal is below 7 percent.');
        expect(text).toContain('Diabetes - Glycemic Targets');
    });

    test('record [Sn] chips still render alongside guideline chips', async () => {
        await run();
        const s2 = el('.oe-ai-agent-answer .oe-ai-agent-cite[data-n="2"]');
        expect(s2).not.toBeNull();
        expect(s2.textContent).toBe('[S2]');
    });

    test('internal [openemr:...] sentinels are stripped from the visible text', async () => {
        await run();
        expect(el('.oe-ai-agent-answer').textContent).not.toContain('openemr:_absence');
        expect(el('.oe-ai-agent-answer').textContent).not.toContain('[openemr');
    });

    test('an unresolved [guideline:...] marker (absent from the map) is stripped, not shown raw', async () => {
        document.body.innerHTML = SCAFFOLD;
        const answerFrame = 'event: answer\ndata: ' +
            JSON.stringify({ answer: 'HbA1c below 7 percent [guideline:diabetes:unmapped]. Warfarin active [S2].' }) + '\n\n';
        // citations map has the record ref but NOT the guideline ref
        const doneFrame = 'event: done\ndata: ' +
            JSON.stringify({ ok: true, correlation_id: 'c', citations: { '2': CITATIONS['2'] } }) + '\n\n';
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
        loadWidget();
        ask();
        await flushAll();
        const a = el('.oe-ai-agent-answer');
        // the raw unresolved guideline tag is gone...
        expect(a.textContent).not.toContain('guideline:diabetes:unmapped');
        expect(a.textContent).not.toContain('[guideline');
        // ...and it did NOT become a chip (no source to show), while the record chip stays
        expect(a.querySelector('.oe-ai-agent-cite[data-n="guideline:diabetes:unmapped"]')).toBeNull();
        expect(a.querySelector('.oe-ai-agent-cite[data-n="2"]')).not.toBeNull();
    });
});
