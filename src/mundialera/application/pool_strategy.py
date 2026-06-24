from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mundialera.domain.models import PredictionOutcome, Scoreline

DEFAULT_POOL_POSITION = 40
DEFAULT_POOL_SIZE = 50
DEFAULT_POOL_STRATEGY = "aggressive_high"
DEFAULT_STRATEGY_HORIZON = "tournament"
DEFAULT_TOURNAMENT_PHASE = "final_phase"
FINAL_PHASE_ALIASES = frozenset(
    {
        "final_phase",
        "fase_final",
        "phase_final",
        "late_group",
        "final_group",
        "knockout",
        "elimination",
    }
)


@dataclass(frozen=True, slots=True)
class PoolStrategyContext:
    position: int = DEFAULT_POOL_POSITION
    pool_size: int = DEFAULT_POOL_SIZE
    strategy: str = DEFAULT_POOL_STRATEGY
    horizon: str = DEFAULT_STRATEGY_HORIZON
    tournament_phase: str = DEFAULT_TOURNAMENT_PHASE

    @property
    def risk_pressure(self) -> float:
        if self.pool_size <= 1:
            return 0.0
        return _clamp((self.position - 1) / (self.pool_size - 1), 0.0, 1.0)

    @property
    def tournament_phase_key(self) -> str:
        return self.tournament_phase.strip().casefold()

    @property
    def is_final_phase(self) -> bool:
        return self.tournament_phase_key in FINAL_PHASE_ALIASES

    @property
    def phase_risk_boost(self) -> float:
        if not self.is_final_phase:
            return 0.0
        return 0.14 if self.risk_pressure >= 0.75 else 0.10

    @property
    def effective_risk_pressure(self) -> float:
        return _clamp(self.risk_pressure + self.phase_risk_boost, 0.0, 1.0)

    def to_payload(self) -> dict[str, object]:
        return {
            "position": self.position,
            "pool_size": self.pool_size,
            "risk_pressure": round(self.risk_pressure, 4),
            "effective_risk_pressure": round(self.effective_risk_pressure, 4),
            "strategy": self.strategy,
            "horizon": self.horizon,
            "tournament_phase": self.tournament_phase,
            "final_phase_aggression": self.is_final_phase,
            "phase_risk_boost": round(self.phase_risk_boost, 4),
        }


