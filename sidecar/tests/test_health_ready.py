"""T40 acceptance tests (LOCKED) — separate /health and /ready.

/health is liveness (the process answers -> alive). /ready actually probes the
meaningful dependencies (OpenEMR boundary, the LLM provider, the observability
backend) and returns 503 when a required one is unreachable — never an
unconditional 200. Deterministic — the HTTP probes take an injected opener, so no
real network is touched.
"""
import urllib.error

from health import (
    build_readiness_checks,
    evaluate_readiness,
    http_reachable,
    liveness,
    ready_response,
)


# --- fake openers -------------------------------------------------------------

class _Resp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok_opener(request, timeout=None):
    return _Resp(200)


def _down_opener(request, timeout=None):
    raise OSError("no route to host")


def _http401_opener(request, timeout=None):
    raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)


def _route_opener(down_substr):
    """An opener that is reachable for all URLs except those containing down_substr."""
    def opener(request, timeout=None):
        if down_substr in request.full_url:
            raise OSError("unreachable")
        return _Resp(200)
    return opener


# --- liveness -----------------------------------------------------------------

def test_liveness_reports_alive():
    body = liveness()
    assert isinstance(body, dict)
    assert body.get("status") == "ok"


# --- http_reachable -----------------------------------------------------------

def test_http_reachable_true_when_server_responds():
    ok, _ = http_reachable("http://x/summary.php", _ok_opener)
    assert ok is True


def test_http_reachable_true_on_http_error_because_server_answered():
    ok, _ = http_reachable("http://x/summary.php", _http401_opener)
    assert ok is True   # a 401 means the server is up and answering


def test_http_reachable_false_on_connection_error():
    ok, detail = http_reachable("http://x/summary.php", _down_opener)
    assert ok is False
    assert "unreachable" in detail.lower()


# --- build_readiness_checks ---------------------------------------------------

def test_build_checks_has_the_three_dependencies():
    checks = build_readiness_checks("http://oe/summary.php", "sk-x", "bt-x", _ok_opener)
    assert set(checks) == {"openemr", "llm", "observability"}


def test_observability_is_skipped_when_braintrust_not_configured():
    checks = build_readiness_checks("http://oe/summary.php", "sk-x", None, _ok_opener)
    ok, detail = checks["observability"]()
    assert ok is None
    assert "not_configured" in detail


# --- ready_response (build + evaluate) ----------------------------------------

def test_ready_when_all_dependencies_reachable():
    status, body = ready_response("http://oe/summary.php", "sk-x", "bt-x", _ok_opener)
    assert status == 200
    assert body["ready"] is True
    assert body["checks"]["openemr"]["ok"] is True
    assert body["checks"]["llm"]["ok"] is True
    assert body["checks"]["observability"]["ok"] is True


def test_not_ready_when_openemr_unreachable():
    status, body = ready_response("http://oe/summary.php", "sk-x", "bt-x", _route_opener("summary.php"))
    assert status == 503
    assert body["ready"] is False
    assert body["checks"]["openemr"]["ok"] is False
    assert body["checks"]["llm"]["ok"] is True


def test_not_ready_when_observability_configured_but_unreachable():
    status, body = ready_response("http://oe/summary.php", "sk-x", "bt-x", _route_opener("braintrust"))
    assert status == 503
    assert body["ready"] is False
    assert body["checks"]["observability"]["ok"] is False


def test_ready_when_observability_not_configured():
    status, body = ready_response("http://oe/summary.php", "sk-x", None, _ok_opener)
    assert status == 200
    assert body["ready"] is True
    assert body["checks"]["observability"]["ok"] is None


def test_not_ready_when_llm_unreachable():
    status, body = ready_response("http://oe/summary.php", "sk-x", "bt-x", _route_opener("anthropic"))
    assert status == 503
    assert body["checks"]["llm"]["ok"] is False
