"""Gemini provider via the google-genai Interactions API (ai.google.dev/api/interactions-api)."""

from __future__ import annotations

import time
from typing import Any

from backend.models.providers import Provider, b64, check_effort, dump
from backend.models.schemas import ModelCall, inline_json_schema

# Gemini has no "off" for thinking, and gemini-3.8-flash rejects "minimal" (400), so
# "none" maps to the lowest level every current model accepts.
THINKING_LEVELS = {"none": "low", "low": "low", "medium": "medium", "high": "high"}
TIMEOUT_S = 180.0  # same as Perceptron; a stalled call otherwise holds the vision loop


class GeminiProvider(Provider):
    name = "gemini"
    default_model = "gemini-3.8-flash"

    def __init__(self) -> None:
        from google import genai

        self.client = genai.Client()  # reads GEMINI_API_KEY

    def structured(self, *, system, user_text, schema, schema_name, model, effort, max_tokens,
                   image=None, mime=None):
        parts: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        if image is not None:
            parts.insert(0, {"type": "image", "data": b64(image), "mime_type": mime})
        body: dict[str, Any] = {
            "model": model,
            "system_instruction": system,
            "input": parts,
            "response_format": {"type": "text", "mime_type": "application/json",
                                "schema": inline_json_schema(schema)},
            "generation_config": {"thinking_level": THINKING_LEVELS[check_effort(effort)],
                                  "max_output_tokens": max_tokens},
        }
        logged = {**body, "input": [{**p, "data": f"<{len(image)} bytes>"} if p["type"] == "image" else p
                                    for p in parts]}
        call: ModelCall = ModelCall(provider=self.name, model=model, parsed=None, latency_s=0.0,
                                    request=logged)
        start = time.perf_counter()
        try:
            interaction = self.client.interactions.create(**body, timeout=TIMEOUT_S)
            call.latency_s = time.perf_counter() - start
            call.response = dump(interaction)
            usage = interaction.usage
            if usage is not None:
                call.input_tokens = usage.total_input_tokens
                # Count thinking as output so totals compare with Claude/Perceptron.
                call.output_tokens = (usage.total_output_tokens or 0) + (usage.total_thought_tokens or 0)
            if interaction.status != "completed":
                raise RuntimeError(f"status={interaction.status!r}, output may be truncated")
            call.parsed = schema.model_validate_json(interaction.output_text)
        except Exception as exc:
            call.latency_s = call.latency_s or time.perf_counter() - start
            call.error = f"{type(exc).__name__}: {exc}"
        return call
