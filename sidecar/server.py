"""Runnable HTTP sidecar: POST /ask -> ClaudeAgent -> {"answer": ...}.

Stateless and single-endpoint. Every request carries a short-lived,
patient-scoped JWT (minted by OpenEMR's token.php); the sidecar forwards that
token to the OpenEMR boundary for each chart read and never sees the signing
key. No PHI is persisted here.

The request handling is split into a pure ``process_ask`` function (unit-tested,
no sockets) and a thin ``BaseHTTPRequestHandler`` that adapts it to HTTP.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from agent import ClaudeAgent
from factory import build_boundary, build_message_creator
from observability import TraceCollector

# An agent-builder maps (pid, jwt) -> an object with .run(question, pid) -> str.
AgentBuilder = Callable[[int, str], Any]

_BEARER_PREFIX = "Bearer "


def process_ask(
    authorization: str,
    raw_body: bytes,
    agent_builder: AgentBuilder,
) -> tuple[int, dict[str, Any]]:
    """Validate a /ask request and run the agent. Returns (status, json_body).

    Pure and side-effect-free apart from the injected agent: no sockets, so it is
    directly unit-testable. Never surfaces internal error detail to the caller.
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
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return 400, {"error": "invalid request"}

    if pid <= 0 or question == "":
        return 400, {"error": "pid and question are required"}

    try:
        agent = agent_builder(pid, jwt)
        answer = agent.run(question, pid)
    except Exception:
        # Never leak internal detail (API errors, boundary failures) to the browser.
        return 502, {"error": "the assistant is unavailable"}

    return 200, {"answer": answer}


def default_agent_builder(summary_url: str, message_creator: Any) -> AgentBuilder:
    """Build a per-request ClaudeAgent bound to the forwarded JWT."""

    def build(pid: int, jwt: str) -> ClaudeAgent:
        boundary = build_boundary(summary_url, jwt)
        return ClaudeAgent(message_creator, boundary, observer=TraceCollector())

    return build


def make_handler(agent_builder: AgentBuilder, allow_origin: str) -> type[BaseHTTPRequestHandler]:
    """Create a request-handler class bound to an agent-builder and CORS origin."""

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
    load_env_file(os.path.join(os.path.dirname(__file__), ".env"))

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is required to run the sidecar.")

    summary_url = os.environ.get(
        "OE_AI_AGENT_SUMMARY_URL",
        "http://localhost:8300/interface/modules/custom_modules/oe-module-ai-agent/public/summary.php",
    )
    allow_origin = os.environ.get("OE_AI_AGENT_ALLOW_ORIGIN", "*")
    # On a platform that assigns a port (Railway sets $PORT), bind all interfaces
    # on that port by default; locally, stay on loopback:8900.
    default_host = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    host = os.environ.get("OE_AI_AGENT_HOST", default_host)
    port = int(os.environ.get("OE_AI_AGENT_PORT") or os.environ.get("PORT") or "8900")

    message_creator = build_message_creator(api_key)
    handler = make_handler(default_agent_builder(summary_url, message_creator), allow_origin)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"AI sidecar listening on http://{host}:{port}/ask -> {summary_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
