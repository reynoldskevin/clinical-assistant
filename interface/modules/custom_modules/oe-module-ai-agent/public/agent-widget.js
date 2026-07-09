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

    form.addEventListener('submit', function (evt) {
        evt.preventDefault();
        var text = (question.value || '').trim();
        if (text === '') {
            return;
        }
        setBusy(true);
        answer.textContent = 'Thinking...';
        mintToken().then(function (jwt) {
            return askSidecar(jwt, text);
        }).then(function (data) {
            answer.textContent = (data && data.answer) ? data.answer : 'No answer returned.';
        }).catch(function () {
            // Never surface internal error detail to the clinician.
            answer.textContent = 'The assistant is unavailable right now.';
        }).finally(function () {
            setBusy(false);
        });
    });
})();
