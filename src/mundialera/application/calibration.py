from __future__ import annotations

from dataclasses import replace

from mundialera.domain.models import EvidenceCategory, PredictionCalibration, ResearchBrief

REQUIRED_CATEGORIES = (
    EvidenceCategory.AVAILABILITY,
    EvidenceCategory.FORM,
    EvidenceCategory.TACTICS,
    EvidenceCategory.VENUE_WEATHER,
    EvidenceCategory.RANKING,
    EvidenceCategory.MARKET,
    EvidenceCategory.REST_TRAVEL,
    EvidenceCategory.GOALKEEPERS_DEFENSE,
    EvidenceCategory.SET_PIECES,
    EvidenceCategory.PLAYER_CONTEXT,
    EvidenceCategory.RECENT_MATCH_STATS,
)

DRAW_TERMS = (
    "draw",
    "empate",
    "under",
    "low-scoring",
    "marcador corto",
    "debut",
    "opening match",
    "primer partido",
)
FAVORITE_BIAS_TERMS = (
    "favorite",
    "favorito",
    "underdog",
    "market",
    "mercado",
    "odds",
    "cuotas",
    "ranking",
)
VOLATILITY_TERMS = (
    "travel",
    "viaje",
    "delay",
    "retraso",
    "fatigue",
    "fatiga",
    "humidity",
    "humedad",
    "heat",
    "calor",
    "saves",
    "atajadas",
    "goalkeeper",
    "portero",
    "corner",
    "córner",
    "set piece",
    "balon parado",
    "rebote",
)


def calibrate_research_brief(brief: ResearchBrief) -> ResearchBrief:
    calibration = build_prediction_calibration(brief)
    return replace(brief, calibration=calibration)


def build_prediction_calibration(brief: ResearchBrief) -> PredictionCalibration:
    categories = {item.category for item in brief.structured_evidence}
    missing = [category for category in REQUIRED_CATEGORIES if category not in categories]
    evidence_quality = _evidence_quality(brief, missing)
    corpus = _corpus(brief)
    draw_risk = _risk_score(corpus, DRAW_TERMS, base=0.18)
    favorite_bias_risk = _risk_score(corpus, FAVORITE_BIAS_TERMS, base=0.12)
    volatility_risk = _risk_score(corpus, VOLATILITY_TERMS, base=0.0)
    risk_flags: list[str] = []

    if (
        EvidenceCategory.MARKET in categories
        and EvidenceCategory.RECENT_MATCH_STATS not in categories
    ):
        risk_flags.append("Market signal lacks recent match-stat counterweight.")
        favorite_bias_risk = min(1.0, favorite_bias_risk + 0.18)
    if (
        EvidenceCategory.RANKING in categories
        and EvidenceCategory.GOALKEEPERS_DEFENSE not in categories
    ):
        risk_flags.append("Ranking gap lacks goalkeeper/defensive validation.")
        favorite_bias_risk = min(1.0, favorite_bias_risk + 0.12)
    if EvidenceCategory.SET_PIECES not in categories:
        risk_flags.append("Set-piece scoring and concession risk is missing.")
        draw_risk = min(1.0, draw_risk + 0.08)
    if EvidenceCategory.GOALKEEPERS_DEFENSE not in categories:
        risk_flags.append("Goalkeeper saves and defensive resilience are missing.")
        draw_risk = min(1.0, draw_risk + 0.08)
    if EvidenceCategory.REST_TRAVEL not in categories:
        risk_flags.append("Rest, travel, and logistics risk is missing.")
    if volatility_risk >= 0.32:
        risk_flags.append("Volatility terms detected: logistics, weather, saves, or set pieces.")
        draw_risk = min(1.0, draw_risk + 0.16)
        favorite_bias_risk = min(1.0, favorite_bias_risk + 0.08)
    if evidence_quality < 0.45:
        risk_flags.append("Evidence quality is low; avoid high-confidence favorite scorelines.")

    return PredictionCalibration(
        evidence_quality=round(evidence_quality, 2),
        missing_categories=missing,
        risk_flags=risk_flags,
        draw_risk=round(draw_risk, 2),
        favorite_bias_risk=round(favorite_bias_risk, 2),
    )


def _evidence_quality(brief: ResearchBrief, missing: list[EvidenceCategory]) -> float:
    if not brief.structured_evidence:
        return 0.0
    average_confidence = sum(item.confidence for item in brief.structured_evidence) / len(
        brief.structured_evidence
    )
    coverage = 1.0 - (len(missing) / len(REQUIRED_CATEGORIES))
    uncertainty_penalty = min(0.25, len(brief.uncertainty) * 0.02)
    return max(0.0, min(1.0, (average_confidence * 0.65) + (coverage * 0.35) - uncertainty_penalty))


def _risk_score(corpus: str, terms: tuple[str, ...], *, base: float) -> float:
    hits = sum(1 for term in terms if term in corpus)
    return min(1.0, base + (hits * 0.08))


def _corpus(brief: ResearchBrief) -> str:
    parts = [
        *brief.evidence,
        *brief.uncertainty,
        *[item.title for item in brief.structured_evidence],
        *[item.summary for item in brief.structured_evidence],
    ]
    return " ".join(parts).casefold()
