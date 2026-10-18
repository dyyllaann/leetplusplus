"""Interjection policy and hint ladder. Plain rules, no model calls.

The voice agent never decides on its own what to say about a finding. It asks the backend
(POST /sessions/{id}/interjection) whenever it could speak, and the policy returns at most
one finding to raise, phrased as an instruction that never contains the fix.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from backend.session.state import Session, TrackedFinding

CONFIDENCE_THRESHOLD = float(os.getenv("POLICY_CONFIDENCE_THRESHOLD", "0.6"))
COOLDOWN_SECONDS = float(os.getenv("POLICY_COOLDOWN_SECONDS", "20"))
# After raising a finding, give the candidate this long to respond before raising another.
RELEASE_HOLD_SECONDS = float(os.getenv("POLICY_RELEASE_HOLD_SECONDS", "60"))
HINT_UNLOCK_SECONDS = float(os.getenv("HINT_UNLOCK_SECONDS", "90"))
MAX_HINT_LEVEL = 3

Phase = Literal["clarifying", "writing", "tracing", "done"]
PHASES: tuple[str, ...] = ("clarifying", "writing", "tracing", "done")


@dataclass
class Release:
    finding_id: str
    region_id: str
    line: int
    tier: int
    category: str
    mode: Literal["statement", "question"]
    instruction: str

    def as_json(self) -> dict[str, Any]:
        return {"findingId": self.finding_id, "regionId": self.region_id, "line": self.line,
                "tier": self.tier, "category": self.category, "mode": self.mode,
                "instruction": self.instruction}


def _where(t: TrackedFinding) -> str:
    f = t.finding
    return f"line {f.line} of {f.region_id}" if f.line else f.region_id


def _instruction(t: TrackedFinding, mode: str) -> str:
    """What the voice agent should do. Built from location and category only:
    the finding's message may name the fix, so it is never passed on."""
    where = _where(t)
    if mode == "question":
        return (f"Ask the candidate to walk you through {where} and explain what it does. "
                "Do not say there is a problem and do not suggest any change.")
    if t.finding.tier == 1:
        return ("Ask the candidate to state the time complexity of their approach and whether "
                "it meets the problem's constraints. Do not name a better approach.")
    if t.finding.tier == 3:
        return (f"Ask the candidate what happens at {where} for an edge-case input "
                f"(related to: {t.finding.category}). Do not give the answer.")
    return (f"Point the candidate to {where} with point_to_region and say there may be a "
            f"{t.finding.category} issue there. Ask them to trace that line. Do not state the fix.")


def _eligible(t: TrackedFinding, session: Session) -> bool:
    tier = t.finding.tier
    if tier == 4:
        return False  # syntax: report only
    if tier == 1:
        return True  # approach: interrupt early
    if tier == 2:
        # Logic: only once the board has settled and findings match the current text.
        return session.board_stable and not session.analysis_pending and not session.transcribing
    return session.phase in ("tracing", "done")  # tier 3: edge cases during trace or at end


def next_release(session: Session, now: float) -> Release | None:
    """Pick at most one finding to raise now, or None. Marks it released."""
    if now - session.last_release_at < COOLDOWN_SECONDS:
        return None
    for t in session.findings:
        if t.status == "released" and now - t.released_at < RELEASE_HOLD_SECONDS:
            return None  # one interruption at a time

    open_findings = [t for t in session.findings if t.status in ("new", "queued")]
    for t in open_findings:
        if t.status == "new" and t.finding.tier != 4:
            t.status = "queued"
    candidates = [t for t in open_findings if _eligible(t, session)]
    if not candidates:
        return None
    best = min(candidates, key=lambda t: (t.finding.tier, -t.finding.confidence, t.first_seen_pass))
    mode = "question" if best.finding.confidence < CONFIDENCE_THRESHOLD else "statement"
    best.status = "released"
    best.released_at = now
    session.last_release_at = now
    release = Release(best.id, best.finding.region_id, best.finding.line, best.finding.tier,
                      best.finding.category, mode, _instruction(best, mode))
    session.events.append({"type": "interjection", "at": now, **release.as_json()})
    return release


# --- Hint ladder ---------------------------------------------------------------

def unlocked_level(session: Session, now: float) -> int:
    """Highest hint level currently allowed. Level 1 is always available; each further
    level unlocks HINT_UNLOCK_SECONDS after the previous one was given."""
    if session.hint_level_given == 0:
        return 1
    if session.hint_level_given >= MAX_HINT_LEVEL:
        return MAX_HINT_LEVEL
    elapsed = now - session.hint_given_at
    return session.hint_level_given + (1 if elapsed >= HINT_UNLOCK_SECONDS else 0)


def _hint_target(session: Session) -> TrackedFinding | None:
    open_findings = [t for t in session.findings if t.status != "resolved" and t.finding.tier != 4]
    if not open_findings:
        return None
    return min(open_findings, key=lambda t: (t.finding.tier, -t.finding.confidence))


def give_hint(session: Session, level: int, candidate_asked: bool, now: float) -> dict[str, Any]:
    level = max(1, min(MAX_HINT_LEVEL, level))
    allowed = unlocked_level(session, now)
    if candidate_asked and session.hint_level_given < MAX_HINT_LEVEL:
        allowed = max(allowed, session.hint_level_given + 1)  # an explicit ask unlocks one step
    if level > allowed:
        return {"allowed": False, "maxLevel": allowed,
                "instruction": f"Hint level {level} is not available yet. Ask a guiding question instead."}

    target = _hint_target(session)
    if level == 1:
        instruction = ("Ask one guiding question, for example: what does your code do on the "
                       "first example input? Do not name a concept or a location.")
    elif target is None:
        instruction = ("No open issue is known. Ask the candidate which part they are unsure "
                       "about and what they expect it to do.")
    elif level == 2:
        instruction = (f"Name the concept to think about: {target.finding.category}. "
                       "Do not say where it applies or how to fix it.")
    else:
        instruction = (f"Name the location: {_where(target)}. Say the {target.finding.category} "
                       "issue is there. Do not state the fix or write code.")

    session.hint_level_given = max(session.hint_level_given, level)
    session.hint_given_at = now
    event = {"type": "hint", "at": now, "level": level, "candidateAsked": candidate_asked,
             "findingId": target.id if target else None}
    session.events.append(event)
    session.hint_events.append(event)
    return {"allowed": True, "level": level, "instruction": instruction}
