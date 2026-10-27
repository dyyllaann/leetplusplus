"""Claude provider via the Anthropic SDK with structured outputs (messages.parse)."""

from __future__ import annotations

import time
from typing import Any

from backend.models.providers import Provider, b64, check_effort, dump
from backend.models.schemas import ModelCall


class ClaudeProvider(Provider):
    name = "claude"
    default_model = "claude-opus-5-5"

    def __init__(self) -> None:
        import anthropic

        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    def structured(self, *, system, user_text, schema, schema_name, model, effort, max_tokens,
                   image=None, mime=None):
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        if image is not None:
            content.insert(0, {"type": "image", "source": {
                "type": "base64", "media_type": mime, "data": b64(image)}})
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            # Server-side refusal fallback, routed by refusal category.
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
        }
        if check_effort(effort) == "none":
            params["thinking"] = {"type": "disabled"}
        else:
            params["thinking"] = {"type": "adaptive"}
            params["output_config"] = {"effort": effort}
        logged = [{**c, "source": {**c["source"], "data": f"<{len(image)} bytes>"}} if c["type"] == "image" else c
                  for c in content]
        call: ModelCall = ModelCall(
            provider=self.name, model=model, parsed=None, latency_s=0.0,
            request={**params, "messages": [{"role": "user", "content": logged}],
                     "output_format": schema.__name__})
        start = time.perf_counter()
        try:
            response = self.client.beta.messages.parse(
                **params, messages=[{"role": "user", "content": content}], output_format=schema)
            call.latency_s = time.perf_counter() - start
            call.response = dump(response)
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
