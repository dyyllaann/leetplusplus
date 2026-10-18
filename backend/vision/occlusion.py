"""Decide whether a new transcription only lost text (view blocked) rather than changed.

When the candidate stands in front of the board, the transcriber returns fewer or
truncated lines. Those readings must not replace the last good transcription; only a
reading that contains something new counts as an actual change.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from backend.models.schemas import Transcription

SIMILAR_RATIO = 0.8
SHRINK_RATIO = 0.9  # a reading with less than 90% of the previous text counts as a loss


def _lines(t: Transcription) -> list[str]:
    return [ln.text.strip() for r in t.regions for ln in r.lines if ln.text.strip()]


def _covered(line: str, previous: list[str]) -> bool:
    """The line already existed: identical, a truncated prefix, or a near-duplicate."""
    squash = line.replace(" ", "")
    for old in previous:
        old_squash = old.replace(" ", "")
        if old_squash.startswith(squash) or SequenceMatcher(None, squash, old_squash).ratio() >= SIMILAR_RATIO:
            return True
    return False


def only_lost_text(previous: Transcription | None, new: Transcription) -> bool:
    if previous is None:
        return False
    old_lines, new_lines = _lines(previous), _lines(new)
    if not old_lines:
        return False
    if not new_lines:
        return True
    if sum(map(len, new_lines)) >= SHRINK_RATIO * sum(map(len, old_lines)):
        return False
    return all(_covered(line, old_lines) for line in new_lines)
