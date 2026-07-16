/**
 * @jest-environment jsdom
 *
 * T69 acceptance test (LOCKED) — the answer/response area clears when a NEW
 * upload is triggered, mirroring the ask-submit behavior.
 *
 * The widget (`agent-widget.js`) is a self-executing IIFE with no exports, so we
 * scaffold the DOM it queries, execute the file against this jsdom document, then
 * drive the wired handlers. `fetch` is stubbed with a never-resolving promise so
 * the assertions observe the SYNCHRONOUS clear that happens before the network
 * call (exactly how ask-submit clears via showThinking()).
 */
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
    // Execute the IIFE against the current jsdom document.
    // eslint-disable-next-line no-new-func
    new Function(WIDGET_SRC)();
}

function attachFile(hasFile) {
    const fileInput = document.querySelector('.oe-ai-agent-file');
    Object.defineProperty(fileInput, 'files', {
        configurable: true,
        value: hasFile ? [{ name: 'scan.png', type: 'image/png' }] : [],
    });
    return fileInput;
}

function seedAnswer(text) {
    const answer = document.querySelector('.oe-ai-agent-answer');
    answer.textContent = text;
    return answer;
}

describe('agent-widget: answer clears on a new upload', () => {
    let fetchMock;

    beforeEach(() => {
        document.body.innerHTML = SCAFFOLD;
        // Never-resolving fetch: the clear under test is synchronous and happens
        // before any response is handled.
        fetchMock = jest.fn(() => new Promise(() => {}));
        global.fetch = fetchMock;
        loadWidget();
    });

    test('triggering an upload with a file clears the previous answer', () => {
        const answer = seedAnswer('A stale previous answer that should be wiped.');
        attachFile(true);

        document.querySelector('.oe-ai-agent-upload-form')
            .dispatchEvent(new Event('submit', { cancelable: true }));

        expect(answer.textContent).toBe('');
        // The upload actually fired (so we cleared because a real upload started).
        expect(fetchMock).toHaveBeenCalled();
    });

    test('submitting the upload form with NO file preserves the answer', () => {
        const answer = seedAnswer('Keep me — no upload actually happened.');
        attachFile(false);

        document.querySelector('.oe-ai-agent-upload-form')
            .dispatchEvent(new Event('submit', { cancelable: true }));

        expect(answer.textContent).toBe('Keep me — no upload actually happened.');
        expect(document.querySelector('.oe-ai-agent-upload-status').textContent)
            .toMatch(/choose a file/i);
        expect(fetchMock).not.toHaveBeenCalled();
    });

    test('asking a new question also clears the previous answer (the mirrored behavior)', () => {
        // The ask path clears the old answer and then shows a "Thinking..." status,
        // so the answer area no longer holds the stale text. The upload path (above)
        // mirrors the CLEAR; it has its own "Uploading..." status elsewhere, so its
        // answer area is left empty.
        const answer = seedAnswer('Old answer under a new question.');
        document.querySelector('.oe-ai-agent-question').value = 'What are the active meds?';

        document.querySelector('.oe-ai-agent-form')
            .dispatchEvent(new Event('submit', { cancelable: true }));

        expect(answer.textContent).not.toContain('Old answer');
    });
});
