"""T81 acceptance tests (LOCKED) — live-eval harness fidelity (offline).

The live sweep (`python -m eval --live`) must drive the SAME agent the server
serves and authenticate its chart reads. These offline tests pin the two harness
fixes without a network or an API key: (1) the eval agent wires every production
tool, and (2) the boundary token minter produces a valid HS256 token matching
ScopedTokenService's claims. The end-to-end score against a seeded chart is a
separate LOCAL/manual step (evals/seed_eval_patient.sql), not a CI gate.
"""
import base64
import hashlib
import hmac
import json

import eval as E


# --- AC1: eval agent wires the full production tool set -----------------------

def test_eval_agent_wires_every_production_tool():
    # Build the tool set with fakes (no network, no key). Parity with
    # server.default_agent_builder: encounter, results, medications, search,
    # documents (list + get), get_intake_form, and evidence_retriever.
    class FakeChartBoundary:
        def __getattr__(self, _):
            return lambda *a, **k: []

    def fake_creator(**kwargs):
        raise AssertionError("message_creator must not be called during construction")

    class FakeObserver:
        def record_retrieval(self, *a, **k):
            pass

    tools = E.build_eval_agent_tools(FakeChartBoundary(), fake_creator, FakeObserver())
    names = {t["name"] for t in tools}

    # The two tools that were MISSING before the fix must now be present...
    assert "get_intake_form" in names
    assert "evidence_retriever" in names
    # ...alongside the original chart tools and the document tool.
    for required in (
        "list_encounters", "get_encounter", "get_results",
        "get_medications", "search_chart", "get_documents",
    ):
        assert required in names, f"missing production tool: {required}"
    # every tool is a well-formed spec
    for t in tools:
        assert callable(t["handler"]) and t["input_schema"]["type"] == "object"


# --- AC2: the eval boundary token is a valid HS256 JWT ------------------------

def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def test_mint_eval_jwt_is_a_valid_hs256_token_with_scoped_claims():
    key = "test-signing-key-000000000000000000000000000000000000000000000000"
    token = E.mint_eval_jwt(77, key, ttl_seconds=300)

    header_b64, payload_b64, sig_b64 = token.split(".")
    header = json.loads(_b64url_decode(header_b64))
    payload = json.loads(_b64url_decode(payload_b64))

    assert header == {"typ": "JWT", "alg": "HS256"}
    # Claims the app-side ScopedTokenService verifies.
    assert payload["aud"] == "oe-ai-agent-boundary"
    assert payload["pid"] == 77
    assert payload["scope"] == "read"
    assert payload["exp"] == payload["iat"] + 300
    assert payload["exp"] > payload["iat"]

    # The signature is a valid HMAC-SHA256 over "header.payload" with the key.
    expected = hmac.new(key.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    assert hmac.compare_digest(_b64url_decode(sig_b64), expected)


def test_mint_eval_jwt_binds_the_requested_pid():
    key = "k" * 64
    p1 = json.loads(_b64url_decode(E.mint_eval_jwt(1, key).split(".")[1]))
    p2 = json.loads(_b64url_decode(E.mint_eval_jwt(999, key).split(".")[1]))
    assert p1["pid"] == 1 and p2["pid"] == 999
