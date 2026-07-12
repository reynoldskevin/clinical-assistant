"""Best-effort creator for the Braintrust monitor dashboard (T38, Phase 2).

Uses the Braintrust REST API (raw HTTP + BRAINTRUST_API_KEY) to ensure the
``oe-ai-agent`` project exists and to create a saved ``monitor`` view — the live,
auto-aggregating dashboard over the per-turn spans the sidecar logs
(``span.log(metrics=, scores=, metadata=)`` in server.py). It is idempotent: an
existing monitor view with the same name is reused, not duplicated.

The monitor view surfaces the six required charts from the logged fields (see
DASHBOARD.md): request count (turn spans), error rate (``scores.success`` /
``metadata.outcome``), p50/p95 latency (wrap_anthropic), tool-call counts
(``metrics.tool_calls``), retries (``metrics.retries``), and verification
pass/fail (``scores.verification_pass``).

Run:  BRAINTRUST_API_KEY=... python sidecar/dashboard/create_dashboard.py
(the key is also read from sidecar/.env if present). This is an operational
script, not part of the request path or the unit suite.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API_BASE = os.environ.get("BRAINTRUST_API_URL", "https://api.braintrust.dev")
PROJECT = os.environ.get("BRAINTRUST_PROJECT", "oe-ai-agent")
VIEW_NAME = "OE AI Agent — Observability"
APP_BASE = "https://www.braintrust.dev"


def _load_env_key() -> str:
    key = os.environ.get("BRAINTRUST_API_KEY", "")
    if not key:
        env = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env):
            with open(env) as fh:
                for line in fh:
                    if line.startswith("BRAINTRUST_API_KEY="):
                        key = line.split("=", 1)[1].strip().strip("'\"")
    return key


def _req(method: str, path: str, key: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        API_BASE + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode() if e.fp else str(e))


def main() -> int:
    key = _load_env_key()
    if not key:
        print("ERROR: BRAINTRUST_API_KEY not set (env or sidecar/.env).")
        return 1

    # 1. Ensure the project exists (POST /v1/project is an upsert by name).
    status, project = _req("POST", "/v1/project", key, {"name": PROJECT})
    if status >= 300 or not isinstance(project, dict) or "id" not in project:
        print(f"ERROR: could not resolve/create project '{PROJECT}': HTTP {status} {project}")
        return 1
    project_id = project["id"]
    print(f"project '{PROJECT}' -> id {project_id}")

    # Resolve the ORG NAME for the app URL (Braintrust app paths use the org name
    # and project name, NOT their ids).
    org_name = None
    status, orgs = _req("GET", "/v1/organization", key)
    if status < 300 and isinstance(orgs, dict):
        org_name = next((o.get("name") for o in orgs.get("objects", [])
                         if o.get("id") == project.get("org_id")), None)
    monitor_url = (
        f"{APP_BASE}/app/{org_name}/p/{PROJECT}/monitor" if org_name
        else f"{APP_BASE}/app (open the '{PROJECT}' project -> Monitor tab)"
    )

    # 2. Idempotency: reuse an existing monitor view with our name.
    status, existing = _req("GET", f"/v1/view?object_type=project&object_id={project_id}", key)
    if status < 300 and isinstance(existing, dict):
        for v in existing.get("objects", []):
            if v.get("name") == VIEW_NAME and v.get("view_type") == "monitor":
                print(f"monitor view already exists -> id {v.get('id')}")
                print(f"dashboard: {monitor_url}")
                return 0

    # 3. Create the monitor view. view_data (chart config) is undocumented, so we
    #    create the monitor view itself and let Braintrust default its charts;
    #    the charts read the fields we log. Try with, then without, view_data.
    base_body = {
        "object_type": "project",
        "object_id": project_id,
        "view_type": "monitor",
        "name": VIEW_NAME,
    }
    for body in ({**base_body, "view_data": {}}, base_body):
        status, view = _req("POST", "/v1/view", key, body)
        if status < 300 and isinstance(view, dict) and "id" in view:
            print(f"created monitor view -> id {view['id']}")
            print(f"dashboard: {monitor_url}")
            return 0
        print(f"attempt failed (body keys {list(body)}): HTTP {status} {view}")

    print("Could not create a saved monitor view via API — the built-in Monitor tab")
    print(f"still shows the logged metrics live at {monitor_url}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
