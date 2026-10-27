"""Board transcription: shared prompts and schemas, any provider (backend/models/providers)."""

from __future__ import annotations

from backend import config
from backend.models.prompts import (LINE_SYSTEM, LINE_USER, TRANSCRIBE_SYSTEM,
                                    TRANSCRIBE_SYSTEM_LINE_BOXES, TRANSCRIBE_USER)
from backend.models.providers import Provider, check_effort, get_provider
from backend.models.schemas import LineReading, ModelCall, Transcription, TranscriptionNoBox


class Transcriber:
    def __init__(self, provider: Provider, model: str | None = None, effort: str = "low"):
        self.provider = provider
        self.model = model or provider.default_model
        self.effort = check_effort(effort)

    @property
    def name(self) -> str:
        return self.provider.name

    def transcribe(self, image: bytes, mime: str) -> ModelCall[Transcription]:
        """Literal transcription of every region on the board."""
        line_boxes = config.LINE_PATCH
        call = self.provider.structured(
            system=TRANSCRIBE_SYSTEM_LINE_BOXES if line_boxes else TRANSCRIBE_SYSTEM,
            user_text=TRANSCRIBE_USER,
            image=image,
            mime=mime,
            # LINE_PATCH=0 sends exactly the original request format (no line boxes).
            schema=Transcription if line_boxes else TranscriptionNoBox,
            schema_name="board_transcription",
            model=self.model,
            effort=self.effort,
            # A full board is ~500 tokens (more with line boxes); a cap stops runaway repetition.
            max_tokens=3072 if line_boxes else 2048,
        )
        if call.parsed is not None and not line_boxes:
            call.parsed = Transcription.model_validate(call.parsed.model_dump())
        return call

    def transcribe_line(self, image: bytes, mime: str) -> ModelCall[LineReading]:
        """Literal transcription of one cropped line."""
        return self.provider.structured(
            system=LINE_SYSTEM,
            user_text=LINE_USER,
            image=image,
            mime=mime,
            schema=LineReading,
            schema_name="line_reading",
            model=self.model,
            effort=self.effort,
            max_tokens=256,
        )


def get_transcriber(provider: str, model: str | None = None, effort: str = "low") -> Transcriber:
    return Transcriber(get_provider(provider), model, effort)
