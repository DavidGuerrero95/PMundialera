from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mundialera.domain.models import (
    Match,
    Prediction,
    PredictionOutcome,
    ProbabilityProfile,
    Scoreline,
    SubmissionResult,
    Team,
)
from mundialera.infrastructure.local_store.history import SqlitePredictionStore
from mundialera.interfaces.factory import _combined_prediction_memory


def test_prediction_store_persists_probability_profile_and_decision_flags(tmp_path: Path) -> None:
    store = SqlitePredictionStore(tmp_path, timezone_name="America/Bogota")
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
    assert store.database_path.name == "pmundialera.sqlite3"


def test_prediction_store_persists_tournament_state_memory(tmp_path: Path) -> None:
    store = SqlitePredictionStore(tmp_path, timezone_name="America/Bogota")

    store.write_tournament_state_memory("# state\n- Canada: P1 W1")

    assert store.load_tournament_state_memory() == "# state\n- Canada: P1 W1"


def test_prediction_store_persists_outcomes_idempotently(tmp_path: Path) -> None:
    store = SqlitePredictionStore(tmp_path, timezone_name="America/Bogota")
    outcome = PredictionOutcome(
        record_id="record-1",
        settled_at=datetime.fromisoformat("2026-06-18T12:00:00-05:00"),
        group="Mundial CoreX",
        match_id="1",
        match_label="A - B",
        predicted=Scoreline(2, 1),
        actual=Scoreline(2, 1),
        points=10,
        exact_ok=True,
        winner_ok=True,
        home_goals_ok=True,
        away_goals_ok=True,
        goal_diff_ok=True,
    )

    inserted = store.record_outcomes([outcome, outcome])

    assert inserted == 1
    assert store.load_outcomes() == [outcome]


def test_prediction_store_ignores_legacy_files(tmp_path: Path) -> None:
    (tmp_path / "predictions.jsonl").write_text(
        (
            '{"record_id":"legacy-1","created_at":"2026-06-18T10:00:00-05:00",'
            '"group":"Mundial CoreX","match_id":"1","match_label":"A - B",'
            '"kickoff":null,"primary":{"home":2,"away":1},"hedge":{"home":1,"away":1},'
            '"submitted_scoreline":{"home":2,"away":1},"confidence":0.61,'
            '"rationale":["legacy"],"submitted":true,"dry_run":false,'
            '"submission_message":"legacy","probabilities":{"home_win":0.5,"draw":0.25,'
            '"away_win":0.25,"over_2_5":0.45,"both_teams_to_score":0.5,'
            '"expected_home_goals":1.5,"expected_away_goals":1.0},'
            '"decision_flags":["legacy-flag"]}\n'
        ),
        encoding="utf-8",
    )
    (tmp_path / "outcomes.jsonl").write_text(
        (
            '{"record_id":"legacy-1","settled_at":"2026-06-18T12:00:00-05:00",'
            '"group":"Mundial CoreX","match_id":"1","match_label":"A - B",'
            '"predicted":{"home":2,"away":1},"actual":{"home":2,"away":1},'
            '"points":10,"exact_ok":true,"winner_ok":true,"home_goals_ok":true,'
            '"away_goals_ok":true,"goal_diff_ok":true}\n'
        ),
        encoding="utf-8",
    )
    (tmp_path / "learning-memory.md").write_text("# learning\n- keep calibration", encoding="utf-8")
    (tmp_path / "tournament-state.md").write_text("# state\n- A: P1 W1", encoding="utf-8")

    store = SqlitePredictionStore(tmp_path, timezone_name="America/Bogota")

    assert store.load_prediction_records() == []
    assert store.load_outcomes() == []
    assert store.load_learning_memory() == ""
    assert store.load_tournament_state_memory() == ""


def test_prediction_prompt_memory_uses_sqlite_only(tmp_path: Path) -> None:
    (tmp_path / "learning-memory.md").write_text("# legacy learning", encoding="utf-8")
    (tmp_path / "tournament-state.md").write_text("# legacy state", encoding="utf-8")
    store = SqlitePredictionStore(tmp_path, timezone_name="America/Bogota")
    store.write_learning_memory("# sqlite learning")
    store.write_tournament_state_memory("# sqlite state")

    memory = _combined_prediction_memory(store)

    assert "# sqlite learning" in memory
    assert "# sqlite state" in memory
    assert "legacy" not in memory
