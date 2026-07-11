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
    var sidecarUrl = root.dataset.sidecarUrl || '/ai-agent-sidecar/ask';

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
            + '.oe-ai-agent-answer:not(:empty){margin-bottom:0.75em}';
        (document.head || document.documentElement).appendChild(style);
    })();

    function setBusy(busy) {
        if (submit) {
            submit.disabled = busy;
        }
    }

    // Show the "Thinking..." status with an animated spinner beside it.
    function showThinking() {
        answer.textContent = '';
        var spinner = document.createElement('span');
        spinner.className = 'oe-ai-agent-spinner';
        spinner.setAttribute('aria-hidden', 'true');
        answer.appendChild(spinner);
        answer.appendChild(document.createTextNode('Thinking...'));
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

    function askSidecar(jwt, text) {
        return fetch(sidecarUrl, {
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
            if (!res.ok) {
                throw new Error('sidecar request failed');
            }
            return res.json();
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
        }).then(function (data) {
            renderAnswer((data && data.answer) ? data.answer : 'No answer returned.');
            // Clear the question but keep focus, ready for the next one.
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
