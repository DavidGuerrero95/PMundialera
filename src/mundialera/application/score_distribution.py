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
            risk_pressure=(
                pool_context.effective_risk_pressure if pool_context is not None else 0.80
            ),
            final_phase=pool_context.is_final_phase if pool_context is not None else False,
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
    final_phase: bool,
) -> Scoreline:
    leader = candidates[0]
    memory = strategy_memory or StrategyMemory()
    if memory.points_floor_active:
        return _points_floor_scoreline(profile, candidates, memory)
    resolved_risk_pressure = _final_phase_risk_pressure(
        risk_pressure,
        final_phase=final_phase,
        strategy_memory=memory,
    )
    viable = [
        candidate
        for candidate in candidates[:36]
        if _is_aggressive_high_candidate(
            profile,
            leader,
            candidate,
            strategy_memory=memory,
            final_phase=final_phase,
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
            risk_pressure=resolved_risk_pressure,
            final_phase=final_phase,
        ),
        reverse=True,
    )
    return viable[0].scoreline


def _points_floor_scoreline(
    profile: ProbabilityProfile,
    candidates: list[ExpectedPointsCandidate],
    strategy_memory: StrategyMemory,
) -> Scoreline:
    leader = candidates[0]
    if _favorite_overconfidence_draw_recovery(profile, strategy_memory):
        return Scoreline(1, 1)
    if _recent_missed_draw_pressure(profile, strategy_memory):
        for candidate in candidates[:12]:
            if _result_class(candidate.scoreline) != "draw":
                continue
            if candidate.expected_pool_points < leader.expected_pool_points - 0.45:
                continue
            if profile.draw < 0.24:
                continue
            return candidate.scoreline
    return leader.scoreline


def _favorite_overconfidence_draw_recovery(
    profile: ProbabilityProfile,
    strategy_memory: StrategyMemory,
) -> bool:
    favorite_probability = max(profile.home_win, profile.away_win)
    favorite_xg = max(profile.expected_home_goals, profile.expected_away_goals)
    underdog_xg = min(profile.expected_home_goals, profile.expected_away_goals)
    xg_gap = favorite_xg - underdog_xg
    return (
        strategy_memory.missed_draw_recovery_active
        and strategy_memory.recent_over_margin_rate >= 0.50
        and 0.58 <= favorite_probability <= 0.68
        and profile.draw >= 0.18
        and profile.over_2_5 <= 0.58
        and profile.both_teams_to_score >= 0.47
        and favorite_xg >= 1.95
        and 0.75 <= underdog_xg <= 1.05
        and xg_gap >= 1.05
    )


def _is_aggressive_high_candidate(
    profile: ProbabilityProfile,
    leader: ExpectedPointsCandidate,
    candidate: ExpectedPointsCandidate,
    *,
    strategy_memory: StrategyMemory,
    final_phase: bool,
) -> bool:
    if candidate == leader:
        return True
    minimum_exact_ratio = 0.30 if final_phase else 0.35
    if candidate.exact_probability < leader.exact_probability * minimum_exact_ratio:
        return False
    max_side_goals = 4 if final_phase else 3
    max_total_goals = 5 if final_phase else 4
    if candidate.home > max_side_goals or candidate.away > max_side_goals:
        return False
    if candidate.home + candidate.away > max_total_goals:
        return False
    if (
        final_phase
        and candidate.home + candidate.away == 5
        and not _final_phase_high_total_supported(
            profile,
            candidate.scoreline,
            strategy_memory,
        )
    ):
        return False
    if _is_modest_favorite_unsupported_high_total(profile, candidate.scoreline):
        return False
    if (
        final_phase
        and max(candidate.home, candidate.away) == 4
        and not _final_phase_four_goal_supported(profile, candidate.scoreline, strategy_memory)
    ):
        return False
    if _btts_candidate_conflicts_with_clean_sheet_profile(profile, candidate.scoreline):
        return False
    if _is_unsupported_three_goal_shutout(
        profile,
        candidate.scoreline,
        strategy_memory=strategy_memory,
        final_phase=final_phase,
    ):
        return False
    if _is_modest_favorite_unsupported_comfortable_margin(
        profile,
        candidate.scoreline,
        strategy_memory=strategy_memory,
    ):
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
    if not draw_ep_bypass and not _close_to_expected_points_leader(
        leader,
        candidate,
        final_phase=final_phase,
    ):
        return False
    strong_favorite = _strong_favorite_class(profile)
    if strong_favorite is not None and candidate_result != strong_favorite:
        return False
    if candidate_result == leader_result:
        if not _same_class_upside_supported(
            profile,
            candidate_result,
            strategy_memory=strategy_memory,
            final_phase=final_phase,
        ):
            return False
        return _candidate_improves_margin_or_total(leader, candidate)
    return _can_change_result_class(
        profile,
        leader,
        candidate,
        strategy_memory=strategy_memory,
        final_phase=final_phase,
    )


