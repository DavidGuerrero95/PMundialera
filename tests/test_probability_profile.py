from __future__ import annotations

from mundialera.application.calibration import calibrate_research_brief
from mundialera.application.probability import build_probability_profile, scoreline_from_profile
from mundialera.domain.models import (
    EvidenceCategory,
    EvidenceItem,
    Match,
    ResearchBrief,
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

    assert profile.draw >= 0.30
    assert profile.over_2_5 < 0.50
    assert scoreline.home == scoreline.away


def test_probability_profile_keeps_1x2_probabilities_normalized() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Home"), away=Team("Away"))
    brief = calibrate_research_brief(ResearchBrief(match=match))

    profile = build_probability_profile(brief)

    assert abs(profile.home_win + profile.draw + profile.away_win - 1.0) <= 0.02
    assert profile.expected_home_goals >= 0
    assert profile.expected_away_goals >= 0
