"""Interjection policy: plain rules deciding which finding, if any, the voice agent
may raise right now. No model calls.

Rules (CLAUDE.md severity tiers):
- Tier 4 (syntax): never released; kept for the report.
- Tier 1 (approach): released as soon as allowed.
- Tier 2 (logic): released once its region has been analyzed on a stable frame.
- Tier 3 (edge case): only during a trace or after the candidate says they are done.
- One interruption at a time, highest tier first, with a cooldown between them.
- Never while the candidate or the interviewer is speaking.
- Confidence below the threshold: released as a question, not a correction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from backend.session.state import TrackedFinding

COOLDOWN_SECONDS = 20.0
CONFIDENCE_THRESHOLD = 0.6
SPEAKING_GRACE_SECONDS = 2.5  # longer than the 2 s end-of-turn silence

DONE_PATTERN = re.compile(
    r"\b(i'?m done|i am done|that'?s it|finished|i think (this|that) works|let'?s (trace|test)|"
    r"walk (you |me )?through|trace (it|this|through))\b",
    re.IGNORECASE,
)


@dataclass
class ConversationState:
    now: float
    last_candidate_speech_at: float | None = None
    last_release_at: float | None = None
    candidate_done_or_tracing: bool = False
    interviewer_speaking: bool = False


@dataclass
class Release:
    finding: TrackedFinding
    mode: Literal["correction", "question"]


def candidate_signals_done(utterance: str) -> bool:
    return bool(DONE_PATTERN.search(utterance))


def eligible(t: TrackedFinding, state: ConversationState) -> bool:
    if t.status not in ("new", "queued"):
        return False
    tier = t.finding.tier
    if tier == 4:
        return False
    if tier == 3:
        return state.candidate_done_or_tracing
    # Tiers 1-2: findings only come from passes run on stable frames, so the
    # region-stable requirement for tier 2 is already met when they exist.
    return True


def decide(findings: list[TrackedFinding], state: ConversationState) -> Release | None:
    if state.last_candidate_speech_at is not None and state.now - state.last_candidate_speech_at < SPEAKING_GRACE_SECONDS:
        return None
    if state.interviewer_speaking:
        return None
    if state.last_release_at is not None and state.now - state.last_release_at < COOLDOWN_SECONDS:
        return None
    candidates = [t for t in findings if eligible(t, state)]
    if not candidates:
        return None
    best = min(candidates, key=lambda t: (t.finding.tier, -t.finding.confidence, t.first_seen_pass))
    mode = "correction" if best.finding.confidence >= CONFIDENCE_THRESHOLD else "question"
    return Release(finding=best, mode=mode)
