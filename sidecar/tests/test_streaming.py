"""T25 acceptance tests (LOCKED) — SSE streaming + verify/stream reconciliation.

Reconciliation strategy: **stream status, buffer answer**. Status/tool events are
emitted live during the turn; the answer TEXT is buffered, run through the
verification gate, and only the gated answer is streamed — so no unverified
clinical content ever reaches the client. Deterministic; no anthropic SDK, no
sockets, no live API call.
"""
import json
from types import SimpleNamespace

from agent import ClaudeAgent
from server import stream_ask


# --- scripted SDK fakes (mirror the other sidecar tests) -----------------------

def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(name, input_, id="tu1"):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id)


def _resp(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class ScriptedCreator:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class RecordingBoundary:
    def __init__(self, summary):
        self.summary = summary

    def __call__(self, pid):
        return self.summary


def _spec(name, handler):
    return {
        "name": name,
        "description": f"{name} tool",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "handler": handler,
    }


# --- agent: on_event status channel --------------------------------------------

def test_on_event_fires_once_per_tool_execution_in_order():
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_tool_use("get_results", {}, "t2")], "tool_use"),
        _resp([_text("All reviewed.")], "end_turn"),
    ])
    meds = _spec("get_medications", lambda pid, inp: [{"ref": "prescription:1", "drug": "Warfarin"}])
    results = _spec("get_results", lambda pid, inp: [{"ref": "result:1", "value": "ok"}])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[meds, results])

    events = []
    answer, _ = agent.run_turn("review the chart", pid=42, on_event=events.append)

    tool_events = [e for e in events if e.get("type") == "tool"]
    assert [e["name"] for e in tool_events] == ["get_medications", "get_results"]
    assert all(e["ok"] is True for e in tool_events)
    assert answer == "All reviewed."


def test_streamed_answer_equals_non_streaming_answer():
    def script():
        return [
            _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
            _resp([_text("On Warfarin 5 mg [S1].\n```citations\n"
                         + json.dumps([{"n": 1, "ref": "prescription:1"}]) + "\n```")], "end_turn"),
        ]
    med = _spec("get_medications", lambda pid, inp: [{"ref": "prescription:1", "drug": "Warfarin"}])

    plain = ClaudeAgent(ScriptedCreator(script()), RecordingBoundary({}), extra_tools=[med])
    streamed = ClaudeAgent(ScriptedCreator(script()), RecordingBoundary({}), extra_tools=[med])

    plain_answer = plain.run("meds?", pid=1)
    streamed_answer, _ = streamed.run_turn("meds?", pid=1, on_event=lambda e: None)
    assert streamed_answer == plain_answer
    assert "```citations" not in streamed_answer  # gate applied in both


def test_default_on_event_none_is_unchanged():
    creator = ScriptedCreator([_resp([_text("Hello.")], "end_turn")])
    agent = ClaudeAgent(creator, RecordingBoundary({}))
    assert agent.run_turn("hi", pid=7) == ("Hello.", [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello."},
    ])


def test_no_status_event_carries_the_answer_text():
    # The answer must only ever be delivered buffered + gated, never via a status
    # event — a status event leaking answer text would be unverified content.
    creator = ScriptedCreator([
        _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
        _resp([_text("The secret answer is 42.")], "end_turn"),
    ])
    med = _spec("get_medications", lambda pid, inp: [{"ref": "prescription:1"}])
    agent = ClaudeAgent(creator, RecordingBoundary({}), extra_tools=[med])

    events = []
    answer, _ = agent.run_turn("q", pid=1, on_event=events.append)
    assert answer == "The secret answer is 42."
    for e in events:
        assert "secret answer" not in json.dumps(e)


# --- server: stream_ask SSE frames ---------------------------------------------

def _frames(raw_iter):
    """Parse an iterable of SSE byte chunks into [(event, data_obj), ...]."""
    text = b"".join(raw_iter).decode("utf-8")
    out = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event = None
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        out.append((event, data))
    return out


class _Builder:
    """agent_builder returning a scripted ClaudeAgent."""
    def __init__(self, responses, tools):
        self._responses = responses
        self._tools = tools

    def __call__(self, pid, jwt):
        return ClaudeAgent(
            ScriptedCreator(list(self._responses)),
            RecordingBoundary({}),
            extra_tools=list(self._tools),
        )


_AUTH = "Bearer tok"


