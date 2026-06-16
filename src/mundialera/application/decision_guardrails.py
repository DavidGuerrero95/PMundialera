from __future__ import annotations

from dataclasses import replace

from mundialera.application.probability import draw_hedge_from_profile
from mundialera.domain.models import Prediction, ResearchBrief, Scoreline


def apply_prediction_guardrails(prediction: Prediction, brief: ResearchBrief) -> Prediction:
    profile = prediction.probabilities or brief.probability_profile
    flags = list(prediction.decision_flags)
    rationale = list(prediction.rationale)
    primary = prediction.primary
    hedge = prediction.hedge
    confidence = prediction.confidence

    if profile is not None and prediction.probabilities is None:
        flags.append("probability-profile-attached")

    if brief.calibration is not None:
        max_confidence = _max_confidence_from_evidence(brief)
        if confidence > max_confidence:
            flags.append(f"confidence-capped-at-{max_confidence:.2f}")
            confidence = max_confidence
        if _unsupported_comfortable_favorite(prediction.primary, brief):
            primary = _reduce_margin(prediction.primary)
            flags.append("comfortable-favorite-reduced-by-evidence-guardrail")
        if profile is not None and _draw_needs_cover(brief):
            hedge = draw_hedge_from_profile(profile, primary)
            flags.append("draw-risk-covered-in-hedge")

    if flags:
        rationale.append("Decision guardrails: " + "; ".join(dict.fromkeys(flags)))

    return replace(
        prediction,
        primary=primary,
        hedge=hedge,
        confidence=round(confidence, 2),
        rationale=rationale,
        probabilities=profile,
        decision_flags=list(dict.fromkeys(flags)),
    )


def _max_confidence_from_evidence(brief: ResearchBrief) -> float:
    if brief.calibration is None:
        return 0.62
    calibration = brief.calibration
    cap = 0.82
    if calibration.evidence_quality < 0.45:
        cap = min(cap, 0.52)
    if calibration.draw_risk >= 0.50:
        cap = min(cap, 0.58)
    if calibration.favorite_bias_risk >= 0.50:
        cap = min(cap, 0.57)
    if len(calibration.missing_categories) >= 5:
        cap = min(cap, 0.55)
    return cap


def _unsupported_comfortable_favorite(scoreline: Scoreline, brief: ResearchBrief) -> bool:
    if brief.calibration is None:
        return False
    if abs(scoreline.home - scoreline.away) < 2:
        return False
    calibration = brief.calibration
    return (
        calibration.evidence_quality < 0.55
        or calibration.favorite_bias_risk >= 0.45
        or calibration.draw_risk >= 0.45
    )


def _reduce_margin(scoreline: Scoreline) -> Scoreline:
    if scoreline.home > scoreline.away:
        return Scoreline(home=max(scoreline.away + 1, scoreline.home - 1), away=scoreline.away)
    return Scoreline(home=scoreline.home, away=max(scoreline.home + 1, scoreline.away - 1))


def _draw_needs_cover(brief: ResearchBrief) -> bool:
    return brief.calibration is not None and brief.calibration.draw_risk >= 0.42
