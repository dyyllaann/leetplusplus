"""Bridges a browser audio WebSocket to Gemini Live (ears + voice) and Claude (brain).

Browser -> server: binary = 16 kHz mono PCM16; text JSON {"type": "ptt", "state": "down"|"up"}.
Server -> browser: binary = 24 kHz mono PCM16; text JSON events (see docs/api.md).

Gemini Live transcribes the candidate and speaks lines verbatim; its own replies are muted.
Claude (voice/brain.py) decides what the interviewer says. Findings reach the brain only
after the interjection policy releases them, as location + category (never the fix).
The voice model never receives camera frames.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from backend import config, metrics, policy
from backend.session.state import Session
from backend.voice.brain import BrainDecision, InterviewerBrain
from backend.voice.tools import VoiceTools, hint_text

logger = logging.getLogger(__name__)

TICK_SECONDS = 0.2
UTTERANCE_END_SECONDS = 0.6     # transcript silence that ends a candidate utterance
TRIGGER_AFTER_SILENCE_SECONDS = 2.0  # pause before asking the vision loop for a fresh pass
CHECK_WINDOW_SECONDS = 30.0     # a check request waits this long for a fresh analysis
TIER_NAMES = {1: "approach", 2: "logic error", 3: "edge case", 4: "syntax"}

RELAY_PROMPT = (
    "You are the voice of an interviewer. You never decide what to say yourself. "
    "When you receive a message starting with [SAY], speak the text after [SAY] aloud exactly, "
    "word for word, in a warm, calm, natural voice, and nothing else. "
    "Never respond to the user's speech on your own; if you must produce a turn, stay silent."
)


def coach_detail(release: policy.Release) -> str:
    """What the brain learns about a released finding: location, tier, category. Never the
    analyzer's message, which often names the fix."""
    f = release.finding.finding
    where = f"line {f.line} of {f.region_id}" if f.line else f.region_id
    mode = ("question: you are not sure it is a real problem, so ask a probing question"
            if release.mode == "question" else "correction: say there is a problem there and you may name its category")
    return (f"Raise this now. Location: {where} (region_id={f.region_id}, line={f.line}). "
            f"Kind: {TIER_NAMES[f.tier]}, category '{f.category}'. Mode: {mode}.")


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
        self.brain = InterviewerBrain(session)
        self.live = None
        self.last_release_at: float | None = None
        self.last_candidate_speech_at: float | None = None
        self.triggered_for_speech_at: float | None = None
        self.candidate_done = False
        self.check_requested_at: float | None = None
        self.interviewer_speaking = False
        self.awaiting_response = False  # a [SAY] was sent; its audio has not finished
        self.turn_voiced: bool | None = None  # decided at the first audio of each Gemini turn
        self.gemini_turn_active = False  # Gemini is generating (voiced or muted) audio
        self.expect_interrupt = False  # our [SAY] will cut off Gemini's muted reply
        self.thinking = False  # a brain call is in flight
        self.pending_events: list[tuple[str, str]] = []
        self.candidate_buffer = ""
        self.utterance_end_at: float | None = None  # last transcript chunk of the latest utterance
        # Timing for the next voiced line: {trigger, since, brain_s, said_at}; see metrics.py.
        self.pending_reply: dict[str, Any] | None = None

    async def _send_json(self, event: dict[str, Any]) -> None:
        await self.ws.send_text(json.dumps(event))

    def _live_config(self) -> dict[str, Any]:
        cfg: dict[str, Any] = {
            "response_modalities": ["AUDIO"],
            "system_instruction": RELAY_PROMPT,
            "input_audio_transcription": {},
            "output_audio_transcription": {},
        }
        if self.push_to_talk:
            cfg["realtime_input_config"] = {"automatic_activity_detection": {"disabled": True}}
        else:
            cfg["realtime_input_config"] = {"automatic_activity_detection": {
                "silence_duration_ms": config.VOICE_SILENCE_MS,
            }}
        if config.VOICE_NAME:
            cfg["speech_config"] = {"voice_config": {"prebuilt_voice_config": {"voice_name": config.VOICE_NAME}}}
        return cfg

    async def run(self) -> None:
        client = genai.Client()  # reads GEMINI_API_KEY
        async with client.aio.live.connect(model=config.VOICE_MODEL, config=self._live_config()) as live:
            self.live = live
            await self._send_json({"type": "voiceStatus", "state": "connected",
                                   "pushToTalk": self.push_to_talk})
            self.pending_events.append(("start", ""))
            tasks = [asyncio.create_task(c) for c in (self._from_browser(), self._from_gemini(), self._tick())]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    if t.exception() and not isinstance(t.exception(), WebSocketDisconnect):
                        raise t.exception()
            finally:
                for t in tasks:
                    t.cancel()

    # --- audio in -------------------------------------------------------------

    async def _from_browser(self) -> None:
        while True:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes"):
                await self.live.send_realtime_input(
                    audio=types.Blob(data=msg["bytes"], mime_type="audio/pcm;rate=16000"))
            elif msg.get("text"):
                event = json.loads(msg["text"])
                if event.get("type") == "ptt" and self.push_to_talk:
                    if event.get("state") == "down":
                        await self.live.send_realtime_input(activity_start=types.ActivityStart())
                    else:
                        await self.live.send_realtime_input(activity_end=types.ActivityEnd())

    # --- Gemini: transcripts in, audio out ---------------------------------------

    def should_voice_turn(self) -> bool:
        """Only lines the brain chose ([SAY]) are played; Gemini's own replies are muted."""
        return self.awaiting_response

    async def _from_gemini(self) -> None:
        while True:  # receive() ends after each turn_complete, so keep re-entering it
            async for msg in self.live.receive():
                sc = msg.server_content
                if sc is None:
                    continue
                if sc.interrupted:
                    self.interviewer_speaking = False
                    self.turn_voiced = None
                    self.gemini_turn_active = False
                    if self.expect_interrupt:
                        # Our own [SAY] replaced a muted reply; the new line is still to come.
                        self.expect_interrupt = False
                    else:
                        # The candidate talked over the interviewer: that line is cancelled.
                        self.awaiting_response = False
                        self.pending_reply = None
                        await self._send_json({"type": "interrupted"})
                if sc.input_transcription and sc.input_transcription.text:
                    self.last_candidate_speech_at = time.monotonic()
                    self.candidate_buffer += sc.input_transcription.text
                if sc.model_turn:
                    for part in sc.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            self.gemini_turn_active = True
                            if self.turn_voiced is None:
                                self.turn_voiced = self.should_voice_turn()
                            if self.turn_voiced:
                                self.interviewer_speaking = True
                                self._record_reply_audio()
                                await self.ws.send_bytes(part.inline_data.data)
                if sc.turn_complete:
                    self.gemini_turn_active = False
                    self.expect_interrupt = False
                    if self.turn_voiced:
                        self.awaiting_response = False
                    self.interviewer_speaking = False
                    self.turn_voiced = None

    def _record_reply_audio(self) -> None:
        r, self.pending_reply = self.pending_reply, None
        if r is None:
            return
        now = time.monotonic()
        metrics.record(self.session.log_dir, "audio_response", now - r["since"], trigger=r["trigger"],
                       brain_s=round(r["brain_s"], 3), tts_s=round(now - r["said_at"], 3))

    async def _say(self, text: str, reply: dict[str, Any] | None = None) -> None:
        if reply is not None:
            self.pending_reply = {**reply, "said_at": time.monotonic()}
        self.expect_interrupt = self.gemini_turn_active
        self.awaiting_response = True
        self.turn_voiced = None
        self.session.transcript.append({"role": "interviewer", "text": text, "at": time.time()})
        await self._send_json({"type": "transcript", "role": "interviewer", "text": text})
        await self.live.send_client_content(turns=user_turn(f"[SAY] {text}"), turn_complete=True)

    # --- the loop: utterances, policy, brain ----------------------------------

    async def _finish_utterance(self) -> None:
        text = self.candidate_buffer.strip()
        self.candidate_buffer = ""
        if not text:
            return
        self.utterance_end_at = self.last_candidate_speech_at or time.monotonic()
        self.session.transcript.append({"role": "candidate", "text": text, "at": time.time()})
        await self._send_json({"type": "transcript", "role": "candidate", "text": text})
        if policy.candidate_signals_done(text):
            self.candidate_done = True
        if "hint" in text.lower():
            self.tools.hints.requested = True
        if policy.candidate_asks_for_check(text):
            self.check_requested_at = time.monotonic()
            self.session.trigger_reason = "candidate_asked_for_check"
        self.pending_events.append(("candidate_spoke", ""))

    def _available_hint(self, now: float) -> tuple[int, str] | None:
        level = max(self.tools.hints.given_at, default=0) + 1
        if self.tools.hints.allowed(level, now):
            return level, hint_text(self.session, level)
        return None

    async def _run_brain(self, event: str, detail: str) -> None:
        self.thinking = True
        try:
            started = time.monotonic()
            since = (self.utterance_end_at if event == "candidate_spoke"
                     else self.last_release_at if event == "coach" else None)
            hint = self._available_hint(started)
            decision = await self.brain.decide(event, detail, hint)
            brain_s = time.monotonic() - started
            metrics.record(self.session.log_dir,
                           "analyze_verbal" if event == "candidate_spoke" else "brain_decision", brain_s,
                           event=event, ok=decision is not None,
                           spoke=bool(decision and decision.say.strip()))
            if decision is not None:
                reply = {"trigger": event, "since": since, "brain_s": brain_s} if since is not None else None
                await self._act(decision, hint, reply)
        except Exception:
            logger.exception("brain call failed")
        finally:
            self.thinking = False

    async def _act(self, d: BrainDecision, hint: tuple[int, str] | None,
                   reply: dict[str, Any] | None = None) -> None:
        if d.point_region_id:
            await self.tools.call("point_to_region", {"region_id": d.point_region_id, "line": d.point_line})
        if d.flag_category and d.point_region_id:
            await self.tools.call("flag_error_type", {"region_id": d.point_region_id, "line": d.point_line,
                                                      "category": d.flag_category})
        if d.used_hint_level and hint and d.used_hint_level == hint[0]:
            await self.tools.call("give_hint", {"level": hint[0]})
        if d.say.strip():
            await self._say(d.say.strip(), reply)

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            now = time.monotonic()
            spoke = self.last_candidate_speech_at

            if self.candidate_buffer and spoke and now - spoke >= UTTERANCE_END_SECONDS:
                await self._finish_utterance()

            # Candidate paused: ask the vision loop for a fresh pass (Phase 1 trigger_now).
            if spoke and spoke != self.triggered_for_speech_at and now - spoke >= TRIGGER_AFTER_SILENCE_SECONDS:
                self.triggered_for_speech_at = spoke
                self.session.trigger_reason = "candidate_stopped_speaking"

            if not self.thinking:
                release = policy.decide(self.session.findings, policy.ConversationState(
                    now=now,
                    last_candidate_speech_at=spoke,
                    last_release_at=self.last_release_at,
                    candidate_done_or_tracing=self.candidate_done,
                    interviewer_speaking=self.interviewer_speaking or self.awaiting_response,
                    candidate_asked_for_check=self.check_requested_at is not None
                    and now - self.check_requested_at < CHECK_WINDOW_SECONDS,
                ))
                if release is not None:
                    release.finding.status = "released"
                    self.last_release_at = now
                    self.check_requested_at = None
                    await self.notify_board()
                    await self._send_json({"type": "released", "findingId": release.finding.id,
                                           "mode": release.mode})
                    self.pending_events.append(("coach", coach_detail(release)))

            if self.pending_events and not self.thinking:
                # Coach events win; otherwise answer the latest candidate utterance only.
                coach = [e for e in self.pending_events if e[0] == "coach"]
                event = coach[0] if coach else self.pending_events[-1]
                self.pending_events.clear()
                self.thinking = True  # set before the task starts so the next tick waits
                asyncio.create_task(self._run_brain(*event))
