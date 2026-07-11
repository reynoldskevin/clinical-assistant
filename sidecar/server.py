"""Runnable HTTP sidecar: POST /ask -> ClaudeAgent -> {"answer": ...}.

Stateless and single-endpoint. Every request carries a short-lived,
patient-scoped JWT (minted by OpenEMR's token.php); the sidecar forwards that
token to the OpenEMR boundary for each chart read and never sees the signing
key. No PHI is persisted here.

The request handling is split into a pure ``process_ask`` function (unit-tested,
no sockets) and a thin ``BaseHTTPRequestHandler`` that adapts it to HTTP.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from agent import ClaudeAgent
from conversation import ConversationStore
from factory import (
    build_boundary,
    build_chart_boundary,
    build_encounter_tools,
    build_medications_tool,
    build_message_creator,
    build_results_tool,
    build_search_tool,
    build_tracer,
)
from observability import TraceCollector

# An agent-builder maps (pid, jwt) -> an object with .run(question, pid) -> str.
AgentBuilder = Callable[[int, str], Any]

_BEARER_PREFIX = "Bearer "


def _span(tracer: Any, metadata: dict[str, Any]) -> contextlib.AbstractContextManager[Any]:
    """Return the tracer's turn context manager, safely defaulting to a no-op.

    Observability must never break the request path: if there is no tracer, or
    ``tracer.turn(metadata)`` raises, a no-op context manager is returned so the
    agent still runs and the answer is still produced.
    """
    if tracer is None:
        return contextlib.nullcontext()
    try:
        return tracer.turn(metadata)
    except Exception:  # noqa: BLE001 - telemetry must never break the request
        logging.getLogger("sidecar").exception("tracer.turn failed; continuing without a span")
        return contextlib.nullcontext()


def _run_agent(
    agent: Any,
    question: str,
    pid: int,
    store: ConversationStore | None,
    conversation_id: Any,
    multi_turn: bool,
) -> tuple[str, list[Any] | None]:
    """Run one agent turn, returning ``(answer, new_history)``.

    ``new_history`` is the updated conversation history for the multi-turn path
    (so the caller can persist it), or ``None`` for the stateless path.
    """
    if multi_turn:
        assert store is not None  # multi_turn implies a store; narrows the type
        history = store.history(conversation_id, pid)
        answer, new_history = agent.run_turn(question, pid, history)
        return answer, new_history
    return agent.run(question, pid), None


def process_ask(
    authorization: str,
    raw_body: bytes,
    agent_builder: AgentBuilder,
    store: ConversationStore | None = None,
    tracer: Any = None,
) -> tuple[int, dict[str, Any]]:
    """Validate a /ask request and run the agent. Returns (status, json_body).

    Pure and side-effect-free apart from the injected agent and (optional)
    conversation store: no sockets, so it is directly unit-testable. Never
    surfaces internal error detail to the caller.

    When ``store`` is supplied and the body carries a non-empty
    ``conversation_id``, the pid-scoped history is loaded, the turn continues it
    via ``run_turn``, and the updated history is persisted. Otherwise the request
    is stateless (``run``), keeping the 3-arg callers backward compatible.
    """
    if not authorization.startswith(_BEARER_PREFIX):
        return 401, {"error": "missing bearer token"}
    jwt = authorization[len(_BEARER_PREFIX):].strip()
    if jwt == "":
        return 401, {"error": "missing bearer token"}

    try:
        data = json.loads(raw_body or b"{}")
        pid = int(data.get("pid", 0))
        question = str(data.get("question", "")).strip()
        conversation_id = data.get("conversation_id")
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return 400, {"error": "invalid request"}

    if pid <= 0 or question == "":
        return 400, {"error": "pid and question are required"}

    multi_turn = store is not None and isinstance(conversation_id, str) and conversation_id != ""

    # Tag this turn's observability span with the patient (and, for multi-turn,
    # the conversation) so the auto-logged Claude calls group by conversation +
    # patient. Guarded end-to-end: a failing tracer never breaks the request.
    metadata: dict[str, Any] = {"pid": pid}
    if multi_turn:
        metadata["conversation_id"] = conversation_id

    try:
        agent = agent_builder(pid, jwt)
        # Enter the span, but never let a span-lifecycle failure re-run the agent.
        # The agent is invoked from exactly ONE call site below so an agent error
        # (the expensive failure path) can never trigger a second LLM call.
        cm = _span(tracer, metadata)
        try:
            cm.__enter__()
            entered = True
        except Exception:  # noqa: BLE001 - a span enter error must not break the request
            logging.getLogger("sidecar").exception("span __enter__ failed; continuing without it")
            entered = False

        try:
            result = _run_agent(agent, question, pid, store, conversation_id, multi_turn)
        except BaseException as e:
            # Agent error: close the span (swallowing exit errors), then let the
            # exception propagate to the outer handler which masks it to 502.
            if entered:
                try:
                    cm.__exit__(type(e), e, e.__traceback__)
                except Exception:  # noqa: BLE001 - a span exit error must not mask the real failure
                    logging.getLogger("sidecar").exception("span __exit__ failed; ignoring")
            raise
        else:
            if entered:
                try:
                    cm.__exit__(None, None, None)
                except Exception:  # noqa: BLE001 - a span exit error must not break the request
                    logging.getLogger("sidecar").exception("span __exit__ failed; ignoring")

        answer, new_history = result
        if multi_turn and new_history is not None:
            store.remember(conversation_id, pid, new_history)
    except Exception:
        # Never leak internal detail (API errors, boundary failures) to the browser.
        logging.getLogger("sidecar").exception("agent turn failed", extra={"pid": pid})
        return 502, {"error": "the assistant is unavailable"}

    # Emit the turn's observability trace (tokens, cost, tool calls). Guarded so
    # non-instrumented agents (e.g. test fakes) don't error.
    observer = getattr(agent, "observer", None)
    summarize = getattr(observer, "summary", None)
    if callable(summarize):
        logging.getLogger("sidecar").info("agent turn: pid=%s trace=%s", pid, json.dumps(summarize()))

    return 200, {"answer": answer}


def default_agent_builder(
    summary_url: str,
    message_creator: Any,
    read_url: str | None = None,
) -> AgentBuilder:
    """Build a per-request ClaudeAgent bound to the forwarded JWT.

    The agent gets the built-in summary tool plus the operation-dispatched chart
    tools (list_encounters / get_encounter) that POST to read.php with the same
    forwarded JWT. ``read_url`` defaults to the summary URL with ``summary.php``
    swapped for ``read.php``.
    """
    chart_url = read_url or summary_url.replace("summary.php", "read.php")
    # Per-turn tool-execution budget; overridable via env (defaults to 8).
    max_tool_calls = int(os.environ.get("OE_AI_AGENT_MAX_TOOL_CALLS") or "8")

    def build(pid: int, jwt: str) -> ClaudeAgent:
        boundary = build_boundary(summary_url, jwt)
        chart_boundary = build_chart_boundary(chart_url, jwt)
        return ClaudeAgent(
            message_creator,
            boundary,
            observer=TraceCollector(),
            extra_tools=build_encounter_tools(chart_boundary)
            + [
                build_results_tool(chart_boundary),
                build_medications_tool(chart_boundary),
                build_search_tool(chart_boundary),
            ],
            max_tool_calls=max_tool_calls,
        )

    return build


def make_handler(
    agent_builder: AgentBuilder,
    allow_origin: str,
    store: ConversationStore | None = None,
    tracer: Any = None,
) -> type[BaseHTTPRequestHandler]:
    """Create a request-handler class bound to an agent-builder and CORS origin.

    An optional ``ConversationStore`` enables multi-turn context for requests
    that carry a ``conversation_id``.
    """

    class Handler(BaseHTTPRequestHandler):
        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", allow_origin)
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

        def _send_json(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self._cors()
            self.end_headers()
            self.wfile.write(payload)

        def do_OPTIONS(self) -> None:  # noqa: N802 (http.server naming)
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802 (http.server naming)
            if self.path.rstrip("/") != "/ask":
                self._send_json(404, {"error": "not found"})
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(length) if length > 0 else b""
            status, body = process_ask(
                self.headers.get("Authorization", ""),
                raw_body,
                agent_builder,
                store,
                tracer,
            )
            self._send_json(status, body)

        def log_message(self, *args: Any) -> None:  # keep the console quiet
            pass

    return Handler


def load_env_file(path: str) -> None:
    """Load simple KEY=VALUE lines from a .env file into os.environ.

    Best-effort and dependency-free: blank lines and '#' comments are skipped,
    surrounding quotes are stripped, and existing environment variables are not
    overwritten (an explicit export always wins over the file).
    """
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line == "" or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    load_env_file(os.path.join(os.path.dirname(__file__), ".env"))

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is required to run the sidecar.")

    summary_url = os.environ.get(
        "OE_AI_AGENT_SUMMARY_URL",
        "http://localhost:8300/interface/modules/custom_modules/oe-module-ai-agent/public/summary.php",
    )
    read_url = os.environ.get("OE_AI_AGENT_READ_URL") or summary_url.replace("summary.php", "read.php")
    allow_origin = os.environ.get("OE_AI_AGENT_ALLOW_ORIGIN", "*")
    # On a platform that assigns a port (Railway sets $PORT), bind all interfaces
    # on that port by default; locally, stay on loopback:8900.
    default_host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    host = os.environ.get("OE_AI_AGENT_HOST", default_host)
    port = int(os.environ.get("OE_AI_AGENT_PORT") or os.environ.get("PORT") or "8900")

    message_creator = build_message_creator(api_key)
    # Ephemeral, pid-scoped, TTL-bounded store so follow-up questions carry
    # context across turns (in-memory only — no PHI persisted to disk).
    store = ConversationStore()
    # Optional Braintrust turn-tracer: no-op unless BRAINTRUST_API_KEY is set,
    # and fully guarded so observability can never break the request path.
    tracer = build_tracer()
    handler = make_handler(
        default_agent_builder(summary_url, message_creator, read_url),
        allow_origin,
        store,
        tracer,
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"AI sidecar listening on http://{host}:{port}/ask -> {summary_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
