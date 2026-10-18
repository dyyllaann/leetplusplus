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
    released_at: float = 0.0  # monotonic time the policy raised it with the candidate
    line_text: str | None = None  # normalized text of the line when last reported


def normalize_line(text: str) -> str:
    return " ".join(text.split())


def line_text(t: Transcription | None, region_id: str, line: int) -> str | None:
    if t is None or not line:
        return None
    for r in t.regions:
        if r.id == region_id:
            for ln in r.lines:
                if ln.n == line:
                    return normalize_line(ln.text)
    return None


def finding_key(f: Finding) -> tuple:
    """Duplicate check within ONE pass: one finding per line and tier (category wording
    drifts between model calls). Matching ACROSS passes is done by match_open."""
    if f.line:
        return (f.region_id, f.tier, f.line)
    return (f.region_id, f.tier, 0, f.category.strip().lower())


def match_open(open_findings: list[TrackedFinding], f: Finding, text: str | None,
               taken: set[str], by_text: bool) -> TrackedFinding | None:
    """Find the tracked finding this new report continues. Called in two rounds so text
    matches win over number matches across the whole pass:
    by_text=True:  same region, tier, and line text (the line moved because lines were
                   inserted or removed); ties (e.g. several "}") go to the closest number.
    by_text=False: same region, tier, and line number (the line was edited in place).
    Region-level findings (line 0) match on category in the first round."""
    pool = [t for t in open_findings if t.id not in taken
            and t.finding.region_id == f.region_id and t.finding.tier == f.tier]
    if not f.line:
        if not by_text:
            return None
        return next((t for t in pool if not t.finding.line and
                     t.finding.category.strip().lower() == f.category.strip().lower()), None)
    if by_text:
        same_text = [t for t in pool if t.finding.line and text and t.line_text == text]
        return min(same_text, key=lambda t: abs(t.finding.line - f.line)) if same_text else None
    return next((t for t in pool if t.finding.line == f.line), None)


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
    board_version: int = 0  # bumps whenever board state changes; the voice bridge watches it
    transcript: list[dict[str, Any]] = field(default_factory=list)  # {role, text, at}
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # True from pass start until the transcriber returns. The voice layer waits on this
    # (via /sync) so it never answers about the board from a stale transcription.
    transcribing: bool = False
    # Latest frame differs from the last analyzed frame (updated on every frame).
    pending_change: bool = False
    # Transcription is newer than the findings: analyzer still running for this text.
    analysis_pending: bool = False
    last_pass_at: float = 0.0
    pass_started_at: float = 0.0
    # --- Voice / policy state (backend/policy.py, backend/voice_tools.py) ---
    board_stable: bool = False  # latest frame has been still for GATE_STABLE_SECONDS
    phase: str = "clarifying"  # clarifying | writing | tracing | done, reported by the voice layer
    last_release_at: float = float("-inf")
    hint_level_given: int = 0
    hint_given_at: float = 0.0
    hint_events: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)  # interjections, tool calls, hints
    partials_since_full: int = 0  # line-level passes since the last full-board transcription
    need_full: bool = False  # a line re-read failed; next pass must transcribe the whole board
    trigger_reason: str | None = None
    updated_at: str | None = None
    ended: bool = False
    submission: Any = None  # backend.submission.Submission once the candidate submits
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
        self.board_version += 1
        self.last_pass_at = time.monotonic()
        self.trigger_reason = None
        self.analysis_pending = False
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.transcription = transcription
        self.raw_transcription = raw or transcription
        self.corrected_lines = corrected_lines or {}
        self.history = (self.history + [transcription])[-HISTORY_LIMIT:]

        open_findings = [t for t in self.findings if t.status != "resolved"]
        reports: list[tuple[Finding, str | None]] = []
        seen_keys: set[tuple] = set()
        for f in findings:
            key = finding_key(f)
            if key not in seen_keys:
                seen_keys.add(key)
                reports.append((f, line_text(transcription, f.region_id, f.line)))

        taken: set[str] = set()
        matched: dict[int, TrackedFinding] = {}
        for by_text in (True, False):
            for i, (f, text) in enumerate(reports):
                if i in matched:
                    continue
                tracked = match_open(open_findings, f, text, taken, by_text)
                if tracked is not None:
                    matched[i] = tracked
                    taken.add(tracked.id)

        for i, (f, text) in enumerate(reports):
            tracked = matched.get(i)
            if tracked is not None:
                # Same issue: keep id and status (so a released issue is not raised again),
                # follow it to its current line number and wording.
                tracked.finding = f
                tracked.line_text = text
                tracked.last_seen_pass = self.pass_count
            else:
                self.findings.append(TrackedFinding(
                    id=f"f{next(self._ids)}", finding=f, line_text=text,
                    first_seen_pass=self.pass_count, last_seen_pass=self.pass_count))
        for tracked in open_findings:
            if tracked.id not in taken:
                tracked.status = "resolved"

    def _line_state(self, region_id: str, ln: Any) -> dict[str, Any]:
        original = self.corrected_lines.get((region_id, ln.n))
        state = {"n": ln.n, "text": ln.text, "lowConfidenceChars": ln.low_confidence_chars,
                 "corrected": original is not None}
        b = getattr(ln, "bbox", None)
        if b is not None:
            state["bbox"] = {"x": b.x1 / 1000, "y": b.y1 / 1000,
                             "width": (b.x2 - b.x1) / 1000, "height": (b.y2 - b.y1) / 1000}
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
