/**
 * @jest-environment jsdom
 *
 * T70 acceptance test (LOCKED) — previous Q&A turns become collapsible accordions
 * (question visible as the heading, answer revealed on click) stacked
 * chronologically ABOVE the live answer area, instead of being cleared. Also locks
 * that a new question is ignored while the model is "thinking" (the Ask button is
 * disabled and Enter does not submit).
 *
 * The widget (`agent-widget.js`) is a self-executing IIFE. We scaffold its DOM,
 * execute it, then drive the real submit handlers. `fetch` never resolves, so the
 * turn stays "in flight" (busy) until the test simulates completion — mirroring
 * how the real `.finally` re-enables the Ask button when the answer arrives.
 */
/* global __dirname */
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

function askQuestion(text) {
    el('.oe-ai-agent-question').value = text;
    el('.oe-ai-agent-form').dispatchEvent(new Event('submit', { cancelable: true }));
}

// Stand in for the streamed answer landing AND the turn completing: the answer
// content appears in the live area and the Ask button re-enables (as the real
// `.finally(setBusy(false))` does when the answer arrives).
function answerArrives(text) {
    el('.oe-ai-agent-answer').textContent = text;
    el('.oe-ai-agent-submit').disabled = false;
}

function attachFileAndUpload(hasFile) {
    const fileInput = el('.oe-ai-agent-file');
    Object.defineProperty(fileInput, 'files', {
        configurable: true,
        value: hasFile ? [{ name: 'scan.png', type: 'image/png' }] : [],
    });
    el('.oe-ai-agent-upload-form').dispatchEvent(new Event('submit', { cancelable: true }));
}

describe('agent-widget: Q&A history accordions', () => {
    beforeEach(() => {
        document.body.innerHTML = SCAFFOLD;
        global.fetch = jest.fn(() => new Promise(() => {}));
        loadWidget();
    });

    test('history container is created before the live answer area', () => {
        const history = el('.oe-ai-agent-history');
        const answer = el('.oe-ai-agent-answer');
        expect(history).not.toBeNull();
        expect(history.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING)
            .toBeTruthy();
    });

    test('asking a second question archives the first turn as a collapsed accordion', () => {
        askQuestion('What are the active medications?');
        answerArrives('Metformin 500mg and lisinopril 10mg.');
        askQuestion('What is the latest A1c?');

        const turns = document.querySelectorAll('.oe-ai-agent-history .oe-ai-agent-turn');
        expect(turns.length).toBe(1);

        const heading = el('.oe-ai-agent-turn-q', turns[0]);
        const body = el('.oe-ai-agent-turn-a', turns[0]);
        expect(heading.textContent).toContain('What are the active medications?');
        expect(body.textContent).toContain('Metformin 500mg and lisinopril 10mg.');

        expect(heading.tagName).toBe('BUTTON');
        expect(heading.getAttribute('aria-expanded')).toBe('false');
        expect(body.hasAttribute('hidden')).toBe(true);

        expect(el('.oe-ai-agent-answer').textContent)
            .not.toContain('Metformin 500mg and lisinopril 10mg.');
    });

    test('clicking the heading expands then collapses the answer', () => {
        askQuestion('Q1');
        answerArrives('A1');
        askQuestion('Q2');

        const heading = el('.oe-ai-agent-turn-q');
        const body = el('.oe-ai-agent-turn-a');

        heading.dispatchEvent(new Event('click', { bubbles: true }));
        expect(heading.getAttribute('aria-expanded')).toBe('true');
        expect(body.hasAttribute('hidden')).toBe(false);

        heading.dispatchEvent(new Event('click', { bubbles: true }));
        expect(heading.getAttribute('aria-expanded')).toBe('false');
        expect(body.hasAttribute('hidden')).toBe(true);
    });

    test('multiple turns are stacked chronologically (oldest first, newest nearest live)', () => {
        askQuestion('Q1');
        answerArrives('A1');
        askQuestion('Q2');
        answerArrives('A2');
        askQuestion('Q3');

        const headings = document.querySelectorAll('.oe-ai-agent-history .oe-ai-agent-turn-q');
        expect(headings.length).toBe(2);
        expect(headings[0].textContent).toContain('Q1');
        expect(headings[1].textContent).toContain('Q2');
    });

    test('uploading a document archives the current turn and clears the live area', () => {
        askQuestion('What meds is the patient on?');
        answerArrives('Metformin.');

        attachFileAndUpload(true);

        const turns = document.querySelectorAll('.oe-ai-agent-history .oe-ai-agent-turn');
        expect(turns.length).toBe(1);
        expect(el('.oe-ai-agent-turn-q', turns[0]).textContent).toContain('What meds is the patient on?');
        expect(el('.oe-ai-agent-turn-a', turns[0]).textContent).toContain('Metformin.');
        expect(el('.oe-ai-agent-answer').textContent).toBe('');
    });

    test('the first question creates no history item', () => {
        askQuestion('First question, nothing before it.');
        const turns = document.querySelectorAll('.oe-ai-agent-history .oe-ai-agent-turn');
        expect(turns.length).toBe(0);
    });
});

describe('agent-widget: no submitting while the model is thinking', () => {
    beforeEach(() => {
        document.body.innerHTML = SCAFFOLD;
        global.fetch = jest.fn(() => new Promise(() => {}));
        loadWidget();
    });

    test('the Ask button is disabled while thinking', () => {
        askQuestion('A question that is now in flight');
        expect(el('.oe-ai-agent-submit').disabled).toBe(true);
    });

    test('a second question submitted while thinking is ignored (no new turn, no request)', () => {
        askQuestion('First, still thinking...');
        // Do NOT complete the turn — the model is still "thinking" (button disabled).
        const callsAfterFirst = global.fetch.mock.calls.length;

        askQuestion('Second, fired while busy');

        // The in-flight turn is neither archived nor replaced, and no new request fired.
        expect(document.querySelectorAll('.oe-ai-agent-history .oe-ai-agent-turn').length).toBe(0);
        expect(global.fetch.mock.calls.length).toBe(callsAfterFirst);
    });

    test('Enter does not submit while thinking, but submits again once idle', () => {
        askQuestion('First question');
        const callsAfterFirst = global.fetch.mock.calls.length;

        // Enter while thinking must NOT start a new turn.
        el('.oe-ai-agent-question').value = 'sneaky follow-up while busy';
        el('.oe-ai-agent-question')
            .dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        expect(global.fetch.mock.calls.length).toBe(callsAfterFirst);

        // Once the turn completes (button re-enabled), Enter works again.
        el('.oe-ai-agent-submit').disabled = false;
        el('.oe-ai-agent-question')
            .dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        expect(global.fetch.mock.calls.length).toBe(callsAfterFirst + 1);
    });
});
