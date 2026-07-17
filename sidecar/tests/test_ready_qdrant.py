"""T58c acceptance tests (LOCKED) — /ready Qdrant dependency probe.

T58b added Qdrant as the sidecar's dense-store dependency. `/ready` must probe it
like the existing openemr/llm/observability checks, using the same injected-opener
contract (a 4xx/5xx answer counts as reachable; a connection failure as down).
Like `observability`, an UNSET `QDRANT_URL` reports `not_configured` — a `None`
ok that does NOT fail readiness — so the offline/demo deploy stays ready.

The qdrant check is opt-in via a new `qdrant_url` parameter so existing callers
(and the locked `test_health_ready.py`) keep the original three dependencies.

Deterministic — the HTTP probes take an injected opener; no sockets.
"""
from health import build_readiness_checks, ready_response


# --- fake openers (mirror test_health_ready.py) -------------------------------

class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok_opener(request, timeout=None):
    return _Resp(200)


def _down_opener(request, timeout=None):
    raise OSError("connection refused")


def _route_opener(down_substr):
    """Reachable for every URL except those containing down_substr."""
    def opener(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if down_substr in url:
            raise OSError("connection refused")
        return _Resp(200)
    return opener


QURL = "http://qdrant:6333"


# --- the check is opt-in and does not disturb the existing three --------------

def test_qdrant_check_is_present_when_a_url_argument_is_supplied():
    checks = build_readiness_checks("http://oe/summary.php", "sk-x", "bt-x", _ok_opener, qdrant_url=QURL)
    assert "qdrant" in checks
    # the original three remain
    assert {"openemr", "llm", "observability"} <= set(checks)


def test_omitting_the_qdrant_argument_keeps_the_original_three_dependencies():
    # Backward compatibility: callers that don't know about qdrant are unchanged.
    checks = build_readiness_checks("http://oe/summary.php", "sk-x", "bt-x", _ok_opener)
    assert set(checks) == {"openemr", "llm", "observability"}


# --- configured + reachable ---------------------------------------------------

def test_ready_when_qdrant_configured_and_reachable():
    status, body = ready_response("http://oe/summary.php", "sk-x", "bt-x", _ok_opener, qdrant_url=QURL)
    assert status == 200
    assert body["ready"] is True
    assert body["checks"]["qdrant"]["ok"] is True


# --- configured + unreachable -> 503, others unaffected -----------------------

def test_not_ready_when_qdrant_configured_but_unreachable():
    status, body = ready_response(
        "http://oe/summary.php", "sk-x", "bt-x", _route_opener("qdrant"), qdrant_url=QURL
    )
    assert status == 503
    assert body["ready"] is False
    assert body["checks"]["qdrant"]["ok"] is False
    # the connection failure is isolated to qdrant
    assert body["checks"]["openemr"]["ok"] is True
    assert body["checks"]["llm"]["ok"] is True
    assert body["checks"]["observability"]["ok"] is True


# --- unset -> not_configured, does NOT fail readiness -------------------------

def test_qdrant_unset_reports_not_configured_and_stays_ready():
    status, body = ready_response("http://oe/summary.php", "sk-x", "bt-x", _ok_opener, qdrant_url=None)
    assert status == 200
    assert body["ready"] is True
    assert body["checks"]["qdrant"]["ok"] is None
    assert "not_configured" in body["checks"]["qdrant"]["detail"]


def test_empty_qdrant_url_also_reports_not_configured():
    status, body = ready_response("http://oe/summary.php", "sk-x", "bt-x", _ok_opener, qdrant_url="")
    assert status == 200
    assert body["checks"]["qdrant"]["ok"] is None
    assert "not_configured" in body["checks"]["qdrant"]["detail"]
