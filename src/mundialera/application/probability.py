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
TEAM_STRENGTH_PRIORS = {
    "argentina": 0.92,
    "francia": 0.90,
    "france": 0.90,
    "inglaterra": 0.88,
    "england": 0.88,
    "portugal": 0.87,
    "espana": 0.86,
    "españa": 0.86,
    "brazil": 0.85,
    "brasil": 0.85,
    "alemania": 0.82,
    "germany": 0.82,
    "paises bajos": 0.80,
    "países bajos": 0.80,
    "netherlands": 0.80,
    "belgica": 0.78,
    "bélgica": 0.78,
    "uruguay": 0.76,
    "croacia": 0.76,
    "croatia": 0.76,
    "colombia": 0.73,
    "suiza": 0.70,
    "switzerland": 0.70,
    "noruega": 0.68,
    "norway": 0.68,
    "senegal": 0.66,
    "austria": 0.65,
    "marruecos": 0.64,
    "morocco": 0.64,
    "estados unidos": 0.63,
    "united states": 0.63,
    "mexico": 0.62,
    "méxico": 0.62,
    "japon": 0.62,
    "japón": 0.62,
    "ecuador": 0.60,
    "suecia": 0.60,
    "sweden": 0.60,
    "costa de marfil": 0.58,
    "ivory coast": 0.58,
    "turquia": 0.57,
    "turquía": 0.57,
    "turkey": 0.57,
    "ghana": 0.55,
    "paraguay": 0.55,
    "escocia": 0.54,
    "scotland": 0.54,
    "tunez": 0.53,
    "túnez": 0.53,
    "tunisia": 0.53,
    "argelia": 0.52,
    "algeria": 0.52,
    "egipto": 0.52,
    "egypt": 0.52,
    "iran": 0.51,
    "irán": 0.51,
    "corea del sur": 0.50,
    "south korea": 0.50,
    "republica checa": 0.50,
    "república checa": 0.50,
    "czech republic": 0.50,
    "canada": 0.49,
    "canadá": 0.49,
    "australia": 0.48,
    "bosnia-herzegovina": 0.47,
    "bosnia": 0.47,
    "sudafrica": 0.46,
    "sudáfrica": 0.46,
    "south africa": 0.46,
    "arabia saudita": 0.45,
    "saudi arabia": 0.45,
    "catar": 0.44,
    "qatar": 0.44,
    "nueva zelanda": 0.43,
    "new zealand": 0.43,
    "panama": 0.42,
    "panamá": 0.42,
    "rd congo": 0.42,
    "dr congo": 0.42,
    "irak": 0.40,
    "iraq": 0.40,
    "uzbekistan": 0.40,
    "uzbekistán": 0.40,
    "cabo verde": 0.38,
    "cape verde": 0.38,
    "jordania": 0.35,
    "jordan": 0.35,
    "haiti": 0.34,
    "haití": 0.34,
    "curazao": 0.30,
    "curacao": 0.30,
}


def enrich_probability_profile(brief: ResearchBrief) -> ResearchBrief:
    if brief.probability_profile is not None:
        return brief
    return replace(brief, probability_profile=build_probability_profile(brief))


def build_probability_profile(brief: ResearchBrief) -> ProbabilityProfile:
    corpus = _corpus(brief)
    quality = brief.calibration.evidence_quality if brief.calibration else 0.0
    draw_risk = brief.calibration.draw_risk if brief.calibration else 0.25
    favorite_bias = brief.calibration.favorite_bias_risk if brief.calibration else 0.0
    diff = _class_gap_diff(brief) + (_base_team_diff(brief) * 0.20)

    if any(term in corpus for term in HOME_FAVORITE_TERMS):
        diff += 0.22
    if any(term in corpus for term in AWAY_FAVORITE_TERMS):
        diff -= 0.22
    diff *= 1.0 - (favorite_bias * 0.16)

    draw = _clamp(0.22 + draw_risk * 0.15 - quality * 0.04 - abs(diff) * 0.18, 0.17, 0.34)
    directional_mass = 1.0 - draw
    home_share = _clamp(0.5 + diff, 0.18, 0.82)
    home_win = directional_mass * home_share
    away_win = directional_mass - home_win

    over_hits = _term_hits(corpus, OVER_TERMS)
    under_hits = _term_hits(corpus, UNDER_TERMS)
    total_goals = _clamp(
        2.48
        + over_hits * 0.12
        - under_hits * 0.08
        - draw_risk * 0.10
        + quality * 0.10
        + abs(diff) * 0.45,
        1.45,
        3.65,
    )
    expected_home = _clamp(total_goals / 2 + diff * 1.35, 0.25, 3.5)
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
    if profile.draw >= max(profile.home_win, profile.away_win) + 0.03:
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
    if profile.home_win >= 0.48 and home - away < 1:
        home = away + 1
    if profile.away_win >= 0.48 and away - home < 1:
        away = home + 1
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


def _class_gap_diff(brief: ResearchBrief) -> float:
    home = TEAM_STRENGTH_PRIORS.get(brief.match.home.name.casefold(), 0.50)
    away = TEAM_STRENGTH_PRIORS.get(brief.match.away.name.casefold(), 0.50)
    return (home - away) * 0.55


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
