/**
 * @jest-environment jsdom
 *
 * T70 acceptance test (LOCKED) — previous Q&A turns become collapsible accordions
 * (question visible as the heading, answer revealed on click) stacked
 * chronologically ABOVE the live answer area, instead of being cleared.
 *
 * The widget (`agent-widget.js`) is a self-executing IIFE. We scaffold its DOM,
 * execute it, then drive the real submit handlers. `fetch` never resolves, so the
 * archiving (which happens synchronously on submit, before the network turn) is
 * what we observe; a turn's answer is simulated by setting the live answer content
 * between submits (standing in for the streamed render).
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

// Stand in for the streamed answer landing in the live area for the current turn.
function simulateAnswer(text) {
    el('.oe-ai-agent-answer').textContent = text;
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
        // history is a previous sibling of the live answer (renders above it).
        expect(history.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING)
            .toBeTruthy();
    });

    test('asking a second question archives the first turn as a collapsed accordion', () => {
        askQuestion('What are the active medications?');
        simulateAnswer('Metformin 500mg and lisinopril 10mg.');
        askQuestion('What is the latest A1c?');

        const turns = document.querySelectorAll('.oe-ai-agent-history .oe-ai-agent-turn');
        expect(turns.length).toBe(1);

        const heading = el('.oe-ai-agent-turn-q', turns[0]);
        const body = el('.oe-ai-agent-turn-a', turns[0]);
        // The question is the always-visible heading; the answer is in the body.
        expect(heading.textContent).toContain('What are the active medications?');
        expect(body.textContent).toContain('Metformin 500mg and lisinopril 10mg.');

        // Collapsed by default.
        expect(heading.tagName).toBe('BUTTON');
        expect(heading.getAttribute('aria-expanded')).toBe('false');
        expect(body.hasAttribute('hidden')).toBe(true);

        // The archived answer is no longer in the live area.
        expect(el('.oe-ai-agent-answer').textContent)
            .not.toContain('Metformin 500mg and lisinopril 10mg.');
    });

    test('clicking the heading expands then collapses the answer', () => {
        askQuestion('Q1');
        simulateAnswer('A1');
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
        simulateAnswer('A1');
        askQuestion('Q2');
        simulateAnswer('A2');
        askQuestion('Q3');

        const headings = document.querySelectorAll('.oe-ai-agent-history .oe-ai-agent-turn-q');
        expect(headings.length).toBe(2);
        expect(headings[0].textContent).toContain('Q1');
        expect(headings[1].textContent).toContain('Q2');
    });

    test('uploading a document archives the current turn and clears the live area', () => {
        askQuestion('What meds is the patient on?');
        simulateAnswer('Metformin.');

        attachFileAndUpload(true);

        const turns = document.querySelectorAll('.oe-ai-agent-history .oe-ai-agent-turn');
        expect(turns.length).toBe(1);
        expect(el('.oe-ai-agent-turn-q', turns[0]).textContent).toContain('What meds is the patient on?');
        expect(el('.oe-ai-agent-turn-a', turns[0]).textContent).toContain('Metformin.');
        // Live area cleared for the extraction that follows.
        expect(el('.oe-ai-agent-answer').textContent).toBe('');
    });

    test('the first question creates no history item', () => {
        askQuestion('First question, nothing before it.');
        const turns = document.querySelectorAll('.oe-ai-agent-history .oe-ai-agent-turn');
        expect(turns.length).toBe(0);
    });
});
