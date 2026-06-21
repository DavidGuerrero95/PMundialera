from __future__ import annotations

import math
from dataclasses import dataclass

from mundialera.application.pool_strategy import PoolStrategyContext, StrategyMemory
from mundialera.domain.models import ProbabilityProfile, Scoreline


@dataclass(frozen=True, slots=True)
class ScorelineProbability:
    home: int
    away: int
    probability: float

    @property
    def scoreline(self) -> Scoreline:
        return Scoreline(self.home, self.away)


@dataclass(frozen=True, slots=True)
class ExpectedPointsCandidate:
    home: int
    away: int
    exact_probability: float
    expected_pool_points: float

    @property
    def scoreline(self) -> Scoreline:
        return Scoreline(self.home, self.away)


def build_scoreline_distribution(
    profile: ProbabilityProfile,
    *,
    max_goals: int = 6,
) -> list[ScorelineProbability]:
    raw: list[ScorelineProbability] = []
    for home in range(max_goals + 1):
        for away in range(max_goals + 1):
            raw.append(
                ScorelineProbability(
                    home=home,
                    away=away,
                    probability=_poisson_pmf(profile.expected_home_goals, home)
                    * _poisson_pmf(profile.expected_away_goals, away),
                )
            )
    total = sum(item.probability for item in raw)
    if total <= 0:
        return []
    return [
        ScorelineProbability(
            home=item.home,
            away=item.away,
            probability=item.probability / total,
        )
        for item in raw
    ]


def coherent_profile_from_expected_goals(
    expected_home_goals: float,
    expected_away_goals: float,
) -> ProbabilityProfile:
    seed_profile = ProbabilityProfile(
        home_win=0.34,
        draw=0.33,
        away_win=0.33,
        over_2_5=0.50,
        both_teams_to_score=0.50,
        expected_home_goals=max(0.05, expected_home_goals),
        expected_away_goals=max(0.05, expected_away_goals),
    )
    distribution = build_scoreline_distribution(seed_profile)
    return probability_profile_from_distribution(distribution)


def probability_profile_from_distribution(
    distribution: list[ScorelineProbability],
) -> ProbabilityProfile:
    home_win = sum(item.probability for item in distribution if item.home > item.away)
    draw = sum(item.probability for item in distribution if item.home == item.away)
    away_win = sum(item.probability for item in distribution if item.home < item.away)
    over_2_5 = sum(item.probability for item in distribution if item.home + item.away >= 3)
    btts = sum(item.probability for item in distribution if item.home > 0 and item.away > 0)
    expected_home = sum(item.home * item.probability for item in distribution)
    expected_away = sum(item.away * item.probability for item in distribution)
    total = home_win + draw + away_win
    if total > 0:
        home_win /= total
        draw /= total
        away_win /= total
    return ProbabilityProfile(
        home_win=round(home_win, 4),
        draw=round(draw, 4),
        away_win=round(away_win, 4),
        over_2_5=round(over_2_5, 4),
        both_teams_to_score=round(btts, 4),
        expected_home_goals=round(expected_home, 2),
        expected_away_goals=round(expected_away, 2),
    )


def expected_points_candidates(
    profile: ProbabilityProfile,
    *,
    max_goals: int = 6,
    knockout: bool = False,
    top: int | None = None,
) -> list[ExpectedPointsCandidate]:
    distribution = build_scoreline_distribution(profile, max_goals=max_goals)
    candidates = [
        ExpectedPointsCandidate(
            home=item.home,
            away=item.away,
            exact_probability=round(item.probability, 6),
            expected_pool_points=round(
                expected_pool_points(item.scoreline, distribution, knockout=knockout),
                4,
            ),
        )
        for item in distribution
    ]
    candidates.sort(
        key=lambda item: (
            item.expected_pool_points,
            item.exact_probability,
            -abs(item.home - item.away),
        ),
        reverse=True,
    )
    return candidates[:top] if top is not None else candidates


def best_scoreline_by_expected_points(profile: ProbabilityProfile) -> Scoreline:
    candidates = expected_points_candidates(profile, top=1)
    return candidates[0].scoreline if candidates else Scoreline(1, 1)


def best_scoreline_by_pool_strategy(
    profile: ProbabilityProfile,
    *,
    strategy: str = "aggressive_high",
    pool_context: PoolStrategyContext | None = None,
    strategy_memory: StrategyMemory | None = None,
) -> Scoreline:
    candidates = expected_points_candidates(profile)
    if not candidates:
        return Scoreline(1, 1)
    strategy_name = pool_context.strategy if pool_context is not None else strategy
    if strategy_name == "aggressive_high":
        return _aggressive_high_scoreline(
            profile,
            candidates,
            strategy_memory=strategy_memory,
            risk_pressure=pool_context.risk_pressure if pool_context is not None else 0.80,
        )
    if strategy_name != "chasing":
        return candidates[0].scoreline
    return _chasing_scoreline(profile, candidates)


