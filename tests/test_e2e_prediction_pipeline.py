from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mundialera.application.calibration import calibrate_research_brief
from mundialera.application.orchestrator import PredictionOrchestrator
from mundialera.domain.models import (
    EvidenceCategory,
    EvidenceItem,
    Match,
    Prediction,
    ResearchBrief,
    Scoreline,
    SourceTier,
    SubmissionResult,
    Team,
)


@dataclass
class FakeClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


class FakeFixtures:
    def __init__(self, match: Match) -> None:
        self._match = match

    def list_groups(self) -> list[str]:
        return ["Mundial CoreX"]

    def list_matches(self, group_name: str) -> list[Match]:
        return [self._match]


class CalibratedResearchAgent:
    def research(self, match: Match) -> ResearchBrief:
        return calibrate_research_brief(
            ResearchBrief(
                match=match,
                structured_evidence=[
                    EvidenceItem(
                        category=EvidenceCategory.MARKET,
                        title="Uruguay favorite",
                        summary="Uruguay favorite by odds, but draw and under are live markets.",
                        url="https://example.test/odds",
                        source="example.test",
                        tier=SourceTier.GENERIC_WEB,
                        confidence=0.6,
                    ),
                    EvidenceItem(
                        category=EvidenceCategory.RECENT_MATCH_STATS,
                        title="Low scoring profile",
                        summary=(
                            "Opening match, under profile, goalkeeper saves and corners matter."
                        ),
                        url="https://example.test/stats",
                        source="example.test",
                        tier=SourceTier.GENERIC_WEB,
                        confidence=0.6,
                    ),
                ]
            )
        )


class CalibrationAwareModel:
    def predict(self, brief: ResearchBrief) -> Prediction:
        assert brief.calibration is not None
        return Prediction(
            match=brief.match,
            primary=Scoreline(1, 1),
            hedge=Scoreline(0, 1),
            confidence=max(0.35, 0.75 - brief.calibration.draw_risk),
            rationale=[f"draw_risk={brief.calibration.draw_risk:.2f}"],
        )


class FakeSink:
    def submit_prediction(
        self,
        match: Match,
        scoreline: Scoreline,
        *,
        dry_run: bool,
    ) -> SubmissionResult:
        return SubmissionResult(
            match=match,
            scoreline=scoreline,
            submitted=False,
            dry_run=dry_run,
            message=f"Dry-run: would submit {scoreline.label()}",
        )


def test_e2e_prediction_pipeline_preserves_calibration_to_submission() -> None:
    tz = ZoneInfo("America/Bogota")
    now = datetime(2026, 6, 16, 12, 0, tzinfo=tz)
    match = Match(
        match_id="tomorrow-1",
        kickoff=now + timedelta(minutes=20),
        home=Team("Saudi Arabia"),
        away=Team("Uruguay"),
        group="Mundial CoreX",
    )
    orchestrator = PredictionOrchestrator(
        fixtures=FakeFixtures(match),
        research_agent=CalibratedResearchAgent(),
        prediction_model=CalibrationAwareModel(),
        sink=FakeSink(),
        clock=FakeClock(now),
        submission_window_minutes=35,
    )

    result = orchestrator.run_group_window("Mundial CoreX", dry_run=True)

    assert result.evaluated[0].primary == Scoreline(1, 1)
    assert "draw_risk=" in result.evaluated[0].rationale[0]
    assert result.submitted[0].scoreline == Scoreline(1, 1)
    assert result.submitted[0].dry_run is True
