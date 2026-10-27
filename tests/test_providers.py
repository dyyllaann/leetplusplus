"""Provider request building and response handling, with fake SDK/HTTP clients (no network)."""

from types import SimpleNamespace

import pytest

from backend import config, pipeline
from backend.models import providers
from backend.models.analyzer import Analyzer, get_analyzer
from backend.models.providers import claude, gemini, perceptron
from backend.models.schemas import LineReading
from backend.models.transcriber import Transcriber, get_transcriber

READING = '{"text": "x = 1", "low_confidence_chars": []}'


def call(provider, effort="low", image=b"img"):
    return provider.structured(system="sys", user_text="read it", schema=LineReading,
                               schema_name="line_reading", model="m", effort=effort,
                               max_tokens=9999, image=image, mime="image/png" if image else None)


class FakeInteractions:
    def __init__(self, status="completed"):
        self.status = status
        self.body = None

    def create(self, **body):
        self.body = body
        usage = SimpleNamespace(total_input_tokens=10, total_output_tokens=5, total_thought_tokens=3)
        return SimpleNamespace(status=self.status, output_text=READING, usage=usage)


def gemini_provider(status="completed"):
    p = object.__new__(gemini.GeminiProvider)
    p.client = SimpleNamespace(interactions=FakeInteractions(status))
    return p


def test_gemini_maps_effort_and_parses_output():
    p = gemini_provider()
    c = call(p, effort="none")
    body = p.client.interactions.body
    assert body["generation_config"] == {"thinking_level": "low", "max_output_tokens": 9999}
    assert [part["type"] for part in body["input"]] == ["image", "text"]
    assert c.parsed.text == "x = 1" and c.output_tokens == 8 and c.error is None
    assert "bytes>" in c.request["input"][0]["data"]  # image redacted from the log


def test_gemini_incomplete_status_is_an_error():
    c = call(gemini_provider(status="incomplete"))
    assert c.parsed is None and "incomplete" in c.error


class FakeMessages:
    def __init__(self):
        self.params = None

    def parse(self, **params):
        self.params = params
        usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        return SimpleNamespace(stop_reason="end_turn", usage=usage,
                               parsed_output=LineReading.model_validate_json(READING))


def claude_provider():
    p = object.__new__(claude.ClaudeProvider)
    p.client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages()))
    return p


def test_claude_maps_effort_and_omits_image_when_absent():
    p = claude_provider()
    c = call(p, effort="high", image=None)
    params = p.client.beta.messages.params
    assert params["thinking"] == {"type": "adaptive"} and params["output_config"] == {"effort": "high"}
    assert [b["type"] for b in params["messages"][0]["content"]] == ["text"]
    assert c.parsed.text == "x = 1"

    call(p, effort="none")
    params = p.client.beta.messages.params
    assert params["thinking"] == {"type": "disabled"} and "output_config" not in params


def test_perceptron_maps_effort_and_caps_tokens(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return "call"

    monkeypatch.setattr(perceptron, "structured_completion", fake)
    assert call(perceptron.PerceptronProvider(), effort="none") == "call"
    assert seen["reasoning_effort"] is None and seen["max_completion_tokens"] == perceptron.MAX_OUTPUT_TOKENS
    call(perceptron.PerceptronProvider(), effort="medium")
    assert seen["reasoning_effort"] == "medium"


def test_unknown_provider_and_effort_are_rejected():
    with pytest.raises(ValueError, match="unknown provider"):
        providers.get_provider("nope")
    with pytest.raises(ValueError, match="effort"):
        Transcriber(perceptron.PerceptronProvider(), effort="max")


def test_config_picks_provider_model_and_effort(monkeypatch):
    monkeypatch.setitem(providers._instances, "gemini", gemini_provider())
    monkeypatch.setitem(providers._instances, "perceptron", perceptron.PerceptronProvider())
    monkeypatch.setattr(config, "TRANSCRIBER", "gemini")
    monkeypatch.setattr(config, "TRANSCRIBER_MODEL", "")
    monkeypatch.setattr(config, "TRANSCRIBER_EFFORT", "medium")
    monkeypatch.setattr(config, "ANALYZER", "perceptron")
    monkeypatch.setattr(config, "ANALYZER_MODEL", "perceptron-test")
    monkeypatch.setattr(pipeline, "_transcriber", None)
    monkeypatch.setattr(pipeline, "_analyzer", None)

    t, a = pipeline.models()
    assert (t.name, t.model, t.effort) == ("gemini", "gemini-3.8-flash", "medium")
    assert (a.name, a.model, a.effort) == ("perceptron", "perceptron-test", "medium")


def test_roles_share_one_provider_instance(monkeypatch):
    monkeypatch.setitem(providers._instances, "gemini", gemini_provider())
    assert get_transcriber("gemini").provider is get_analyzer("gemini").provider
    assert isinstance(get_analyzer("gemini"), Analyzer)
