/**
 * @jest-environment jsdom
 *
 * T75c acceptance test (LOCKED) — med_list (third document type) in the card UI.
 *
 * A clinician selects "Medication List" and uploads a medication-list PDF; the
 * widget extracts a MedicationListFact ({medications, source_citation}), renders
 * its fields in the FACT_FIELDS order (medications before source_citation, even
 * when the /extract JSON lists them the other way), and the existing (doc-type
 * agnostic) file-to-chart button POSTs the envelope to persist.php and confirms.
 *
 * Deterministic: mocked token/upload/extract/persist fetches; no live sidecar.
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
    <select class="oe-ai-agent-doc-type"><option value="med_list" selected>Medication List</option></select>
    <button type="submit" class="oe-ai-agent-upload-submit">Upload</button>
    <div class="oe-ai-agent-upload-status"></div>
  </form>
  <div class="oe-ai-agent-extract"></div>
</div>
`;

const MEDS = 'Lisinopril 10 mg PO once daily; Metformin 500 mg PO twice daily';
const CITE = 'Medication list, page 1';

function el(sel, root) { return (root || document).querySelector(sel); }
function loadWidget() { new Function(WIDGET_SRC)(); }

function flushAll() {
    return new Promise(function (resolve) {
        let n = 0;
        (function tick() { if (n++ > 10) { return resolve(); } setTimeout(tick, 0); })();
    });
}

function installFetch() {
    const calls = [];
    global.fetch = jest.fn(function (url, opts) {
        const u = String(url);
        calls.push({ url: u, opts: opts || {} });
        function json(body) {
            return Promise.resolve({ ok: true, json: function () { return Promise.resolve(body); } });
        }
        if (u.indexOf('token.php') !== -1) { return json({ token: 'jwt' }); }
        if (u.indexOf('upload.php') !== -1) { return json({ ok: true, id: 77, category: 'Patient Information', duplicate: false }); }
        if (u.indexOf('/extract') !== -1) {
            return json({
                ok: true,
                doc_type: 'med_list',
                confidence: 0.94,
                correlation_id: 'run-med',
                // NOTE: source_citation is listed BEFORE medications on purpose —
                // only FACT_FIELDS[med_list] ordering renders medications first.
                fact: { source_citation: CITE, medications: MEDS },
            });
        }
        if (u.indexOf('persist.php') !== -1) {
            return json({ ok: true, doc_type: 'med_list', total: 2, filed: [{ fact_type: 'medication', count: 2 }], superseded: 0 });
        }
        return json({});
    });
    return calls;
}

function upload() {
    const fileInput = el('.oe-ai-agent-file');
    Object.defineProperty(fileInput, 'files', {
        configurable: true,
        value: [{ name: 'medlist.pdf', type: 'application/pdf' }],
    });
    el('.oe-ai-agent-upload-form').dispatchEvent(new Event('submit', { cancelable: true }));
}

describe('agent-widget: med_list document type', () => {
    test('a med_list extraction renders its fields, medications before source_citation', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch();
        loadWidget();

        upload();
        await flushAll();

        const text = el('.oe-ai-agent-extract').textContent;
        expect(text).toContain('Lisinopril');
        expect(text).toContain(CITE);
        // FACT_FIELDS[med_list] order = [medications, source_citation] — medications
        // renders first even though the /extract JSON listed source_citation first.
        expect(text.indexOf('Lisinopril')).toBeLessThan(text.indexOf(CITE));
    });

    test('the upload posts doc_type=med_list to /extract', async () => {
        document.body.innerHTML = SCAFFOLD;
        const calls = installFetch();
        loadWidget();

        upload();
        await flushAll();

        const extractCall = calls.find(function (c) { return c.url.indexOf('/extract') !== -1; });
        expect(extractCall).toBeTruthy();
        expect(String(extractCall.opts.body)).toContain('med_list');
    });

    test('the extracted medications can be filed to the chart', async () => {
        document.body.innerHTML = SCAFFOLD;
        const calls = installFetch();
        loadWidget();

        upload();
        await flushAll();

        const btn = el('.oe-ai-agent-extract .oe-ai-agent-file-btn');
        expect(btn).not.toBeNull();
        btn.dispatchEvent(new Event('click', { bubbles: true }));
        await flushAll();

        const persistCall = calls.find(function (c) { return c.url.indexOf('persist.php') !== -1; });
        expect(persistCall).toBeTruthy();
        expect(String(persistCall.opts.method).toUpperCase()).toBe('POST');
        expect(String(persistCall.opts.body)).toContain('med_list');
        expect(el('.oe-ai-agent-extract').textContent.toLowerCase()).toContain('filed');
    });
});
