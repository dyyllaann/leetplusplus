"""Strict output schemas shared by all model clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Transcription -----------------------------------------------------------

class BBox(_Strict):
    """Box on Perceptron's normalized 0-1000 grid, origin top-left."""

    x1: int
    y1: int
    x2: int
    y2: int


class Line(_Strict):
    n: int = Field(description="1-based line number within the region")
    text: str = Field(description="Exact characters as written, errors included")
    low_confidence_chars: list[int] = Field(
        description="0-based indices into text of characters that are hard to read"
    )
    # Used to re-read only the lines that changed (backend/vision/localize.py).
    bbox: BBox | None = Field(default=None, description="Box around this written line")


class LineReading(_Strict):
    """Output of a single-line re-read from a cropped image."""

    text: str = Field(description="Exact characters as written, errors included; empty if blank")
    low_confidence_chars: list[int] = Field(
        description="0-based indices into text of characters that are hard to read"
    )


class Region(_Strict):
    id: str
    type: Literal["code", "diagram", "examples", "trace"]
    bbox: BBox
    lines: list[Line]


class Transcription(_Strict):
    regions: list[Region]


# Request schema used when LINE_PATCH=0: identical to the original format (no line boxes),
# so line-level updates can be fully switched off from .env. Parsed output is converted
# to Transcription with every line bbox set to None.
class LineNoBox(_Strict):
    n: int = Field(description="1-based line number within the region")
    text: str = Field(description="Exact characters as written, errors included")
    low_confidence_chars: list[int] = Field(
        description="0-based indices into text of characters that are hard to read"
    )


class RegionNoBox(_Strict):
    id: str
    type: Literal["code", "diagram", "examples", "trace"]
    bbox: BBox
    lines: list[LineNoBox]


class TranscriptionNoBox(_Strict):
    regions: list[RegionNoBox]


# --- Analysis ----------------------------------------------------------------

class Finding(_Strict):
    tier: Literal[1, 2, 3, 4] = Field(
        description="1 approach, 2 logic, 3 edge case, 4 syntax"
    )
    category: str
    line: int = Field(description="Line number in the region, or 0 if not line-specific")
    region_id: str
    confidence: float = Field(description="0.0 to 1.0")
    message: str


class Correction(_Strict):
    region_id: str
    line: int
    text: str = Field(description="The line exactly as written on the board, errors included")


class RegionRewrite(_Strict):
    region_id: str
    lines: list[str] = Field(description="Every line of the region exactly as written on the board")


class AnalysisResult(_Strict):
    findings: list[Finding]
    transcription_corrections: list[Correction] = Field(
        description="Lines where the image shows different characters than the transcription"
    )
    region_rewrites: list[RegionRewrite] = Field(
        description="Regions whose transcription invented or missed lines, rewritten in full"
    )


# --- Call metadata (not a model output) --------------------------------------

T = TypeVar("T", bound=BaseModel)


@dataclass
class ModelCall(Generic[T]):
    """One model request: parsed output plus what we need for scoring and logs."""

    provider: str
    model: str
    parsed: T | None
    latency_s: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    request: dict[str, Any] = field(default_factory=dict)
    response: Any = None
    error: str | None = None


def inline_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic JSON schema with $refs inlined and titles dropped.

    Some providers' strict modes do not resolve $ref, so we send a flat schema.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            out = {k: resolve(v) for k, v in node.items() if k not in ("title", "default")}
            if out.get("type") == "object" and "properties" in out:
                # Strict modes require every property listed; optional ones are nullable.
                out["required"] = list(out["properties"])
            return out
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)
