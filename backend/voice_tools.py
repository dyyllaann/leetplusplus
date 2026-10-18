"""The voice agent's tools: declarations to register with the voice model, and their
backend execution. These four are the only tools allowed (CLAUDE.md invariants); none
of them can write or dictate code.

Wiring (voice layer): register TOOL_DECLARATIONS with the Gemini Live session. When the
model calls a tool, POST {"name": ..., "args": {...}} to /sessions/{id}/tools and return
the JSON response to the model as the tool result.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from backend import policy
from backend.session.state import Session

Broadcast = Callable[[dict[str, Any]], Awaitable[None]]

# JSON-schema style declarations (the shape Gemini function declarations use).
TOOL_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "ask_question",
        "description": "Ask the candidate one interview question. Plain language only; never "
                       "include code, a corrected line, or the solution.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "The question to ask."}},
            "required": ["text"]},
    },
    {
        "name": "point_to_region",
        "description": "Highlight a region of the whiteboard (and optionally one line) on the "
                       "candidate's screen while you talk about it.",
        "parameters": {"type": "object", "properties": {
            "region_id": {"type": "string", "description": "Region id from the board state, e.g. code_1."},
            "line": {"type": "integer", "description": "Line number in the region, or 0 for the whole region."}},
            "required": ["region_id"]},
    },
    {
        "name": "flag_error_type",
        "description": "Tell the candidate the CATEGORY of a problem at a location (e.g. "
                       "'off-by-one', 'wrong comparison') without saying how to fix it.",
        "parameters": {"type": "object", "properties": {
            "region_id": {"type": "string"},
            "line": {"type": "integer"},
            "category": {"type": "string", "description": "A short category name, not a fix."}},
            "required": ["region_id", "line", "category"]},
    },
    {
        "name": "give_hint",
        "description": "Request a hint. Level 1 = guiding question, 2 = names the concept, "
                       "3 = names the location. Higher levels unlock over time or when the "
                       "candidate explicitly asks; the backend may refuse. Follow the returned instruction.",
        "parameters": {"type": "object", "properties": {
            "level": {"type": "integer", "description": "1, 2, or 3."},
            "candidate_asked": {"type": "boolean",
                                "description": "True only if the candidate explicitly asked for a hint."}},
            "required": ["level"]},
    },
]

ALLOWED_TOOLS = {d["name"] for d in TOOL_DECLARATIONS}

_CODE_SIGNALS = [r"[{};]", r"=>", r"\breturn\b", r"\bdef\b", r"\bfor\s*\(", r"\bwhile\s*\(",
                 r"\w+\s*\(.*\)\s*[{:]", r"\n\s{2,}\S", r"\w+\[\w*\]\s*="]


def looks_like_code(text: str) -> bool:
    """Heuristic guard: two or more code signals means the text is dictating code."""
    return sum(bool(re.search(p, text)) for p in _CODE_SIGNALS) >= 2


def _region_ok(session: Session, region_id: str, line: int) -> str | None:
    regions = {r.id: r for r in (session.transcription.regions if session.transcription else [])}
    region = regions.get(region_id)
    if region is None:
        return f"unknown region {region_id!r}; known: {sorted(regions)}"
    if line and line not in {ln.n for ln in region.lines}:
        return f"{region_id} has no line {line}"
    return None


async def execute(session: Session, name: str, args: dict[str, Any], broadcast: Broadcast,
                  now: float | None = None) -> dict[str, Any]:
    now = time.monotonic() if now is None else now
    session.events.append({"type": "tool", "at": now, "name": name, "args": args})
    if name not in ALLOWED_TOOLS:
        return {"ok": False, "error": f"tool {name!r} is not allowed"}

    if name == "ask_question":
        text = str(args.get("text", ""))
        if looks_like_code(text):
            return {"ok": False, "error": "Rejected: questions must not contain code. Rephrase in plain words."}
        return {"ok": True, "instruction": "Ask the question now."}

    if name == "point_to_region":
        region_id, line = str(args.get("region_id", "")), int(args.get("line") or 0)
        if err := _region_ok(session, region_id, line):
            return {"ok": False, "error": err}
        await broadcast({"type": "highlight", "regionId": region_id, "line": line})
        return {"ok": True}

    if name == "flag_error_type":
        region_id, line = str(args.get("region_id", "")), int(args.get("line") or 0)
        category = str(args.get("category", "")).strip()
        if err := _region_ok(session, region_id, line):
            return {"ok": False, "error": err}
        if not category or len(category) > 40 or looks_like_code(category):
            return {"ok": False, "error": "category must be a short name (e.g. 'off-by-one'), not a fix"}
        await broadcast({"type": "highlight", "regionId": region_id, "line": line})
        return {"ok": True, "instruction": f"Say there is a {category} issue at line {line}. Do not state the fix."}

    # give_hint
    try:
        level = int(args.get("level", 1))
    except (TypeError, ValueError):
        return {"ok": False, "error": "level must be 1, 2, or 3"}
    result = policy.give_hint(session, level, bool(args.get("candidate_asked", False)), now)
    return {"ok": result["allowed"], **result}
