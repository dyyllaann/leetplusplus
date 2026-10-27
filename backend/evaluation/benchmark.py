"""Transcriber benchmark: run candidates over fixtures and aggregate scores.

A fixture is an image plus <name>.expected.json (see fixtures/whiteboard_1.expected.json):
code lines as written, preserve_checks for the bugs that must survive, and approx_bbox
for each region. CLI: scripts/benchmark_transcribers.py.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from backend.evaluation.scoring import code_box_iou, line_box_coverage, score_transcription
from backend.models.schemas import ModelCall, Transcription


@dataclass(frozen=True)
class Spec:
    """One candidate: "provider[:model[:effort]]", e.g. "gemini:gemini-3.8-flash:low"."""

    provider: str
    model: str | None = None
    effort: str = "low"

    @classmethod
    def parse(cls, text: str) -> "Spec":
        provider, model, effort = (text.split(":") + ["", ""])[:3]
        return cls(provider.strip(), model.strip() or None, effort.strip() or "low")

    @property
    def label(self) -> str:
        return ":".join(p for p in (self.provider, self.model or "", self.effort) if p)


@dataclass
class Fixture:
    name: str
    image: Path
    expected: dict[str, Any]


def load_fixtures(directory: Path, root: Path) -> list[Fixture]:
    out = []
    for path in sorted(directory.glob("*.expected.json")):
        expected = json.loads(path.read_text())
        image = root / expected["image"] if "image" in expected else path.with_name(
            path.name.replace(".expected.json", ".png"))
        out.append(Fixture(path.name.removesuffix(".expected.json"), image, expected))
    return out


@dataclass
class RunScore:
    fixture: str
    latency_s: float
    output_tokens: int | None
    error: str | None = None
    char_accuracy: float | None = None
    bugs_kept: int = 0
    bugs_total: int = 0
    corrected: list[str] = field(default_factory=list)  # preserve checks the model "fixed"
    box_iou: float | None = None
    line_boxes: float | None = None


def score_run(fixture: Fixture, call: ModelCall[Transcription],
              transcription: Transcription | None) -> RunScore:
    run = RunScore(fixture.name, call.latency_s, call.output_tokens, call.error)
    if transcription is None:
        run.error = run.error or "no transcription"
        return run
    s = score_transcription(transcription, fixture.expected)
    run.char_accuracy = s.char_accuracy
    run.bugs_kept, run.bugs_total = len(s.preserved), len(s.preserved) + len(s.missing)
    run.corrected = s.fixed
    run.box_iou = code_box_iou(transcription, fixture.expected)
    run.line_boxes = line_box_coverage(transcription)
    return run


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.fmean(present) if present else None


def aggregate(runs: list[RunScore]) -> dict[str, Any]:
    ok = [r for r in runs if r.error is None]
    latencies = sorted(r.latency_s for r in ok)
    return {
        "runs": len(runs),
        "errors": len(runs) - len(ok),
        "char_accuracy": _mean([r.char_accuracy for r in ok]),
        "bugs_kept": sum(r.bugs_kept for r in ok),
        "bugs_total": sum(r.bugs_total for r in ok),
        # Any correction breaks the literal-transcription invariant.
        "corrected_runs": sum(1 for r in ok if r.corrected),
        "box_iou": _mean([r.box_iou for r in ok]),
        "line_boxes": _mean([r.line_boxes for r in ok]),
        "latency_p50": latencies[len(latencies) // 2] if latencies else None,
        "latency_max": latencies[-1] if latencies else None,
        "output_tokens": _mean([r.output_tokens for r in ok]),
        "details": [asdict(r) for r in runs],
    }
