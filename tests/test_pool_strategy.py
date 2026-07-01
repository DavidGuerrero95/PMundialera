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
    assert round(round_trip.recent_under_margin_rate, 2) == 0.60


def test_strategy_memory_uses_latest_matchday_as_recency_overlay() -> None:
    tz = ZoneInfo("America/Bogota")
    old_day = datetime(2026, 6, 23, tzinfo=tz)
    latest_day = datetime(2026, 6, 24, tzinfo=tz)
    outcomes = [
        _outcome(1, Scoreline(2, 0), Scoreline(2, 0), points=10),
        _outcome(2, Scoreline(1, 0), Scoreline(1, 0), points=10),
        _outcome(3, Scoreline(1, 2), Scoreline(1, 2), points=10),
        _outcome(4, Scoreline(2, 1), Scoreline(2, 1), points=10),
        _outcome(5, Scoreline(2, 1), Scoreline(4, 1), points=5),
        _outcome(6, Scoreline(1, 2), Scoreline(0, 3), points=5),
        _outcome(7, Scoreline(1, 0), Scoreline(3, 1), points=5),
    ]
    dated = [
        _with_settled_at(outcome, old_day + timedelta(minutes=index))
        if index < 4
        else _with_settled_at(outcome, latest_day + timedelta(minutes=index))
        for index, outcome in enumerate(outcomes)
    ]

    memory = summarize_recent_performance(dated, limit=24)
    round_trip = strategy_memory_from_json(memory.to_json())

    assert round(round_trip.under_margin_rate, 2) == 0.43
    assert round(round_trip.recent_under_margin_rate, 2) == 1.00
    assert round_trip.margin_pressure is True


def test_strategy_memory_can_group_latest_matchday_by_played_date() -> None:
    settled_day = datetime(2026, 6, 26, tzinfo=ZoneInfo("America/Bogota"))
    outcomes = [
        _with_settled_at(_outcome(1, Scoreline(2, 1), Scoreline(2, 1), points=10), settled_day),
        _with_settled_at(_outcome(2, Scoreline(1, 4), Scoreline(0, 2), points=5), settled_day),
        _with_settled_at(_outcome(3, Scoreline(1, 3), Scoreline(2, 1), points=0), settled_day),
    ]
    played_dates = {
        outcomes[0].record_id: datetime(2026, 6, 24, tzinfo=ZoneInfo("America/Bogota")).date(),
        outcomes[1].record_id: datetime(2026, 6, 25, tzinfo=ZoneInfo("America/Bogota")).date(),
        outcomes[2].record_id: datetime(2026, 6, 25, tzinfo=ZoneInfo("America/Bogota")).date(),
    }

    memory = summarize_recent_performance(
        outcomes,
        limit=24,
        played_dates=played_dates,
    )

    assert memory.recent_sample_size == 2
    assert round(memory.recent_over_margin_rate, 2) == 1.00


def test_strategy_memory_activates_points_floor_after_bad_over_margin_day() -> None:
    latest_day = datetime(2026, 6, 25, tzinfo=ZoneInfo("America/Bogota"))
    outcomes = [
        _with_settled_at(
            _outcome(1, Scoreline(1, 4), Scoreline(0, 2), points=5),
            latest_day + timedelta(minutes=1),
        ),
        _with_settled_at(
            _outcome(2, Scoreline(1, 3), Scoreline(2, 1), points=0),
            latest_day + timedelta(minutes=2),
        ),
        _with_settled_at(
            _outcome(3, Scoreline(2, 1), Scoreline(1, 1), points=2),
            latest_day + timedelta(minutes=3),
        ),
        _with_settled_at(
            _outcome(4, Scoreline(1, 0), Scoreline(0, 0), points=2),
            latest_day + timedelta(minutes=4),
        ),
    ]

    memory = summarize_recent_performance(outcomes, limit=24)

    assert round(memory.recent_winner_accuracy, 2) == 0.25
    assert round(memory.recent_over_margin_rate, 2) == 1.00
    assert round(memory.recent_average_points, 2) == 2.25
    assert memory.points_floor_active is True
    assert memory.margin_pressure is False


