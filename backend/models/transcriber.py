"""Board transcription behind a swappable interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend import config
from backend.models import perceptron_client
from backend.models.prompts import (LINE_SYSTEM, LINE_USER, TRANSCRIBE_SYSTEM,
                                    TRANSCRIBE_SYSTEM_LINE_BOXES, TRANSCRIBE_USER)
from backend.models.schemas import LineReading, ModelCall, Transcription, TranscriptionNoBox


class Transcriber(ABC):
    name: str

    @abstractmethod
    def transcribe(self, image: bytes, mime: str) -> ModelCall[Transcription]:
        """Literal transcription of every region on the board."""

    @abstractmethod
    def transcribe_line(self, image: bytes, mime: str) -> ModelCall[LineReading]:
        """Literal transcription of one cropped line."""


class PerceptronTranscriber(Transcriber):
    name = "perceptron"

    def __init__(self, model: str = perceptron_client.DEFAULT_MODEL,
                 reasoning_effort: str | None = "low"):
        self.model = model
        self.reasoning_effort = reasoning_effort

    def transcribe(self, image: bytes, mime: str) -> ModelCall[Transcription]:
        line_boxes = config.LINE_PATCH
        call = perceptron_client.structured_completion(
            system=TRANSCRIBE_SYSTEM_LINE_BOXES if line_boxes else TRANSCRIBE_SYSTEM,
            user_text=TRANSCRIBE_USER,
            image=image,
            mime=mime,
            # LINE_PATCH=0 sends exactly the original request format (no line boxes).
            schema_model=Transcription if line_boxes else TranscriptionNoBox,
            schema_name="board_transcription",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            # A full board is ~500 tokens (more with line boxes); a cap stops runaway repetition.
            max_completion_tokens=3072 if line_boxes else 2048,
        )
        if call.parsed is not None and not line_boxes:
            call.parsed = Transcription.model_validate(call.parsed.model_dump())
        return call

    def transcribe_line(self, image: bytes, mime: str) -> ModelCall[LineReading]:
        return perceptron_client.structured_completion(
            system=LINE_SYSTEM,
            user_text=LINE_USER,
            image=image,
            mime=mime,
            schema_model=LineReading,
            schema_name="line_reading",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            max_completion_tokens=256,
        )


TRANSCRIBERS: dict[str, type[Transcriber]] = {
    PerceptronTranscriber.name: PerceptronTranscriber,
}


def get_transcriber(name: str, **kwargs) -> Transcriber:
    return TRANSCRIBERS[name](**kwargs)