def test_stream_frame_sequence_status_tool_answer_done():
    builder = _Builder(
        [
            _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
            _resp([_text("Reviewed.")], "end_turn"),
        ],
        [_spec("get_medications", lambda pid, inp: [{"ref": "prescription:1"}])],
    )
    body = json.dumps({"pid": 1, "question": "meds?"}).encode()
    frames = _frames(stream_ask(_AUTH, body, builder))

    names = [ev for ev, _ in frames]
    assert names[0] == "status"                 # a live start/status frame first
    assert "tool" in names                      # a live tool frame
    assert names.count("answer") == 1           # exactly one answer frame
    assert names[-1] == "done"                  # terminal
    # ordering: a tool frame precedes the answer frame (status live, answer buffered)
    assert names.index("tool") < names.index("answer")
    answer_data = next(d for ev, d in frames if ev == "answer")
    assert answer_data["answer"] == "Reviewed."


def test_streamed_answer_is_the_gated_answer():
    # A fabricated citation must be stripped BEFORE the answer frame is emitted.
    final = ("On Warfarin 5 mg [S1] and Metformin 500 mg [S2].\n```citations\n"
             + json.dumps([{"n": 1, "ref": "prescription:1"}, {"n": 2, "ref": "prescription:999"}])
             + "\n```")
    builder = _Builder(
        [
            _resp([_tool_use("get_medications", {}, "t1")], "tool_use"),
            _resp([_text(final)], "end_turn"),
        ],
        [_spec("get_medications", lambda pid, inp: [{"ref": "prescription:1", "drug": "Warfarin"}])],
    )
    body = json.dumps({"pid": 1, "question": "meds?"}).encode()
    frames = _frames(stream_ask(_AUTH, body, builder))
    answer = next(d for ev, d in frames if ev == "answer")["answer"]
    assert "[S1]" in answer            # valid citation kept
    assert "[S2]" not in answer        # fabricated stripped by the gate
    assert "```citations" not in answer


def test_stream_missing_auth_yields_single_error_frame():
    builder = _Builder([_resp([_text("x")], "end_turn")], [])
    frames = _frames(stream_ask("", json.dumps({"pid": 1, "question": "q"}).encode(), builder))
    assert len(frames) == 1
    ev, data = frames[0]
    assert ev == "error"
    assert data["status"] == 401


def test_stream_bad_body_yields_error_frame():
    builder = _Builder([_resp([_text("x")], "end_turn")], [])
    frames = _frames(stream_ask(_AUTH, b"{not json", builder))
    assert len(frames) == 1
    ev, data = frames[0]
    assert ev == "error"
    assert data["status"] == 400


def test_stream_agent_error_yields_error_frame_without_leaking_detail():
    class Boom:
        def __call__(self, pid, jwt):
            class _A:
                def run_turn(self, *a, **k):
                    raise RuntimeError("internal boundary SQL blew up")

                def run(self, *a, **k):
                    raise RuntimeError("internal boundary SQL blew up")
            return _A()

    body = json.dumps({"pid": 1, "question": "q"}).encode()
    frames = _frames(stream_ask(_AUTH, body, Boom()))
    assert any(ev == "error" for ev, _ in frames)
    blob = json.dumps(frames)
    assert "SQL" not in blob and "boundary" not in blob
    assert not any(ev == "answer" for ev, _ in frames)


# --- server: multi-turn over the stream ----------------------------------------

class _RecordingStore:
    def __init__(self):
        self.saved = []
        self._hist = {}

    def history(self, cid, pid):
        return self._hist.get((cid, pid))

    def remember(self, cid, pid, messages):
        self.saved.append((cid, pid, messages))
        self._hist[(cid, pid)] = messages


def test_stream_multi_turn_persists_history():
    builder = _Builder([_resp([_text("Hi there.")], "end_turn")], [])
    store = _RecordingStore()
    body = json.dumps({"pid": 5, "question": "hello", "conversation_id": "c-1"}).encode()
    list(stream_ask(_AUTH, body, builder, store))
    assert len(store.saved) == 1
    cid, pid, messages = store.saved[0]
    assert cid == "c-1" and pid == 5
    assert {"role": "user", "content": "hello"} in messages


def test_stream_stateless_does_not_persist():
    builder = _Builder([_resp([_text("Hi.")], "end_turn")], [])
    store = _RecordingStore()
    body = json.dumps({"pid": 5, "question": "hello"}).encode()  # no conversation_id
    list(stream_ask(_AUTH, body, builder, store))
    assert store.saved == []
