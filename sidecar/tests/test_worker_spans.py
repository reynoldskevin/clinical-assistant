"""T57b acceptance tests (LOCKED) — distributed tracing: worker child spans.

`W2_ARCHITECTURE.md` §7: "Supervisor span → worker child spans →
extraction/retrieval sub-spans. A full Week-2 request trace is reconstructable
from the correlation ID alone." This ticket wires each graph worker to run inside
its own child span:

  * `NullTracer` gains a no-op `worker_span(name, correlation_id, kind, parent)`
    context manager (zero-overhead default — existing callers unaffected).
  * `build_supervisor_graph(..., tracer=None)` defaults to the null tracer.
  * each routed worker opens a child span carrying its name, the turn's
    correlation id, its kind, and `parent="supervisor"`, entered+exited around
    the tool call.

Deterministic: a recording tracer captures span open/close; no live API, no
sockets.
"""
import contextlib

from observability import NullTracer
from graph import _EVIDENCE, _INTAKE, build_supervisor_graph


# --- a recording tracer ------------------------------------------------------

class _RecordingTracer:
    """Captures every worker_span open/close in order."""

    def __init__(self):
        self.spans = []
        self.events = []  # ("open"|"close", name) in call order

    def turn(self, metadata):
        return contextlib.nullcontext()

    @contextlib.contextmanager
    def worker_span(self, name, correlation_id, kind=None, parent="supervisor"):
        span = {
            "name": name,
            "correlation_id": correlation_id,
            "kind": kind,
            "parent": parent,
            "closed": False,
        }
        self.spans.append(span)
        self.events.append(("open", name))
        try:
            yield span
        finally:
            span["closed"] = True
            self.events.append(("close", name))


class _Tool:
    def __init__(self, citations=None, payload=None, boom=False):
        self._citations = list(citations or [])
        self._payload = dict(payload or {})
        self._boom = boom

    def __call__(self, *, question, pid, correlation_id):
        if self._boom:
            raise RuntimeError("tool failure")
        return {"citations": list(self._citations), "payload": dict(self._payload)}


def _invoke(*, route, tracer, extractor=None, retriever=None, cid="cid-span"):
    app = build_supervisor_graph(
        extractor=extractor or _Tool(),
        retriever=retriever or _Tool(),
        finalizer=lambda state: "composed",
        tracer=tracer,
    )
    return app.invoke({"question": "q", "pid": 1, "correlation_id": cid, "route": route})


# --- 1. NullTracer no-op contract --------------------------------------------

def test_null_tracer_worker_span_is_a_usable_no_op_context_manager():
    with NullTracer().worker_span("intake_extractor", "cid-x", kind="extraction") as span:
        # A no-op span — nothing is required of the yielded value.
        assert span is None or isinstance(span, object)


def test_build_supervisor_graph_defaults_tracer_and_stays_backward_compatible():
    # No tracer passed — existing callers must keep working unchanged.
    app = build_supervisor_graph(extractor=_Tool(), retriever=_Tool())
    state = app.invoke({"question": "q", "pid": 1, "correlation_id": "cid-bc", "route": [_INTAKE]})
    assert state["worker_results"][0]["worker"] == _INTAKE


# --- 2. one child span per routed worker -------------------------------------

def test_one_child_span_per_worker_with_name_kind_parent_and_cid():
    tracer = _RecordingTracer()
    _invoke(
        route=[_INTAKE, _EVIDENCE],
        tracer=tracer,
        extractor=_Tool(["intake:1"]),
        retriever=_Tool(["[S1]"]),
        cid="cid-two",
    )
    by_name = {s["name"]: s for s in tracer.spans}
    assert set(by_name) == {_INTAKE, _EVIDENCE}
    assert by_name[_INTAKE]["kind"] == "extraction"
    assert by_name[_EVIDENCE]["kind"] == "evidence"
    for span in tracer.spans:
        assert span["parent"] == "supervisor"
        assert span["correlation_id"] == "cid-two"


def test_every_span_shares_the_turn_correlation_id():
    tracer = _RecordingTracer()
    _invoke(route=[_INTAKE, _EVIDENCE], tracer=tracer, cid="cid-recon")
    assert tracer.spans, "no worker spans recorded"
    assert {s["correlation_id"] for s in tracer.spans} == {"cid-recon"}


# --- 3. spans are entered AND exited around the tool call --------------------

def test_worker_span_is_opened_and_closed():
    tracer = _RecordingTracer()
    _invoke(route=[_INTAKE], tracer=tracer)
    assert tracer.events == [("open", _INTAKE), ("close", _INTAKE)]
    assert all(s["closed"] for s in tracer.spans)


def test_span_is_closed_even_when_the_worker_tool_raises():
    tracer = _RecordingTracer()
    try:
        _invoke(route=[_INTAKE], tracer=tracer, extractor=_Tool(boom=True))
    except Exception:
        pass  # the tool error propagates; we only care the span closed
    assert tracer.spans, "span should have opened before the tool ran"
    assert tracer.spans[0]["name"] == _INTAKE
    assert tracer.spans[0]["closed"] is True
    assert ("close", _INTAKE) in tracer.events
