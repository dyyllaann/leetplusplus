"""FastAPI entry point. Contract: docs/api.md.

Run: .venv/bin/uvicorn backend.app:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from backend import config  # noqa: E402
from backend.pipeline import run_pass  # noqa: E402
from backend.problems import get_problem, list_problems, problem_text  # noqa: E402
from backend.session.state import Session, SessionStore  # noqa: E402
from backend.vision.gate import thumbnail  # noqa: E402
from backend.vision.localize import PassPlan, plan_pass  # noqa: E402
from backend import policy, voice_tools  # noqa: E402

app = FastAPI(title="Whiteboard Practice Coach")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = SessionStore()
subscribers: dict[str, set[WebSocket]] = defaultdict(set)


class CreateSession(BaseModel):
    problemId: str


class Trigger(BaseModel):
    reason: str = "manual"


class Sync(BaseModel):
    timeoutSeconds: float = 2.5


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = {}


class PhaseUpdate(BaseModel):
    phase: str


class TranscriptTurn(BaseModel):
    role: str  # candidate | interviewer
    text: str


INTERVIEWER_PROMPT = (Path(__file__).resolve().parent / "prompts/interviewer.md").read_text()


def require(session_id: str) -> Session:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, "unknown session")
    return session


async def broadcast(session_id: str, event: dict[str, Any]) -> None:
    for ws in list(subscribers[session_id]):
        try:
            await ws.send_json(event)
        except Exception:
            subscribers[session_id].discard(ws)


def decode_data_url(data_url: str) -> tuple[bytes, str]:
    header, _, payload = data_url.partition(",")
    if not header.startswith("data:") or ";base64" not in header:
        raise ValueError("imageData must be a base64 data URL")
    return base64.b64decode(payload), header[5:].split(";")[0]


STATIC = Path(__file__).resolve().parent / "static"


@app.get("/debug/camera")
def camera_debug_page() -> FileResponse:
    return FileResponse(STATIC / "camera.html")


@app.get("/problems")
def problems() -> list[dict[str, str]]:
    return [{"id": p["id"], "title": p.get("title", p["id"])} for p in list_problems()]


@app.post("/sessions")
def create_session(body: CreateSession) -> dict[str, str]:
    problem = get_problem(body.problemId)
    if problem is None:
        raise HTTPException(404, f"unknown problem {body.problemId!r}")
    session = store.create(body.problemId, problem_text(problem))
    return {"sessionId": session.id}


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    return require(session_id).board_state()


@app.post("/sessions/{session_id}/trigger")
def trigger(session_id: str, body: Trigger) -> dict[str, bool]:
    require(session_id).trigger_reason = body.reason
    return {"ok": True}


@app.post("/sessions/{session_id}/sync")
async def sync(session_id: str, body: Sync) -> dict[str, Any]:
    """Wait until the transcription reflects the current board, up to timeoutSeconds.
    Call this before the voice agent answers anything about the board."""
    session = require(session_id)
    if session.pending_change:
        session.trigger_reason = "sync"  # skip the analysis interval
    deadline = time.monotonic() + max(0.0, min(body.timeoutSeconds, 10.0))
    while not session.is_current() and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    return {"fresh": session.is_current(), "boardState": session.board_state()}


@app.get("/sessions/{session_id}/voice-config")
def voice_config(session_id: str) -> dict[str, Any]:
    """System prompt and tool declarations for the voice session."""
    session = require(session_id)
    return {"systemPrompt": INTERVIEWER_PROMPT.replace("{problem}", session.problem_text),
            "tools": voice_tools.TOOL_DECLARATIONS}


@app.post("/sessions/{session_id}/tools")
async def run_tool(session_id: str, body: ToolCall) -> dict[str, Any]:
    """Execute a voice-agent tool call; return the response to the model as the tool result."""
    session = require(session_id)
    return await voice_tools.execute(session, body.name, body.args, lambda e: broadcast(session_id, e))


@app.post("/sessions/{session_id}/interjection")
def interjection(session_id: str) -> dict[str, Any]:
    """Ask the policy whether to raise a finding now. Call when the candidate pauses
    (and every few seconds while they are silent). At most one release at a time."""
    release = policy.next_release(require(session_id), time.monotonic())
    return {"release": release.as_json() if release else None}


@app.post("/sessions/{session_id}/phase")
def set_phase(session_id: str, body: PhaseUpdate) -> dict[str, Any]:
    if body.phase not in policy.PHASES:
        raise HTTPException(422, f"phase must be one of {policy.PHASES}")
    require(session_id).phase = body.phase
    return {"ok": True}


@app.post("/sessions/{session_id}/transcript")
def add_transcript(session_id: str, body: TranscriptTurn) -> dict[str, bool]:
    require(session_id).transcript.append(
        {"role": body.role, "text": body.text, "at": time.monotonic()})
    return {"ok": True}


@app.post("/sessions/{session_id}/end")
def end_session(session_id: str) -> dict[str, bool]:
    require(session_id).ended = True
    return {"ok": True}


async def _pass_task(session: Session, image: bytes, mime: str, plan: PassPlan) -> None:
    ok = False
    try:
        ok = await run_pass(session, image, mime, lambda e: broadcast(session.id, e), plan)
    except Exception as exc:
        await broadcast(session.id, {"type": "status", "stage": "error", "detail": repr(exc)})
    finally:
        # Also set on failure, so a broken pass backs off instead of retrying every frame.
        session.last_pass_at = time.monotonic()
        if not ok:
            session.gate.reset_analyzed()
        session.transcribing = False
        session.busy = False


@app.websocket("/sessions/{session_id}/ws")
async def frames_ws(ws: WebSocket, session_id: str) -> None:
    session = store.get(session_id)
    if session is None:
        await ws.close(code=4404)
        return
    await ws.accept()
    subscribers[session_id].add(ws)
    if session.transcription is not None:
        await ws.send_json(session.board_state())
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") != "frame" or session.ended:
                continue
            try:
                image, mime = decode_data_url(msg["imageData"])
                thumb = thumbnail(image)
            except (KeyError, ValueError, binascii.Error, OSError) as exc:
                await ws.send_json({"type": "status", "stage": "error", "detail": f"bad frame: {exc}"})
                continue

            now = time.monotonic()
            gate = session.gate.update(thumb, now)
            session.pending_change = gate.changed
            session.board_stable = gate.stable
            await ws.send_json({"type": "gate", "changed": gate.changed,
                                "stable": gate.stable, "busy": session.busy})
            if gate.ready and not session.busy and session.due(now, config.ANALYSIS_INTERVAL_SECONDS):
                plan = (PassPlan(True, "previous line re-read failed") if session.need_full
                        else plan_pass(session.gate.changed_mask(thumb), session.raw_transcription,
                                       session.partials_since_full))
                session.busy = True
                session.transcribing = True
                session.pending_change = False
                session.pass_started_at = now
                session.gate.mark_analyzed(thumb)
                asyncio.create_task(_pass_task(session, image, mime, plan))
    except WebSocketDisconnect:
        pass
    finally:
        subscribers[session_id].discard(ws)
