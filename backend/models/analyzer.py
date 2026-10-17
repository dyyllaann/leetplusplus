"""Logic analysis behind a swappable interface.

Every analyzer gets the same prompt, the same board image, and the same
transcription, and returns AnalysisResult findings plus call metadata.
"""

from __future__ import annotations

import base64
import time
from abc import ABC, abstractmethod
from typing import Any

from backend.models import perceptron_client
from backend.models.prompts import ANALYZE_SYSTEM, analyze_user
from backend.models.schemas import AnalysisResult, ModelCall, Transcription, inline_json_schema


def _dump(obj: Any) -> Any:
    return obj.model_dump(mode="json") if hasattr(obj, "model_dump") else repr(obj)


class Analyzer(ABC):
    name: str
    model: str

    @abstractmethod
    def analyze(self, image: bytes, mime: str, transcription: Transcription,
                problem: str) -> ModelCall[AnalysisResult]:
        """Findings for the current board state."""


class PerceptronAnalyzer(Analyzer):
    name = "perceptron"

    def __init__(self, model: str = perceptron_client.DEFAULT_MODEL,
                 reasoning_effort: str | None = "medium"):
        self.model = model
        self.reasoning_effort = reasoning_effort

    def analyze(self, image, mime, transcription, problem):
        return perceptron_client.structured_completion(
            system=ANALYZE_SYSTEM,
            user_text=analyze_user(problem, transcription.model_dump_json(indent=2)),
            image=image,
            mime=mime,
            schema_model=AnalysisResult,
            schema_name="analysis_result",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )


class GeminiAnalyzer(Analyzer):
    """Gemini via the google-genai Interactions API (ai.google.dev/api/interactions-api)."""

    name = "gemini"

    def __init__(self, model: str = "gemini-3.8-flash", thinking_level: str | None = "medium"):
        from google import genai

        self.model = model
        self.thinking_level = thinking_level
        # The SDK reads GEMINI_API_KEY from the environment.
        self.client = genai.Client()

    def analyze(self, image, mime, transcription, problem):
        user_text = analyze_user(problem, transcription.model_dump_json(indent=2))
        body: dict[str, Any] = {
            "model": self.model,
            "system_instruction": ANALYZE_SYSTEM,
            "input": [
                {"type": "text", "text": user_text},
                {"type": "image", "data": base64.b64encode(image).decode(), "mime_type": mime},
            ],
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": inline_json_schema(AnalysisResult),
            },
        }
        if self.thinking_level:
            body["generation_config"] = {"thinking_level": self.thinking_level}

        logged = {**body, "input": [body["input"][0], {"type": "image", "data": f"<{len(image)} bytes>", "mime_type": mime}]}
        call: ModelCall[AnalysisResult] = ModelCall(
            provider="gemini", model=self.model, parsed=None, latency_s=0.0, request=logged)
        start = time.perf_counter()
        try:
            interaction = self.client.interactions.create(**body)
            call.latency_s = time.perf_counter() - start
            call.response = _dump(interaction)
            usage = interaction.usage
            if usage is not None:
                call.input_tokens = usage.total_input_tokens
                # Count thinking as output so totals compare with Claude/Perceptron.
                call.output_tokens = (usage.total_output_tokens or 0) + (usage.total_thought_tokens or 0)
            call.parsed = AnalysisResult.model_validate_json(interaction.output_text)
        except Exception as exc:
            call.latency_s = call.latency_s or time.perf_counter() - start
            call.error = f"{type(exc).__name__}: {exc}"
        return call


class ClaudeAnalyzer(Analyzer):
    """Claude via the Anthropic SDK with structured outputs (messages.parse)."""

    name = "claude"

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium"):
        import anthropic

        self.model = model
        self.effort = effort
        self.client = anthropic.Anthropic()

    def analyze(self, image, mime, transcription, problem):
        user_text = analyze_user(problem, transcription.model_dump_json(indent=2))
        image_block = {"type": "image", "source": {
            "type": "base64", "media_type": mime, "data": base64.b64encode(image).decode()}}
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "system": ANALYZE_SYSTEM,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
            # Server-side refusal fallback, routed by refusal category.
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
        }
        logged_image = {**image_block, "source": {**image_block["source"], "data": f"<{len(image)} bytes>"}}
        call: ModelCall[AnalysisResult] = ModelCall(
            provider="claude", model=self.model, parsed=None, latency_s=0.0,
            request={**params, "messages": [{"role": "user", "content": [logged_image, {"type": "text", "text": user_text}]}],
                     "output_format": "AnalysisResult"})
        start = time.perf_counter()
        try:
            response = self.client.beta.messages.parse(
                **params,
                messages=[{"role": "user", "content": [image_block, {"type": "text", "text": user_text}]}],
                output_format=AnalysisResult,
            )
            call.latency_s = time.perf_counter() - start
            call.response = _dump(response)
            call.input_tokens = response.usage.input_tokens
            call.output_tokens = response.usage.output_tokens
            if response.stop_reason == "refusal":
                raise RuntimeError(f"refusal: {response.stop_details}")
            if response.stop_reason == "max_tokens":
                raise RuntimeError("stop_reason=max_tokens, output truncated")
            call.parsed = response.parsed_output
        except Exception as exc:
            call.latency_s = call.latency_s or time.perf_counter() - start
            call.error = f"{type(exc).__name__}: {exc}"
        return call


ANALYZERS: dict[str, type[Analyzer]] = {
    cls.name: cls for cls in (PerceptronAnalyzer, GeminiAnalyzer, ClaudeAnalyzer)
}


def get_analyzer(name: str, **kwargs) -> Analyzer:
    return ANALYZERS[name](**kwargs)
