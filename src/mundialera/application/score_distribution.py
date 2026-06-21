from __future__ import annotations

import math
from dataclasses import dataclass

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
    strategy: str = "chasing",
) -> Scoreline:
    candidates = expected_points_candidates(profile)
    if not candidates:
        return Scoreline(1, 1)
    if strategy != "chasing":
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


def _poisson_pmf(mean: float, goals: int) -> float:
    return math.exp(-mean) * (mean**goals) / math.factorial(goals)


def _result_class(scoreline: Scoreline) -> str:
    if scoreline.home > scoreline.away:
        return "home"
    if scoreline.home < scoreline.away:
        return "away"
    return "draw"
