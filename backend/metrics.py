"""Latency metrics: one JSON line per measurement in logs/sessions/<id>/metrics.jsonl.

Metric names (all values in seconds, monotonic clock):
- board_to_display:  first frame that differed from the last analyzed frame -> new
                     transcription broadcast to the client.
- analyze_written:   analyzer call on the transcribed board (code written on the board).
- analyze_verbal:    brain call deciding how to respond to a candidate utterance.
- audio_response:    end of the candidate's utterance (or a policy release) -> first
                     interviewer audio chunk sent to the browser.
- brain_decision:    brain calls for other events (session start, policy releases).
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

METRICS_FILE = "metrics.jsonl"


def record(log_dir: Path, name: str, seconds: float, **fields: Any) -> dict[str, Any]:
    entry = {"metric": name, "seconds": round(seconds, 3), "at": time.time(), **fields}
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / METRICS_FILE).open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    logger.info("metric %s=%.2fs %s", name, seconds, fields or "")
    return entry


def load(log_dir: Path) -> list[dict[str, Any]]:
    path = log_dir / METRICS_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _percentile(sorted_values: list[float], q: float) -> float:
    i = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[i]


def summarize(entries: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """{metric: {count, mean, p50, p90, max}}."""
    by_name: dict[str, list[float]] = {}
    for e in entries:
        by_name.setdefault(e["metric"], []).append(e["seconds"])
    out = {}
    for name, values in sorted(by_name.items()):
        values.sort()
        out[name] = {"count": len(values), "mean": round(statistics.fmean(values), 3),
                     "p50": _percentile(values, 0.5), "p90": _percentile(values, 0.9),
                     "max": values[-1]}
    return out
