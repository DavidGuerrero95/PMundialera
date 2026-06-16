from __future__ import annotations

import hashlib
from dataclasses import replace

from mundialera.domain.models import ProbabilityProfile, ResearchBrief, Scoreline

OVER_TERMS = (
    "over",
    "goles esperados",
    "xg",
    "both teams",
    "ambos anotan",
    "high scoring",
)
UNDER_TERMS = (
    "under",
    "marcador corto",
    "low-scoring",
    "defensive",
    "defensivo",
)
HOME_FAVORITE_TERMS = ("home favorite", "local favorito", "favorito local")
AWAY_FAVORITE_TERMS = ("away favorite", "visitante favorito", "favorito visitante")


def enrich_probability_profile(brief: ResearchBrief) -> ResearchBrief:
    if brief.probability_profile is not None:
        return brief
    return replace(brief, probability_profile=build_probability_profile(brief))


def build_probability_profile(brief: ResearchBrief) -> ProbabilityProfile:
    corpus = _corpus(brief)
    quality = brief.calibration.evidence_quality if brief.calibration else 0.0
    draw_risk = brief.calibration.draw_risk if brief.calibration else 0.25
    favorite_bias = brief.calibration.favorite_bias_risk if brief.calibration else 0.0
    diff = _base_team_diff(brief)

    if any(term in corpus for term in HOME_FAVORITE_TERMS):
        diff += 0.22
    if any(term in corpus for term in AWAY_FAVORITE_TERMS):
        diff -= 0.22
    diff *= 1.0 - (favorite_bias * 0.28)

    draw = _clamp(0.24 + draw_risk * 0.30 - quality * 0.04 - abs(diff) * 0.08, 0.18, 0.42)
    directional_mass = 1.0 - draw
    home_share = _clamp(0.5 + diff, 0.18, 0.82)
    home_win = directional_mass * home_share
    away_win = directional_mass - home_win

    over_hits = _term_hits(corpus, OVER_TERMS)
    under_hits = _term_hits(corpus, UNDER_TERMS)
    total_goals = _clamp(
        2.28 + over_hits * 0.14 - under_hits * 0.16 - draw_risk * 0.25 + quality * 0.10,
        1.45,
        3.35,
    )
    expected_home = _clamp(total_goals / 2 + diff * 0.85, 0.25, 3.5)
    expected_away = _clamp(total_goals - expected_home, 0.25, 3.5)
    over_25 = _clamp(
        0.42 + (total_goals - 2.35) * 0.16 + over_hits * 0.05 - under_hits * 0.06,
        0.18,
        0.72,
    )
    both_score = _clamp(
        0.49 - abs(diff) * 0.18 + over_hits * 0.04 - under_hits * 0.03,
        0.22,
        0.68,
    )

    return ProbabilityProfile(
        home_win=round(home_win, 2),
        draw=round(draw, 2),
        away_win=round(away_win, 2),
        over_2_5=round(over_25, 2),
        both_teams_to_score=round(both_score, 2),
        expected_home_goals=round(expected_home, 2),
        expected_away_goals=round(expected_away, 2),
    )


def scoreline_from_profile(profile: ProbabilityProfile) -> Scoreline:
    if profile.draw >= max(profile.home_win, profile.away_win) - 0.04:
        goals = 1 if profile.expected_home_goals + profile.expected_away_goals >= 1.55 else 0
        return Scoreline(goals, goals)

    home = _goal_count(profile.expected_home_goals)
    away = _goal_count(profile.expected_away_goals)
    if profile.home_win > profile.away_win and home <= away:
        home = away + 1
    if profile.away_win > profile.home_win and away <= home:
        away = home + 1
    if abs(home - away) > 2:
        if home > away:
            home = away + 2
        else:
            away = home + 2
    return Scoreline(home, away)


def draw_hedge_from_profile(profile: ProbabilityProfile, primary: Scoreline) -> Scoreline:
    total_goals = profile.expected_home_goals + profile.expected_away_goals
    draw_goals = 1 if total_goals >= 1.65 else 0
    if primary.home == primary.away:
        if profile.home_win >= profile.away_win:
            return Scoreline(primary.home + 1, primary.away)
        return Scoreline(primary.home, primary.away + 1)
    return Scoreline(draw_goals, draw_goals)


def _base_team_diff(brief: ResearchBrief) -> float:
    seed = f"{brief.match.home.name}|{brief.match.away.name}".encode()
    digest = hashlib.sha256(seed).digest()
    return ((digest[0] / 255) - (digest[1] / 255)) * 0.22


def _goal_count(expected_goals: float) -> int:
    if expected_goals < 0.65:
        return 0
    if expected_goals < 1.45:
        return 1
    if expected_goals < 2.25:
        return 2
    return 3


def _corpus(brief: ResearchBrief) -> str:
    parts = [
        *brief.evidence,
        *brief.uncertainty,
        *[item.title for item in brief.structured_evidence],
        *[item.summary for item in brief.structured_evidence],
    ]
    return " ".join(parts).casefold()


def _term_hits(corpus: str, terms: tuple[str, ...]) -> int:
    return sum(1 for term in terms if term in corpus)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
