from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mundialera.application.orchestrator import PredictionOrchestrator
from mundialera.application.subagents import HeuristicPredictionModel, default_research_agent
from mundialera.domain.models import (
    Match,
    Prediction,
    ResearchBrief,
    Scoreline,
    SubmissionResult,
    Team,
)


@dataclass
class FakeClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


class FakeFixtures:
    def __init__(self, matches: list[Match]) -> None:
        self._matches = matches

    def list_groups(self) -> list[str]:
        return ["Mundial CoreX"]

    def list_matches(self, group_name: str) -> list[Match]:
        return self._matches


class FakeSink:
    def __init__(self) -> None:
        self.submissions: list[SubmissionResult] = []

    def submit_prediction(
        self,
        match: Match,
        scoreline: Scoreline,
        *,
        dry_run: bool,
    ) -> SubmissionResult:
        result = SubmissionResult(
            match=match,
            scoreline=scoreline,
            submitted=False,
            dry_run=dry_run,
            message="ok",
        )
        self.submissions.append(result)
        return result


class FixedPredictionModel:
    def predict(self, brief: ResearchBrief) -> Prediction:
        return Prediction(
            match=brief.match,
            primary=Scoreline(2, 0),
            hedge=Scoreline(1, 1),
            confidence=0.62,
            rationale=["fixed test prediction"],
        )


class RecordingResearchAgent:
    def research(self, match: Match) -> ResearchBrief:
        return ResearchBrief(
            match=match,
            evidence=["titularidad, lesionados, arbitro, hinchada y sede revisados"],
            uncertainty=["mercado pendiente"],
        )


class FakeResearchRecorder:
    def __init__(self) -> None:
        self.briefs: list[ResearchBrief] = []

    def record_research_brief(self, brief: ResearchBrief) -> None:
        self.briefs.append(brief)


def test_run_group_window_only_predicts_inside_window() -> None:
    tz = ZoneInfo("America/Bogota")
    now = datetime(2026, 6, 15, 13, 45, tzinfo=tz)
    inside = Match(
        match_id="16",
        kickoff=now + timedelta(minutes=35),
        home=Team("Bélgica"),
        away=Team("Egipto"),
    )
    outside = Match(
        match_id="13",
        kickoff=now + timedelta(minutes=36),
        home=Team("Arabia Saudita"),
        away=Team("Uruguay"),
    )
    already_started = Match(
        match_id="12",
        kickoff=now - timedelta(minutes=1),
        home=Team("Marruecos"),
        away=Team("Escocia"),
    )
    sink = FakeSink()
    orchestrator = PredictionOrchestrator(
        fixtures=FakeFixtures([inside, outside, already_started]),
        research_agent=default_research_agent(),
        prediction_model=HeuristicPredictionModel(),
        sink=sink,
        clock=FakeClock(now),
        submission_window_minutes=35,
    )

    result = orchestrator.run_group_window("Mundial CoreX", dry_run=True)

    assert [prediction.match.match_id for prediction in result.evaluated] == ["16"]
    assert len(result.submitted) == 1
    assert result.submitted[0].dry_run is True
    assert result.skipped == [
        "Arabia Saudita - Uruguay: outside submission window",
        "Marruecos - Escocia: outside submission window",
    ]


def test_run_group_window_uses_hedge_for_configured_group() -> None:
    tz = ZoneInfo("America/Bogota")
    now = datetime(2026, 6, 15, 13, 45, tzinfo=tz)
    match = Match(
        match_id="16",
        kickoff=now + timedelta(minutes=15),
        home=Team("Bélgica"),
        away=Team("Egipto"),
    )
    sink = FakeSink()
    orchestrator = PredictionOrchestrator(
        fixtures=FakeFixtures([match]),
        research_agent=default_research_agent(),
        prediction_model=FixedPredictionModel(),
        sink=sink,
        clock=FakeClock(now),
        submission_window_minutes=20,
        hedge_group_names={"mundial fifa 2026"},
    )

    corex = orchestrator.run_group_window("Mundial CoreX", dry_run=True)
    fifa = orchestrator.run_group_window("Mundial FIFA 2026", dry_run=True)

    assert corex.submitted[0].scoreline == corex.evaluated[0].primary
    assert fifa.submitted[0].scoreline == fifa.evaluated[0].hedge


def test_predict_match_records_research_brief_before_prediction() -> None:
    tz = ZoneInfo("America/Bogota")
    now = datetime(2026, 6, 15, 13, 45, tzinfo=tz)
    match = Match(
        match_id="32",
        kickoff=now + timedelta(minutes=15),
        home=Team("Estados Unidos"),
        away=Team("Australia"),
        group="Mundial CoreX",
    )
    recorder = FakeResearchRecorder()
    orchestrator = PredictionOrchestrator(
        fixtures=FakeFixtures([match]),
        research_agent=RecordingResearchAgent(),
        prediction_model=FixedPredictionModel(),
        sink=FakeSink(),
        clock=FakeClock(now),
        submission_window_minutes=35,
        research_recorder=recorder,
    )

    prediction = orchestrator.predict_match(match)

    assert prediction.primary == Scoreline(2, 0)
    assert len(recorder.briefs) == 1
    assert recorder.briefs[0].match.match_id == "32"
    assert "titularidad" in recorder.briefs[0].evidence[0]
