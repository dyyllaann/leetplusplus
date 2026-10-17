"""Problem bank lookup. data/problems.json is owned by the frontend; read only."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROBLEMS_PATH = Path(__file__).resolve().parents[1] / "data/problems.json"


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in json.loads(PROBLEMS_PATH.read_text())}


def get_problem(problem_id: str) -> dict[str, Any] | None:
    return _load().get(problem_id)


def problem_text(problem: dict[str, Any]) -> str:
    """Plain-text statement handed to the analyzer."""
    prompt = problem.get("prompt", {})
    parts = [problem.get("title", problem["id"]), prompt.get("description", "")]
    for ex in prompt.get("examples", []):
        parts.append(f"Example: {ex.get('input')} -> {ex.get('output')}")
    parts += [f"Constraint: {c}" for c in prompt.get("constraints", [])]
    return "\n".join(p for p in parts if p)
