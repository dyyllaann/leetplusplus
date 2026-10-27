"""Logic analysis: shared prompts and schemas, any provider (backend/models/providers).

Every analyzer gets the same prompt, the same board image, and the same
transcription, and returns AnalysisResult findings plus call metadata.
"""

from __future__ import annotations

from backend.models.prompts import ANALYZE_SYSTEM, CODE_REVIEW_SYSTEM, analyze_user, code_review_user
from backend.models.providers import PROVIDER_NAMES, Provider, check_effort, get_provider
from backend.models.schemas import AnalysisResult, CodeReviewResult, ModelCall, Transcription

ANALYZERS = PROVIDER_NAMES


class Analyzer:
    def __init__(self, provider: Provider, model: str | None = None, effort: str = "medium"):
        self.provider = provider
        self.model = model or provider.default_model
        self.effort = check_effort(effort)

    @property
    def name(self) -> str:
        return self.provider.name

    def analyze(self, image: bytes, mime: str, transcription: Transcription,
                problem: str) -> ModelCall[AnalysisResult]:
        """Findings for the current board state."""
        return self.provider.structured(
            system=ANALYZE_SYSTEM,
            user_text=analyze_user(problem, transcription.model_dump_json(indent=2)),
            image=image,
            mime=mime,
            schema=AnalysisResult,
            schema_name="analysis_result",
            model=self.model,
            effort=self.effort,
            max_tokens=16000,
        )

    def review_code(self, problem: str, code: str, language: str) -> ModelCall[CodeReviewResult]:
        """Review typed code without requiring a board image."""
        return self.provider.structured(
            system=CODE_REVIEW_SYSTEM,
            user_text=code_review_user(problem, language, code),
            schema=CodeReviewResult,
            schema_name="code_review",
            model=self.model,
            effort=self.effort,
            max_tokens=4000,
        )


def get_analyzer(provider: str, model: str | None = None, effort: str = "medium") -> Analyzer:
    return Analyzer(get_provider(provider), model, effort)
