"""Thin HTTP client for Perceptron's chat completions API.

Request format per docs.perceptron.inc (perceptron-mk1.5 API reference):
POST https://api.perceptron.inc/v1/chat/completions, Bearer auth, OpenAI-style
messages, image_url parts accept base64 data URLs, response_format json_schema.
"""

from __future__ import annotations

import base64
import os
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from backend.models.schemas import ModelCall, inline_json_schema

BASE_URL = "https://api.perceptron.inc/v1"
DEFAULT_MODEL = "perceptron-mk1.5"

T = TypeVar("T", bound=BaseModel)

# One shared client keeps the TLS connection open between calls (saves a handshake per pass).
_http: httpx.Client | None = None


def http() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client(timeout=180.0)
    return _http


def data_url(image: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(image).decode()}"


def redact_images(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy of a request with base64 image data replaced by its length, for logs."""
    out = {**payload, "messages": []}
    for msg in payload["messages"]:
        content = msg["content"]
        if isinstance(content, list):
            content = [
                {"type": "image_url", "image_url": {"url": f"<data url, {len(p['image_url']['url'])} chars>"}}
                if p.get("type") == "image_url" else p
                for p in content
            ]
        out["messages"].append({**msg, "content": content})
    return out


def structured_completion(
    *,
    system: str,
    user_text: str,
    image: bytes | None = None,
    mime: str | None = None,
    schema_model: type[T],
    schema_name: str,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str | None = None,
    max_completion_tokens: int = 8192,
    timeout_s: float = 180.0,
) -> ModelCall[T]:
    if image is not None and mime is None:
        raise ValueError("mime is required when image is provided")
    user_content: str | list[dict[str, Any]] = user_text
    if image is not None:
        user_content = [
            {"type": "image_url", "image_url": {"url": data_url(image, mime)}},
            {"type": "text", "text": user_text},
        ]
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": inline_json_schema(schema_model),
            },
        },
        "max_completion_tokens": max_completion_tokens,
        "temperature": 0,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    call: ModelCall[T] = ModelCall(
        provider="perceptron", model=model, parsed=None, latency_s=0.0,
        request=redact_images(payload),
    )
    headers = {"Authorization": f"Bearer {os.environ['PERCEPTRON_API_KEY']}"}
    start = time.perf_counter()
    try:
        resp = http().post(f"{BASE_URL}/chat/completions", json=payload,
                           headers=headers, timeout=timeout_s)
        call.latency_s = time.perf_counter() - start
        call.response = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        resp.raise_for_status()
        body = call.response
        usage = body.get("usage") or {}
        call.input_tokens = usage.get("prompt_tokens")
        call.output_tokens = usage.get("completion_tokens")
        choice = body["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise RuntimeError(f"finish_reason={choice.get('finish_reason')!r}, output may be truncated")
        call.parsed = schema_model.model_validate_json(choice["message"]["content"])
    except Exception as exc:  # recorded, not raised: one bad candidate should not stop the run
        call.latency_s = call.latency_s or time.perf_counter() - start
        call.error = f"{type(exc).__name__}: {exc}"
    return call
