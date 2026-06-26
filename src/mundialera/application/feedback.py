from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from mundialera.application.pool_strategy import summarize_recent_performance
from mundialera.application.tournament_state import build_tournament_state_memory
from mundialera.domain.models import Match, PredictionOutcome, PredictionRecord, Scoreline
from mundialera.domain.ports import FixtureRepository
from mundialera.infrastructure.local_store.history import SqlitePredictionStore


class FeedbackService:
    def __init__(
        self,
        fixtures: FixtureRepository,
        store: SqlitePredictionStore,
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
        all_matches: list[Match] = []
        for group_name in group_names:
            group_matches = self._fixtures.list_matches(group_name)
            all_matches.extend(group_matches)
            matches = {match.match_id: match for match in group_matches}
            for record in records:
                if record.group != group_name:
                    continue
                match = matches.get(record.match_id)
                if match is None or match.result is None:
                    continue
                outcomes.append(_build_outcome(record, match, self._now))
        count = self._store.record_outcomes(outcomes)
        settled_outcomes = self._store.load_outcomes()
        played_dates = _played_dates_by_record_id(records)
        self._store.write_learning_memory(build_learning_memory(settled_outcomes))
        self._store.write_strategy_memory(
            build_strategy_memory(
                settled_outcomes,
                self._now,
                played_dates=played_dates,
            )
        )
        self._store.write_tournament_state_memory(build_tournament_state_memory(all_matches))
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

    outcomes = _latest_outcomes_by_real_match(outcomes)
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
        "Do not overfit single matches; convert errors into conservative, reusable rules.",
        "",
        "## Scorecard",
        f"- Settled predictions: {total}",
        f"- Exact score hit rate: {_pct(exact, total)}",
        f"- Winner/draw hit rate: {_pct(winner, total)}",
        f"- Home goals hit rate: {_pct(home_goals, total)}",
        f"- Away goals hit rate: {_pct(away_goals, total)}",
        f"- Goal-difference hit rate: {_pct(diff, total)}",
        f"- Average GolPredictor points: {avg_points:.2f}",
        f"- Sample reliability: {_sample_reliability(total)}",
        "",
        "## Error tendencies",
        *[f"- {item}" for item in patterns],
        "",
        "## Calibration rules",
        "- Treat this memory as a weak prior when settled sample is below 20 matches.",
        "- Prefer probability calibration over memorizing specific teams or one-off results.",
        (
            "- Lower confidence when market/ranking favorite lacks lineup, goalkeeper, "
            "recent-stat, or set-piece support."
        ),
        "- Do not use draw as the default response to uncertainty; require concrete draw evidence.",
        "- Restore favorite wins when class gap, market, form, and attacking ceiling align.",
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


def build_strategy_memory(
    outcomes: list[PredictionOutcome],
    updated_at: datetime,
    *,
    played_dates: dict[str, date] | None = None,
) -> str:
    return summarize_recent_performance(
        outcomes,
        updated_at=updated_at,
        played_dates=played_dates,
    ).to_json()


def _played_dates_by_record_id(records: list[PredictionRecord]) -> dict[str, date]:
    return {
        record.record_id: record.kickoff.date()
        for record in records
        if record.kickoff is not None
    }


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


def _sample_reliability(total: int) -> str:
    if total < 5:
        return "very low; use only as directional guardrail"
    if total < 20:
        return "low; avoid strong conclusions"
    if total < 60:
        return "medium; monitor drift"
    return "higher; still validate by current evidence"


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
        if _winner(item.predicted) == "draw" and _winner(item.actual) != "draw":
            counter["The model overpredicted draws; do not default uncertainty to 1-1."] += 1
            if _margin(item.actual) >= 2:
                counter["Draw guardrail was too aggressive against a clear winner."] += 1
        if _winner(item.actual) == "draw" and _winner(item.predicted) != "draw":
            counter[
                "The model missed a draw; raise draw-risk calibration for similar matches."
            ] += 1
        if _winner(item.predicted) != "draw" and _margin(item.predicted) > _margin(item.actual):
            counter["The model overestimated the favorite margin."] += 1
        if item.winner_ok and not item.exact_ok:
            counter["Winner was right but exact score was off."] += 1
    if not counter:
        return ["No dominant error pattern yet."]
    return [f"{label} ({count}x)" for label, count in counter.most_common(5)]


def _latest_outcomes_by_real_match(outcomes: list[PredictionOutcome]) -> list[PredictionOutcome]:
    latest: dict[str, PredictionOutcome] = {}
    for outcome in outcomes:
        key = outcome.match_id or outcome.match_label
        current = latest.get(key)
        if current is None or outcome.settled_at >= current.settled_at:
            latest[key] = outcome
    return sorted(latest.values(), key=lambda item: item.settled_at)


def _margin(score: Scoreline) -> int:
    return abs(score.home - score.away)
