"""The OE_AI_AGENT_MODEL override is honored by the live agent + extract builders.

Proves a deployment can switch Claude model tiers (e.g. to a faster one) with an
env var and no code change, and that unset preserves the historical Opus default.
"""
from server import _configured_model, default_agent_builder, default_extract_builder


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


def test_extract_builder_passes_env_model(monkeypatch):
    monkeypatch.setenv("OE_AI_AGENT_MODEL", "claude-haiku-4-5-20251001")

    captured = {}

    class _Boundary:
        def get_document(self, pid, document_id):
            return {"mimetype": "application/pdf", "document_data": "ZmFrZQ=="}

    def fake_message_creator(**kwargs):
        captured["model"] = kwargs.get("model")
        raise RuntimeError("stop after capturing the model")  # avoid a real parse

    import server as server_module
    monkeypatch.setattr(server_module, "build_chart_boundary", lambda url, jwt, **kw: _Boundary())

    fn = default_extract_builder("http://openemr/summary.php", fake_message_creator)
    try:
        fn(7, "tok", 12, "lab_pdf")
    except RuntimeError:
        pass
    assert captured["model"] == "claude-haiku-4-5-20251001"