def _close_to_expected_points_leader(
    leader: ExpectedPointsCandidate,
    candidate: ExpectedPointsCandidate,
    *,
    final_phase: bool,
) -> bool:
    ep_tolerance = 0.68 if final_phase else 0.55
    ep_ratio = 0.86 if final_phase else 0.90
    return (
        candidate.expected_pool_points >= leader.expected_pool_points - ep_tolerance
        or candidate.expected_pool_points >= leader.expected_pool_points * ep_ratio
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
    final_phase: bool,
) -> bool:
    return (
        _is_open_match(profile)
        or _strong_favorite_class(profile) == candidate_result
        or strategy_memory.total_high_pressure
        or strategy_memory.margin_pressure
        or (
            final_phase
            and _class_probability(profile, candidate_result) >= 0.46
            and (profile.over_2_5 >= 0.54 or strategy_memory.sample_size >= 12)
        )
    )


def _can_change_result_class(
    profile: ProbabilityProfile,
    leader: ExpectedPointsCandidate,
    candidate: ExpectedPointsCandidate,
    *,
    strategy_memory: StrategyMemory,
    final_phase: bool,
) -> bool:
    leader_class = _result_class(leader.scoreline)
    candidate_class = _result_class(candidate.scoreline)
    leader_probability = _class_probability(profile, leader_class)
    candidate_probability = _class_probability(profile, candidate_class)
    favorite_probability = max(profile.home_win, profile.away_win)
    if favorite_probability >= 0.72:
        return False
    class_gap_limit = 0.18 if final_phase else 0.16
    minimum_class_probability = 0.22 if final_phase else 0.24
    if abs(candidate_probability - leader_probability) > class_gap_limit:
        return False
    if candidate_probability < minimum_class_probability:
        return False
    if candidate_class == "draw":
        return _is_aggressive_draw(profile, candidate.scoreline, strategy_memory)
    if not _is_open_match(profile) and not (
        final_phase and profile.over_2_5 >= 0.54 and profile.both_teams_to_score >= 0.52
    ):
        return False
    ep_tolerance = 0.55 if final_phase else 0.45
    if candidate.expected_pool_points < leader.expected_pool_points - ep_tolerance:
        return False
    if abs(candidate.home - candidate.away) > 1:
        return False
    if leader_class != "draw" and candidate_probability < leader_probability:
        favorite_limit = 0.64 if final_phase else 0.62
        return favorite_probability <= favorite_limit
    return True