def test_strategy_memory_activates_points_floor_after_three_match_missed_draw_crash() -> None:
    latest_day = datetime(2026, 6, 29, tzinfo=ZoneInfo("America/Bogota"))
    outcomes = [
        _with_settled_at(
            _outcome(1, Scoreline(2, 1), Scoreline(2, 1), points=10),
            latest_day + timedelta(minutes=1),
        ),
        _with_settled_at(
            _outcome(2, Scoreline(2, 1), Scoreline(1, 1), points=2),
            latest_day + timedelta(minutes=2),
        ),
        _with_settled_at(
            _outcome(3, Scoreline(2, 1), Scoreline(1, 1), points=2),
            latest_day + timedelta(minutes=3),
        ),
    ]

    memory = summarize_recent_performance(outcomes, limit=24)

    assert round(memory.recent_winner_accuracy, 2) == 0.33
    assert round(memory.recent_missed_draw_rate, 2) == 0.67
    assert round(memory.recent_over_margin_rate, 2) == 0.67
    assert round(memory.recent_average_points, 2) == 4.67
    assert memory.missed_draw_recovery_active is True
    assert memory.points_floor_active is False


def test_strategy_memory_activates_points_floor_after_three_low_point_missed_draws() -> None:
    latest_day = datetime(2026, 6, 29, tzinfo=ZoneInfo("America/Bogota"))
    outcomes = [
        _with_settled_at(
            _outcome(1, Scoreline(2, 1), Scoreline(2, 1), points=2),
            latest_day + timedelta(minutes=1),
        ),
        _with_settled_at(
            _outcome(2, Scoreline(2, 1), Scoreline(1, 1), points=4),
            latest_day + timedelta(minutes=2),
        ),
        _with_settled_at(
            _outcome(3, Scoreline(2, 1), Scoreline(1, 1), points=4),
            latest_day + timedelta(minutes=3),
        ),
    ]

    memory = summarize_recent_performance(outcomes, limit=24)

    assert round(memory.recent_average_points, 2) == 3.33
    assert memory.missed_draw_recovery_active is True
    assert memory.points_floor_active is True


def test_strategy_memory_recovers_under_totals_when_winners_were_correct() -> None:
    latest_day = datetime(2026, 6, 30, tzinfo=ZoneInfo("America/Bogota"))
    outcomes = [
        _with_settled_at(
            _outcome(1, Scoreline(0, 1), Scoreline(1, 2), points=7),
            latest_day + timedelta(minutes=1),
        ),
        _with_settled_at(
            _outcome(2, Scoreline(1, 0), Scoreline(3, 0), points=7),
            latest_day + timedelta(minutes=2),
        ),
    ]

    memory = summarize_recent_performance(outcomes, limit=24)
    payload = memory.to_payload()

    assert round(memory.recent_winner_accuracy, 2) == 1.00
    assert round(memory.recent_under_total_rate, 2) == 1.00
    assert round(memory.recent_under_margin_rate, 2) == 0.50
    assert round(memory.recent_average_points, 2) == 7.00
    assert memory.under_total_recovery_active is True
    assert memory.supported_margin_recovery_active is True
    assert memory.points_floor_active is False
    assert payload["adjustments"]["recover_under_totals"] is True
    assert payload["adjustments"]["recover_supported_margin"] is True


def _result(scoreline: Scoreline) -> str:
    if scoreline.home > scoreline.away:
        return "home"
    if scoreline.home < scoreline.away:
        return "away"
    return "draw"


def _with_settled_at(
    outcome: PredictionOutcome,
    settled_at: datetime,
) -> PredictionOutcome:
    return PredictionOutcome(
        record_id=outcome.record_id,
        settled_at=settled_at,
        group=outcome.group,
        match_id=outcome.match_id,
        match_label=outcome.match_label,
        predicted=outcome.predicted,
        actual=outcome.actual,
        points=outcome.points,
        exact_ok=outcome.exact_ok,
        winner_ok=outcome.winner_ok,
        home_goals_ok=outcome.home_goals_ok,
        away_goals_ok=outcome.away_goals_ok,
        goal_diff_ok=outcome.goal_diff_ok,
    )
