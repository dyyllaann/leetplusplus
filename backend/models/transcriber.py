"""Board transcription behind a swappable interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.models import perceptron_client
from backend.models.prompts import TRANSCRIBE_SYSTEM, TRANSCRIBE_USER
from backend.models.schemas import ModelCall, Transcription


class Transcriber(ABC):
    name: str

    @abstractmethod
    def transcribe(self, image: bytes, mime: str) -> ModelCall[Transcription]:
        """Literal transcription of every region on the board."""


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
        )


TRANSCRIBERS: dict[str, type[Transcriber]] = {
    PerceptronTranscriber.name: PerceptronTranscriber,
}


def get_transcriber(name: str, **kwargs) -> Transcriber:
    return TRANSCRIBERS[name](**kwargs)
