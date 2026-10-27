"""Model providers: one structured-output call per provider, shared by every role.

A provider handles transport only (auth, image encoding, JSON schema, usage, errors).
Roles (transcriber.py, analyzer.py) own the prompts and schemas and pick a provider by
config, so adding a new model is one file here plus a PROVIDERS entry.

Effort is one provider-neutral setting: "none" | "low" | "medium" | "high". Each provider
maps it to its own knob (Perceptron reasoning_effort, Gemini thinking_level, Claude effort).
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel

from backend.models.schemas import ModelCall

T = TypeVar("T", bound=BaseModel)

EFFORTS = ("none", "low", "medium", "high")


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def dump(obj: Any) -> Any:
    return obj.model_dump(mode="json") if hasattr(obj, "model_dump") else repr(obj)


class Provider(ABC):
    name: str
    default_model: str

    @abstractmethod
    def structured(self, *, system: str, user_text: str, schema: type[T], schema_name: str,
                   model: str, effort: str, max_tokens: int,
                   image: bytes | None = None, mime: str | None = None) -> ModelCall[T]:
        """One request returning `schema`. Errors are recorded on the ModelCall, not raised."""


def _registry() -> dict[str, type[Provider]]:
    from backend.models.providers.claude import ClaudeProvider
    from backend.models.providers.gemini import GeminiProvider
    from backend.models.providers.perceptron import PerceptronProvider

    return {p.name: p for p in (PerceptronProvider, GeminiProvider, ClaudeProvider)}


PROVIDER_NAMES = ("perceptron", "gemini", "claude")
_instances: dict[str, Provider] = {}


def get_provider(name: str) -> Provider:
    """Shared instance per provider, so SDK clients and HTTP connections are reused."""
    if name not in _instances:
        providers = _registry()
        if name not in providers:
            raise ValueError(f"unknown provider {name!r}; choose from {sorted(providers)}")
        _instances[name] = providers[name]()
    return _instances[name]


def check_effort(effort: str) -> str:
    if effort not in EFFORTS:
        raise ValueError(f"effort must be one of {EFFORTS}, got {effort!r}")
    return effort
