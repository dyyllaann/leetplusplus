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
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from backend import config  # noqa: E402
from backend.pipeline import run_pass  # noqa: E402
from backend.problems import get_problem, problem_text  # noqa: E402
from backend.session.state import Session, SessionStore  # noqa: E402
from backend.vision.gate import thumbnail  # noqa: E402

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


@app.post("/sessions/{session_id}/end")
def end_session(session_id: str) -> dict[str, bool]:
    require(session_id).ended = True
    return {"ok": True}


async def _pass_task(session: Session, image: bytes, mime: str) -> None:
    ok = False
    try:
        ok = await run_pass(session, image, mime, lambda e: broadcast(session.id, e))
    except Exception as exc:
        await broadcast(session.id, {"type": "status", "stage": "error", "detail": repr(exc)})
    finally:
        # Also set on failure, so a broken pass backs off instead of retrying every frame.
        session.last_pass_at = time.monotonic()
        if not ok:
            session.gate.reset_analyzed()
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
            await ws.send_json({"type": "gate", "changed": gate.changed,
                                "stable": gate.stable, "busy": session.busy})
            if gate.ready and not session.busy and session.due(now, config.ANALYSIS_INTERVAL_SECONDS):
                session.busy = True
                session.gate.mark_analyzed(thumb)
                asyncio.create_task(_pass_task(session, image, mime))
    except WebSocketDisconnect:
        pass
    finally:
        subscribers[session_id].discard(ws)