def hedge_scoreline_by_expected_points(
    profile: ProbabilityProfile,
    primary: Scoreline,
) -> Scoreline:
    for candidate in expected_points_candidates(profile, top=12):
        scoreline = candidate.scoreline
        if scoreline != primary:
            return scoreline
    return primary


def expected_pool_points(
    candidate: Scoreline,
    distribution: list[ScorelineProbability],
    *,
    knockout: bool = False,
) -> float:
    result_weight = 10.0 if knockout else 5.0
    home_goal_weight = 4.0 if knockout else 2.0
    away_goal_weight = 4.0 if knockout else 2.0
    diff_weight = 2.0 if knockout else 1.0
    result = _result_class(candidate)
    diff = candidate.home - candidate.away
    return (
        result_weight
        * sum(item.probability for item in distribution if _result_class(item.scoreline) == result)
        + home_goal_weight
        * sum(item.probability for item in distribution if item.home == candidate.home)
        + away_goal_weight
        * sum(item.probability for item in distribution if item.away == candidate.away)
        + diff_weight
        * sum(item.probability for item in distribution if item.home - item.away == diff)
    )


def result_probability(profile: ProbabilityProfile, scoreline: Scoreline) -> float:
    result = _result_class(scoreline)
    if result == "home":
        return profile.home_win
    if result == "away":
        return profile.away_win
    return profile.draw


def scoreline_distribution_payload(
    profile: ProbabilityProfile,
    *,
    max_goals: int = 6,
) -> list[dict[str, float | int]]:
    return [
        {
            "home": item.home,
            "away": item.away,
            "probability": round(item.probability, 6),
        }
        for item in build_scoreline_distribution(profile, max_goals=max_goals)
    ]


def expected_points_payload(
    profile: ProbabilityProfile,
    *,
    top: int = 10,
) -> list[dict[str, float | int]]:
    return [
        {
            "home": item.home,
            "away": item.away,
            "exact_probability": item.exact_probability,
            "expected_pool_points": item.expected_pool_points,
        }
        for item in expected_points_candidates(profile, top=top)
    ]


def _chasing_scoreline(
    profile: ProbabilityProfile,
    candidates: list[ExpectedPointsCandidate],
) -> Scoreline:
    leader = candidates[0]
    leader_scoreline = leader.scoreline
    leader_result = _result_class(leader_scoreline)
    favorite_probability = max(profile.home_win, profile.away_win)
    if leader_result == "draw":
        if profile.over_2_5 < 0.62 or profile.both_teams_to_score < 0.58:
            return leader_scoreline
        ep_tolerance = 0.24
    elif favorite_probability >= 0.70:
        ep_tolerance = 0.36
    elif profile.over_2_5 >= 0.60:
        ep_tolerance = 0.32
    elif favorite_probability >= 0.45:
        ep_tolerance = 0.18
    else:
        return leader_scoreline

    minimum_exact_probability = leader.exact_probability * 0.40
    viable = [
        candidate
        for candidate in candidates[:16]
        if _result_class(candidate.scoreline) == leader_result
        and candidate.expected_pool_points >= leader.expected_pool_points - ep_tolerance
        and candidate.exact_probability >= minimum_exact_probability
    ]
    if len(viable) <= 1:
        return leader_scoreline
    viable.sort(
        key=lambda item: _chasing_candidate_score(profile, leader, item),
        reverse=True,
    )
    return viable[0].scoreline


def _chasing_candidate_score(
    profile: ProbabilityProfile,
    leader: ExpectedPointsCandidate,
    candidate: ExpectedPointsCandidate,
) -> tuple[float, float, int, int]:
    leader_total = leader.home + leader.away
    candidate_total = candidate.home + candidate.away
    leader_margin = abs(leader.home - leader.away)
    candidate_margin = abs(candidate.home - candidate.away)
    favorite_probability = max(profile.home_win, profile.away_win)
    total_bonus = max(0, candidate_total - leader_total)
    margin_bonus = max(0, candidate_margin - leader_margin)
    if favorite_probability >= 0.70:
        upside_bonus = (margin_bonus * 0.30) + (total_bonus * 0.12)
    else:
        upside_bonus = (total_bonus * 0.22) + (margin_bonus * 0.10)
    return (
        candidate.expected_pool_points + upside_bonus,
        candidate.exact_probability,
        candidate_total,
        candidate_margin,
    )


