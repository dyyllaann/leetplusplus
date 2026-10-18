"""In-memory session state: latest board transcription and tracked findings."""

from __future__ import annotations

import itertools
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from backend.models.schemas import Finding, Transcription
from backend.vision.gate import FrameGate

FindingStatus = Literal["new", "queued", "released", "resolved"]
HISTORY_LIMIT = 20
LOG_ROOT = Path(__file__).resolve().parents[2] / "logs/sessions"


@dataclass
class TrackedFinding:
    id: str
    finding: Finding
    status: FindingStatus = "new"
    first_seen_pass: int = 0
    last_seen_pass: int = 0


def finding_key(f: Finding) -> tuple:
    """Identity of an issue across passes. Category wording drifts between
    model calls, so line-specific findings are keyed by location and tier."""
    if f.line:
        return (f.region_id, f.line, f.tier)
    return (f.region_id, 0, f.tier, f.category.strip().lower())


@dataclass
class Session:
    id: str
    problem_id: str
    problem_text: str
    gate: FrameGate = field(default_factory=FrameGate)
    pass_count: int = 0
    attempts: int = 0  # every pass started, including skipped/failed; numbers log files
    transcription: Transcription | None = None
    raw_transcription: Transcription | None = None  # Perceptron output before corrections
    corrected_lines: dict[tuple[str, int], str] = field(default_factory=dict)  # -> transcribed text
    history: list[Transcription] = field(default_factory=list)
    findings: list[TrackedFinding] = field(default_factory=list)
    busy: bool = False
    # True from pass start until the transcriber returns. The voice layer waits on this
    # (via /sync) so it never answers about the board from a stale transcription.
    transcribing: bool = False
    # Latest frame differs from the last analyzed frame (updated on every frame).
    pending_change: bool = False
    # Transcription is newer than the findings: analyzer still running for this text.
    analysis_pending: bool = False
    last_pass_at: float = 0.0
    pass_started_at: float = 0.0
    trigger_reason: str | None = None
    updated_at: str | None = None
    ended: bool = False
    _ids: Any = field(default_factory=lambda: itertools.count(1))

    @property
    def log_dir(self) -> Path:
        return LOG_ROOT / self.id

    def due(self, now: float, interval: float) -> bool:
        # Measured from pass START, so a slow pass does not add the full interval on top.
        return self.trigger_reason is not None or now - self.pass_started_at >= interval

    def is_current(self) -> bool:
        """Transcription reflects the board as it is now."""
        return not self.transcribing and not self.pending_change

    def apply_transcription(self, transcription: Transcription) -> None:
        """Publish new board text before the analyzer finishes. Findings are left
        as they are until apply_pass; analysis_pending marks them as possibly stale."""
        self.transcription = transcription
        self.raw_transcription = transcription
        self.corrected_lines = {}
        self.analysis_pending = True
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def mark_unchanged_pass(self) -> None:
        self.last_pass_at = time.monotonic()
        self.trigger_reason = None

    def apply_pass(self, transcription: Transcription, findings: list[Finding],
                   raw: Transcription | None = None,
                   corrected_lines: dict[tuple[str, int], str] | None = None) -> None:
        """Record a completed pass. Findings that persist keep their id and status;
        findings no longer reported become resolved."""
        self.pass_count += 1
        self.last_pass_at = time.monotonic()
        self.trigger_reason = None
        self.analysis_pending = False
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.transcription = transcription
        self.raw_transcription = raw or transcription
        self.corrected_lines = corrected_lines or {}
        self.history = (self.history + [transcription])[-HISTORY_LIMIT:]

        open_by_key = {finding_key(t.finding): t for t in self.findings if t.status != "resolved"}
        seen = set()
        for f in findings:
            key = finding_key(f)
            if key in seen:
                continue
            seen.add(key)
            if key in open_by_key:
                tracked = open_by_key[key]
                tracked.finding = f
                tracked.last_seen_pass = self.pass_count
            else:
                self.findings.append(TrackedFinding(
                    id=f"f{next(self._ids)}", finding=f,
                    first_seen_pass=self.pass_count, last_seen_pass=self.pass_count))
        for key, tracked in open_by_key.items():
            if key not in seen:
                tracked.status = "resolved"

    def _line_state(self, region_id: str, ln: Any) -> dict[str, Any]:
        original = self.corrected_lines.get((region_id, ln.n))
        state = {"n": ln.n, "text": ln.text, "lowConfidenceChars": ln.low_confidence_chars,
                 "corrected": original is not None}
        if original is not None:
            state["transcribedText"] = original
        return state

    def board_state(self) -> dict[str, Any]:
        regions = []
        for r in (self.transcription.regions if self.transcription else []):
            b = r.bbox
            regions.append({
                "id": r.id, "type": r.type,
                "bbox": {"x": b.x1 / 1000, "y": b.y1 / 1000,
                         "width": (b.x2 - b.x1) / 1000, "height": (b.y2 - b.y1) / 1000},
                "lines": [self._line_state(r.id, ln) for ln in r.lines],
            })
        findings = [{
            "id": t.id, "regionId": t.finding.region_id, "line": t.finding.line,
            "severity": t.finding.tier, "category": t.finding.category,
            "confidence": t.finding.confidence, "message": t.finding.message, "status": t.status,
        } for t in self.findings]
        return {"type": "boardState", "pass": self.pass_count, "updatedAt": self.updated_at,
                "analysisPending": self.analysis_pending,
                "regions": regions, "findings": findings}


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self, problem_id: str, problem_text: str) -> Session:
        session = Session(id=uuid.uuid4().hex[:8], problem_id=problem_id, problem_text=problem_text)
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)
