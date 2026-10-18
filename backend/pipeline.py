"""One analysis pass: frame -> literal transcription -> findings -> session state."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from backend import config
from backend.models.analyzer import Analyzer, get_analyzer
from backend.models.call_log import save_call
from backend.models.transcriber import Transcriber, get_transcriber
from backend.models.schemas import BBox, Correction, Line, Region, RegionRewrite, Transcription
from backend.session.state import Session
from backend.vision.occlusion import only_lost_text

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
    by type in reading order so findings keep a stable region_id, and renumber lines."""
    regions = sorted(t.regions, key=lambda r: (r.bbox.y1, r.bbox.x1))
    counts: dict[str, int] = {}
    renamed = []
    for r in regions:
        counts[r.type] = counts.get(r.type, 0) + 1
        # Line numbers are also reassigned: the model sometimes repeats or skips them.
        lines = [ln.model_copy(update={"n": i}) for i, ln in enumerate(r.lines, 1)]
        renamed.append(r.model_copy(update={"id": f"{r.type}_{counts[r.type]}", "lines": lines}))
    return Transcription(regions=renamed)


def apply_corrections(t: Transcription, corrections: list[Correction],
                      rewrites: list[RegionRewrite] | None = None,
                      ) -> tuple[Transcription, dict[tuple[str, int], str]]:
    """Patch what the analyzer read differently from the image. A region rewrite
    replaces the whole region (the transcriber invented or dropped lines); line
    corrections patch single lines. Returns the patched transcription and
    {(region_id, line): text the transcriber returned}."""
    by_key = {(c.region_id, c.line): c.text for c in corrections}
    rewrite_by_region = {rw.region_id: rw.lines for rw in rewrites or []}
    originals: dict[tuple[str, int], str] = {}
    regions = []
    for r in t.regions:
        if r.id in rewrite_by_region:
            old = {ln.n: ln.text for ln in r.lines}
            lines = [Line(n=i, text=text, low_confidence_chars=[])
                     for i, text in enumerate(rewrite_by_region[r.id], 1)]
            for ln in lines:
                if old.get(ln.n, "").strip() != ln.text.strip():
                    originals[(r.id, ln.n)] = old.get(ln.n, "")
            regions.append(r.model_copy(update={"lines": lines}))
            continue
        lines = []
        for ln in r.lines:
            new_text = by_key.get((r.id, ln.n))
            if new_text is not None and new_text.strip() != ln.text.strip():
                originals[(r.id, ln.n)] = ln.text
                ln = ln.model_copy(update={"text": new_text, "low_confidence_chars": []})
            lines.append(ln)
        regions.append(r.model_copy(update={"lines": lines}))
    known = {r.id for r in t.regions}
    for region_id, texts in rewrite_by_region.items():
        if region_id in known:
            continue
        # The transcriber missed this region entirely; the analyzer read it from the image.
        regions.append(Region(id=region_id, type="code", bbox=BBox(x1=0, y1=0, x2=1000, y2=1000),
                              lines=[Line(n=i, text=text, low_confidence_chars=[]) for i, text in enumerate(texts, 1)]))
        for i, text in enumerate(texts, 1):
            originals[(region_id, i)] = ""
    return Transcription(regions=regions), originals


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
    if only_lost_text(session.raw_transcription, transcription):
        # Something is blocking the board: keep the last good reading until an actual change.
        session.mark_unchanged_pass()
        await emit({"type": "status", "stage": "idle", "detail": "view blocked; keeping last transcription"})
        return True
    if session.raw_transcription is not None and board_text(transcription) == board_text(session.raw_transcription):
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

    corrected, originals = apply_corrections(transcription, a_call.parsed.transcription_corrections,
                                             a_call.parsed.region_rewrites)
    session.apply_pass(corrected, a_call.parsed.findings, raw=transcription, corrected_lines=originals)
    await emit(session.board_state())
    await emit({"type": "status", "stage": "idle"})
    return True