def _aggressive_candidate_score(
    profile: ProbabilityProfile,
    leader: ExpectedPointsCandidate,
    candidate: ExpectedPointsCandidate,
    *,
    strategy_memory: StrategyMemory,
    risk_pressure: float,
    final_phase: bool,
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
    if final_phase:
        total_bonus += 0.06
        margin_bonus += 0.08
    if _strong_favorite_class(profile) == _result_class(candidate.scoreline):
        margin_bonus += 0.10

    score += total_delta * total_bonus
    score += margin_delta * margin_bonus

    if _is_open_match(profile) and _is_open_match_upside(candidate.scoreline):
        score += 0.28
    if _clean_sheet_margin_upside(profile, candidate.scoreline):
        score += 0.34
    if _btts_bucket_against_lower_btts_profile(profile, candidate.scoreline):
        score -= 0.22
    if final_phase and candidate_total >= 5:
        score += 0.12
    if final_phase and candidate_margin >= 2 and _class_probability(
        profile,
        _result_class(candidate.scoreline),
    ) >= 0.58:
        score += 0.10
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


def _final_phase_risk_pressure(
    risk_pressure: float,
    *,
    final_phase: bool,
    strategy_memory: StrategyMemory,
) -> float:
    if not final_phase:
        return risk_pressure
    memory_boost = 0.06 if strategy_memory.sample_size >= 12 else 0.0
    if strategy_memory.total_high_pressure or strategy_memory.margin_pressure:
        memory_boost += 0.04
    return min(1.0, risk_pressure + memory_boost)


def _final_phase_high_total_supported(
    profile: ProbabilityProfile,
    scoreline: Scoreline,
    strategy_memory: StrategyMemory,
) -> bool:
    if profile.over_2_5 >= 0.62 and profile.both_teams_to_score >= 0.58:
        return True
    if (
        _strong_favorite_class(profile) == _result_class(scoreline)
        and max(profile.expected_home_goals, profile.expected_away_goals) >= 2.30
        and min(profile.expected_home_goals, profile.expected_away_goals) <= 1.05
    ):
        return True
    return strategy_memory.total_high_pressure and profile.over_2_5 >= 0.56


def _final_phase_four_goal_supported(
    profile: ProbabilityProfile,
    scoreline: Scoreline,
    strategy_memory: StrategyMemory,
) -> bool:
    favorite_class = _result_class(scoreline)
    favorite_xg = (
        profile.expected_home_goals if favorite_class == "home" else profile.expected_away_goals
    )
    underdog_xg = (
        profile.expected_away_goals if favorite_class == "home" else profile.expected_home_goals
    )
    if _strong_favorite_class(profile) == favorite_class and favorite_xg >= 2.35:
        return True
    return (
        strategy_memory.margin_pressure
        and _class_probability(profile, favorite_class) >= 0.68
        and favorite_xg >= 2.25
        and underdog_xg <= 1.05
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


def _recent_missed_draw_pressure(
    profile: ProbabilityProfile,
    strategy_memory: StrategyMemory,
) -> bool:
    favorite_probability = max(profile.home_win, profile.away_win)
    return (
        strategy_memory.recent_sample_size >= 4
        and strategy_memory.recent_missed_draw_rate >= 0.25
        and favorite_probability - profile.draw <= 0.20
        and profile.over_2_5 <= 0.58
    )


def _is_unsupported_three_goal_shutout(
    profile: ProbabilityProfile,
    scoreline: Scoreline,
    *,
    strategy_memory: StrategyMemory,
    final_phase: bool,
) -> bool:
    if scoreline == Scoreline(3, 0):
        return not (
            profile.home_win >= 0.72
            and profile.expected_home_goals >= 2.15
            and profile.expected_away_goals <= 0.75
        ) and not (
            final_phase
            and strategy_memory.margin_pressure
            and profile.home_win >= 0.70
            and profile.expected_home_goals >= 1.85
            and profile.expected_away_goals <= 0.60
            and profile.both_teams_to_score <= 0.42
        )
    if scoreline == Scoreline(0, 3):
        return not (
            profile.away_win >= 0.72
            and profile.expected_away_goals >= 2.15
            and profile.expected_home_goals <= 0.75
        ) and not (
            final_phase
            and strategy_memory.margin_pressure
            and profile.away_win >= 0.70
            and profile.expected_away_goals >= 1.85
            and profile.expected_home_goals <= 0.60
            and profile.both_teams_to_score <= 0.42
        )
    return False


def _btts_candidate_conflicts_with_clean_sheet_profile(
    profile: ProbabilityProfile,
    scoreline: Scoreline,
) -> bool:
    if scoreline.home == 0 or scoreline.away == 0:
        return False
    favorite = _result_class(scoreline)
    if favorite == "draw":
        return False
    favorite_probability = _class_probability(profile, favorite)
    underdog_xg = (
        profile.expected_away_goals if favorite == "home" else profile.expected_home_goals
    )
    return (
        favorite_probability >= 0.60
        and underdog_xg <= 0.65
        and profile.both_teams_to_score <= 0.42
    )


def _is_modest_favorite_unsupported_comfortable_margin(
    profile: ProbabilityProfile,
    scoreline: Scoreline,
    *,
    strategy_memory: StrategyMemory,
) -> bool:
    if abs(scoreline.home - scoreline.away) < 2:
        return False
    result = _result_class(scoreline)
    if result == "draw" or _strong_favorite_class(profile) == result:
        return False
    class_probability = _class_probability(profile, result)
    if class_probability >= 0.52:
        return False
    favorite_xg = profile.expected_home_goals if result == "home" else profile.expected_away_goals
    underdog_xg = profile.expected_away_goals if result == "home" else profile.expected_home_goals
    if _clean_sheet_margin_upside(profile, scoreline):
        return False
    if (
        _is_open_match_upside(scoreline)
        and profile.over_2_5 >= 0.60
        and profile.both_teams_to_score >= 0.58
        and underdog_xg <= 1.15
    ):
        return False
    if (
        strategy_memory.margin_pressure
        and favorite_xg >= 1.60
        and underdog_xg <= 1.35
        and profile.both_teams_to_score <= 0.60
    ):
        return False
    return True


def _is_modest_favorite_unsupported_high_total(
    profile: ProbabilityProfile,
    scoreline: Scoreline,
) -> bool:
    if scoreline.home + scoreline.away < 5:
        return False
    result = _result_class(scoreline)
    if result == "draw" or _strong_favorite_class(profile) == result:
        return False
    favorite_xg = profile.expected_home_goals if result == "home" else profile.expected_away_goals
    return _class_probability(profile, result) < 0.52 and favorite_xg < 2.05


def _is_unsupported_comfortable_margin(
    profile: ProbabilityProfile,
    scoreline: Scoreline,
    *,
    strategy_memory: StrategyMemory,
) -> bool:
    if abs(scoreline.home - scoreline.away) < 2:
        return False
    if strategy_memory.margin_pressure and _clean_sheet_margin_upside(profile, scoreline):
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


def _clean_sheet_margin_upside(profile: ProbabilityProfile, scoreline: Scoreline) -> bool:
    if scoreline.home == scoreline.away or abs(scoreline.home - scoreline.away) < 2:
        return False
    result = _result_class(scoreline)
    favorite_probability = _class_probability(profile, result)
    favorite_xg = profile.expected_home_goals if result == "home" else profile.expected_away_goals
    underdog_xg = profile.expected_away_goals if result == "home" else profile.expected_home_goals
    clean_sheet_scoreline = (
        (result == "home" and scoreline.away == 0)
        or (result == "away" and scoreline.home == 0)
    )
    return (
        clean_sheet_scoreline
        and favorite_probability >= 0.48
        and favorite_xg >= 1.55
        and underdog_xg <= 1.10
        and profile.both_teams_to_score <= 0.54
    )


def _btts_bucket_against_lower_btts_profile(
    profile: ProbabilityProfile,
    scoreline: Scoreline,
) -> bool:
    return (
        scoreline.home > 0
        and scoreline.away > 0
        and _result_class(scoreline) != "draw"
        and profile.both_teams_to_score <= 0.54
    )


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
