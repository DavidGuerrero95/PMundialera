from __future__ import annotations

from mundialera.application.calibration import calibrate_research_brief
from mundialera.application.decision_guardrails import apply_prediction_guardrails
from mundialera.application.probability import enrich_probability_profile
from mundialera.domain.models import (
    EvidenceCategory,
    EvidenceItem,
    Match,
    Prediction,
    ResearchBrief,
    Scoreline,
    SourceTier,
    Team,
)


def test_guardrails_cap_confidence_and_reduce_unsupported_favorite_margin() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Saudi Arabia"), away=Team("Uruguay"))
    brief = enrich_probability_profile(
        calibrate_research_brief(
            ResearchBrief(
                match=match,
                structured_evidence=[
                    EvidenceItem(
                        category=EvidenceCategory.MARKET,
                        title="Away favorite",
                        summary="Uruguay away favorite by odds, but lineup and stats are missing.",
                        url="https://example.test/odds",
                        source="example.test",
                        tier=SourceTier.GENERIC_WEB,
                        confidence=0.55,
                    )
                ],
            )
        )
    )
    prediction = Prediction(
        match=match,
        primary=Scoreline(0, 3),
        hedge=Scoreline(1, 2),
        confidence=0.78,
        rationale=["market favorite"],
    )

    guarded = apply_prediction_guardrails(prediction, brief)

    assert guarded.primary == Scoreline(0, 2)
    assert guarded.confidence <= 0.57
    assert "comfortable-favorite-reduced-by-evidence-guardrail" in guarded.decision_flags
    assert guarded.probabilities is not None


def test_guardrails_add_draw_hedge_when_draw_risk_is_high() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("A"), away=Team("B"))
    brief = enrich_probability_profile(
        calibrate_research_brief(
            ResearchBrief(
                match=match,
                structured_evidence=[
                    EvidenceItem(
                        category=EvidenceCategory.RECENT_MATCH_STATS,
                        title="Under",
                        summary="Opening match draw, under, saves, corners and set piece rebounds.",
                        url="https://example.test/stats",
                        source="example.test",
                        tier=SourceTier.GENERIC_WEB,
                        confidence=0.65,
                    )
                ],
            )
        )
    )
    prediction = Prediction(
        match=match,
        primary=Scoreline(2, 1),
        hedge=Scoreline(3, 1),
        confidence=0.62,
        rationale=["narrow favorite"],
    )

    guarded = apply_prediction_guardrails(prediction, brief)

    assert guarded.hedge.home == guarded.hedge.away
    assert "draw-risk-covered-in-hedge" in guarded.decision_flags
