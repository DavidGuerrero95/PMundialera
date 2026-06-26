from __future__ import annotations

from mundialera.application.calibration import calibrate_research_brief
from mundialera.application.pool_strategy import PoolStrategyContext, StrategyMemory
from mundialera.application.probability import (
    build_probability_profile,
    draw_hedge_from_profile,
    portfolio_hedge_from_profile,
    scoreline_from_profile,
)
from mundialera.application.score_distribution import (
    best_scoreline_by_expected_points,
    best_scoreline_by_pool_strategy,
    build_scoreline_distribution,
    coherent_profile_from_expected_goals,
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
    assert scoreline == Scoreline(3, 0)


def test_probability_profile_lifts_good_must_win_team_without_overfitting() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Ecuador"), away=Team("Alemania"))
    base = calibrate_research_brief(
        ResearchBrief(
            match=match,
            structured_evidence=[
                _evidence(
                    EvidenceCategory.RECENT_MATCH_STATS,
                    "Ecuador: P2 W1 D0 L1, PTS 3, GF 3, GA 2, GD +1. "
                    "Alemania: P2 W2 D0 L0, PTS 6, GF 4, GA 1, GD +3.",
                ),
                _evidence(
                    EvidenceCategory.RANKING,
                    "Alemania favorite by ranking, but Ecuador is a good team.",
                ),
            ],
        )
    )
    pressure = calibrate_research_brief(
        ResearchBrief(
            match=match,
            structured_evidence=[
                _evidence(
                    EvidenceCategory.RECENT_MATCH_STATS,
                    "Ecuador: P2 W1 D0 L1, PTS 3, GF 3, GA 2, GD +1. "
                    "Alemania: P2 W2 D0 L0, PTS 6, GF 4, GA 1, GD +3.",
                ),
                _evidence(
                    EvidenceCategory.TABLE_INCENTIVES,
                    (
                        "Ecuador: PTS 3, GD +1, qualification_pressure "
                        "best_third_possible_win_improves_direct_path, scoring_posture "
                        "needs_win_for_direct_path_best_third_floor. Alemania: PTS 6, "
                        "qualification_pressure direct_control, scoring_posture can_manage_result."
                    ),
                ),
                _evidence(
                    EvidenceCategory.RANKING,
                    "Alemania favorite by ranking, but Ecuador is a good team.",
                ),
            ],
        )
    )

    base_profile = build_probability_profile(base)
    pressure_profile = build_probability_profile(pressure)

    assert pressure_profile.expected_home_goals > base_profile.expected_home_goals
    assert pressure_profile.home_win > base_profile.home_win
    assert pressure_profile.away_win < base_profile.away_win
    assert pressure_profile.home_win < 0.50


def test_clear_home_favorite_can_expand_margin_beyond_narrow_win() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Canada"), away=Team("Qatar"))
    brief = calibrate_research_brief(
        ResearchBrief(
            match=match,
            structured_evidence=[
                _evidence(
                    EvidenceCategory.RECENT_MATCH_STATS,
                    (
                        "Canada: P1 W0 D1 L0, GF 1, GA 1, GD 0. "
                        "Qatar: P1 W0 D0 L1, GF 0, GA 2, GD -2."
                    ),
                ),
                _evidence(
                    EvidenceCategory.RANKING,
                    (
                        "Canada clear favorite by market, ranking gap, "
                        "superioridad notoria and squad quality over Qatar."
                    ),
                ),
            ],
        )
    )

    profile = build_probability_profile(brief)
    scoreline = scoreline_from_profile(profile)

    assert profile.home_win >= 0.75
    assert profile.expected_home_goals >= 2.0
    assert profile.expected_away_goals <= 0.60
    assert scoreline == Scoreline(3, 0)


def test_clear_away_favorite_can_expand_margin_beyond_narrow_win() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Escocia"), away=Team("Marruecos"))
    brief = calibrate_research_brief(
        ResearchBrief(
            match=match,
            structured_evidence=[
                _evidence(
                    EvidenceCategory.RECENT_MATCH_STATS,
                    (
                        "Escocia: P1 W1 D0 L0, GF 1, GA 0, GD +1. "
                        "Marruecos: P1 W0 D1 L0, GF 1, GA 1, GD 0."
                    ),
                ),
                _evidence(
                    EvidenceCategory.RANKING,
                    (
                        "Marruecos clear favorite by market, higher ranked, "
                        "ranking gap, superioridad notoria and squad quality. "
                        "Escocia sin ser favorita."
                    ),
                ),
            ],
        )
    )

    profile = build_probability_profile(brief)
    scoreline = scoreline_from_profile(profile)

    assert profile.away_win >= 0.70
    assert profile.expected_away_goals >= 2.0
    assert profile.expected_home_goals <= 0.80
    assert scoreline == Scoreline(0, 3)


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


def test_chasing_strategy_takes_higher_upside_same_result_when_ep_is_close() -> None:
    profile = ProbabilityProfile(
        home_win=0.82,
        draw=0.14,
        away_win=0.04,
        over_2_5=0.51,
        both_teams_to_score=0.29,
        expected_home_goals=2.30,
        expected_away_goals=0.38,
    )

    assert best_scoreline_by_expected_points(profile) == Scoreline(2, 0)
    assert best_scoreline_by_pool_strategy(profile) == Scoreline(3, 0)


def test_aggressive_high_expands_strong_favorite_without_changing_winner() -> None:
    profile = ProbabilityProfile(
        home_win=0.82,
        draw=0.14,
        away_win=0.04,
        over_2_5=0.51,
        both_teams_to_score=0.29,
        expected_home_goals=2.30,
        expected_away_goals=0.38,
    )

    assert best_scoreline_by_expected_points(profile) == Scoreline(2, 0)
    assert best_scoreline_by_pool_strategy(profile, strategy="aggressive_high") == Scoreline(3, 0)


def test_aggressive_high_expands_open_match_when_ep_is_close() -> None:
    profile = ProbabilityProfile(
        home_win=0.48,
        draw=0.25,
        away_win=0.27,
        over_2_5=0.64,
        both_teams_to_score=0.60,
        expected_home_goals=1.90,
        expected_away_goals=1.10,
    )

    assert best_scoreline_by_expected_points(profile) == Scoreline(2, 1)
    assert best_scoreline_by_pool_strategy(profile, strategy="aggressive_high") == Scoreline(3, 1)


def test_aggressive_high_allows_two_two_only_when_draw_over_and_btts_are_live() -> None:
    profile = ProbabilityProfile(
        home_win=0.34,
        draw=0.32,
        away_win=0.34,
        over_2_5=0.68,
        both_teams_to_score=0.66,
        expected_home_goals=1.65,
        expected_away_goals=1.65,
    )

    assert best_scoreline_by_pool_strategy(profile, strategy="aggressive_high") == Scoreline(2, 2)


def test_aggressive_high_surprise_requires_close_class_and_no_strong_favorite() -> None:
    profile = ProbabilityProfile(
        home_win=0.40,
        draw=0.24,
        away_win=0.36,
        over_2_5=0.59,
        both_teams_to_score=0.56,
        expected_home_goals=1.28,
        expected_away_goals=1.32,
    )
    memory = StrategyMemory(
        sample_size=24,
        bucket_repetition_rate=0.50,
        repeated_buckets=("1 - 0", "2 - 1"),
    )

    scoreline = best_scoreline_by_pool_strategy(
        profile,
        strategy="aggressive_high",
        strategy_memory=memory,
    )

    assert scoreline.away > scoreline.home


def test_aggressive_high_does_not_change_winner_against_strong_favorite() -> None:
    profile = ProbabilityProfile(
        home_win=0.74,
        draw=0.18,
        away_win=0.08,
        over_2_5=0.64,
        both_teams_to_score=0.55,
        expected_home_goals=2.25,
        expected_away_goals=0.70,
    )

    scoreline = best_scoreline_by_pool_strategy(profile, strategy="aggressive_high")

    assert scoreline.home > scoreline.away


def test_aggressive_high_does_not_take_three_nil_from_generic_market_only_profile() -> None:
    profile = ProbabilityProfile(
        home_win=0.70,
        draw=0.18,
        away_win=0.12,
        over_2_5=0.48,
        both_teams_to_score=0.30,
        expected_home_goals=1.85,
        expected_away_goals=0.75,
    )

    assert best_scoreline_by_pool_strategy(profile, strategy="aggressive_high") != Scoreline(3, 0)


def test_aggressive_high_penalizes_repeated_low_bucket_after_underestimation() -> None:
    profile = ProbabilityProfile(
        home_win=0.48,
        draw=0.25,
        away_win=0.27,
        over_2_5=0.64,
        both_teams_to_score=0.60,
        expected_home_goals=1.90,
        expected_away_goals=1.10,
    )
    memory = StrategyMemory(
        sample_size=24,
        under_total_rate=0.58,
        under_margin_rate=0.54,
        bucket_repetition_rate=0.50,
        repeated_buckets=("2 - 1", "1 - 1"),
    )

    assert best_scoreline_by_expected_points(profile) == Scoreline(2, 1)
    assert best_scoreline_by_pool_strategy(
        profile,
        strategy="aggressive_high",
        strategy_memory=memory,
    ) == Scoreline(3, 1)


def test_aggressive_high_memory_allows_near_open_margin_upgrade() -> None:
    profile = ProbabilityProfile(
        home_win=0.4652,
        draw=0.2399,
        away_win=0.2949,
        over_2_5=0.5691,
        both_teams_to_score=0.5893,
        expected_home_goals=1.67,
        expected_away_goals=1.29,
    )
    memory = StrategyMemory(
        sample_size=20,
        under_total_rate=0.60,
        under_margin_rate=0.60,
        bucket_repetition_rate=0.50,
        repeated_buckets=("2 - 1", "1 - 0"),
    )

    assert best_scoreline_by_expected_points(profile) == Scoreline(2, 1)
    assert best_scoreline_by_pool_strategy(
        profile,
        strategy="aggressive_high",
        strategy_memory=memory,
    ) == Scoreline(3, 1)


def test_final_phase_aggression_expands_supported_favorite_margin() -> None:
    profile = coherent_profile_from_expected_goals(2.40, 0.30)
    memory = StrategyMemory(
        sample_size=18,
        under_total_rate=0.58,
        under_margin_rate=0.54,
        bucket_repetition_rate=0.50,
        repeated_buckets=("2 - 0", "3 - 0"),
    )

    assert best_scoreline_by_expected_points(profile) == Scoreline(2, 0)
    assert best_scoreline_by_pool_strategy(
        profile,
        strategy="aggressive_high",
        strategy_memory=memory,
    ) == Scoreline(3, 0)
    assert best_scoreline_by_pool_strategy(
        profile,
        pool_context=PoolStrategyContext(tournament_phase="final_phase"),
        strategy_memory=memory,
    ) == Scoreline(4, 0)


def test_final_phase_aggression_still_blocks_winner_change_against_strong_favorite() -> None:
    profile = coherent_profile_from_expected_goals(2.40, 0.30)
    memory = StrategyMemory(sample_size=18, under_total_rate=0.58, under_margin_rate=0.54)

    scoreline = best_scoreline_by_pool_strategy(
        profile,
        pool_context=PoolStrategyContext(tournament_phase="final_phase"),
        strategy_memory=memory,
    )

    assert scoreline.home > scoreline.away


def test_recent_margin_pressure_turns_low_btts_favorite_into_clean_sheet_margin() -> None:
    profile = ProbabilityProfile(
        home_win=0.7261,
        draw=0.1955,
        away_win=0.0784,
        over_2_5=0.4177,
        both_teams_to_score=0.3085,
        expected_home_goals=1.89,
        expected_away_goals=0.45,
    )
    memory = StrategyMemory(
        sample_size=24,
        under_margin_rate=0.4583,
        recent_sample_size=5,
        recent_under_margin_rate=0.60,
    )

    assert best_scoreline_by_expected_points(profile) == Scoreline(1, 0)
    assert best_scoreline_by_pool_strategy(
        profile,
        pool_context=PoolStrategyContext(tournament_phase="final_phase"),
        strategy_memory=memory,
    ) == Scoreline(3, 0)


def test_recent_margin_pressure_prefers_away_clean_sheet_over_btts_bucket() -> None:
    profile = ProbabilityProfile(
        home_win=0.2586,
        draw=0.2475,
        away_win=0.4939,
        over_2_5=0.5105,
        both_teams_to_score=0.5349,
        expected_home_goals=1.10,
        expected_away_goals=1.61,
    )
    memory = StrategyMemory(recent_sample_size=5, recent_under_margin_rate=0.60)

    assert best_scoreline_by_expected_points(profile) == Scoreline(0, 1)
    assert best_scoreline_by_pool_strategy(
        profile,
        pool_context=PoolStrategyContext(tournament_phase="final_phase"),
        strategy_memory=memory,
    ) == Scoreline(0, 2)


def test_modest_open_favorite_does_not_jump_to_two_goal_btts_margin() -> None:
    profile = ProbabilityProfile(
        home_win=0.2893,
        draw=0.2259,
        away_win=0.4848,
        over_2_5=0.6331,
        both_teams_to_score=0.6368,
        expected_home_goals=1.40,
        expected_away_goals=1.85,
    )
    memory = StrategyMemory(recent_sample_size=5, recent_under_margin_rate=0.60)

    assert best_scoreline_by_pool_strategy(
        profile,
        pool_context=PoolStrategyContext(tournament_phase="final_phase"),
        strategy_memory=memory,
    ) == Scoreline(1, 2)


def test_points_floor_mode_returns_expected_points_leader_after_bad_margin_day() -> None:
    profile = ProbabilityProfile(
        home_win=0.1212,
        draw=0.1559,
        away_win=0.7229,
        over_2_5=0.7201,
        both_teams_to_score=0.6034,
        expected_home_goals=1.04,
        expected_away_goals=2.63,
    )
    memory = StrategyMemory(
        recent_sample_size=6,
        recent_winner_accuracy=0.3333,
        recent_over_margin_rate=0.8333,
        recent_average_points=3.17,
    )

    assert best_scoreline_by_expected_points(profile) == Scoreline(1, 2)
    assert best_scoreline_by_pool_strategy(
        profile,
        pool_context=PoolStrategyContext(tournament_phase="final_phase"),
        strategy_memory=memory,
    ) == Scoreline(1, 2)


def test_points_floor_mode_can_take_close_draw_when_recent_draws_were_missed() -> None:
    profile = ProbabilityProfile(
        home_win=0.38,
        draw=0.30,
        away_win=0.32,
        over_2_5=0.45,
        both_teams_to_score=0.47,
        expected_home_goals=1.08,
        expected_away_goals=1.02,
    )
    memory = StrategyMemory(
        recent_sample_size=6,
        recent_winner_accuracy=0.3333,
        recent_missed_draw_rate=0.3333,
        recent_over_margin_rate=0.50,
        recent_average_points=3.17,
    )

    assert best_scoreline_by_pool_strategy(
        profile,
        pool_context=PoolStrategyContext(tournament_phase="final_phase"),
        strategy_memory=memory,
    ) == Scoreline(1, 1)
