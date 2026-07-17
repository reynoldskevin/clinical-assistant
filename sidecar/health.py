"""Liveness and readiness probes for the AI sidecar.

Liveness (`/health`) is unconditional: if `liveness()` runs, the process is
alive and answering, so it always reports ok. It says nothing about the health
of downstream dependencies.

Readiness (`/ready`) actually probes the meaningful boundaries — OpenEMR (the
chart-read boundary), the LLM provider (Anthropic), and the observability
backend (Braintrust) — and reports 503 when a required one is unreachable,
never an unconditional 200.

A 4xx/5xx response from a dependency counts as *reachable*: the server answered,
so the network path and the endpoint are up. For example, an unauthenticated GET
to OpenEMR's summary.php returns 401 — that 401 proves the boundary is up. Only
a connection-level failure (no route, refused, timeout) marks a dependency down.
"""
from __future__ import annotations

import urllib.error
import urllib.request
from typing import Callable, Optional

# Sentinel distinguishing an OMITTED qdrant_url (old callers -> no qdrant check)
# from a supplied-but-falsy value (None/"" -> a qdrant check reporting
# not_configured). None/"" are meaningful "configured-but-empty" states, so they
# cannot double as the "argument omitted" marker.
_UNSET = object()


def liveness() -> dict:
    """Unconditional liveness payload — if this runs, the process is alive."""
    return {"status": "ok", "service": "ai-sidecar"}


def http_reachable(url, opener=urllib.request.urlopen, headers=None, timeout=3.0) -> tuple[bool, str]:
    """Probe a URL; a server answer (incl. 4xx/5xx) counts as reachable."""
    try:
        request = urllib.request.Request(url, method="GET", headers=headers or {})
        with opener(request, timeout=timeout) as response:
            return True, f"http {getattr(response, 'status', 200)}"
    except urllib.error.HTTPError as e:
        return True, f"http {e.code}"   # server answered (4xx/5xx) => reachable
    except Exception:
        return False, "unreachable"


def build_readiness_checks(summary_url, anthropic_key, braintrust_key, opener, qdrant_url=_UNSET) -> dict:
    """Build zero-arg dependency checks, each returning (ok, detail).

    ``qdrant_url`` is opt-in via a sentinel default: an OMITTED argument adds no
    ``qdrant`` check (so existing three-dependency callers are unchanged), a
    supplied-but-falsy value reports ``not_configured`` (like ``observability``),
    and a truthy value is probed like the other boundaries.
    """
    def openemr() -> tuple[Optional[bool], str]:
        if not summary_url:
            return False, "not_configured"
        return http_reachable(summary_url, opener)

    def llm() -> tuple[Optional[bool], str]:
        return http_reachable(
            "https://api.anthropic.com/v1/models",
            opener,
            {"x-api-key": anthropic_key or "", "anthropic-version": "2023-06-01"},
        )

    if braintrust_key:
        def observability() -> tuple[Optional[bool], str]:
            return http_reachable(
                "https://api.braintrust.dev/v1/project?limit=1",
                opener,
                {"Authorization": f"Bearer {braintrust_key}"},
            )
    else:
        def observability() -> tuple[Optional[bool], str]:
            return (None, "not_configured")

    checks = {"openemr": openemr, "llm": llm, "observability": observability}

    if qdrant_url is not _UNSET:
        if qdrant_url:
            probe_url = qdrant_url.rstrip("/") + "/healthz"

            def qdrant() -> tuple[Optional[bool], str]:
                return http_reachable(probe_url, opener)
        else:
            def qdrant() -> tuple[Optional[bool], str]:
                return (None, "not_configured")

        checks["qdrant"] = qdrant

    return checks


def evaluate_readiness(checks) -> tuple[int, dict]:
    """Run checks; 503 if any check's ok is False (None does not fail readiness)."""
    results: dict = {}
    ready = True
    for name, check in checks.items():
        try:
            ok, detail = check()
        except Exception:
            ok, detail = False, "error"
        results[name] = {"ok": ok, "detail": detail}
        if ok is False:
            ready = False
    return (200 if ready else 503, {"ready": ready, "checks": results})


def ready_response(summary_url, anthropic_key, braintrust_key, opener, qdrant_url=_UNSET) -> tuple[int, dict]:
    """Build + evaluate the readiness checks in one call.

    ``qdrant_url`` threads through with the same sentinel default, so old 4-arg
    callers are unaffected.
    """
    return evaluate_readiness(
        build_readiness_checks(summary_url, anthropic_key, braintrust_key, opener, qdrant_url=qdrant_url)
    )
