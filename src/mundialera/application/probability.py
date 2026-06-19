from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace

from mundialera.application.score_distribution import (
    best_scoreline_by_expected_points,
    coherent_profile_from_expected_goals,
    hedge_scoreline_by_expected_points,
)
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
    "close_profile",
    "closed-match",
    "clean sheet",
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


@dataclass(frozen=True, slots=True)
class TeamStateSnapshot:
    played: int
    goals_for: int
    goals_against: int
    goal_difference: int

    @property
    def avg_goals_for(self) -> float:
        return self.goals_for / max(self.played, 1)

    @property
    def avg_goals_against(self) -> float:
        return self.goals_against / max(self.played, 1)


def enrich_probability_profile(brief: ResearchBrief) -> ResearchBrief:
    if brief.probability_profile is not None:
        return brief
    return replace(brief, probability_profile=build_probability_profile(brief))


def build_probability_profile(brief: ResearchBrief) -> ProbabilityProfile:
    corpus = _corpus(brief)
    quality = brief.calibration.evidence_quality if brief.calibration else 0.0
    draw_risk = brief.calibration.draw_risk if brief.calibration else 0.25
    favorite_bias = brief.calibration.favorite_bias_risk if brief.calibration else 0.0
    strength_gap = _team_strength_gap(brief)
    diff = (strength_gap * 0.55) + (_base_team_diff(brief) * 0.12)

    if any(term in corpus for term in HOME_FAVORITE_TERMS):
        diff += 0.22
    if any(term in corpus for term in AWAY_FAVORITE_TERMS):
        diff -= 0.22
    favorite_bias_discount = 0.08 if abs(strength_gap) >= 0.20 else 0.16
    diff *= 1.0 - (favorite_bias * favorite_bias_discount)

    over_hits = _term_hits(corpus, OVER_TERMS)
    under_hits = _term_hits(corpus, UNDER_TERMS)
    home_state = _team_state_snapshot(corpus, brief.match.home.name)
    away_state = _team_state_snapshot(corpus, brief.match.away.name)
    state_home_xg, state_away_xg, state_total = _state_xg_adjustments(
        home_state,
        away_state,
        strength_gap,
    )
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
    total_goals = _clamp(total_goals + state_total, 1.45, 3.65)
    expected_home = _clamp(total_goals / 2 + diff * 1.35 + state_home_xg, 0.25, 3.5)
    expected_away = _clamp(total_goals - expected_home + state_away_xg, 0.25, 3.5)
    return coherent_profile_from_expected_goals(
        round(expected_home, 2),
        round(expected_away, 2),
    )


def scoreline_from_profile(profile: ProbabilityProfile) -> Scoreline:
    return best_scoreline_by_expected_points(profile)


def draw_hedge_from_profile(profile: ProbabilityProfile, primary: Scoreline) -> Scoreline:
    total_goals = profile.expected_home_goals + profile.expected_away_goals
    draw_goals = 0
    if profile.over_2_5 >= 0.58 and profile.both_teams_to_score >= 0.60:
        draw_goals = 2
    elif total_goals >= 1.65:
        draw_goals = 1
    if primary.home == primary.away:
        if profile.home_win >= profile.away_win:
            return Scoreline(primary.home + 1, primary.away)
        return Scoreline(primary.home, primary.away + 1)
    return Scoreline(draw_goals, draw_goals)


def portfolio_hedge_from_profile(profile: ProbabilityProfile, primary: Scoreline) -> Scoreline:
    return hedge_scoreline_by_expected_points(profile, primary)


def _base_team_diff(brief: ResearchBrief) -> float:
    seed = f"{brief.match.home.name}|{brief.match.away.name}".encode()
    digest = hashlib.sha256(seed).digest()
    return ((digest[0] / 255) - (digest[1] / 255)) * 0.22


def _team_strength_gap(brief: ResearchBrief) -> float:
    return _team_strength(brief.match.home.name) - _team_strength(brief.match.away.name)


def _team_strength(team_name: str) -> float:
    normalized = team_name.casefold()
    if normalized in TEAM_STRENGTH_PRIORS:
        return TEAM_STRENGTH_PRIORS[normalized]
    normalized = (
        normalized.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )
    return TEAM_STRENGTH_PRIORS.get(normalized, 0.50)


def _team_state_snapshot(corpus: str, team_name: str) -> TeamStateSnapshot | None:
    pattern = re.compile(
        rf"{re.escape(team_name.casefold())}\s*:\s*"
        r"p\s*(?P<played>\d+).*?"
        r"gf\s*(?P<gf>\d+)\s*,?\s*"
        r"ga\s*(?P<ga>\d+)\s*,?\s*"
        r"gd\s*(?P<gd>[+-]?\d+)",
        re.DOTALL,
    )
    match = pattern.search(corpus)
    if match is None:
        return None
    return TeamStateSnapshot(
        played=int(match.group("played")),
        goals_for=int(match.group("gf")),
        goals_against=int(match.group("ga")),
        goal_difference=int(match.group("gd")),
    )


def _state_xg_adjustments(
    home_state: TeamStateSnapshot | None,
    away_state: TeamStateSnapshot | None,
    strength_gap: float,
) -> tuple[float, float, float]:
    home_xg = 0.0
    away_xg = 0.0
    total = 0.0

    if home_state is not None:
        if home_state.avg_goals_for >= 3.0:
            home_xg += 0.16
            total += 0.04
        if home_state.avg_goals_for >= 5.0 or home_state.goal_difference >= 5:
            home_xg += 0.24
            total += 0.08
        if home_state.avg_goals_against >= 2.5:
            away_xg += 0.14
            total += 0.04
        if home_state.avg_goals_against <= 0.5 and home_state.played >= 1:
            away_xg -= 0.10
        if home_state.goal_difference >= 4:
            home_xg += 0.08
        if home_state.goal_difference <= -4:
            home_xg -= 0.10
            away_xg += 0.12

    if away_state is not None:
        if away_state.avg_goals_for >= 3.0:
            away_xg += 0.16
            total += 0.04
        if away_state.avg_goals_for >= 5.0 or away_state.goal_difference >= 5:
            away_xg += 0.24
            total += 0.08
        if away_state.avg_goals_against >= 2.5:
            home_xg += 0.14
            total += 0.04
        if away_state.avg_goals_against <= 0.5 and away_state.played >= 1:
            home_xg -= 0.10
        if away_state.goal_difference >= 4:
            away_xg += 0.08
        if away_state.goal_difference <= -4:
            away_xg -= 0.10
            home_xg += 0.12

    if strength_gap >= 0.22 and away_state is not None:
        if away_state.avg_goals_against >= 3.0 or away_state.goal_difference <= -4:
            home_xg += 0.18
            away_xg -= 0.18
        if away_state.avg_goals_against >= 5.0 or away_state.goal_difference <= -5:
            home_xg += 0.28
            total += 0.08
    if strength_gap <= -0.22 and home_state is not None:
        if home_state.avg_goals_against >= 3.0 or home_state.goal_difference <= -4:
            away_xg += 0.18
            home_xg -= 0.18
        if home_state.avg_goals_against >= 5.0 or home_state.goal_difference <= -5:
            away_xg += 0.28
            total += 0.08

    return home_xg, away_xg, total


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
