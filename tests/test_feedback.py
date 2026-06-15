from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mundialera.application.feedback import FeedbackService
from mundialera.domain.models import Match, Prediction, Scoreline, SubmissionResult, Team
from mundialera.infrastructure.local_store.history import JsonlPredictionStore


class FakeFixtures:
    def list_groups(self) -> list[str]:
        return ["Mundial CoreX"]

    def list_matches(self, group_name: str) -> list[Match]:
        return [
            Match(
                match_id="1",
                kickoff=None,
                home=Team("A"),
                away=Team("B"),
                group=group_name,
                result=Scoreline(2, 1),
                points=7,
            )
        ]


def test_feedback_settles_submitted_prediction_and_writes_memory(tmp_path: Path) -> None:
    store = JsonlPredictionStore(tmp_path, timezone_name="America/Bogota")
    match = Match(
        match_id="1",
        kickoff=None,
        home=Team("A"),
        away=Team("B"),
        group="Mundial CoreX",
    )
    prediction = Prediction(
        match=match,
        primary=Scoreline(2, 0),
        hedge=Scoreline(2, 1),
        confidence=0.7,
        rationale=["test"],
    )
    store.record_prediction(
        prediction,
        SubmissionResult(
            match=match,
            scoreline=prediction.primary,
            submitted=True,
            dry_run=False,
            message="submitted",
        ),
    )
    service = FeedbackService(
        fixtures=FakeFixtures(),
        store=store,
        now=datetime(2026, 6, 15, tzinfo=ZoneInfo("America/Bogota")),
    )

    count = service.settle_groups(["Mundial CoreX"])

    assert count == 1
    outcomes = store.load_outcomes()
    assert outcomes[0].winner_ok is True
    assert outcomes[0].away_goals_ok is False
    assert "Settled predictions: 1" in store.load_learning_memory()
