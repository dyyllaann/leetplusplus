"""Bridges a browser audio WebSocket to a Gemini Live session (audio only).

Browser -> server: binary = 16 kHz mono PCM16; text JSON {"type": "ptt", "state": "down"|"up"}.
Server -> browser: binary = 24 kHz mono PCM16; text JSON events (see docs/api.md).

The model never sees camera frames. Board state reaches it as "[BOARD]" text notes,
and findings only as "[COACH]" notes after the interjection policy releases them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from backend import config, policy
from backend.session.state import Session
from backend.voice.tools import FUNCTION_DECLARATIONS, VoiceTools

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts/interviewer.md"
TICK_SECONDS = 0.5
TIER_NAMES = {1: "approach", 2: "logic error", 3: "edge case", 4: "syntax"}
TRIGGER_AFTER_SILENCE_SECONDS = 1.0


def board_note(session: Session) -> str:
    """Literal board text only: no findings, which go through the policy."""
    if session.transcription is None:
        return "[BOARD] The board is empty so far."
    parts = ["[BOARD] Current whiteboard (literal transcription, for your reference only):"]
    for r in session.transcription.regions:
        parts.append(f"{r.id} ({r.type}):")
        parts += [f"  line {ln.n}: {ln.text}" for ln in r.lines]
    return "\n".join(parts)


def coach_note(release: policy.Release) -> str:
    f = release.finding.finding
    where = f"line {f.line} of {f.region_id}" if f.line else f.region_id
    if release.mode == "question":
        how = "You are not sure it is a real problem, so ask a probing question about it; do not assert an error."
    else:
        how = "Tell the candidate there is a problem and name its category; do not say how to fix it."
    # The analyzer's message often names the fix, so the voice model only gets
    # the location, tier and category.
    return (
        f"[COACH] Raise this now, briefly. Location: {where}. Kind of issue: {TIER_NAMES[f.tier]}, "
        f"category '{f.category}'. {how} Call point_to_region with region_id={f.region_id!r}"
        + (f" and line={f.line}." if f.line else ".")
    )


def user_turn(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


class VoiceBridge:
    def __init__(self, session: Session, ws: WebSocket,
                 notify_board: Callable[[], Awaitable[None]],
                 push_to_talk: bool = config.VOICE_PUSH_TO_TALK):
        self.session = session
        self.ws = ws
        self.notify_board = notify_board
        self.push_to_talk = push_to_talk
        self.tools = VoiceTools(session, self._send_json, time.monotonic)
        self.board_version_sent = -1
        self.last_release_at: float | None = None
        self.last_candidate_speech_at: float | None = None
        self.triggered_for_speech_at: float | None = None
        self.candidate_done = False
        self.interviewer_speaking = False
        self.awaiting_response = False  # a turn_complete=True note was sent; reply not finished yet
        self._buffers = {"candidate": "", "interviewer": ""}

    async def _send_json(self, event: dict[str, Any]) -> None:
        await self.ws.send_text(json.dumps(event))

    def _live_config(self) -> dict[str, Any]:
        cfg: dict[str, Any] = {
            "response_modalities": ["AUDIO"],
            "system_instruction": PROMPT_PATH.read_text().format(problem=self.session.problem_text),
            "tools": [{"function_declarations": FUNCTION_DECLARATIONS}],
            "input_audio_transcription": {},
            "output_audio_transcription": {},
        }
        if self.push_to_talk:
            cfg["realtime_input_config"] = {"automatic_activity_detection": {"disabled": True}}
        return cfg

    async def run(self) -> None:
        client = genai.Client()  # reads GEMINI_API_KEY
        async with client.aio.live.connect(model=config.VOICE_MODEL, config=self._live_config()) as live:
            await self._send_json({"type": "voiceStatus", "state": "connected",
                                   "pushToTalk": self.push_to_talk})
            await self._sync_board(live)
            await self._prompt_response(live, "[COACH] The candidate just joined. Greet them in one "
                                              "sentence and ask them to explain the problem and their approach.")
            tasks = [asyncio.create_task(c) for c in
                     (self._from_browser(live), self._from_gemini(live), self._tick(live))]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                        raise t.exception()
            finally:
                for t in tasks:
                    t.cancel()

    async def _from_browser(self, live) -> None:
        while True:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes"):
                await live.send_realtime_input(
                    audio=types.Blob(data=msg["bytes"], mime_type="audio/pcm;rate=16000"))
            elif msg.get("text"):
                event = json.loads(msg["text"])
                if event.get("type") == "ptt" and self.push_to_talk:
                    if event.get("state") == "down":
                        await live.send_realtime_input(activity_start=types.ActivityStart())
                    else:
                        await live.send_realtime_input(activity_end=types.ActivityEnd())

    async def _from_gemini(self, live) -> None:
        while True:  # receive() ends after each turn_complete, so keep re-entering it
            async for msg in live.receive():
                if msg.tool_call:
                    await self._handle_tool_call(live, msg.tool_call)
                sc = msg.server_content
                if sc is None:
                    continue
                if sc.interrupted:
                    self.interviewer_speaking = False
                    await self._send_json({"type": "interrupted"})
                if sc.model_turn:
                    for part in sc.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            self.interviewer_speaking = True
                            await self.ws.send_bytes(part.inline_data.data)
                if sc.input_transcription and sc.input_transcription.text:
                    self.last_candidate_speech_at = time.monotonic()
                    self._buffers["candidate"] += sc.input_transcription.text
                if sc.output_transcription and sc.output_transcription.text:
                    self._buffers["interviewer"] += sc.output_transcription.text
                if sc.turn_complete:
                    self.interviewer_speaking = False
                    self.awaiting_response = False
                    await self._flush_transcripts()

    async def _flush_transcripts(self) -> None:
        for role in ("candidate", "interviewer"):
            text = self._buffers[role].strip()
            self._buffers[role] = ""
            if not text:
                continue
            if role == "candidate":
                if policy.candidate_signals_done(text):
                    self.candidate_done = True
                if "hint" in text.lower():
                    self.tools.hints.requested = True
            self.session.transcript.append({"role": role, "text": text, "at": time.time()})
            await self._send_json({"type": "transcript", "role": role, "text": text})

    async def _handle_tool_call(self, live, tool_call) -> None:
        responses = []
        for fc in tool_call.function_calls or []:
            result = await self.tools.call(fc.name, dict(fc.args or {}))
            await self._send_json({"type": "toolCall", "name": fc.name, "args": dict(fc.args or {}),
                                   "result": result})
            responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response=result))
        if responses:
            self.awaiting_response = True  # the model continues speaking after a tool result
            await live.send_tool_response(function_responses=responses)

    async def _prompt_response(self, live, text: str) -> None:
        """Send a note the model must answer aloud now."""
        self.awaiting_response = True
        await live.send_client_content(turns=user_turn(text), turn_complete=True)

    async def _sync_board(self, live) -> None:
        if self.session.board_version != self.board_version_sent:
            self.board_version_sent = self.session.board_version
            await live.send_client_content(turns=user_turn(board_note(self.session)), turn_complete=False)

    async def _tick(self, live) -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            now = time.monotonic()
            await self._sync_board(live)

            # Candidate paused: ask the vision loop for a fresh pass (Phase 1 trigger_now).
            spoke = self.last_candidate_speech_at
            if spoke and spoke != self.triggered_for_speech_at and now - spoke >= TRIGGER_AFTER_SILENCE_SECONDS:
                self.triggered_for_speech_at = spoke
                self.session.trigger_reason = "candidate_stopped_speaking"

            release = policy.decide(self.session.findings, policy.ConversationState(
                now=now,
                last_candidate_speech_at=self.last_candidate_speech_at,
                last_release_at=self.last_release_at,
                candidate_done_or_tracing=self.candidate_done,
                interviewer_speaking=self.interviewer_speaking or self.awaiting_response,
            ))
            if release is None:
                continue
            release.finding.status = "released"
            self.last_release_at = now
            await self.notify_board()
            logger.info(f"releasing {release.finding.id} as {release.mode}")
            await self._prompt_response(live, coach_note(release))
            await self._send_json({"type": "released", "findingId": release.finding.id, "mode": release.mode})
