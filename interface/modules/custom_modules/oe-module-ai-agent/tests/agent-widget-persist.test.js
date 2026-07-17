/**
 * @jest-environment jsdom
 *
 * T53d acceptance test (LOCKED) — "Accept & file to chart" on the extracted-facts
 * panel. After a document is extracted, a clinician can file the facts to the chart:
 * the button POSTs the held fact envelope (+ document id + extraction-run id + csrf)
 * to persist.php, disables while in flight, and confirms on success. The button is
 * hidden when the wrong-chart identity check flags a mismatch.
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

// Resolving fetch for the upload → extract flow. `identityMatches=false` makes the
// extract response report a wrong-chart mismatch. Records all calls for assertions.
function installFetch(identityMatches, duplicate) {
    const calls = [];
    global.fetch = jest.fn(function (url, opts) {
        const u = String(url);
        calls.push({ url: u, opts: opts || {} });
        function json(body, ok) {
            return Promise.resolve({ ok: ok !== false, json: function () { return Promise.resolve(body); } });
        }
        if (u.indexOf('token.php') !== -1) {
            return json({ token: 'jwt' });
        }
        if (u.indexOf('upload.php') !== -1) {
            return json({ ok: true, id: 42, category: 'Patient Information', duplicate: duplicate === true });
        }
        if (u.indexOf('/extract') !== -1) {
            return json({
                ok: true,
                doc_type: 'intake_form',
                confidence: 0.9,
                correlation_id: 'run-xyz',
                fact: { demographics: 'Jane Doe', allergies: 'Penicillin' },
                identity_check: identityMatches === false
                    ? { matches: false, mismatched_identifiers: ['name'] }
                    : { matches: true, mismatched_identifiers: [] },
            });
        }
        if (u.indexOf('persist.php') !== -1) {
            return json({ ok: true, doc_type: 'intake_form', total: 3, filed: [], superseded: 0 });
        }
        return json({});
    });
    return calls;
}

function uploadNamed(name) {
    const fileInput = el('.oe-ai-agent-file');
    Object.defineProperty(fileInput, 'files', {
        configurable: true,
        value: [{ name: name, type: 'image/png' }],
    });
    el('.oe-ai-agent-upload-form').dispatchEvent(new Event('submit', { cancelable: true }));
}

describe('agent-widget: Accept & file to chart', () => {
    test('the facts panel shows a file-to-chart button after extraction', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch(true);
        loadWidget();

        uploadNamed('intake.png');
        await flushAll();

        const btn = el('.oe-ai-agent-extract .oe-ai-agent-file-btn');
        expect(btn).not.toBeNull();
        expect(btn.textContent.toLowerCase()).toContain('file to chart');
    });

    test('clicking the button POSTs the fact envelope to persist.php and disables while in flight', async () => {
        document.body.innerHTML = SCAFFOLD;
        const calls = installFetch(true);
        loadWidget();

        uploadNamed('intake.png');
        await flushAll();

        const btn = el('.oe-ai-agent-extract .oe-ai-agent-file-btn');
        btn.dispatchEvent(new Event('click', { bubbles: true }));

        const persistCall = calls.find(function (c) { return c.url.indexOf('persist.php') !== -1; });
        expect(persistCall).toBeTruthy();
        expect(String(persistCall.opts.method).toUpperCase()).toBe('POST');
        const body = String(persistCall.opts.body);
        expect(body).toContain('source_document_id');
        expect(body).toContain('42');
        expect(body).toContain('extraction_run_id');
        expect(body).toContain('run-xyz');
        expect(body).toContain('intake_form');
        // Disabled immediately on click (before the request resolves).
        expect(btn.disabled).toBe(true);
    });

    test('a successful file shows a confirmation', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch(true);
        loadWidget();

        uploadNamed('intake.png');
        await flushAll();

        el('.oe-ai-agent-extract .oe-ai-agent-file-btn')
            .dispatchEvent(new Event('click', { bubbles: true }));
        await flushAll();

        expect(el('.oe-ai-agent-extract').textContent.toLowerCase()).toContain('filed');
    });

    test('the file button is hidden when the identity check flags a wrong-chart mismatch', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch(false);
        loadWidget();

        uploadNamed('wrongchart.png');
        await flushAll();

        // The wrong-chart warning renders, but no file-to-chart button is offered.
        expect(el('.oe-ai-agent-extract').textContent).toContain('Possible wrong-chart');
        expect(el('.oe-ai-agent-extract .oe-ai-agent-file-btn')).toBeNull();
    });

    test('an already-on-file (duplicate) upload disables the button with a clear label', async () => {
        document.body.innerHTML = SCAFFOLD;
        const calls = installFetch(true, true); // duplicate = true
        loadWidget();

        uploadNamed('already-here.png');
        await flushAll();

        const btn = el('.oe-ai-agent-extract .oe-ai-agent-file-btn');
        expect(btn).not.toBeNull();
        expect(btn.disabled).toBe(true);
        expect(btn.textContent.toLowerCase()).toContain('cannot file an old upload');

        // Clicking it does nothing — no persist request fires.
        btn.dispatchEvent(new Event('click', { bubbles: true }));
        await flushAll();
        expect(calls.some(function (c) { return c.url.indexOf('persist.php') !== -1; })).toBe(false);
    });
});
