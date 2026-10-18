"""Board transcription behind a swappable interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.models import perceptron_client
from backend.models.prompts import LINE_SYSTEM, LINE_USER, TRANSCRIBE_SYSTEM, TRANSCRIBE_USER
from backend.models.schemas import LineReading, ModelCall, Transcription


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
        return perceptron_client.structured_completion(
            system=TRANSCRIBE_SYSTEM,
            user_text=TRANSCRIBE_USER,
            image=image,
            mime=mime,
            schema_model=Transcription,
            schema_name="board_transcription",
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            # A full board is ~500 tokens; a low cap stops runaway repetition fast.
            max_completion_tokens=2048,
        )

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
