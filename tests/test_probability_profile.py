from __future__ import annotations

from mundialera.application.calibration import calibrate_research_brief
from mundialera.application.probability import (
    build_probability_profile,
    draw_hedge_from_profile,
    portfolio_hedge_from_profile,
    scoreline_from_profile,
)
from mundialera.application.score_distribution import (
    build_scoreline_distribution,
    expected_points_candidates,
)
from mundialera.domain.models import (
    EvidenceCategory,
    EvidenceItem,
    Match,
    ProbabilityProfile,
    ResearchBrief,
    Scoreline,
    SourceTier,
    Team,
)


def _evidence(category: EvidenceCategory, summary: str) -> EvidenceItem:
    return EvidenceItem(
        category=category,
        title=category.value,
        summary=summary,
        url="https://example.test",
        source="example.test",
        tier=SourceTier.GENERIC_WEB,
        confidence=0.65,
    )


def test_probability_profile_balances_draw_and_under_without_overfitting() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("A"), away=Team("B"))
    brief = calibrate_research_brief(
        ResearchBrief(
            match=match,
            structured_evidence=[
                _evidence(
                    EvidenceCategory.RECENT_MATCH_STATS,
                    "Opening match under profile, goalkeeper saves, low-scoring draw risk.",
                ),
                _evidence(EvidenceCategory.SET_PIECES, "Corners and set piece rebounds matter."),
                _evidence(EvidenceCategory.GOALKEEPERS_DEFENSE, "Goalkeeper saves are reliable."),
            ],
        )
    )

    profile = build_probability_profile(brief)
    scoreline = scoreline_from_profile(profile)

    assert profile.draw >= 0.28
    assert profile.over_2_5 < 0.50
    assert scoreline == Scoreline(1, 0)


def test_probability_profile_keeps_1x2_probabilities_normalized() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Home"), away=Team("Away"))
    brief = calibrate_research_brief(ResearchBrief(match=match))

    profile = build_probability_profile(brief)

    assert abs(profile.home_win + profile.draw + profile.away_win - 1.0) <= 0.02
    assert profile.expected_home_goals >= 0
    assert profile.expected_away_goals >= 0


def test_probability_profile_uses_class_gap_before_defaulting_to_draw() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Argentina"), away=Team("Argelia"))
    brief = calibrate_research_brief(
        ResearchBrief(
            match=match,
            structured_evidence=[
                _evidence(
                    EvidenceCategory.RANKING,
                    "Argentina favorite by ranking and squad quality.",
                ),
                _evidence(
                    EvidenceCategory.FORM,
                    "Argentina attacking ceiling is higher and can win by multiple goals.",
                ),
            ],
        )
    )

    profile = build_probability_profile(brief)
    scoreline = scoreline_from_profile(profile)

    assert profile.home_win > profile.draw
    assert scoreline.home > scoreline.away


def test_probability_profile_supports_stronger_away_favorite() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Irak"), away=Team("Noruega"))
    brief = calibrate_research_brief(
        ResearchBrief(
            match=match,
            structured_evidence=[
                _evidence(EvidenceCategory.RANKING, "Noruega favorite by ranking."),
                _evidence(EvidenceCategory.FORM, "Noruega has high attacking ceiling."),
            ],
        )
    )

    profile = build_probability_profile(brief)
    scoreline = scoreline_from_profile(profile)

    assert profile.away_win > profile.draw
    assert scoreline.away > scoreline.home


def test_probability_profile_uses_leaky_underdog_state_without_defaulting_to_two_one() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Ecuador"), away=Team("Curazao"))
    brief = calibrate_research_brief(
        ResearchBrief(
            match=match,
            structured_evidence=[
                _evidence(
                    EvidenceCategory.RECENT_MATCH_STATS,
                    (
                        "Ecuador: P1 W0 D0 L1, GF 0, GA 1, GD -1. "
                        "Curazao: P1 W0 D0 L1, GF 1, GA 7, GD -6."
                    ),
                ),
                _evidence(
                    EvidenceCategory.RANKING,
                    "Ecuador has the higher squad-quality prior and attacking ceiling.",
                ),
            ],
        )
    )

    profile = build_probability_profile(brief)
    scoreline = scoreline_from_profile(profile)

    assert profile.home_win >= 0.75
    assert profile.expected_away_goals <= 0.50
    assert scoreline == Scoreline(2, 0)


def test_global_tournament_open_terms_do_not_inflate_match_total() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("A"), away=Team("B"))
    baseline = calibrate_research_brief(ResearchBrief(match=match))
    global_only = calibrate_research_brief(
        ResearchBrief(
            match=match,
            structured_evidence=[
                _evidence(
                    EvidenceCategory.RECENT_MATCH_STATS,
                    (
                        "Global prior only: open_profile, open match rate, "
                        "hot attacks, leaky defenses."
                    ),
                ),
            ],
        )
    )

    baseline_profile = build_probability_profile(baseline)
    global_profile = build_probability_profile(global_only)

    assert global_profile.expected_home_goals <= baseline_profile.expected_home_goals + 0.05
    assert global_profile.expected_away_goals <= baseline_profile.expected_away_goals + 0.05
    assert global_profile.over_2_5 <= baseline_profile.over_2_5 + 0.03


def test_portfolio_hedge_preserves_winner_when_over_profile_is_not_draw_led() -> None:
    profile = ProbabilityProfile(
        home_win=0.38,
        draw=0.33,
        away_win=0.29,
        over_2_5=0.57,
        both_teams_to_score=0.57,
        expected_home_goals=1.46,
        expected_away_goals=1.28,
    )

    hedge = portfolio_hedge_from_profile(profile, Scoreline(2, 1))

    assert hedge == Scoreline(1, 0)


def test_portfolio_hedge_uses_high_scoring_draw_for_strong_btts_favorite_risk() -> None:
    profile = ProbabilityProfile(
        home_win=0.48,
        draw=0.30,
        away_win=0.22,
        over_2_5=0.72,
        both_teams_to_score=0.63,
        expected_home_goals=1.77,
        expected_away_goals=1.27,
    )

    hedge = portfolio_hedge_from_profile(profile, Scoreline(2, 1))

    assert hedge == Scoreline(1, 0)


def test_draw_hedge_uses_two_two_when_draw_and_over_are_both_live() -> None:
    profile = ProbabilityProfile(
        home_win=0.34,
        draw=0.34,
        away_win=0.32,
        over_2_5=0.71,
        both_teams_to_score=0.66,
        expected_home_goals=1.49,
        expected_away_goals=1.46,
    )

    hedge = draw_hedge_from_profile(profile, Scoreline(2, 1))

    assert hedge == Scoreline(2, 2)


def test_expected_points_optimizer_can_prefer_non_modal_scoreline() -> None:
    profile = ProbabilityProfile(
        home_win=0.41,
        draw=0.30,
        away_win=0.29,
        over_2_5=0.72,
        both_teams_to_score=0.68,
        expected_home_goals=1.74,
        expected_away_goals=1.53,
    )

    distribution = build_scoreline_distribution(profile)
    modal = max(distribution, key=lambda item: item.probability).scoreline
    candidates = expected_points_candidates(profile, top=2)

    assert modal == Scoreline(1, 1)
    assert candidates[0].scoreline == Scoreline(2, 1)
    assert candidates[0].expected_pool_points > candidates[1].expected_pool_points
