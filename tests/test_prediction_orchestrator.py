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


class GroupedFakeFixtures:
    def __init__(self, matches_by_group: dict[str, list[Match]]) -> None:
        self._matches_by_group = matches_by_group

    def list_groups(self) -> list[str]:
        return list(self._matches_by_group)

    def list_matches(self, group_name: str) -> list[Match]:
        return self._matches_by_group[group_name]


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


class FakeSubmissionRegistry:
    def __init__(self, submitted_match_ids: set[tuple[str, str]]) -> None:
        self._submitted_match_ids = submitted_match_ids

    def has_successful_submission(self, group_name: str, match_id: str) -> bool:
        return (group_name, match_id) in self._submitted_match_ids


class FixedPredictionModel:
    def __init__(self) -> None:
        self.predicted_match_ids: list[str] = []

    def predict(self, brief: ResearchBrief) -> Prediction:
        self.predicted_match_ids.append(brief.match.match_id)
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
    platform_locked = Match(
        match_id="15",
        kickoff=now + timedelta(minutes=9),
        home=Team("MÃ©xico"),
        away=Team("Ecuador"),
    )
    already_started = Match(
        match_id="12",
        kickoff=now - timedelta(minutes=1),
        home=Team("Marruecos"),
        away=Team("Escocia"),
    )
    sink = FakeSink()
    orchestrator = PredictionOrchestrator(
        fixtures=FakeFixtures([inside, outside, platform_locked, already_started]),
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
        "MÃ©xico - Ecuador: outside submission window",
        "Marruecos - Escocia: outside submission window",
    ]


def test_run_group_window_uses_primary_for_all_groups() -> None:
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
    )

    corex = orchestrator.run_group_window("Mundial CoreX", dry_run=True)
    fifa = orchestrator.run_group_window("Mundial FIFA 2026", dry_run=True)

    assert corex.submitted[0].scoreline == corex.evaluated[0].primary
    assert fifa.submitted[0].scoreline == fifa.evaluated[0].primary
    assert fifa.submitted[0].scoreline == corex.submitted[0].scoreline


def test_run_groups_window_submits_same_kickoff_match_to_all_groups_first() -> None:
    tz = ZoneInfo("America/Bogota")
    now = datetime(2026, 6, 24, 13, 25, tzinfo=tz)
    kickoff = datetime(2026, 6, 24, 14, 0, tzinfo=tz)
    corex_suiza = Match(
        match_id="51",
        kickoff=kickoff,
        home=Team("Suiza"),
        away=Team("Canadá"),
    )
    corex_bosnia = Match(
        match_id="52",
        kickoff=kickoff,
        home=Team("Bosnia-Herzegovina"),
        away=Team("Catar"),
    )
    fifa_suiza = Match(
        match_id="51",
        kickoff=kickoff,
        home=Team("Suiza"),
        away=Team("Canadá"),
    )
    fifa_bosnia = Match(
        match_id="52",
        kickoff=kickoff,
        home=Team("Bosnia-Herzegovina"),
        away=Team("Catar"),
    )
    sink = FakeSink()
    model = FixedPredictionModel()
    orchestrator = PredictionOrchestrator(
        fixtures=GroupedFakeFixtures(
            {
                "Mundial CoreX": [corex_suiza, corex_bosnia],
                "Mundial FIFA 2026": [fifa_suiza, fifa_bosnia],
            }
        ),
        research_agent=RecordingResearchAgent(),
        prediction_model=model,
        sink=sink,
        clock=FakeClock(now),
        submission_window_minutes=35,
    )

    results = orchestrator.run_groups_window(
        ["Mundial CoreX", "Mundial FIFA 2026"],
        dry_run=True,
    )

    assert [result.group_name for result in results] == ["Mundial CoreX", "Mundial FIFA 2026"]
    assert [item.match.match_id for item in sink.submissions] == ["51", "51", "52", "52"]
    assert [item.match.group for item in sink.submissions] == [
        "Mundial CoreX",
        "Mundial FIFA 2026",
        "Mundial CoreX",
        "Mundial FIFA 2026",
    ]
    assert sorted(model.predicted_match_ids) == ["51", "52"]


def test_run_group_window_skips_real_submission_already_recorded() -> None:
    tz = ZoneInfo("America/Bogota")
    now = datetime(2026, 6, 20, 18, 30, tzinfo=tz)
    match = Match(
        match_id="34",
        kickoff=now + timedelta(minutes=15),
        home=Team("Ecuador"),
        away=Team("Curazao"),
    )
    sink = FakeSink()
    orchestrator = PredictionOrchestrator(
        fixtures=FakeFixtures([match]),
        research_agent=RecordingResearchAgent(),
        prediction_model=FixedPredictionModel(),
        sink=sink,
        clock=FakeClock(now),
        submission_window_minutes=35,
        submission_registry=FakeSubmissionRegistry({("Mundial CoreX", "34")}),
    )

    result = orchestrator.run_group_window("Mundial CoreX", dry_run=False)

    assert result.evaluated == []
    assert result.submitted == []
    assert sink.submissions == []
    assert result.skipped == ["Ecuador - Curazao: already submitted for Mundial CoreX"]


def test_run_group_window_dry_run_ignores_submission_registry() -> None:
    tz = ZoneInfo("America/Bogota")
    now = datetime(2026, 6, 20, 18, 30, tzinfo=tz)
    match = Match(
        match_id="34",
        kickoff=now + timedelta(minutes=15),
        home=Team("Ecuador"),
        away=Team("Curazao"),
    )
    sink = FakeSink()
    orchestrator = PredictionOrchestrator(
        fixtures=FakeFixtures([match]),
        research_agent=RecordingResearchAgent(),
        prediction_model=FixedPredictionModel(),
        sink=sink,
        clock=FakeClock(now),
        submission_window_minutes=35,
        submission_registry=FakeSubmissionRegistry({("Mundial CoreX", "34")}),
    )

    result = orchestrator.run_group_window("Mundial CoreX", dry_run=True)

    assert len(result.evaluated) == 1
    assert len(result.submitted) == 1
    assert result.submitted[0].dry_run is True


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
