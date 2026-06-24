from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mundialera.application.pool_strategy import (
    build_pool_strategy_context,
    strategy_memory_from_json,
    summarize_recent_performance,
)
from mundialera.domain.models import PredictionOutcome, Scoreline


def _outcome(
    index: int,
    predicted: Scoreline,
    actual: Scoreline,
    *,
    points: int = 0,
) -> PredictionOutcome:
    tz = ZoneInfo("America/Bogota")
    return PredictionOutcome(
        record_id=f"r-{index}",
        settled_at=datetime(2026, 6, 15, tzinfo=tz) + timedelta(minutes=index),
        group="Mundial CoreX",
        match_id=f"m-{index}",
        match_label=f"A{index} - B{index}",
        predicted=predicted,
        actual=actual,
        points=points,
        exact_ok=predicted == actual,
        winner_ok=_result(predicted) == _result(actual),
        home_goals_ok=predicted.home == actual.home,
        away_goals_ok=predicted.away == actual.away,
        goal_diff_ok=predicted.home - predicted.away == actual.home - actual.away,
    )


def test_pool_strategy_context_calculates_risk_pressure_for_rank_40_of_50() -> None:
    context = build_pool_strategy_context(position=40, pool_size=50)

    assert context.strategy == "aggressive_high"
    assert context.horizon == "tournament"
    assert context.tournament_phase == "final_phase"
    assert context.is_final_phase is True
    assert context.to_payload()["risk_pressure"] == 0.7959
    assert context.to_payload()["effective_risk_pressure"] == 0.9359


def test_strategy_memory_summarizes_recent_unique_underestimation_patterns() -> None:
    outcomes = [
        _outcome(1, Scoreline(2, 1), Scoreline(3, 1), points=6),
        _outcome(2, Scoreline(1, 1), Scoreline(0, 0), points=5),
        _outcome(3, Scoreline(1, 0), Scoreline(0, 2), points=0),
        _outcome(4, Scoreline(2, 1), Scoreline(2, 1), points=10),
        _outcome(5, Scoreline(1, 1), Scoreline(3, 1), points=0),
    ]
    duplicate_older = _outcome(99, Scoreline(3, 0), Scoreline(3, 0), points=10)
    duplicate_older = PredictionOutcome(
        record_id=duplicate_older.record_id,
        settled_at=outcomes[0].settled_at - timedelta(hours=1),
        group=duplicate_older.group,
        match_id=outcomes[0].match_id,
        match_label=duplicate_older.match_label,
        predicted=duplicate_older.predicted,
        actual=duplicate_older.actual,
        points=duplicate_older.points,
        exact_ok=duplicate_older.exact_ok,
        winner_ok=duplicate_older.winner_ok,
        home_goals_ok=duplicate_older.home_goals_ok,
        away_goals_ok=duplicate_older.away_goals_ok,
        goal_diff_ok=duplicate_older.goal_diff_ok,
    )

    memory = summarize_recent_performance([duplicate_older, *outcomes], limit=24)
    round_trip = strategy_memory_from_json(memory.to_json())

    assert round_trip.sample_size == 5
    assert round(round_trip.under_total_rate, 2) == 0.60
    assert round(round_trip.under_margin_rate, 2) == 0.60
    assert round(round_trip.false_draw_rate, 2) == 0.20
    assert round(round_trip.missed_draw_rate, 2) == 0.00
    assert round(round_trip.winner_accuracy, 2) == 0.60
    assert round(round_trip.exact_hit_rate, 2) == 0.20
    assert round(round_trip.bucket_repetition_rate, 2) == 0.80
    assert round_trip.repeated_buckets == ("2 - 1", "1 - 1")
    assert round_trip.total_high_pressure is True
    assert round_trip.margin_pressure is True
    assert round_trip.draw_penalty_active is True
    assert round_trip.bucket_penalty_active is True


def _result(scoreline: Scoreline) -> str:
    if scoreline.home > scoreline.away:
        return "home"
    if scoreline.home < scoreline.away:
        return "away"
    return "draw"
