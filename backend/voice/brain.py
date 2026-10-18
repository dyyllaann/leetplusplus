"""Claude decides what the interviewer says; Gemini Live only speaks it.

One call per event (candidate finished speaking, policy release, session start).
The brain sees the conversation, the literal board text, and the hint the backend
currently allows. It never sees the analyzer's finding messages (they can name the fix).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend import config
from backend.models.call_log import save_call
from backend.models.schemas import ModelCall
from backend.session.state import Session
from backend.voice.tools import ERROR_CATEGORIES

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts/brain.md"
HISTORY_TURNS = 30

FlagCategory = Literal[tuple(["", *ERROR_CATEGORIES])]  # type: ignore[valid-type]


class BrainDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    say: str = Field(description='Exact words to speak aloud, or "" to stay silent')
    point_region_id: str = Field(description='Region to highlight, or ""')
    point_line: int = Field(description="Line to highlight, or 0")
    flag_category: FlagCategory = Field(description='Error category you named aloud, or ""')
    used_hint_level: int = Field(description="Level of the available hint you used, or 0")


def render_request(session: Session, event: str, detail: str, hint: tuple[int, str] | None) -> str:
    convo = [f"{t['role']}: {t['text']}" for t in session.transcript[-HISTORY_TURNS:]] or ["(nothing yet)"]
    if session.transcription and session.transcription.regions:
        board = [f"{r.id} ({r.type}):\n" + "\n".join(f"  line {ln.n}: {ln.text}" for ln in r.lines)
                 for r in session.transcription.regions]
    else:
        board = ["(empty)"]
    hint_text = f"level {hint[0]}: {hint[1]}" if hint else "none available right now"
    return (
        "Conversation so far:\n" + "\n".join(convo)
        + "\n\nCurrent board (literal transcription):\n" + "\n".join(board)
        + f"\n\nAvailable hint: {hint_text}"
        + f"\n\nEvent: {event}" + (f"\n{detail}" if detail else "")
    )


class InterviewerBrain:
    def __init__(self, session: Session, model: str = config.BRAIN_MODEL, effort: str = config.BRAIN_EFFORT):
        import anthropic

        self.session = session
        self.model = model
        self.effort = effort
        self.client = anthropic.AsyncAnthropic()
        self.system = PROMPT_PATH.read_text().format(problem=session.problem_text)
        self.calls = 0

    async def decide(self, event: str, detail: str = "", hint: tuple[int, str] | None = None) -> BrainDecision | None:
        request = render_request(self.session, event, detail, hint)
        call: ModelCall = ModelCall(provider="claude", model=self.model, parsed=None, latency_s=0.0,
                                    request={"system": self.system, "user": request})
        start = time.perf_counter()
        try:
            response = await self.client.beta.messages.parse(
                model=self.model,
                max_tokens=4000,
                system=self.system,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": request}],
                output_format=BrainDecision,
            )
            call.latency_s = time.perf_counter() - start
            call.response = response.model_dump(mode="json")
            call.input_tokens = response.usage.input_tokens
            call.output_tokens = response.usage.output_tokens
            if response.stop_reason in ("refusal", "max_tokens"):
                raise RuntimeError(f"stop_reason={response.stop_reason}")
            call.parsed = response.parsed_output
        except Exception as exc:
            call.latency_s = call.latency_s or time.perf_counter() - start
            call.error = f"{type(exc).__name__}: {exc}"
        self.calls += 1
        save_call(self.session.log_dir, f"brain_{self.calls:03d}_{event}", call)
        return call.parsed
