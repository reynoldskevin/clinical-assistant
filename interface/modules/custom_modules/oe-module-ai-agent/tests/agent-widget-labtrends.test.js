/**
 * @jest-environment jsdom
 *
 * T77 acceptance test (LOCKED) — the "Lab trends" chart in the Co-Pilot card.
 *
 * On demand (clicking the "Lab trends" button) the widget mints its pid-scoped
 * JWT, POSTs read.php {op:'get_results', pid} with Authorization: Bearer <jwt>,
 * groups the numeric results by test name, and renders a dependency-free inline
 * SVG line chart for a selected test (a series <select> lists every numeric
 * test), with abnormal points marked and the reference range shown.
 *
 * CONTRACT: the mocked read.php response is the SHARED fixture
 * tests/fixtures/get_results_contract.json — the exact row shape
 * PatientSummaryService::getResults emits (pinned producer-side by
 * ChartReadServiceResultsTest). A producer shape change breaks this consumer.
 *
 * Deterministic: mocked token/read fetches; no live boundary.
 */
/* global __dirname, setTimeout */
const fs = require('fs');
const path = require('path');

const WIDGET_SRC = fs.readFileSync(
    path.join(__dirname, '..', 'public', 'agent-widget.js'),
    'utf8'
);

const CONTRACT_ROWS = JSON.parse(fs.readFileSync(
    path.join(__dirname, 'fixtures', 'get_results_contract.json'),
    'utf8'
));

const SCAFFOLD = `
<div id="oe-ai-agent" data-pid="1" data-csrf="tok" data-sidecar-url="http://localhost:8900/ask">
  <div class="oe-ai-agent-answer"></div>
  <form class="oe-ai-agent-form">
    <textarea class="oe-ai-agent-question"></textarea>
    <button type="submit" class="oe-ai-agent-submit">Ask</button>
  </form>
  <button type="button" class="oe-ai-agent-trends-btn">Lab trends</button>
  <div class="oe-ai-agent-trends"></div>
  <form class="oe-ai-agent-upload-form">
    <input type="file" class="oe-ai-agent-file" />
    <select class="oe-ai-agent-doc-type"><option value="lab_pdf" selected>Lab PDF</option></select>
    <button type="submit" class="oe-ai-agent-upload-submit">Upload</button>
    <div class="oe-ai-agent-upload-status"></div>
  </form>
  <div class="oe-ai-agent-extract"></div>
</div>
`;

