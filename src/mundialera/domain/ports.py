from __future__ import annotations

from datetime import datetime
from typing import Protocol

from mundialera.domain.models import (
    Match,
    Prediction,
    PredictionRecord,
    ResearchBrief,
    ResearchRecord,
    Scoreline,
    SubmissionResult,
)


class FixtureRepository(Protocol):
    def list_groups(self) -> list[str]:
        """Return group names visible to the authenticated user."""

    def list_matches(self, group_name: str) -> list[Match]:
        """Return matches for a group."""


class ResearchAgent(Protocol):
    def research(self, match: Match) -> ResearchBrief:
        """Return evidence and uncertainties for a match."""


class PredictionModel(Protocol):
    def predict(self, brief: ResearchBrief) -> Prediction:
        """Return the primary scoreline selected for submission."""


class PredictionSink(Protocol):
    def submit_prediction(
        self,
        match: Match,
        scoreline: Scoreline,
        *,
        dry_run: bool,
    ) -> SubmissionResult:
        """Submit or preview a prediction."""


class PredictionRecorder(Protocol):
    def record_prediction(
        self,
        prediction: Prediction,
        submission: SubmissionResult,
    ) -> None:
        """Persist a prediction attempt."""

    def load_learning_memory(self) -> str:
        """Return learning memory to include in future predictions."""


class PredictionSubmissionRegistry(Protocol):
    def has_successful_submission(self, group_name: str, match_id: str) -> bool:
        """Return whether a real successful submission is already recorded."""


class ResearchRecorder(Protocol):
    def record_research_brief(self, brief: ResearchBrief) -> None:
        """Persist the complete research and analysis context for a match."""


class PredictionHistory(Protocol):
    def load_prediction_records(self) -> list[PredictionRecord]:
        """Return persisted prediction attempts."""

    def load_research_records(self) -> list[ResearchRecord]:
        """Return persisted research contexts."""


class Clock(Protocol):
    def now(self) -> datetime:
        """Return current local time."""
