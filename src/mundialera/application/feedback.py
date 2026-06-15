from __future__ import annotations

from collections import Counter
from datetime import datetime

from mundialera.domain.models import Match, PredictionOutcome, PredictionRecord, Scoreline
from mundialera.domain.ports import FixtureRepository
from mundialera.infrastructure.local_store.history import JsonlPredictionStore


class FeedbackService:
    def __init__(
        self,
        fixtures: FixtureRepository,
        store: JsonlPredictionStore,
        *,
        now: datetime,
    ) -> None:
        self._fixtures = fixtures
        self._store = store
        self._now = now

    def settle_groups(self, group_names: list[str]) -> int:
        records = [
            record
            for record in self._store.load_prediction_records()
            if record.submitted and not record.dry_run
        ]
        outcomes: list[PredictionOutcome] = []
        for group_name in group_names:
            matches = {match.match_id: match for match in self._fixtures.list_matches(group_name)}
            for record in records:
                if record.group != group_name:
                    continue
                match = matches.get(record.match_id)
                if match is None or match.result is None:
                    continue
                outcomes.append(_build_outcome(record, match, self._now))
        count = self._store.record_outcomes(outcomes)
        self._store.write_learning_memory(build_learning_memory(self._store.load_outcomes()))
        return count

    def close(self) -> None:
        close = getattr(self._fixtures, "close", None)
        if callable(close):
            close()


def build_learning_memory(outcomes: list[PredictionOutcome]) -> str:
    if not outcomes:
        return (
            "# PMundialera learning memory\n\n"
            "No settled predictions yet. Prefer conservative confidence and explain uncertainty."
        )

    total = len(outcomes)
    exact = sum(1 for item in outcomes if item.exact_ok)
    winner = sum(1 for item in outcomes if item.winner_ok)
    home_goals = sum(1 for item in outcomes if item.home_goals_ok)
    away_goals = sum(1 for item in outcomes if item.away_goals_ok)
    diff = sum(1 for item in outcomes if item.goal_diff_ok)
    avg_points = _average([item.points for item in outcomes if item.points is not None])
    patterns = _error_patterns(outcomes)
    recent = outcomes[-8:]

    lines = [
        "# PMundialera learning memory",
        "",
        "Use this as private feedback from previous GolPredictor predictions.",
        "",
        "## Scorecard",
        f"- Settled predictions: {total}",
        f"- Exact score hit rate: {_pct(exact, total)}",
        f"- Winner/draw hit rate: {_pct(winner, total)}",
        f"- Home goals hit rate: {_pct(home_goals, total)}",
        f"- Away goals hit rate: {_pct(away_goals, total)}",
        f"- Goal-difference hit rate: {_pct(diff, total)}",
        f"- Average GolPredictor points: {avg_points:.2f}",
        "",
        "## Error tendencies",
        *[f"- {item}" for item in patterns],
        "",
        "## Recent settled matches",
        *[
            (
                f"- {item.match_label}: predicted {item.predicted.label()}, "
                f"actual {item.actual.label()}, points={item.points}"
            )
            for item in recent
        ],
    ]
    return "\n".join(lines)


def _build_outcome(
    record: PredictionRecord,
    match: Match,
    settled_at: datetime,
) -> PredictionOutcome:
    if match.result is None:
        msg = "Cannot settle a match without result"
        raise ValueError(msg)
    predicted = record.submitted_scoreline
    return PredictionOutcome(
        record_id=record.record_id,
        settled_at=settled_at,
        group=record.group,
        match_id=record.match_id,
        match_label=record.match_label,
        predicted=predicted,
        actual=match.result,
        points=match.points,
        exact_ok=predicted == match.result,
        winner_ok=_winner(predicted) == _winner(match.result),
        home_goals_ok=predicted.home == match.result.home,
        away_goals_ok=predicted.away == match.result.away,
        goal_diff_ok=_goal_diff(predicted) == _goal_diff(match.result),
    )


def _winner(score: Scoreline) -> str:
    if score.home > score.away:
        return "home"
    if score.home < score.away:
        return "away"
    return "draw"


def _goal_diff(score: Scoreline) -> int:
    return score.home - score.away


def _average(values: list[int]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _pct(count: int, total: int) -> str:
    return f"{(count / total) * 100:.1f}%"


def _error_patterns(outcomes: list[PredictionOutcome]) -> list[str]:
    counter: Counter[str] = Counter()
    for item in outcomes:
        if item.predicted.home > item.actual.home:
            counter["The model overestimated home-team goals."] += 1
        elif item.predicted.home < item.actual.home:
            counter["The model underestimated home-team goals."] += 1
        if item.predicted.away > item.actual.away:
            counter["The model overestimated away-team goals."] += 1
        elif item.predicted.away < item.actual.away:
            counter["The model underestimated away-team goals."] += 1
        if not item.winner_ok:
            counter["The model missed winner/draw classification."] += 1
        if item.winner_ok and not item.exact_ok:
            counter["Winner was right but exact score was off."] += 1
    if not counter:
        return ["No dominant error pattern yet."]
    return [f"{label} ({count}x)" for label, count in counter.most_common(5)]
