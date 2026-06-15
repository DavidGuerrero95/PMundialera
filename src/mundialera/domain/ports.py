from __future__ import annotations

from datetime import datetime
from typing import Protocol

from mundialera.domain.models import (
    Match,
    Prediction,
    PredictionRecord,
    ResearchBrief,
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
        """Return primary and hedge scorelines."""


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


class PredictionHistory(Protocol):
    def load_prediction_records(self) -> list[PredictionRecord]:
        """Return persisted prediction attempts."""


class Clock(Protocol):
    def now(self) -> datetime:
        """Return current local time."""
