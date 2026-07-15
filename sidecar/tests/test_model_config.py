"""The OE_AI_AGENT_MODEL override is honored by the live agent + extract builders.

Proves a deployment can switch Claude model tiers (e.g. to a faster one) with an
env var and no code change, and that unset preserves the historical Opus default.

The document extractor is deliberately decoupled: it follows OE_AI_AGENT_EXTRACT_MODEL
(default Opus), NOT the chat-loop OE_AI_AGENT_MODEL — a fast chat tier must never
weaken the strict-contract VLM extraction.
"""
from server import (
    _configured_model,
    _extract_model,
    default_agent_builder,
    default_extract_builder,
)


def test_default_model_is_opus_when_unset(monkeypatch):
    monkeypatch.delenv("OE_AI_AGENT_MODEL", raising=False)
    assert _configured_model() == "claude-opus-4-8"


def test_env_overrides_model(monkeypatch):
    monkeypatch.setenv("OE_AI_AGENT_MODEL", "claude-haiku-4-5-20251001")
    assert _configured_model() == "claude-haiku-4-5-20251001"


def test_agent_builder_applies_env_model(monkeypatch):
    monkeypatch.setenv("OE_AI_AGENT_MODEL", "claude-haiku-4-5-20251001")
    # No network at construction: build_boundary just wraps the url/jwt.
    agent = default_agent_builder("http://openemr/summary.php", object())(7, "tok")
    assert agent._model == "claude-haiku-4-5-20251001"


def test_agent_builder_defaults_to_opus(monkeypatch):
    monkeypatch.delenv("OE_AI_AGENT_MODEL", raising=False)
    agent = default_agent_builder("http://openemr/summary.php", object())(7, "tok")
    assert agent._model == "claude-opus-4-8"


def test_extract_model_defaults_to_opus_regardless_of_chat_model(monkeypatch):
    # A fast chat tier must NOT drag the extractor down with it.
    monkeypatch.setenv("OE_AI_AGENT_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.delenv("OE_AI_AGENT_EXTRACT_MODEL", raising=False)
    assert _extract_model() == "claude-opus-4-8"


def test_extract_model_env_override(monkeypatch):
    monkeypatch.setenv("OE_AI_AGENT_EXTRACT_MODEL", "claude-sonnet-4-6")
    assert _extract_model() == "claude-sonnet-4-6"


def _capture_extract_model(monkeypatch, build):
    """Run ``build`` (agent or extract builder) once and return the model the VLM saw."""
    captured = {}

    class _Boundary:
        def get_documents(self, pid):
            return [{"id": 12, "doc_type": "intake_form"}]

        def get_document(self, pid, document_id):
            return {"mimetype": "application/pdf", "document_data": "ZmFrZQ=="}

    def fake_message_creator(**kwargs):
        captured["model"] = kwargs.get("model")
        raise RuntimeError("stop after capturing the model")  # avoid a real parse

    import server as server_module
    monkeypatch.setattr(server_module, "build_chart_boundary", lambda url, jwt, **kw: _Boundary())
    try:
        build(fake_message_creator, _Boundary())
    except RuntimeError:
        pass
    return captured.get("model")


def test_extract_builder_uses_extract_model_not_chat_model(monkeypatch):
    # Chat model is Haiku, but /extract must still run on the capable Opus default.
    monkeypatch.setenv("OE_AI_AGENT_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.delenv("OE_AI_AGENT_EXTRACT_MODEL", raising=False)

    def build(message_creator, _boundary):
        fn = default_extract_builder("http://openemr/summary.php", message_creator)
        fn(7, "tok", 12, "lab_pdf")

    assert _capture_extract_model(monkeypatch, build) == "claude-opus-4-8"


def test_intake_tool_uses_extract_model_not_chat_model(monkeypatch):
    # The /ask get_intake_form tool runs the VLM mid-turn — it too must use the
    # capable extraction model even when the chat loop is on a fast tier.
    monkeypatch.setenv("OE_AI_AGENT_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.delenv("OE_AI_AGENT_EXTRACT_MODEL", raising=False)

    def build(message_creator, boundary):
        agent = default_agent_builder("http://openemr/summary.php", message_creator)(7, "tok")
        intake = next(t for t in agent._extra_tools if t["name"] == "get_intake_form")
        intake["handler"](7, {})

    assert _capture_extract_model(monkeypatch, build) == "claude-opus-4-8"
