"""One analysis pass: frame -> literal transcription -> findings -> session state."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from backend import config
from backend.models.analyzer import Analyzer, get_analyzer
from backend.models.call_log import save_call
from backend.models.transcriber import Transcriber, get_transcriber
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


async def run_pass(session: Session, image: bytes, mime: str, emit: Emit) -> bool:
    """Returns True if the pass completed and session state was updated."""
    transcriber, analyzer = models()
    n = session.pass_count + 1

    await emit({"type": "status", "stage": "transcribing"})
    t_call = await asyncio.to_thread(transcriber.transcribe, image, mime)
    save_call(session.log_dir, f"{n:03d}_transcription", t_call)
    if t_call.parsed is None:
        await emit({"type": "status", "stage": "error", "detail": f"transcription: {t_call.error}"})
        return False

    await emit({"type": "status", "stage": "analyzing"})
    a_call = await asyncio.to_thread(analyzer.analyze, image, mime, t_call.parsed, session.problem_text)
    save_call(session.log_dir, f"{n:03d}_analysis", a_call)
    if a_call.parsed is None:
        await emit({"type": "status", "stage": "error", "detail": f"analysis: {a_call.error}"})
        return False

    session.apply_pass(t_call.parsed, a_call.parsed.findings)
    await emit(session.board_state())
    await emit({"type": "status", "stage": "idle"})
    return True
