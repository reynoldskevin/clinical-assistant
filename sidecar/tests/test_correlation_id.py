"""T35 acceptance tests (LOCKED) — correlation ID across the sidecar.

Deliverable: every agent invocation carries a unique correlation ID (CID) that
appears in every log entry, tool call, and LLM interaction so a full trace can be
reconstructed from logs alone. This covers the sidecar half: the CID is generated
per invocation, exposed on the agent, forwarded as an X-Correlation-ID header on
boundary calls, returned to the caller, and written into the per-turn log line.
(The PHP boundary audit-logging the forwarded header is T36.)

Deterministic — scripted SDK fakes + a capturing opener; no live API, no sockets.
"""
import json
import logging
from types import SimpleNamespace

import factory
from agent import ClaudeAgent
from factory import build_boundary, build_chart_boundary, new_correlation_id
from server import default_agent_builder, process_ask, stream_ask


# --- SDK / HTTP fakes ----------------------------------------------------------

def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(name, input_, id="tu1"):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id)


def _resp(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class CapturingOpener:
    """Stands in for urllib.request.urlopen; records each Request's headers."""

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        return _FakeResp(self._payload)

    def header(self, name):
        # Case-insensitive lookup of the last request's header value.
        req = self.requests[-1]
        for k, v in req.header_items():
            if k.lower() == name.lower():
                return v
        return None


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --- new_correlation_id --------------------------------------------------------

def test_new_correlation_id_is_unique_and_non_empty():
    a, b = new_correlation_id(), new_correlation_id()
    assert isinstance(a, str) and a != ""
    assert a != b


# --- boundary forwards the header ----------------------------------------------

def test_build_boundary_forwards_correlation_id_header():
    opener = CapturingOpener({"problems": []})
    boundary = build_boundary("http://oe/summary.php", "jwt-x", opener=opener, correlation_id="cid-123")
    boundary(42)
    assert opener.header("X-Correlation-ID") == "cid-123"


def test_build_boundary_without_cid_sends_no_correlation_header():
    opener = CapturingOpener({"problems": []})
    boundary = build_boundary("http://oe/summary.php", "jwt-x", opener=opener)
    boundary(42)
    assert opener.header("X-Correlation-ID") is None


def test_chart_boundary_forwards_correlation_id_header():
    opener = CapturingOpener([{"ref": "encounter:1"}])
    cb = build_chart_boundary("http://oe/read.php", "jwt-x", opener=opener, correlation_id="cid-777")
    cb.list_encounters(42)
    assert opener.header("X-Correlation-ID") == "cid-777"


# --- agent + builder -----------------------------------------------------------

def test_agent_exposes_correlation_id():
    agent = ClaudeAgent(lambda **k: _resp([_text("ok")], "end_turn"), lambda pid: {}, correlation_id="abc-1")
    assert agent.correlation_id == "abc-1"


def test_default_agent_builder_assigns_unique_cid_per_build():
    creator = lambda **k: _resp([_text("ok")], "end_turn")  # noqa: E731
    builder = default_agent_builder("http://oe/summary.php", creator)
    a1 = builder(42, "jwt")
    a2 = builder(42, "jwt")
    assert a1.correlation_id and a2.correlation_id
    assert a1.correlation_id != a2.correlation_id


# --- process_ask returns + logs the CID ----------------------------------------

def _body(jwt="jwt", pid=42, q="hi"):
    return json.dumps({"pid": pid, "question": q}).encode("utf-8")


def _fixed_cid_builder(cid):
    def builder(pid, jwt):
        agent = ClaudeAgent(lambda **k: _resp([_text("Answer.")], "end_turn"), lambda p: {}, correlation_id=cid)
        return agent
    return builder


def test_process_ask_returns_and_logs_correlation_id(caplog):
    with caplog.at_level(logging.INFO, logger="sidecar"):
        status, body = process_ask("Bearer jwt", _body(), _fixed_cid_builder("cid-log-1"))
    assert status == 200
    assert body["correlation_id"] == "cid-log-1"
    assert "cid-log-1" in caplog.text


# --- stream_ask emits + logs the CID -------------------------------------------

def test_stream_ask_emits_and_logs_correlation_id(caplog):
    with caplog.at_level(logging.INFO, logger="sidecar"):
        frames = b"".join(stream_ask("Bearer jwt", _body(), _fixed_cid_builder("cid-stream-9")))
    text = frames.decode("utf-8")
    assert "cid-stream-9" in text          # surfaced to the client in a frame
    assert "cid-stream-9" in caplog.text   # and written to the log


class _RecordingTracer:
    """Captures the metadata each turn's span is opened with."""

    def __init__(self):
        self.turns = []

    def turn(self, metadata):
        self.turns.append(dict(metadata))
        import contextlib
        return contextlib.nullcontext()


def test_process_ask_tags_span_metadata_with_correlation_id():
    tracer = _RecordingTracer()
    process_ask("Bearer jwt", _body(), _fixed_cid_builder("cid-span-p"), tracer=tracer)
    assert tracer.turns and tracer.turns[0]["correlation_id"] == "cid-span-p"


def test_stream_ask_tags_span_metadata_with_correlation_id():
    tracer = _RecordingTracer()
    b"".join(stream_ask("Bearer jwt", _body(), _fixed_cid_builder("cid-span-s"), tracer=tracer))
    assert tracer.turns and tracer.turns[0]["correlation_id"] == "cid-span-s"
