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

    // The CSRF token is embedded server-side on the card (data-csrf); fall back
    // to OpenEMR's page global (csrf_token_js) where one is present.
    var csrfToken = root.dataset.csrf
        || ((typeof window.csrf_token_js !== 'undefined') ? window.csrf_token_js : '');

    function setBusy(busy) {
        if (submit) {
            submit.disabled = busy;
        }
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
            body: JSON.stringify({ pid: parseInt(root.dataset.pid, 10), question: text })
        }).then(function (res) {
            if (!res.ok) {
                throw new Error('sidecar request failed');
            }
            return res.json();
        });
    }

    // Append inline text to a node, bolding **...** spans. Model text only ever
    // becomes text nodes / <strong> we create — it is never interpreted as HTML,
    // so there is no XSS surface.
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
                parent.appendChild(document.createTextNode(part));
            }
        });
    }

    // Render a small, safe subset of Markdown: **bold** and '-'/'*' bullet lists.
    // Consecutive bullet lines are grouped into a single <ul>.
    function renderAnswer(text) {
        answer.textContent = '';
        var list = null;
        String(text).split('\n').forEach(function (line) {
            var trimmed = line.trim();
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
                return;
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
                return;
            }
            list = null;
            if (trimmed === '') {
                return;
            }
            var block = document.createElement('div');
            appendInline(block, line);
            answer.appendChild(block);
        });
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
        answer.textContent = 'Thinking...';
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
