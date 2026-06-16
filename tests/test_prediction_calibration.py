from __future__ import annotations

from mundialera.application.calibration import build_prediction_calibration
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
        title=f"{category.value} evidence",
        summary=summary,
        url="https://example.test/item",
        source="example.test",
        tier=SourceTier.GENERIC_WEB,
        confidence=0.6,
    )


def test_calibration_flags_favorite_bias_without_stats_counterweight() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("Saudi Arabia"), away=Team("Uruguay"))
    brief = ResearchBrief(
        match=match,
        structured_evidence=[
            _evidence(EvidenceCategory.MARKET, "Uruguay favorite by market odds."),
            _evidence(EvidenceCategory.RANKING, "Uruguay ranking gap is large."),
        ],
    )

    calibration = build_prediction_calibration(brief)

    assert calibration.favorite_bias_risk >= 0.4
    assert EvidenceCategory.RECENT_MATCH_STATS in calibration.missing_categories
    assert any("Market signal lacks" in item for item in calibration.risk_flags)


def test_calibration_raises_draw_risk_for_under_set_piece_and_goalkeeper_terms() -> None:
    match = Match(match_id="1", kickoff=None, home=Team("A"), away=Team("B"))
    brief = ResearchBrief(
        match=match,
        structured_evidence=[
            _evidence(
                EvidenceCategory.RECENT_MATCH_STATS,
                "Opening match under profile with many saves, corners and set piece rebounds.",
            ),
            _evidence(EvidenceCategory.GOALKEEPERS_DEFENSE, "Goalkeeper had nine saves."),
            _evidence(EvidenceCategory.SET_PIECES, "Corner-kick threat on both sides."),
        ],
    )

    calibration = build_prediction_calibration(brief)

    assert calibration.draw_risk >= 0.5
    assert any("Volatility terms detected" in item for item in calibration.risk_flags)
