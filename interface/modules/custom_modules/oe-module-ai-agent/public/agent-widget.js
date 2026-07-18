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

    // Q&A history: prior turns are archived as collapsible accordions stacked
    // chronologically (oldest first) directly ABOVE the live answer area, rather
    // than being discarded when a new question is asked or an upload starts.
    var history = document.createElement('div');
    history.className = 'oe-ai-agent-history';
    if (answer.parentNode) {
        answer.parentNode.insertBefore(history, answer);
    }
    // The question that produced whatever currently sits in the live answer area.
    var currentQuestion = null;

    // Build one collapsed accordion turn: a caret+label heading over a hidden
    // body that receives all of sourceEl's child nodes (they are MOVED, not
    // copied). Clicking the heading toggles aria-expanded and the body's hidden
    // attribute. The turn is appended to the history stack and returned. Shared
    // by Q&A archiving and extraction archiving.
    function appendAccordion(headingText, sourceEl) {
        var turn = document.createElement('div');
        turn.className = 'oe-ai-agent-turn';

        var heading = document.createElement('button');
        heading.type = 'button';
        heading.className = 'oe-ai-agent-turn-q';
        heading.setAttribute('aria-expanded', 'false');

        // Caret first (visual affordance, hidden from a11y), then the label text.
        var caret = document.createElement('span');
        caret.className = 'oe-ai-agent-turn-caret';
        caret.setAttribute('aria-hidden', 'true');
        caret.textContent = '▸';
        heading.appendChild(caret);

        var label = document.createElement('span');
        label.className = 'oe-ai-agent-turn-label';
        label.textContent = headingText;
        heading.appendChild(label);

        var body = document.createElement('div');
        body.className = 'oe-ai-agent-turn-a';
        body.setAttribute('hidden', '');
        while (sourceEl.firstChild) {
            body.appendChild(sourceEl.firstChild);
        }

        heading.addEventListener('click', function () {
            var expanded = heading.getAttribute('aria-expanded') === 'true';
            heading.setAttribute('aria-expanded', expanded ? 'false' : 'true');
            if (expanded) {
                body.setAttribute('hidden', '');
            } else {
                body.removeAttribute('hidden');
            }
        });

        turn.appendChild(heading);
        turn.appendChild(body);
        history.appendChild(turn);
        return turn;
    }

    // Move the live answer's rendered nodes into a collapsed accordion under its
    // question, then leave the live area empty. No-op archive (just a clear) when
    // there is no tracked question or no content.
    function archiveTurn() {
        var hasContent = answer.childNodes.length > 0 && (answer.textContent || '').trim() !== '';
        if (currentQuestion && hasContent) {
            appendAccordion(currentQuestion, answer);
        }
        answer.textContent = '';
        currentQuestion = null;
    }

    // Endpoints. The token endpoint is co-located with this script; the sidecar
    // URL is configurable via a data-attribute so deployments can point it at
    // their own boundary service.
    var tokenUrl = new URL('token.php', document.currentScript ? document.currentScript.src : window.location.href).href;
    var uploadUrl = new URL('upload.php', document.currentScript ? document.currentScript.src : window.location.href).href;
    var persistUrl = new URL('persist.php', document.currentScript ? document.currentScript.src : window.location.href).href;
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
            + '.oe-ai-agent-upload-status:not(:empty)+.oe-ai-agent-upload-label{display:none}'
            // Q&A history accordions: prior turns stacked above the live answer.
            + '.oe-ai-agent-history{margin-bottom:0.75em}'
            + '.oe-ai-agent-turn{border:1px solid #d0d0d0;border-radius:4px;margin-bottom:0.35em}'
            + '.oe-ai-agent-turn-q{display:block;width:100%;text-align:left;background:#f4f6f8;'
            + 'border:0;padding:6px 10px;font-weight:bold;cursor:pointer;border-radius:4px}'
            + '.oe-ai-agent-turn-q[aria-expanded="true"]{border-bottom:1px solid #d0d0d0;'
            + 'border-radius:4px 4px 0 0}'
            // Caret to the left of the label; rotates from pointing right (collapsed)
            // to pointing down (expanded) as the turn opens.
            + '.oe-ai-agent-turn-caret{display:inline-block;margin-right:0.45em;'
            + 'transition:transform 0.15s ease}'
            + '.oe-ai-agent-turn-q[aria-expanded="true"] .oe-ai-agent-turn-caret{transform:rotate(90deg)}'
            + '.oe-ai-agent-turn-a{padding:6px 10px}'
            // "Accept & file to chart" action on the extracted-facts panel.
            + '.oe-ai-agent-file-btn{margin-top:0.5em;background:#337ab7;color:#fff;'
            + 'border:0;border-radius:4px;padding:5px 12px;cursor:pointer}'
            + '.oe-ai-agent-file-btn:disabled{opacity:0.6;cursor:default}'
            + '.oe-ai-agent-filed{margin-top:0.5em;color:#3c763d;font-weight:bold}'
            + '.oe-ai-agent-file-error{margin-top:0.5em;color:#a94442}';
        (document.head || document.documentElement).appendChild(style);
    })();

    function setBusy(busy) {
        if (submit) {
            submit.disabled = busy;
        }
    }

    // Client-side citation-box locator — a faithful port of the sidecar's
    // ``bbox.py`` (``locate_citation_boxes``). Maps a fact's quote onto a page's
    // word geometry and returns one union box per rendered line. Used for the PDF
    // path, where the page's OWN text-layer word geometry (from the render seam)
    // locates each fact value on the actually-rendered page — no server geometry,
    // so it works for any uploaded PDF rather than only the exact demo document.
    //
    //   words: array of {text, x, y, w, h} in pixel space, in reading order.
    //   quote: the string to locate.
    //
    // Tokens normalize by lowercasing and stripping non-alphanumerics; tokens
    // that normalize to empty (punctuation-only) are dropped from both the quote
    // and the page. The quote's normalized token sequence is matched as a
    // contiguous subsequence of the page's non-empty word tokens (first match
    // wins). The matched run is grouped into lines (consecutive words share a
    // line iff their vertical ranges overlap) and each group returns its union
    // box in reading order. Returns [] when there is no match or nothing to match.
    function normalizeToken(tok) {
        return String(tok).toLowerCase().replace(/[^a-z0-9]/g, '');
    }

    function sameLine(a, b) {
        return !(a.y + a.h <= b.y || b.y + b.h <= a.y);
    }

    function unionBox(group) {
        var minX = group[0].x;
        var minY = group[0].y;
        var maxX = group[0].x + group[0].w;
        var maxY = group[0].y + group[0].h;
        group.forEach(function (w) {
            if (w.x < minX) { minX = w.x; }
            if (w.y < minY) { minY = w.y; }
            if (w.x + w.w > maxX) { maxX = w.x + w.w; }
            if (w.y + w.h > maxY) { maxY = w.y + w.h; }
        });
        return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
    }

    function groupLines(matched) {
        var boxes = [];
        var group = [matched[0]];
        for (var i = 1; i < matched.length; i++) {
            if (sameLine(group[group.length - 1], matched[i])) {
                group.push(matched[i]);
            } else {
                boxes.push(unionBox(group));
                group = [matched[i]];
            }
        }
        boxes.push(unionBox(group));
        return boxes;
    }

    function locateCitationBoxes(words, quote) {
        var quoteTokens = String(quote || '').split(/\s+/)
            .map(normalizeToken)
            .filter(function (t) { return t !== ''; });
        if (!quoteTokens.length) {
            return [];
        }
        if (!Array.isArray(words) || !words.length) {
            return [];
        }

        // Keep only words whose text normalizes to a non-empty token, preserving
        // order, so punctuation-only page words don't break contiguity.
        var page = [];
        words.forEach(function (w) {
            var norm = normalizeToken(w.text);
            if (norm !== '') {
                page.push({ word: w, norm: norm });
            }
        });
        if (!page.length) {
            return [];
        }

        var n = quoteTokens.length;
        for (var start = 0; start <= page.length - n; start++) {
            var match = true;
            for (var k = 0; k < n; k++) {
                if (page[start + k].norm !== quoteTokens[k]) {
                    match = false;
                    break;
                }
            }
            if (match) {
                var matched = [];
                for (var m = 0; m < n; m++) {
                    matched.push(page[start + m].word);
                }
                return groupLines(matched);
            }
        }
        return [];
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

    // Lazily-built citation-source modal shared by all [Sn] controls. Same class
    // contract as the extraction modal (T56e): a fixed full-viewport backdrop
    // ``div.oe-ai-agent-source-modal`` (hidden by default, flex-centered) with a
    // content box, a ``button.oe-ai-agent-source-close``, and backdrop-click to
    // dismiss. A single body element receives the active citation's source.
    var citationModal = null;
    var citationModalBody = null;

    function ensureCitationModal() {
        if (citationModal) {
            return;
        }
        var modal = document.createElement('div');
        modal.className = 'oe-ai-agent-source-modal';
        modal.style.display = 'none';
        modal.style.position = 'fixed';
        modal.style.top = '0';
        modal.style.left = '0';
        modal.style.right = '0';
        modal.style.bottom = '0';
        modal.style.background = 'rgba(0,0,0,0.6)';
        modal.style.zIndex = '10500';
        modal.style.alignItems = 'center';
        modal.style.justifyContent = 'center';
        // Backdrop click (the modal element itself, not its content) dismisses.
        modal.addEventListener('click', function (evt) {
            if (evt.target === modal) {
                modal.style.display = 'none';
            }
        });

        var content = document.createElement('div');
        content.className = 'oe-ai-agent-source-modal-content';
        content.style.background = '#fff';
        content.style.padding = '0.75em';
        content.style.borderRadius = '4px';
        content.style.maxWidth = '90vw';
        content.style.maxHeight = '90vh';
        content.style.overflow = 'auto';

        var closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'oe-ai-agent-source-close';
        closeBtn.textContent = '×';
        closeBtn.style.float = 'right';
        closeBtn.style.border = '0';
        closeBtn.style.background = 'transparent';
        closeBtn.style.fontSize = '1.4em';
        closeBtn.style.lineHeight = '1';
        closeBtn.style.cursor = 'pointer';
        closeBtn.addEventListener('click', function () {
            modal.style.display = 'none';
        });
        content.appendChild(closeBtn);

        var body = document.createElement('div');
        body.className = 'oe-ai-agent-source-body';
        body.style.clear = 'both';
        content.appendChild(body);

        modal.appendChild(content);
        if (answer.parentNode) {
            answer.parentNode.insertBefore(modal, answer.nextSibling);
        } else {
            answer.appendChild(modal);
        }
        citationModal = modal;
        citationModalBody = body;
    }

    // Fill the shared modal body with one citation's source and show it. Built
    // entirely with createElement + textContent — never innerHTML.
    function openCitation(citation) {
        ensureCitationModal();
        while (citationModalBody.firstChild) {
            citationModalBody.removeChild(citationModalBody.firstChild);
        }
        if (citation.section) {
            var section = document.createElement('div');
            section.className = 'oe-ai-agent-source-section';
            section.style.fontWeight = 'bold';
            section.style.marginBottom = '0.35em';
            section.textContent = String(citation.section);
            citationModalBody.appendChild(section);
        }
        if (citation.text) {
            var snippet = document.createElement('div');
            snippet.className = 'oe-ai-agent-source-text';
            snippet.textContent = String(citation.text);
            citationModalBody.appendChild(snippet);
        }
        if (citation.type) {
            var type = document.createElement('div');
            type.className = 'oe-ai-agent-source-type';
            type.style.color = '#777';
            type.style.fontSize = '0.85em';
            type.style.marginTop = '0.35em';
            type.textContent = String(citation.type);
            citationModalBody.appendChild(type);
        }
        citationModal.style.display = 'flex';
    }

    // Walk the answer's text nodes and turn each ``[Sn]`` marker whose number is
    // a key in ``citations`` into a small clickable ``button.oe-ai-agent-cite``
    // that opens the citation modal. Markers with no matching source are left as
    // plain text. Text nodes are collected first, then split into
    // text-node / button / text-node fragments — never innerHTML, and buttons we
    // create are never re-walked.
    function enhanceCitations(container, citations) {
        var textNodes = [];
        (function collect(node) {
            for (var child = node.firstChild; child; child = child.nextSibling) {
                if (child.nodeType === 3) {
                    textNodes.push(child);
                } else if (child.nodeType === 1) {
                    collect(child);
                }
            }
        })(container);

        textNodes.forEach(function (textNode) {
            var value = textNode.nodeValue;
            var re = /\[S(\d+)\]/g;
            var match = re.exec(value);
            if (!match) {
                return;
            }
            var parent = textNode.parentNode;
            if (!parent) {
                return;
            }
            var frag = document.createDocumentFragment();
            var lastIndex = 0;
            var replaced = false;
            do {
                var n = match[1];
                if (Object.prototype.hasOwnProperty.call(citations, n)) {
                    if (match.index > lastIndex) {
                        frag.appendChild(document.createTextNode(value.slice(lastIndex, match.index)));
                    }
                    frag.appendChild(makeCiteButton(n, citations[n]));
                    lastIndex = match.index + match[0].length;
                    replaced = true;
                }
                match = re.exec(value);
            } while (match);

            if (!replaced) {
                return;
            }
            if (lastIndex < value.length) {
                frag.appendChild(document.createTextNode(value.slice(lastIndex)));
            }
            parent.replaceChild(frag, textNode);
        });
    }

    function makeCiteButton(n, citation) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'oe-ai-agent-cite';
        btn.setAttribute('data-n', n);
        btn.textContent = '[S' + n + ']';
        btn.style.fontSize = '0.85em';
        btn.style.border = '0';
        btn.style.background = 'transparent';
        btn.style.color = '#337ab7';
        btn.style.cursor = 'pointer';
        btn.style.padding = '0';
        btn.style.verticalAlign = 'baseline';
        btn.addEventListener('click', function () {
            openCitation(citation);
        });
        return btn;
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
                } else if (frame.event === 'done') {
                    // The terminal frame carries a citations map keyed by marker
                    // number (T72a). When present and non-empty, turn the already-
                    // rendered [Sn] markers into clickable source controls.
                    var citations = frame.data && frame.data.citations;
                    if (citations && typeof citations === 'object' && Object.keys(citations).length) {
                        enhanceCitations(answer, citations);
                    }
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
        // Ignore new questions while a turn is in flight ("thinking"): the Ask
        // button is disabled during that window, and this guard makes the block
        // apply to Enter and any programmatic submit too, not just a button click.
        if (submit && submit.disabled) {
            return;
        }
        var text = (question.value || '').trim();
        if (text === '') {
            return;
        }
        // A long previous answer may have scrolled the page down; bring the card
        // back into view at the top of the page when a new question is asked.
        window.scrollTo({ top: 0, behavior: 'smooth' });
        setBusy(true);
        // Archive the PRIOR turn (currentQuestion still holds the prior question),
        // then track THIS question before the live area is repainted.
        archiveTurn();
        currentQuestion = text;
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
                'allergies', 'family_history', 'source_citation'],
            med_list: ['medications', 'source_citation']
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

        // The file name whose extraction currently sits in the extract box. Set
        // only when a real facts panel is rendered; used to key its archive turn.
        var extractedFileName = null;

        // Clear the extraction panel and its status.
        function clearExtract() {
            if (extractBox) {
                extractBox.textContent = '';
            }
        }

        // If a real facts panel (a '.card') is currently rendered in the extract
        // box and we know which file produced it, move it into a collapsed history
        // accordion keyed by that file name BEFORE the box is cleared. A plain
        // status note (no '.card') and the first-ever upload archive nothing.
        function archiveExtraction() {
            if (!extractBox || !extractedFileName) {
                return;
            }
            if (extractBox.querySelector('.card')) {
                appendAccordion(extractedFileName, extractBox);
            }
            extractedFileName = null;
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
        function renderExtraction(data, documentId, isDuplicate, preview) {
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

            // Proactive wrong-chart / wrong-patient warning: shown the moment an
            // intake form is extracted whose identifiers do not match this chart.
            var identityCheck = data.identity_check;
            if (identityCheck && identityCheck.matches === false) {
                var warn = document.createElement('div');
                warn.className = 'alert alert-danger p-2 mb-2 small';

                var warnTitle = document.createElement('div');
                warnTitle.className = 'font-weight-bold';
                warnTitle.textContent = 'Possible wrong-chart / wrong-patient upload';
                warn.appendChild(warnTitle);

                var mismatched = identityCheck.mismatched_identifiers || [];
                var warnDetail = document.createElement('div');
                warnDetail.textContent = 'identifiers do not match this chart: '
                    + mismatched.map(humanize).join(', ');
                warn.appendChild(warnDetail);

                panel.appendChild(warn);
            }

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

            // Click-to-reveal citation source (T56e/T56h). ``boxesByField`` is a
            // PER-FIELD map ``{field: [ {x,y,w,h} ]}`` driving the SAME modal UX
            // from either of two geometry sources:
            //  - PDF uploads: the render seam returns the page's OWN text-layer word
            //    geometry (``preview.words``); each fact value is located CLIENT-SIDE
            //    on the actually-rendered page, so it works for any uploaded PDF.
            //  - image uploads: the /extract response's ``citation_boxes`` (server
            //    demo geometry), with page dimensions from the same response.
            // When present, each cited fact gets a small "show source" control (not
            // the whole row). Clicking it opens a MODAL overlay showing the document
            // image with ONLY that fact's box(es); the close control, the backdrop,
            // or re-clicking the active control dismisses it. The modal + overlay
            // layer are built first so the dl's control handlers can reference them.
            var boxesByField = null;
            var pageW = null;
            var pageH = null;
            var imgUrl = null;
            if (preview && preview.words) {
                // PDF: locate each fact value in the page's own text-layer words.
                pageW = preview.page_width;
                pageH = preview.page_height;
                imgUrl = preview.url;
                boxesByField = {};
                keys.forEach(function (k) {
                    var v = fact[k];
                    if (typeof v === 'string' && v !== '') {
                        var b = locateCitationBoxes(preview.words, String(v));
                        if (b.length) {
                            boxesByField[k] = b;
                        }
                    }
                });
            } else if (preview && data.citation_boxes && typeof data.citation_boxes === 'object') {
                // Image: server-provided per-field demo geometry.
                boxesByField = data.citation_boxes;
                pageW = data.page_width;
                pageH = data.page_height;
                imgUrl = preview.url;
            }

            var hasCites = boxesByField
                && typeof boxesByField === 'object'
                && Object.keys(boxesByField).length
                && pageW
                && pageH
                && imgUrl;

            var modal = null;
            var overlayLayer = null;
            var activeField = null;

            function citedField(k) {
                return hasCites
                    && Object.prototype.hasOwnProperty.call(boxesByField, k)
                    && Array.isArray(boxesByField[k])
                    && boxesByField[k].length;
            }

            function clearOverlay() {
                while (overlayLayer.firstChild) {
                    overlayLayer.removeChild(overlayLayer.firstChild);
                }
            }

            function drawField(k) {
                clearOverlay();
                boxesByField[k].forEach(function (box) {
                    var boxEl = document.createElement('div');
                    boxEl.className = 'oe-ai-agent-citation-box';
                    boxEl.style.position = 'absolute';
                    boxEl.style.left = (box.x / pageW * 100) + '%';
                    boxEl.style.top = (box.y / pageH * 100) + '%';
                    boxEl.style.width = (box.w / pageW * 100) + '%';
                    boxEl.style.height = (box.h / pageH * 100) + '%';
                    boxEl.style.border = '2px solid #d9534f';
                    boxEl.style.background = 'rgba(217,83,79,0.12)';
                    overlayLayer.appendChild(boxEl);
                });
            }

            function closeModal() {
                modal.style.display = 'none';
                clearOverlay();
                activeField = null;
            }

            function toggleField(k) {
                if (activeField === k) {
                    closeModal();
                    return;
                }
                drawField(k);
                modal.style.display = 'flex';
                activeField = k;
            }

            if (hasCites) {
                modal = document.createElement('div');
                modal.className = 'oe-ai-agent-source-modal';
                modal.style.display = 'none';
                modal.style.position = 'fixed';
                modal.style.top = '0';
                modal.style.left = '0';
                modal.style.right = '0';
                modal.style.bottom = '0';
                modal.style.background = 'rgba(0,0,0,0.6)';
                modal.style.zIndex = '10500';
                modal.style.alignItems = 'center';
                modal.style.justifyContent = 'center';
                // Clicking the backdrop (the modal element itself, not its content)
                // dismisses the modal; clicks inside the content box do not bubble
                // up to here as evt.target === modal, so they are ignored.
                modal.addEventListener('click', function (evt) {
                    if (evt.target === modal) {
                        closeModal();
                    }
                });

                var content = document.createElement('div');
                content.className = 'oe-ai-agent-source-modal-content';
                content.style.background = '#fff';
                content.style.padding = '0.75em';
                content.style.borderRadius = '4px';
                content.style.maxWidth = '90vw';
                content.style.maxHeight = '90vh';
                content.style.overflow = 'auto';

                var closeBtn = document.createElement('button');
                closeBtn.type = 'button';
                closeBtn.className = 'oe-ai-agent-source-close';
                closeBtn.textContent = '×';
                closeBtn.style.float = 'right';
                closeBtn.style.border = '0';
                closeBtn.style.background = 'transparent';
                closeBtn.style.fontSize = '1.4em';
                closeBtn.style.lineHeight = '1';
                closeBtn.style.cursor = 'pointer';
                closeBtn.addEventListener('click', closeModal);
                content.appendChild(closeBtn);

                var frame = document.createElement('div');
                frame.style.position = 'relative';
                frame.style.clear = 'both';

                var img = document.createElement('img');
                img.className = 'oe-ai-agent-doc-image';
                img.setAttribute('src', imgUrl);
                img.style.width = '100%';
                img.style.display = 'block';
                frame.appendChild(img);

                overlayLayer = document.createElement('div');
                overlayLayer.style.position = 'absolute';
                overlayLayer.style.left = '0';
                overlayLayer.style.top = '0';
                overlayLayer.style.width = '100%';
                overlayLayer.style.height = '100%';
                frame.appendChild(overlayLayer);

                content.appendChild(frame);
                modal.appendChild(content);
            }

            var dl = document.createElement('dl');
            dl.className = 'row mb-0';
            keys.forEach(function (k) {
                var dt = document.createElement('dt');
                dt.className = 'col-5 text-muted text-truncate';
                dt.textContent = humanize(k);
                var dd = document.createElement('dd');
                dd.className = 'col-7 mb-1';
                // Keep the value text in the dd via its own text node so the small
                // control can be appended after it without the dd itself carrying
                // any click affordance (no data-field / role="button").
                dd.appendChild(document.createTextNode(valueText(fact[k])));
                if (citedField(k)) {
                    var btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'oe-ai-agent-show-source';
                    btn.setAttribute('data-field', k);
                    btn.textContent = 'show source';
                    btn.style.marginLeft = '0.4em';
                    btn.style.fontSize = '0.75em';
                    btn.style.border = '0';
                    btn.style.background = 'transparent';
                    btn.style.color = '#337ab7';
                    btn.style.textDecoration = 'underline';
                    btn.style.cursor = 'pointer';
                    btn.style.padding = '0';
                    btn.addEventListener('click', function () {
                        toggleField(k);
                    });
                    dd.appendChild(btn);
                }
                dl.appendChild(dt);
                dl.appendChild(dd);
            });
            panel.appendChild(dl);

            if (modal) {
                panel.appendChild(modal);
            }

            var unsupported = data.unsupported_fields || [];
            if (unsupported.length) {
                var flagged = document.createElement('div');
                flagged.className = 'text-muted font-italic mt-1';
                flagged.textContent = 'Left blank (not grounded in the document): '
                    + unsupported.map(humanize).join(', ') + '.';
                panel.appendChild(flagged);
            }

            // "Accept & file to chart": commit the held facts to the chart. Hidden
            // on a wrong-chart identity mismatch — don't invite filing to the wrong
            // patient. On click the button disables, POSTs the held envelope to
            // persist.php, and confirms (or shows a safe failure) inline.
            if (!(identityCheck && identityCheck.matches === false)) {
                var fileBtn = document.createElement('button');
                fileBtn.type = 'button';
                fileBtn.className = 'oe-ai-agent-file-btn';
                // A duplicate ("already on file") upload is an OLD document — filing
                // it could re-file stale facts, so the action is disabled with a
                // clear label rather than offered.
                if (isDuplicate) {
                    fileBtn.textContent = 'Cannot file an old upload';
                    fileBtn.disabled = true;
                    panel.appendChild(fileBtn);
                    extractBox.appendChild(panel);
                    return;
                }
                fileBtn.textContent = 'Accept & file to chart';
                fileBtn.addEventListener('click', function () {
                    fileBtn.disabled = true;

                    var body = new URLSearchParams();
                    body.set('csrf_token', csrfToken);
                    body.set('payload', JSON.stringify({
                        source_document_id: documentId,
                        extraction_run_id: data.correlation_id || '',
                        doc_type: data.doc_type,
                        fact: data.fact || {}
                    }));

                    fetch(persistUrl, {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                        body: body.toString()
                    }).then(function (res) {
                        return res.json().catch(function () {
                            return {};
                        }).then(function (respBody) {
                            return { ok: res.ok, body: respBody || {} };
                        });
                    }).then(function (result) {
                        if (!result.ok || !result.body.ok) {
                            throw new Error('file failed');
                        }
                        var filed = document.createElement('div');
                        filed.className = 'oe-ai-agent-filed';
                        var count = Number(result.body.total) || 0;
                        filed.textContent = 'Filed ' + count + ' facts to the chart.';
                        if (fileBtn.parentNode) {
                            fileBtn.parentNode.replaceChild(filed, fileBtn);
                        }
                    }).catch(function () {
                        // Never surface internal detail; a safe inline message only.
                        var existing = panel.querySelector('.oe-ai-agent-file-error');
                        if (!existing) {
                            var err = document.createElement('div');
                            err.className = 'oe-ai-agent-file-error';
                            err.textContent = 'Could not file to the chart. Please try again.';
                            panel.appendChild(err);
                        }
                        fileBtn.disabled = false;
                    });
                });
                panel.appendChild(fileBtn);
            }

            extractBox.appendChild(panel);
        }

        // Resolve a normalized preview DESCRIPTOR for the source-citation modal,
        // asynchronously: ``{url, words, page_width, page_height}`` (or null).
        // Images get an object URL directly and carry no words (their geometry is
        // server-provided ``citation_boxes``): ``{url, words: null}``. PDFs cannot
        // render as an <img>, so they are routed through the optional
        // ``window.OE_AI_AGENT_PDF_RENDER`` seam (a pdf.js glue script, loaded
        // separately) which resolves to ``{url, words, page_width, page_height}``
        // — a page-1 raster PLUS the page's own text-layer word geometry, so the
        // widget can locate each fact value client-side. When that hook is absent,
        // or any other file type is uploaded, there is no preview. The widget
        // itself never imports pdf.js — it only consults the hook — so it stays
        // jsdom-testable. Always resolves (null on any failure or unsupported type).
        function resolvePreview(file) {
            if (!file || !file.type) {
                return Promise.resolve(null);
            }
            if (file.type.indexOf('image/') === 0) {
                if (!(window.URL && URL.createObjectURL)) {
                    return Promise.resolve(null);
                }
                return Promise.resolve({ url: URL.createObjectURL(file), words: null });
            }
            if (file.type === 'application/pdf') {
                if (typeof window.OE_AI_AGENT_PDF_RENDER === 'function') {
                    return Promise.resolve(window.OE_AI_AGENT_PDF_RENDER(file)).catch(function () {
                        return null;
                    });
                }
                return Promise.resolve(null);
            }
            return Promise.resolve(null);
        }

        // After a successful store, mint a patient-scoped JWT and ask the sidecar
        // to extract strict facts from the freshly-uploaded document. The pid is
        // sent from the card (as /ask does); the boundary re-checks the token
        // scope on the document read, so it can only reach the patient in context.
        function extractDocument(documentId, docType, fileName, isDuplicate, file) {
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
                // Resolve the preview DESCRIPTOR (image object URL, or a PDF page
                // raster + text-layer words via the seam) asynchronously, then
                // render the facts panel with it so the [show source] modal has an
                // image to draw citation boxes over.
                resolvePreview(file).then(function (preview) {
                    renderExtraction(result.body, documentId, isDuplicate, preview);
                    // Record the file only now that a real facts panel is on screen,
                    // so a note/failure path leaves nothing to archive on next upload.
                    extractedFileName = fileName || null;
                });
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
            // Capture the chosen doc_type and file name before reset() clears the
            // form, so the extraction call uses the type the file was filed under
            // and any archived extraction is keyed by the right name.
            var docType = docTypeSelect.value;
            var fileName = file.name;
            // The File reference is captured here and stays valid after
            // uploadForm.reset() clears the input, so the preview (image object
            // URL, or a PDF rendered via the seam) is resolved asynchronously from
            // it once extraction succeeds — see resolvePreview / extractDocument.
            var payload = new FormData();
            payload.append('csrf_token', csrfToken);
            payload.append('doc_type', docType);
            payload.append('document', file);

            if (uploadSubmit) {
                uploadSubmit.disabled = true;
            }
            setStatus('Uploading...', true);
            // Mirror the ask-submit behavior: a new upload clears the previous
            // answer/response so a stale answer never lingers above the new
            // extraction. Only runs once a real upload starts (past the no-file
            // guard above).
            archiveTurn();
            // Archive any prior rendered extraction into history BEFORE the box is
            // cleared, so it moves alongside the Q&A turns instead of being wiped.
            archiveExtraction();
            clearExtract();

            fetch(uploadUrl, {
                method: 'POST',
                credentials: 'same-origin',
                body: payload
            }).then(function (res) {
                // Parse the JSON body even on a 4xx/5xx so the endpoint's specific,
                // safe message (invalid type, too large, ...) can be shown instead
                // of a generic failure.
                return res.json().catch(function () {
                    return {};
                }).then(function (data) {
                    return { ok: res.ok, data: data || {} };
                });
            }).then(function (result) {
                var data = result.data;
                if (!result.ok || !data.ok) {
                    // setStatus writes via textContent, so the server message is
                    // inserted as plain text — never interpreted as HTML.
                    setStatus(data.error || 'Upload failed. Please try again.', false);
                    return;
                }
                // A duplicate was not re-stored; the existing document is reused.
                if (data.duplicate) {
                    setStatus('Already on file — using the existing document.', true);
                } else {
                    setStatus(
                        data.category ? ('Uploaded to ' + data.category + '.') : 'Uploaded.',
                        true
                    );
                }
                uploadForm.reset();
                // Auto-extract strict facts from the stored document (existing or new).
                extractDocument(data.id, docType, fileName, data.duplicate === true, file);
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
            // Don't submit while a turn is in flight ("thinking").
            if (submit && submit.disabled) {
                return;
            }
            if (typeof form.requestSubmit === 'function') {
                form.requestSubmit();
            } else {
                form.dispatchEvent(new Event('submit', { cancelable: true }));
            }
        }
    });
})();
