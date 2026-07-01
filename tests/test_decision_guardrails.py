from __future__ import annotations

from mundialera.application.calibration import calibrate_research_brief
from mundialera.application.decision_guardrails import apply_prediction_guardrails
from mundialera.application.probability import enrich_probability_profile
from mundialera.domain.models import (
    EvidenceCategory,
    EvidenceItem,
    Match,
    Prediction,
    PredictionCalibration,
    ProbabilityProfile,
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


def test_guardrails_do_not_force_draw_hedge_from_general_uncertainty() -> None:
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

    assert guarded.hedge == Scoreline(3, 1)
    assert "draw-risk-covered-in-hedge" not in guarded.decision_flags


def test_guardrails_keep_supported_near_open_two_goal_margin() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Uruguay"), away=Team("Cabo Verde"))
    brief = ResearchBrief(
        match=match,
        calibration=PredictionCalibration(
            evidence_quality=0.42,
            draw_risk=0.66,
            favorite_bias_risk=0.52,
        ),
        probability_profile=ProbabilityProfile(
            home_win=0.4676,
            draw=0.2392,
            away_win=0.2932,
            over_2_5=0.5714,
            both_teams_to_score=0.5907,
            expected_home_goals=1.68,
            expected_away_goals=1.29,
        ),
    )
    prediction = Prediction(
        match=match,
        primary=Scoreline(3, 1),
        hedge=Scoreline(3, 1),
        confidence=0.47,
        rationale=["aggressive margin"],
    )

    guarded = apply_prediction_guardrails(prediction, brief)

    assert guarded.primary == Scoreline(3, 1)
    assert "comfortable-favorite-reduced-by-evidence-guardrail" not in guarded.decision_flags


def test_guardrails_keep_supported_clean_sheet_two_goal_margin() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Mexico"), away=Team("Ecuador"))
    brief = ResearchBrief(
        match=match,
        calibration=PredictionCalibration(
            evidence_quality=0.48,
            draw_risk=0.58,
            favorite_bias_risk=0.55,
        ),
        probability_profile=ProbabilityProfile(
            home_win=0.5397,
            draw=0.2435,
            away_win=0.2167,
            over_2_5=0.4882,
            both_teams_to_score=0.5007,
            expected_home_goals=1.66,
            expected_away_goals=0.96,
        ),
        structured_evidence=[
            EvidenceItem(
                category=EvidenceCategory.FORM,
                title="Team solidity",
                summary="Mexico has recent clean sheets and stronger structural form.",
                url="https://example.test/form",
                source="example.test",
                tier=SourceTier.GENERIC_WEB,
                confidence=0.66,
            ),
            EvidenceItem(
                category=EvidenceCategory.RANKING,
                title="Ranking and market edge",
                summary="Mexico has ranking and market support for a controlled win.",
                url="https://example.test/ranking",
                source="example.test",
                tier=SourceTier.GENERIC_WEB,
                confidence=0.66,
            ),
        ],
    )
    prediction = Prediction(
        match=match,
        primary=Scoreline(2, 0),
        hedge=Scoreline(2, 0),
        confidence=0.54,
        rationale=["supported clean-sheet margin"],
    )

    guarded = apply_prediction_guardrails(prediction, brief)

    assert guarded.primary == Scoreline(2, 0)
    assert "comfortable-favorite-reduced-by-evidence-guardrail" not in guarded.decision_flags


def test_guardrails_replace_default_draw_hedge_when_over_profile_favors_winner() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Inglaterra"), away=Team("Croacia"))
    brief = ResearchBrief(
        match=match,
        calibration=PredictionCalibration(
            evidence_quality=0.50,
            draw_risk=0.90,
            favorite_bias_risk=0.80,
        ),
        probability_profile=ProbabilityProfile(
            home_win=0.38,
            draw=0.33,
            away_win=0.29,
            over_2_5=0.57,
            both_teams_to_score=0.57,
            expected_home_goals=1.46,
            expected_away_goals=1.28,
        ),
    )
    prediction = Prediction(
        match=match,
        primary=Scoreline(2, 1),
        hedge=Scoreline(1, 1),
        confidence=0.48,
        rationale=["codex hedge"],
    )

    guarded = apply_prediction_guardrails(prediction, brief)

    assert guarded.hedge == Scoreline(1, 0)
    assert "hedge-rebalanced-away-from-default-draw" in guarded.decision_flags
