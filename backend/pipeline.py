"""One analysis pass: frame -> literal transcription -> findings -> session state."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from backend import config
from backend.models.analyzer import Analyzer, get_analyzer
from backend.models.call_log import save_call
from backend.models.transcriber import Transcriber, get_transcriber
from backend.models.schemas import Transcription
from backend.session.state import Session

Emit = Callable[[dict[str, Any]], Awaitable[None]]

_transcriber: Transcriber | None = None
_analyzer: Analyzer | None = None


def models() -> tuple[Transcriber, Analyzer]:
    global _transcriber, _analyzer
    if _transcriber is None:
        _transcriber = get_transcriber(config.TRANSCRIBER, reasoning_effort=config.TRANSCRIBER_REASONING)
    if _analyzer is None:
        _analyzer = get_analyzer(config.ANALYZER)
    return _transcriber, _analyzer


def normalize_region_ids(t: Transcription) -> Transcription:
    """Model-chosen ids drift between passes ("code", "code_block", ...). Renumber
    by type in reading order so findings keep a stable region_id."""
    regions = sorted(t.regions, key=lambda r: (r.bbox.y1, r.bbox.x1))
    counts: dict[str, int] = {}
    renamed = []
    for r in regions:
        counts[r.type] = counts.get(r.type, 0) + 1
        renamed.append(r.model_copy(update={"id": f"{r.type}_{counts[r.type]}"}))
    return Transcription(regions=renamed)


def board_text(t: Transcription | None) -> list[tuple[str, list[str]]]:
    return [(r.id, [ln.text.strip() for ln in r.lines]) for r in t.regions] if t else []


async def run_pass(session: Session, image: bytes, mime: str, emit: Emit) -> bool:
    """Returns True if the pass completed and session state was updated."""
    transcriber, analyzer = models()
    session.attempts += 1
    n = session.attempts
    session.log_dir.mkdir(parents=True, exist_ok=True)
    ext = mime.split("/")[-1].replace("jpeg", "jpg")
    (session.log_dir / f"{n:03d}_frame.{ext}").write_bytes(image)

    await emit({"type": "status", "stage": "transcribing"})
    t_call = await asyncio.to_thread(transcriber.transcribe, image, mime)
    save_call(session.log_dir, f"{n:03d}_transcription", t_call)
    if t_call.parsed is None:
        await emit({"type": "status", "stage": "error", "detail": f"transcription: {t_call.error}"})
        return False

    transcription = normalize_region_ids(t_call.parsed)
    if session.transcription is not None and board_text(transcription) == board_text(session.transcription):
        # Same text as last pass: keep current findings, skip the analyzer call.
        session.mark_unchanged_pass()
        await emit({"type": "status", "stage": "idle", "detail": "board text unchanged"})
        return True

    await emit({"type": "status", "stage": "analyzing"})
    a_call = await asyncio.to_thread(analyzer.analyze, image, mime, transcription, session.problem_text)
    save_call(session.log_dir, f"{n:03d}_analysis", a_call)
    if a_call.parsed is None:
        await emit({"type": "status", "stage": "error", "detail": f"analysis: {a_call.error}"})
        return False

    session.apply_pass(transcription, a_call.parsed.findings)
    await emit(session.board_state())
    await emit({"type": "status", "stage": "idle"})
    return True