@dataclass(frozen=True, slots=True)
class StrategyMemory:
    sample_size: int = 0
    under_total_rate: float = 0.0
    under_margin_rate: float = 0.0
    false_draw_rate: float = 0.0
    missed_draw_rate: float = 0.0
    winner_accuracy: float = 0.0
    exact_hit_rate: float = 0.0
    bucket_repetition_rate: float = 0.0
    repeated_buckets: tuple[str, ...] = ()
    average_points: float = 0.0
    updated_at: str | None = None

    @property
    def total_high_pressure(self) -> bool:
        return self.under_total_rate >= 0.50

    @property
    def margin_pressure(self) -> bool:
        return self.under_margin_rate >= 0.50

    @property
    def draw_penalty_active(self) -> bool:
        return self.false_draw_rate > self.missed_draw_rate

    @property
    def bucket_penalty_active(self) -> bool:
        return self.bucket_repetition_rate > 0.35 and bool(self.repeated_buckets)

    def is_repeated_bucket(self, scoreline: Scoreline) -> bool:
        return scoreline.label() in self.repeated_buckets

    def to_payload(self) -> dict[str, object]:
        return {
            "sample_size": self.sample_size,
            "under_total_rate": round(self.under_total_rate, 4),
            "under_margin_rate": round(self.under_margin_rate, 4),
            "false_draw_rate": round(self.false_draw_rate, 4),
            "missed_draw_rate": round(self.missed_draw_rate, 4),
            "winner_accuracy": round(self.winner_accuracy, 4),
            "exact_hit_rate": round(self.exact_hit_rate, 4),
            "bucket_repetition_rate": round(self.bucket_repetition_rate, 4),
            "repeated_buckets": list(self.repeated_buckets),
            "average_points": round(self.average_points, 4),
            "updated_at": self.updated_at,
            "adjustments": {
                "boost_high_total": self.total_high_pressure,
                "boost_margin": self.margin_pressure,
                "penalize_false_draws": self.draw_penalty_active,
                "penalize_repeated_buckets": self.bucket_penalty_active,
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, sort_keys=True)


def build_pool_strategy_context(
    *,
    position: int = DEFAULT_POOL_POSITION,
    pool_size: int = DEFAULT_POOL_SIZE,
    strategy: str = DEFAULT_POOL_STRATEGY,
    horizon: str = DEFAULT_STRATEGY_HORIZON,
    tournament_phase: str = DEFAULT_TOURNAMENT_PHASE,
) -> PoolStrategyContext:
    return PoolStrategyContext(
        position=max(1, position),
        pool_size=max(2, pool_size),
        strategy=strategy.strip() or DEFAULT_POOL_STRATEGY,
        horizon=horizon.strip() or DEFAULT_STRATEGY_HORIZON,
        tournament_phase=tournament_phase.strip() or DEFAULT_TOURNAMENT_PHASE,
    )


def strategy_memory_from_json(value: str) -> StrategyMemory:
    if not value.strip():
        return StrategyMemory()
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        return StrategyMemory()
    return StrategyMemory(
        sample_size=_int(parsed.get("sample_size")),
        under_total_rate=_float(parsed.get("under_total_rate")),
        under_margin_rate=_float(parsed.get("under_margin_rate")),
        false_draw_rate=_float(parsed.get("false_draw_rate")),
        missed_draw_rate=_float(parsed.get("missed_draw_rate")),
        winner_accuracy=_float(parsed.get("winner_accuracy")),
        exact_hit_rate=_float(parsed.get("exact_hit_rate")),
        bucket_repetition_rate=_float(parsed.get("bucket_repetition_rate")),
        repeated_buckets=tuple(str(item) for item in _list(parsed.get("repeated_buckets"))),
        average_points=_float(parsed.get("average_points")),
        updated_at=_optional_str(parsed.get("updated_at")),
    )


def summarize_recent_performance(
    outcomes: list[PredictionOutcome],
    *,
    limit: int = 24,
    updated_at: datetime | None = None,
) -> StrategyMemory:
    recent = _recent_unique_outcomes(outcomes, limit=limit)
    total = len(recent)
    if total == 0:
        return StrategyMemory(updated_at=updated_at.isoformat() if updated_at else None)

    predicted_buckets = Counter(item.predicted.label() for item in recent)
    repeated = tuple(score for score, _count in predicted_buckets.most_common(2))
    repeated_count = sum(count for _score, count in predicted_buckets.most_common(2))
    points = [item.points for item in recent if item.points is not None]

    return StrategyMemory(
        sample_size=total,
        under_total_rate=_rate(
            sum(
                1
                for item in recent
                if _total_goals(item.predicted) < _total_goals(item.actual)
            ),
            total,
        ),
        under_margin_rate=_rate(
            sum(
                1
                for item in recent
                if abs(_goal_diff(item.predicted)) < abs(_goal_diff(item.actual))
            ),
            total,
        ),
        false_draw_rate=_rate(
            sum(
                1
                for item in recent
                if _result_class(item.predicted) == "draw"
                and _result_class(item.actual) != "draw"
            ),
            total,
        ),
        missed_draw_rate=_rate(
            sum(
                1
                for item in recent
                if _result_class(item.predicted) != "draw"
                and _result_class(item.actual) == "draw"
            ),
            total,
        ),
        winner_accuracy=_rate(sum(1 for item in recent if item.winner_ok), total),
        exact_hit_rate=_rate(sum(1 for item in recent if item.exact_ok), total),
        bucket_repetition_rate=_rate(repeated_count, total),
        repeated_buckets=repeated,
        average_points=sum(points) / len(points) if points else 0.0,
        updated_at=updated_at.isoformat() if updated_at else None,
    )


def _recent_unique_outcomes(
    outcomes: list[PredictionOutcome],
    *,
    limit: int,
) -> list[PredictionOutcome]:
    latest: dict[str, PredictionOutcome] = {}
    for outcome in outcomes:
        key = outcome.match_id or outcome.match_label
        current = latest.get(key)
        if current is None or outcome.settled_at >= current.settled_at:
            latest[key] = outcome
    ordered = sorted(latest.values(), key=lambda item: item.settled_at)
    return ordered[-limit:]


def _result_class(scoreline: Scoreline) -> str:
    if scoreline.home > scoreline.away:
        return "home"
    if scoreline.home < scoreline.away:
        return "away"
    return "draw"


def _total_goals(scoreline: Scoreline) -> int:
    return scoreline.home + scoreline.away


def _goal_diff(scoreline: Scoreline) -> int:
    return scoreline.home - scoreline.away


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def _float(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float | str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
