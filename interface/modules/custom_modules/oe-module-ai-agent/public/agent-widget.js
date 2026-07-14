/**
 * agent-widget.js — front-end for the AI Clinical Co-Pilot patient-summary card.
 *
 * Flow on submit:
 *   1. POST the page CSRF token to token.php to obtain a short-lived, patient-scoped JWT.
 *   2. POST the clinician's question to the AI sidecar with Authorization: Bearer <jwt>.
 *   3. Render the sidecar's answer back into the card.
 *
 * Dependency-free (vanilla fetch). The JWT is never persisted; it lives only for
 * the duration of a single request.
 *
 * @package   OpenEMR
 * @link      https://www.open-emr.org
 * @author    Kevin Reynolds <kevin.reynolds1@gmail.com>
 * @copyright Copyright (c) 2026 Kevin Reynolds
 * @license   https://github.com/openemr/openemr/blob/master/LICENSE GNU General Public License 3
 */
(function () {
    'use strict';

    var root = document.getElementById('oe-ai-agent');
    if (!root || root.dataset.oeAiAgentWired === '1') {
        return;
    }
    root.dataset.oeAiAgentWired = '1';

    var form = root.querySelector('.oe-ai-agent-form');
    var question = root.querySelector('.oe-ai-agent-question');
    var answer = root.querySelector('.oe-ai-agent-answer');
    var submit = root.querySelector('.oe-ai-agent-submit');
    if (!form || !question || !answer) {
        return;
    }

    // Endpoints. The token endpoint is co-located with this script; the sidecar
    // URL is configurable via a data-attribute so deployments can point it at
    // their own boundary service.
    var tokenUrl = new URL('token.php', document.currentScript ? document.currentScript.src : window.location.href).href;
    var uploadUrl = new URL('upload.php', document.currentScript ? document.currentScript.src : window.location.href).href;
    var sidecarUrl = root.dataset.sidecarUrl || '/ai-agent-sidecar/ask';
    // The SSE endpoint is derived from the same base as the buffered /ask URL, so
    // a deployment that overrides data-sidecar-url need only set it once.
    var streamUrl = sidecarUrl.replace(/\/ask\/?$/, '/ask/stream');
    // The document-extraction endpoint is derived the same way, so auto-extract
    // on upload follows the same sidecar base as /ask.
    var extractUrl = sidecarUrl.replace(/\/ask\/?$/, '/extract');

    // One conversation id per card instance (per page load), sent with every
    // question so the sidecar can carry context across follow-ups within its
    // short TTL. It is ephemeral and pid-scoped server-side; not persisted here.
    var conversationId = (window.crypto && typeof crypto.randomUUID === 'function')
        ? crypto.randomUUID()
        : ('oe-ai-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2));

    // The CSRF token is embedded server-side on the card (data-csrf); fall back
    // to OpenEMR's page global (csrf_token_js) where one is present.
    var csrfToken = root.dataset.csrf
        || ((typeof window.csrf_token_js !== 'undefined') ? window.csrf_token_js : '');

    // Inject the widget's animation + spacing CSS once (keyframes and the
    // ':not(:empty)' rule can't be expressed as inline styles). The margin rule
    // only spaces the answer from the question field when it actually has content.
    (function injectStyle() {
        if (document.getElementById('oe-ai-agent-style')) {
            return;
        }
        var style = document.createElement('style');
        style.id = 'oe-ai-agent-style';
        style.textContent =
            '@keyframes oe-ai-agent-spin{to{transform:rotate(360deg)}}'
            + '.oe-ai-agent-spinner{display:inline-block;width:0.85em;height:0.85em;'
            + 'margin-right:0.45em;vertical-align:-0.1em;border:2px solid rgba(0,0,0,0.2);'
            + 'border-top-color:#337ab7;border-radius:50%;'
            + 'animation:oe-ai-agent-spin 0.7s linear infinite}'
            + '.oe-ai-agent-answer:not(:empty){margin-bottom:0.75em}'
            // Once the upload status has content, it takes the label's place:
            // hide the adjacent "Upload a document" label so the message sits
            // directly against the doc-type dropdown.
            + '.oe-ai-agent-upload-status:not(:empty)+.oe-ai-agent-upload-label{display:none}';
        (document.head || document.documentElement).appendChild(style);
    })();

    function setBusy(busy) {
        if (submit) {
            submit.disabled = busy;
        }
    }

    // Show a live status line ("Thinking..." by default) with a spinner beside it.
    function showThinking(note) {
        answer.textContent = '';
        var spinner = document.createElement('span');
        spinner.className = 'oe-ai-agent-spinner';
        spinner.setAttribute('aria-hidden', 'true');
        answer.appendChild(spinner);
        answer.appendChild(document.createTextNode(note || 'Thinking...'));
    }

    // Turn a tool name (e.g. "get_medications") into a short, friendly progress
    // note (e.g. "Reading medications..."). Purely cosmetic; falls back cleanly.
    function toolNote(name) {
        var readable = String(name || '')
            .replace(/^(get|list|search)_/, '')
            .replace(/_/g, ' ')
            .trim();
        return readable ? ('Reading ' + readable + '...') : 'Working...';
    }

    function mintToken() {
        var body = new URLSearchParams();
        body.set('csrf_token', csrfToken);
        return fetch(tokenUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body.toString()
        }).then(function (res) {
            if (!res.ok) {
                throw new Error('token request failed');
            }
            return res.json();
        }).then(function (data) {
            if (!data || !data.token) {
                throw new Error('no token returned');
            }
            return data.token;
        });
    }

    // Parse one SSE frame block ("event: X\ndata: {...}") into {event, data}.
    function parseFrame(block) {
        var event = null;
        var data = null;
        block.split('\n').forEach(function (line) {
            if (line.indexOf('event:') === 0) {
                event = line.slice('event:'.length).trim();
            } else if (line.indexOf('data:') === 0) {
                var raw = line.slice('data:'.length).trim();
                try {
                    data = JSON.parse(raw);
                } catch (e) {
                    data = null;
                }
            }
        });
        return { event: event, data: data };
    }

    // POST to the SSE endpoint and consume the response body incrementally.
    // Status/tool frames update the live "thinking" line; the single gated
    // answer frame is rendered through the existing markdown path; an error
    // frame surfaces the friendly failure. Resolves once the stream ends.
    function askSidecar(jwt, text) {
        return fetch(streamUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + jwt
            },
            body: JSON.stringify({
                pid: parseInt(root.dataset.pid, 10),
                question: text,
                conversation_id: conversationId
            })
        }).then(function (res) {
            if (!res.ok || !res.body) {
                throw new Error('sidecar request failed');
            }
            var reader = res.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';

            function handleFrame(frame) {
                if (frame.event === 'status') {
                    showThinking('Thinking...');
                } else if (frame.event === 'tool') {
                    showThinking(toolNote(frame.data && frame.data.name));
                } else if (frame.event === 'answer') {
                    renderAnswer(
                        (frame.data && frame.data.answer)
                            ? frame.data.answer
                            : 'No answer returned.'
                    );
                } else if (frame.event === 'error') {
                    // Never surface internal detail; a friendly message only.
                    answer.textContent = 'The assistant is unavailable right now.';
                }
            }

            function pump() {
                return reader.read().then(function (result) {
                    if (result.value) {
                        buffer += decoder.decode(result.value, { stream: true });
                        var parts = buffer.split('\n\n');
                        // Keep the last, possibly-incomplete segment in the buffer.
                        buffer = parts.pop();
                        parts.forEach(function (block) {
                            if (block.trim() !== '') {
                                handleFrame(parseFrame(block));
                            }
                        });
                    }
                    if (result.done) {
                        var tail = buffer.trim();
                        if (tail !== '') {
                            handleFrame(parseFrame(tail));
                        }
                        return;
                    }
                    return pump();
                });
            }

            return pump();
        });
    }

    // Append text with single-'*' *italic* spans as <em>. Called for the non-bold
    // segments by appendInline (bold '**' is consumed first, so only single
    // asterisks remain here). Text-node / createElement only — never innerHTML.
    function appendItalic(parent, text) {
        var parts = String(text).split('*');
        parts.forEach(function (part, i) {
            if (part === '') {
                return;
            }
            if (i % 2 === 1) {
                var em = document.createElement('em');
                em.textContent = part;
                parent.appendChild(em);
            } else {
                parent.appendChild(document.createTextNode(part));
            }
        });
    }

    // Append inline text to a node, styling **bold** (<strong>) and *italic*
    // (<em>) spans. Model text only ever becomes text nodes / <strong> / <em> we
    // create — it is never interpreted as HTML, so there is no XSS surface.
    function appendInline(parent, text) {
        var parts = String(text).split('**');
        parts.forEach(function (part, i) {
            if (part === '') {
                return;
            }
            if (i % 2 === 1) {
                var strong = document.createElement('strong');
                strong.textContent = part;
                parent.appendChild(strong);
            } else {
                appendItalic(parent, part);
            }
        });
    }

    // A markdown table row has at least one pipe plus some non-pipe content.
    function isTableRow(s) {
        return s.indexOf('|') !== -1 && s.replace(/\|/g, '').trim() !== '';
    }

    // A separator row is only dashes/colons and pipes, e.g. |---|:--:|.
    function isTableSeparator(s) {
        return /^\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?$/.test(s);
    }

    // Split a row into trimmed cell strings (outer pipes stripped).
    function tableCells(s) {
        return s.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (c) {
            return c.trim();
        });
    }

    // Build a <table> from markdown lines (header, separator, then data rows).
    // Every cell goes through appendInline (bold-aware, text-node only) — never
    // innerHTML — so there is no XSS surface.
    function buildTable(lines) {
        var table = document.createElement('table');
        table.className = 'oe-ai-agent-table';
        table.style.borderCollapse = 'collapse';
        table.style.margin = '0.5em 0';

        var headCells = tableCells(lines[0]);
        var thead = document.createElement('thead');
        var htr = document.createElement('tr');
        headCells.forEach(function (c) {
            var th = document.createElement('th');
            th.style.border = '1px solid #b0b0b0';
            th.style.padding = '2px 8px';
            th.style.textAlign = 'left';
            th.style.background = '#f2f2f2';
            appendInline(th, c);
            htr.appendChild(th);
        });
        thead.appendChild(htr);
        table.appendChild(thead);

        var tbody = document.createElement('tbody');
        for (var r = 2; r < lines.length; r++) {
            var cells = tableCells(lines[r]);
            var tr = document.createElement('tr');
            // Pad to the header width so ragged rows still render cleanly.
            for (var c = 0; c < headCells.length; c++) {
                var td = document.createElement('td');
                td.style.border = '1px solid #d0d0d0';
                td.style.padding = '2px 8px';
                td.style.verticalAlign = 'top';
                appendInline(td, cells[c] !== undefined ? cells[c] : '');
                tr.appendChild(td);
            }
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        return table;
    }

    // Render a small, safe subset of Markdown: **bold**, '-'/'*' bullet lists,
    // '#' headings, and pipe tables. Consecutive bullet lines group into one <ul>.
    function renderAnswer(text) {
        answer.textContent = '';
        var list = null;
        var lines = String(text).split('\n');
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            var trimmed = line.trim();

            // Table: a pipe header row immediately followed by a separator row.
            if (isTableRow(trimmed) && i + 1 < lines.length && isTableSeparator(lines[i + 1].trim())) {
                list = null;
                var tableLines = [line, lines[i + 1]];
                var j = i + 2;
                while (j < lines.length && isTableRow(lines[j].trim())) {
                    tableLines.push(lines[j]);
                    j++;
                }
                answer.appendChild(buildTable(tableLines));
                i = j - 1;
                continue;
            }

            var heading = trimmed.match(/^#{1,6}\s+/);
            if (heading) {
                list = null;
                var h = document.createElement('div');
                h.className = 'oe-ai-agent-heading';
                h.style.marginTop = '0.5em';
                var hStrong = document.createElement('strong');
                appendInline(hStrong, trimmed.slice(heading[0].length));
                h.appendChild(hStrong);
                answer.appendChild(h);
                continue;
            }
            if (/^[-*]\s+/.test(trimmed)) {
                if (!list) {
                    list = document.createElement('ul');
                    list.className = 'oe-ai-agent-list';
                    answer.appendChild(list);
                }
                var li = document.createElement('li');
                appendInline(li, trimmed.replace(/^[-*]\s+/, ''));
                list.appendChild(li);
                continue;
            }
            list = null;
            if (trimmed === '') {
                continue;
            }
            var block = document.createElement('div');
            appendInline(block, line);
            answer.appendChild(block);
        }
    }

    form.addEventListener('submit', function (evt) {
        evt.preventDefault();
        var text = (question.value || '').trim();
        if (text === '') {
            return;
        }
        // A long previous answer may have scrolled the page down; bring the card
        // back into view at the top of the page when a new question is asked.
        window.scrollTo({ top: 0, behavior: 'smooth' });
        setBusy(true);
        showThinking();
        mintToken().then(function (jwt) {
            return askSidecar(jwt, text);
        }).then(function () {
            // The answer (or an error frame) was already rendered as the stream
            // was consumed. Clear the question but keep focus for the next one.
            question.value = '';
        }).catch(function () {
            // Never surface internal error detail to the clinician. Leave the
            // question text in place so it can be retried.
            answer.textContent = 'The assistant is unavailable right now.';
        }).finally(function () {
            setBusy(false);
            question.focus();
        });
    });

    // Document upload: POST the selected file + chosen doc_type as multipart to
    // upload.php, including the page CSRF token. The pid is fixed server-side
    // from the session, so it is never sent from here. Success/failure is
    // reflected inline; no internal error detail is ever surfaced.
    (function wireUpload() {
        var uploadForm = root.querySelector('.oe-ai-agent-upload-form');
        if (!uploadForm) {
            return;
        }
        var fileInput = uploadForm.querySelector('.oe-ai-agent-file');
        var docTypeSelect = uploadForm.querySelector('.oe-ai-agent-doc-type');
        var uploadSubmit = uploadForm.querySelector('.oe-ai-agent-upload-submit');
        var status = uploadForm.querySelector('.oe-ai-agent-upload-status');
        var extractBox = root.querySelector('.oe-ai-agent-extract');
        if (!fileInput || !docTypeSelect || !status) {
            return;
        }

        function setStatus(text, ok) {
            status.textContent = text;
            status.style.color = ok ? '#3c763d' : '#a94442';
        }

        // The human-readable field order per doc_type (matches the LabFact /
        // IntakeFact contracts). Anything not listed is appended after these.
        var FACT_FIELDS = {
            lab_pdf: ['test_name', 'value', 'unit', 'reference_range',
                'collection_date', 'abnormal_flag', 'source_citation'],
            intake_form: ['demographics', 'chief_concern', 'current_medications',
                'allergies', 'family_history', 'source_citation']
        };

        function humanize(key) {
            return key.replace(/_/g, ' ').replace(/\b\w/g, function (c) {
                return c.toUpperCase();
            });
        }

        // Render a value as plain text: strings verbatim, null/'' as an em dash,
        // objects/arrays as compact JSON. Always returned as a string for
        // textContent — never inserted as HTML.
        function valueText(value) {
            if (value === null || value === undefined || value === '') {
                return '—';
            }
            if (typeof value === 'string') {
                return value;
            }
            try {
                return JSON.stringify(value);
            } catch (e) {
                return String(value);
            }
        }

        // Clear the extraction panel and its status.
        function clearExtract() {
            if (extractBox) {
                extractBox.textContent = '';
            }
        }

        function setExtractNote(text, ok) {
            if (!extractBox) {
                return;
            }
            extractBox.textContent = '';
            var note = document.createElement('div');
            note.className = 'small';
            note.style.color = ok ? '#31708f' : '#a94442';
            note.textContent = text;
            extractBox.appendChild(note);
        }

        // Render a validated LabFact / IntakeFact envelope as a small facts panel.
        // Built entirely with createElement + textContent, so no server- or
        // model-supplied value is ever interpreted as HTML.
        function renderExtraction(data) {
            if (!extractBox) {
                return;
            }
            extractBox.textContent = '';

            var panel = document.createElement('div');
            panel.className = 'card card-body p-2 small';

            var heading = document.createElement('div');
            heading.className = 'font-weight-bold mb-1';
            var label = data.doc_type === 'lab_pdf' ? 'Extracted lab result' : 'Extracted intake facts';
            var pct = Math.round((Number(data.confidence) || 0) * 100);
            heading.textContent = label + ' · confidence ' + pct + '%';
            panel.appendChild(heading);

            var fact = data.fact || {};
            var order = FACT_FIELDS[data.doc_type] || [];
            var keys = order.filter(function (k) {
                return Object.prototype.hasOwnProperty.call(fact, k);
            });
            Object.keys(fact).forEach(function (k) {
                if (keys.indexOf(k) === -1) {
                    keys.push(k);
                }
            });

            var dl = document.createElement('dl');
            dl.className = 'row mb-0';
            keys.forEach(function (k) {
                var dt = document.createElement('dt');
                dt.className = 'col-5 text-muted text-truncate';
                dt.textContent = humanize(k);
                var dd = document.createElement('dd');
                dd.className = 'col-7 mb-1';
                dd.textContent = valueText(fact[k]);
                dl.appendChild(dt);
                dl.appendChild(dd);
            });
            panel.appendChild(dl);

            var unsupported = data.unsupported_fields || [];
            if (unsupported.length) {
                var flagged = document.createElement('div');
                flagged.className = 'text-muted font-italic mt-1';
                flagged.textContent = 'Left blank (not grounded in the document): '
                    + unsupported.map(humanize).join(', ') + '.';
                panel.appendChild(flagged);
            }

            extractBox.appendChild(panel);
        }

        // After a successful store, mint a patient-scoped JWT and ask the sidecar
        // to extract strict facts from the freshly-uploaded document. The pid is
        // sent from the card (as /ask does); the boundary re-checks the token
        // scope on the document read, so it can only reach the patient in context.
        function extractDocument(documentId, docType) {
            if (!extractBox || !documentId) {
                return;
            }
            setExtractNote('Extracting facts from the document...', true);
            mintToken().then(function (jwt) {
                return fetch(extractUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + jwt
                    },
                    body: JSON.stringify({
                        pid: parseInt(root.dataset.pid, 10),
                        document_id: documentId,
                        doc_type: docType
                    })
                });
            }).then(function (res) {
                return res.json().then(function (body) {
                    return { ok: res.ok, body: body };
                });
            }).then(function (result) {
                if (!result.ok || !result.body || !result.body.ok) {
                    // 422 means the document couldn't be extracted cleanly; any
                    // other failure is a generic unavailability. Either way, no
                    // internal detail is surfaced.
                    setExtractNote('Stored, but automatic extraction did not produce a valid result.', false);
                    return;
                }
                renderExtraction(result.body);
            }).catch(function () {
                setExtractNote('Stored, but automatic extraction is unavailable right now.', false);
            });
        }

        uploadForm.addEventListener('submit', function (evt) {
            evt.preventDefault();
            var file = fileInput.files && fileInput.files[0];
            if (!file) {
                setStatus('Choose a file to upload.', false);
                return;
            }
            // Capture the chosen doc_type before reset() clears the form, so the
            // extraction call uses the type the file was actually filed under.
            var docType = docTypeSelect.value;
            var payload = new FormData();
            payload.append('csrf_token', csrfToken);
            payload.append('doc_type', docType);
            payload.append('document', file);

            if (uploadSubmit) {
                uploadSubmit.disabled = true;
            }
            setStatus('Uploading...', true);
            clearExtract();

            fetch(uploadUrl, {
                method: 'POST',
                credentials: 'same-origin',
                body: payload
            }).then(function (res) {
                if (!res.ok) {
                    throw new Error('upload failed');
                }
                return res.json();
            }).then(function (data) {
                if (!data || !data.ok) {
                    throw new Error('upload rejected');
                }
                // Confirm where the document was filed. setStatus writes via
                // textContent, so the server-supplied category name is inserted
                // as plain text — never interpreted as HTML.
                setStatus(
                    data.category ? ('Uploaded to ' + data.category + '.') : 'Uploaded.',
                    true
                );
                uploadForm.reset();
                // Auto-extract strict facts from the just-stored document.
                extractDocument(data.id, docType);
            }).catch(function () {
                setStatus('Upload failed. Please try again.', false);
            }).finally(function () {
                if (uploadSubmit) {
                    uploadSubmit.disabled = false;
                }
            });
        });
    })();

    // Enter submits the question (same as clicking Ask); Shift+Enter inserts a
    // newline so multi-line questions are still possible.
    question.addEventListener('keydown', function (evt) {
        if (evt.key === 'Enter' && !evt.shiftKey) {
            evt.preventDefault();
            if (typeof form.requestSubmit === 'function') {
                form.requestSubmit();
            } else {
                form.dispatchEvent(new Event('submit', { cancelable: true }));
            }
        }
    });
})();