function el(sel, root) { return (root || document).querySelector(sel); }
function els(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
function loadWidget() { new Function(WIDGET_SRC)(); }

function flushAll() {
    return new Promise(function (resolve) {
        let n = 0;
        (function tick() { if (n++ > 12) { return resolve(); } setTimeout(tick, 0); })();
    });
}

// rows = the read.php body; readOk = whether read.php responds ok.
function installFetch(rows, readOk) {
    const calls = [];
    global.fetch = jest.fn(function (url, opts) {
        const u = String(url);
        calls.push({ url: u, opts: opts || {} });
        function json(body, ok) {
            return Promise.resolve({
                ok: ok !== false,
                status: ok !== false ? 200 : 500,
                json: function () { return Promise.resolve(body); },
                text: function () { return Promise.resolve(JSON.stringify(body)); }
            });
        }
        if (u.indexOf('token.php') !== -1) { return json({ token: 'jwt' }); }
        if (u.indexOf('read.php') !== -1) {
            if (readOk === false) { return json({ error: 'Service unavailable' }, false); }
            return json(rows);
        }
        return json({});
    });
    return calls;
}

function openTrends() {
    el('.oe-ai-agent-trends-btn').dispatchEvent(new Event('click', { bubbles: true }));
}

function pointData(root) {
    return els('.oe-ai-agent-trends .oe-ai-agent-trends-point', root).map(function (p) {
        return {
            date: p.getAttribute('data-date'),
            value: p.getAttribute('data-value'),
            abnormal: p.getAttribute('data-abnormal')
        };
    });
}

describe('agent-widget: lab trend chart', () => {
    test('clicking Lab trends mints a token then POSTs read.php get_results with the pid + Bearer', async () => {
        document.body.innerHTML = SCAFFOLD;
        const calls = installFetch(CONTRACT_ROWS);
        loadWidget();

        openTrends();
        await flushAll();

        const tokenCall = calls.find(function (c) { return c.url.indexOf('token.php') !== -1; });
        const readCall = calls.find(function (c) { return c.url.indexOf('read.php') !== -1; });
        expect(tokenCall).toBeTruthy();
        expect(readCall).toBeTruthy();
        expect(String(readCall.opts.method).toUpperCase()).toBe('POST');
        expect(readCall.opts.headers.Authorization).toBe('Bearer jwt');
        const body = JSON.parse(String(readCall.opts.body));
        expect(body.op).toBe('get_results');
        expect(body.pid).toBe(1);
        expect(body.params).toEqual({});
    });

    test('numeric results group into a per-test selector; non-numeric-only tests are excluded', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch(CONTRACT_ROWS);
        loadWidget();

        openTrends();
        await flushAll();

        const select = el('.oe-ai-agent-trends-select');
        expect(select).not.toBeNull();
        const options = els('option', select).map(function (o) { return o.value; });
        // Glucose + HbA1c have numeric+dated points; "Blood culture" ("positive")
        // is non-numeric and must NOT appear. Sorted by test name.
        expect(options).toEqual(['Glucose', 'HbA1c']);
    });

    test('the chart renders an SVG whose points are date-ascending, dropping the undated/non-numeric rows', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch(CONTRACT_ROWS);
        loadWidget();

        openTrends();
        await flushAll();

        expect(el('.oe-ai-agent-trends .oe-ai-agent-trends-chart')).not.toBeNull();
        // Glucose is first (default) — its 3 numeric+dated points only (the
        // date:"" Glucose row is dropped), ordered oldest→newest.
        const pts = pointData();
        expect(pts.map(function (p) { return p.date; })).toEqual(['2019-06-01', '2020-06-01', '2021-06-01']);
        expect(pts.map(function (p) { return Number(p.value); })).toEqual([95, 110, 142]);
        // The 2021 Glucose (142, "high") is the only abnormal point in the series.
        const abnormal = pts.filter(function (p) { return p.abnormal === '1'; });
        expect(abnormal).toHaveLength(1);
        expect(Number(abnormal[0].value)).toBe(142);
        // The selected test's reference range is surfaced.
        expect(el('.oe-ai-agent-trends-range').textContent).toContain('70-99');
    });

    test('changing the series selector re-renders for the newly-selected test', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch(CONTRACT_ROWS);
        loadWidget();

        openTrends();
        await flushAll();

        const select = el('.oe-ai-agent-trends-select');
        select.value = 'HbA1c';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        await flushAll();

        const pts = pointData();
        expect(pts).toHaveLength(1);
        expect(Number(pts[0].value)).toBe(7.8);
        expect(pts[0].abnormal).toBe('1');
        expect(el('.oe-ai-agent-trends-range').textContent).toContain('4.0-5.6');
    });

    test('empty result set shows a friendly no-results message and no chart', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch([]);
        loadWidget();

        openTrends();
        await flushAll();

        const container = el('.oe-ai-agent-trends');
        expect(el('svg', container)).toBeNull();
        expect(container.textContent).toMatch(/no/i);
        expect(container.textContent).toMatch(/result|lab/i);
    });

    test('a read.php failure shows a generic error and no chart (no token leak)', async () => {
        document.body.innerHTML = SCAFFOLD;
        installFetch(CONTRACT_ROWS, false);
        loadWidget();

        openTrends();
        await flushAll();

        const container = el('.oe-ai-agent-trends');
        expect(el('svg', container)).toBeNull();
        expect(container.textContent).toMatch(/could ?n.?t|could not|unable|error|fail/i);
        expect(container.textContent).not.toContain('jwt');
    });
});
