"""The voice agent's only tools, executed by the backend.

Allowed tools (CLAUDE.md): ask_question, point_to_region, flag_error_type, give_hint.
None of them can write code. give_hint levels are enforced here, not by the model.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from backend.session.state import Session

Emit = Callable[[dict[str, Any]], Awaitable[None]]

ERROR_CATEGORIES = [
    "off_by_one", "wrong_comparison", "null_or_empty_input", "missing_state_update",
    "wrong_method", "wrong_data_structure", "wrong_complexity", "unhandled_duplicates", "syntax",
]

HINT_UNLOCK_SECONDS = 90.0
MAX_HINT_LEVEL = 3

FUNCTION_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "ask_question",
        "description": "Log a question for the session record. This does NOT speak: you must also "
                       "say the question aloud yourself. Never include code.",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    },
    {
        "name": "point_to_region",
        "description": "Highlight a board region (and optionally a line) for the candidate.",
        "parameters": {
            "type": "object",
            "properties": {"region_id": {"type": "string"}, "line": {"type": "integer"}},
            "required": ["region_id"],
        },
    },
    {
        "name": "flag_error_type",
        "description": "Tell the candidate which category of error is on a line, without the fix.",
        "parameters": {
            "type": "object",
            "properties": {
                "region_id": {"type": "string"},
                "line": {"type": "integer"},
                "category": {"type": "string", "enum": ERROR_CATEGORIES},
            },
            "required": ["region_id", "line", "category"],
        },
    },
    {
        "name": "give_hint",
        "description": "Request a hint. 1 = guiding question, 2 = names the concept, 3 = names the location. "
                       "The backend decides whether the level is available.",
        "parameters": {"type": "object", "properties": {"level": {"type": "integer"}}, "required": ["level"]},
    },
]


@dataclass
class HintLadder:
    """Level n+1 unlocks HINT_UNLOCK_SECONDS after level n was given, or immediately
    when the candidate explicitly asks for a hint."""

    unlocked: int = 1
    given_at: dict[int, float] = field(default_factory=dict)
    requested: bool = False

    def allowed(self, level: int, now: float) -> bool:
        if level < 1 or level > MAX_HINT_LEVEL:
            return False
        prev = level - 1
        timed = prev in self.given_at and now - self.given_at[prev] >= HINT_UNLOCK_SECONDS
        explicit = self.requested and prev in self.given_at
        return level <= self.unlocked or timed or explicit

    def give(self, level: int, now: float) -> None:
        self.given_at[level] = now
        self.unlocked = max(self.unlocked, level)
        self.requested = False


def hint_text(session: Session, level: int) -> str:
    """Hint content comes from the backend's current findings, never from the model."""
    open_findings = sorted(
        (t for t in session.findings if t.status != "resolved" and t.finding.tier < 4),
        key=lambda t: (t.finding.tier, -t.finding.confidence),
    )
    if not open_findings:
        return {1: "Ask what their code returns for the smallest possible input.",
                2: "Ask how they would test the code against each example.",
                3: "Ask them to trace their code line by line on the first example."}[level]
    f = open_findings[0].finding
    concept = f.category.replace("_", " ")
    if level == 1:
        return f"Ask them to walk you through line {f.line} with the first example." if f.line else \
            "Ask them to trace through the first example step by step."
    if level == 2:
        return f"Tell them the issue is related to: {concept}. Do not say where or how to fix it."
    return f"Tell them to look closely at line {f.line} ({concept}). Do not say how to fix it."


class VoiceTools:
    def __init__(self, session: Session, emit: Emit, clock: Callable[[], float]):
        self.session = session
        self.emit = emit
        self.clock = clock
        self.hints = HintLadder()

    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_{name}", None)
        if handler is None:
            return {"error": f"unknown tool {name!r}"}
        result = await handler(**args)
        self.session.tool_calls.append({"at": self.clock(), "name": name, "args": args, "result": result})
        return result

    async def _ask_question(self, text: str) -> dict[str, Any]:
        return {"ok": True, "note": "Logged only. Say the question aloud to the candidate now."}

    async def _point_to_region(self, region_id: str, line: int | None = None) -> dict[str, Any]:
        await self.emit({"type": "highlight", "regionId": region_id, "line": line or 0})
        return {"ok": True}

    async def _flag_error_type(self, region_id: str, line: int, category: str) -> dict[str, Any]:
        if category not in ERROR_CATEGORIES:
            return {"error": f"category must be one of {ERROR_CATEGORIES}"}
        await self.emit({"type": "highlight", "regionId": region_id, "line": line})
        return {"ok": True}

    async def _give_hint(self, level: int) -> dict[str, Any]:
        now = self.clock()
        if not self.hints.allowed(int(level), now):
            return {"hint": "not yet available"}
        self.hints.give(int(level), now)
        return {"hint": hint_text(self.session, int(level))}