def _aggressive_high_scoreline(
    profile: ProbabilityProfile,
    candidates: list[ExpectedPointsCandidate],
    *,
    strategy_memory: StrategyMemory | None,
    risk_pressure: float,
) -> Scoreline:
    leader = candidates[0]
    memory = strategy_memory or StrategyMemory()
    viable = [
        candidate
        for candidate in candidates[:36]
        if _is_aggressive_high_candidate(
            profile,
            leader,
            candidate,
            strategy_memory=memory,
        )
    ]
    if len(viable) <= 1:
        return leader.scoreline
    viable.sort(
        key=lambda item: _aggressive_candidate_score(
            profile,
            leader,
            item,
            strategy_memory=memory,
            risk_pressure=risk_pressure,
        ),
        reverse=True,
    )
    return viable[0].scoreline


def _is_aggressive_high_candidate(
    profile: ProbabilityProfile,
    leader: ExpectedPointsCandidate,
    candidate: ExpectedPointsCandidate,
    *,
    strategy_memory: StrategyMemory,
) -> bool:
    if candidate == leader:
        return True
    if candidate.exact_probability < leader.exact_probability * 0.35:
        return False
    if candidate.home > 3 or candidate.away > 3:
        return False
    if candidate.home + candidate.away > 4:
        return False
    if _is_unsupported_three_goal_shutout(profile, candidate.scoreline):
        return False
    if _is_unsupported_comfortable_margin(
        profile,
        candidate.scoreline,
        strategy_memory=strategy_memory,
    ):
        return False

    leader_result = _result_class(leader.scoreline)
    candidate_result = _result_class(candidate.scoreline)
    draw_ep_bypass = _is_aggressive_draw(profile, candidate.scoreline, strategy_memory)
    if not draw_ep_bypass and not _close_to_expected_points_leader(leader, candidate):
        return False
    strong_favorite = _strong_favorite_class(profile)
    if strong_favorite is not None and candidate_result != strong_favorite:
        return False
    if candidate_result == leader_result:
        if not _same_class_upside_supported(
            profile,
            candidate_result,
            strategy_memory=strategy_memory,
        ):
            return False
        return _candidate_improves_margin_or_total(leader, candidate)
    return _can_change_result_class(profile, leader, candidate, strategy_memory=strategy_memory)


def _close_to_expected_points_leader(
    leader: ExpectedPointsCandidate,
    candidate: ExpectedPointsCandidate,
) -> bool:
    return (
        candidate.expected_pool_points >= leader.expected_pool_points - 0.55
        or candidate.expected_pool_points >= leader.expected_pool_points * 0.90
    )


def _candidate_improves_margin_or_total(
    leader: ExpectedPointsCandidate,
    candidate: ExpectedPointsCandidate,
) -> bool:
    return (
        candidate.home + candidate.away > leader.home + leader.away
        or abs(candidate.home - candidate.away) > abs(leader.home - leader.away)
    )


def _same_class_upside_supported(
    profile: ProbabilityProfile,
    candidate_result: str,
    *,
    strategy_memory: StrategyMemory,
) -> bool:
    return (
        _is_open_match(profile)
        or _strong_favorite_class(profile) == candidate_result
        or strategy_memory.total_high_pressure
        or strategy_memory.margin_pressure
    )


def _can_change_result_class(
    profile: ProbabilityProfile,
    leader: ExpectedPointsCandidate,
    candidate: ExpectedPointsCandidate,
    *,
    strategy_memory: StrategyMemory,
) -> bool:
    leader_class = _result_class(leader.scoreline)
    candidate_class = _result_class(candidate.scoreline)
    leader_probability = _class_probability(profile, leader_class)
    candidate_probability = _class_probability(profile, candidate_class)
    favorite_probability = max(profile.home_win, profile.away_win)
    if favorite_probability >= 0.72:
        return False
    if abs(candidate_probability - leader_probability) > 0.16:
        return False
    if candidate_probability < 0.24:
        return False
    if candidate_class == "draw":
        return _is_aggressive_draw(profile, candidate.scoreline, strategy_memory)
    if not _is_open_match(profile):
        return False
    if candidate.expected_pool_points < leader.expected_pool_points - 0.45:
        return False
    if abs(candidate.home - candidate.away) > 1:
        return False
    if leader_class != "draw" and candidate_probability < leader_probability:
        return favorite_probability <= 0.62
    return True


