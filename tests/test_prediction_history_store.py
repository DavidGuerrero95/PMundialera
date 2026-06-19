from __future__ import annotations

from pathlib import Path

from mundialera.domain.models import (
    Match,
    Prediction,
    ProbabilityProfile,
    Scoreline,
    SubmissionResult,
    Team,
)
from mundialera.infrastructure.local_store.history import JsonlPredictionStore


def test_prediction_store_persists_probability_profile_and_decision_flags(tmp_path: Path) -> None:
    store = JsonlPredictionStore(tmp_path, timezone_name="America/Bogota")
    match = Match(match_id="1", kickoff=None, home=Team("A"), away=Team("B"), group="G")
    profile = ProbabilityProfile(
        home_win=0.31,
        draw=0.34,
        away_win=0.35,
        over_2_5=0.42,
        both_teams_to_score=0.51,
        expected_home_goals=1.1,
        expected_away_goals=1.2,
    )
    prediction = Prediction(
        match=match,
        primary=Scoreline(1, 1),
        hedge=Scoreline(1, 2),
        confidence=0.52,
        rationale=["audited"],
        probabilities=profile,
        decision_flags=["draw-risk-covered-in-hedge"],
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

    loaded = store.load_prediction_records()[0]

    assert loaded.probabilities == profile
    assert loaded.decision_flags == ["draw-risk-covered-in-hedge"]


def test_prediction_store_persists_tournament_state_memory(tmp_path: Path) -> None:
    store = JsonlPredictionStore(tmp_path, timezone_name="America/Bogota")

    store.write_tournament_state_memory("# state\n- Canadá: P1 W1")

    assert store.load_tournament_state_memory() == "# state\n- Canadá: P1 W1"
    assert store.tournament_state_path.name == "tournament-state.md"