def _aggressive_candidate_score(
    profile: ProbabilityProfile,
    leader: ExpectedPointsCandidate,
    candidate: ExpectedPointsCandidate,
    *,
    strategy_memory: StrategyMemory,
    risk_pressure: float,
) -> tuple[float, float, int, int, float]:
    leader_total = leader.home + leader.away
    candidate_total = candidate.home + candidate.away
    leader_margin = abs(leader.home - leader.away)
    candidate_margin = abs(candidate.home - candidate.away)
    total_delta = max(0, candidate_total - leader_total)
    margin_delta = max(0, candidate_margin - leader_margin)
    score = candidate.expected_pool_points

    total_bonus = 0.16 + (0.14 if strategy_memory.total_high_pressure else 0.0)
    margin_bonus = 0.14 + (0.20 if strategy_memory.margin_pressure else 0.0)
    total_bonus += risk_pressure * 0.10
    margin_bonus += risk_pressure * 0.10
    if _strong_favorite_class(profile) == _result_class(candidate.scoreline):
        margin_bonus += 0.10

    score += total_delta * total_bonus
    score += margin_delta * margin_bonus

    if _is_open_match(profile) and _is_open_match_upside(candidate.scoreline):
        score += 0.28
    if _is_aggressive_draw(profile, candidate.scoreline, strategy_memory):
        score += 0.95
    if _is_low_total_leader(leader.scoreline) and candidate_total >= 3:
        score += 0.08
    if _result_class(candidate.scoreline) != _result_class(leader.scoreline):
        score += risk_pressure * 0.12
    if _result_class(candidate.scoreline) == "draw" and strategy_memory.draw_penalty_active:
        score -= 0.26
    if (
        strategy_memory.bucket_penalty_active
        and strategy_memory.is_repeated_bucket(candidate.scoreline)
        and leader.expected_pool_points - candidate.expected_pool_points <= 0.35
    ):
        score -= 0.30

    return (
        score,
        candidate.exact_probability,
        candidate_total,
        candidate_margin,
        _class_probability(profile, _result_class(candidate.scoreline)),
    )


def _is_open_match(profile: ProbabilityProfile) -> bool:
    return profile.over_2_5 >= 0.58 and profile.both_teams_to_score >= 0.55


def _is_open_match_upside(scoreline: Scoreline) -> bool:
    return (scoreline.home, scoreline.away) in {
        (2, 1),
        (1, 2),
        (3, 1),
        (1, 3),
        (2, 2),
    }


def _is_low_total_leader(scoreline: Scoreline) -> bool:
    return (scoreline.home, scoreline.away) in {(1, 0), (0, 1), (1, 1), (2, 1), (1, 2)}


def _is_aggressive_draw(
    profile: ProbabilityProfile,
    scoreline: Scoreline,
    strategy_memory: StrategyMemory,
) -> bool:
    if scoreline != Scoreline(2, 2):
        return False
    return (
        not strategy_memory.draw_penalty_active
        and profile.draw >= 0.28
        and profile.over_2_5 >= 0.60
        and profile.both_teams_to_score >= 0.58
    )


def _is_unsupported_three_goal_shutout(
    profile: ProbabilityProfile,
    scoreline: Scoreline,
) -> bool:
    if scoreline == Scoreline(3, 0):
        return not (
            profile.home_win >= 0.72
            and profile.expected_home_goals >= 2.15
            and profile.expected_away_goals <= 0.75
        )
    if scoreline == Scoreline(0, 3):
        return not (
            profile.away_win >= 0.72
            and profile.expected_away_goals >= 2.15
            and profile.expected_home_goals <= 0.75
        )
    return False


def _is_unsupported_comfortable_margin(
    profile: ProbabilityProfile,
    scoreline: Scoreline,
    *,
    strategy_memory: StrategyMemory,
) -> bool:
    if abs(scoreline.home - scoreline.away) < 2:
        return False
    if _strong_favorite_class(profile) == _result_class(scoreline):
        return False
    if (
        strategy_memory.margin_pressure
        and profile.over_2_5 >= 0.54
        and profile.both_teams_to_score >= 0.52
    ):
        return False
    return not _is_open_match(profile)


def _strong_favorite_class(profile: ProbabilityProfile) -> str | None:
    if (
        profile.home_win >= 0.72
        and profile.expected_home_goals >= 2.15
        and profile.expected_away_goals <= 0.75
    ):
        return "home"
    if (
        profile.away_win >= 0.72
        and profile.expected_away_goals >= 2.15
        and profile.expected_home_goals <= 0.75
    ):
        return "away"
    return None


def _class_probability(profile: ProbabilityProfile, result: str) -> float:
    if result == "home":
        return profile.home_win
    if result == "away":
        return profile.away_win
    return profile.draw


def _poisson_pmf(mean: float, goals: int) -> float:
    return math.exp(-mean) * (mean**goals) / math.factorial(goals)


def _result_class(scoreline: Scoreline) -> str:
    if scoreline.home > scoreline.away:
        return "home"
    if scoreline.home < scoreline.away:
        return "away"
    return "draw"
