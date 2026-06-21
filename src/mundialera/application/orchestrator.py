from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from mundialera.application.decision_guardrails import apply_prediction_guardrails
from mundialera.domain.models import Match, Prediction, SubmissionResult
from mundialera.domain.ports import (
    Clock,
    FixtureRepository,
    PredictionModel,
    PredictionRecorder,
    PredictionSink,
    ResearchAgent,
    ResearchRecorder,
)


@dataclass(frozen=True, slots=True)
class WindowRunResult:
    group_name: str
    evaluated: list[Prediction]
    submitted: list[SubmissionResult]
    skipped: list[str]


class PredictionOrchestrator:
    def __init__(
        self,
        fixtures: FixtureRepository,
        research_agent: ResearchAgent,
        prediction_model: PredictionModel,
        sink: PredictionSink,
        clock: Clock,
        submission_window_minutes: int,
        recorder: PredictionRecorder | None = None,
        research_recorder: ResearchRecorder | None = None,
    ) -> None:
        self._fixtures = fixtures
        self._research_agent = research_agent
        self._prediction_model = prediction_model
        self._sink = sink
        self._clock = clock
        self._window = timedelta(minutes=submission_window_minutes)
        self._prediction_cache: dict[str, Prediction] = {}
        self._recorder = recorder
        self._research_recorder = research_recorder

    def predict_match(self, match: Match) -> Prediction:
        cache_key = _prediction_cache_key(match)
        if cache_key in self._prediction_cache:
            return replace(self._prediction_cache[cache_key], match=match)
        brief = self._research_agent.research(match)
        if self._research_recorder is not None:
            self._research_recorder.record_research_brief(brief)
        prediction = apply_prediction_guardrails(self._prediction_model.predict(brief), brief)
        self._prediction_cache[cache_key] = prediction
        return prediction

    def run_group_window(self, group_name: str, *, dry_run: bool) -> WindowRunResult:
        now = self._clock.now()
        predictions: list[Prediction] = []
        submissions: list[SubmissionResult] = []
        skipped: list[str] = []

        for match in self._fixtures.list_matches(group_name):
            if match.kickoff is None:
                skipped.append(f"{match.label}: kickoff unavailable")
                continue

            delta = match.kickoff - now
            if timedelta() <= delta <= self._window:
                prediction = self.predict_match(match)
                predictions.append(prediction)
                submission = self._sink.submit_prediction(
                    match,
                    prediction.primary,
                    dry_run=dry_run,
                )
                submissions.append(submission)
                if self._recorder is not None:
                    self._recorder.record_prediction(prediction, submission)
            else:
                skipped.append(f"{match.label}: outside submission window")

        return WindowRunResult(
            group_name=group_name,
            evaluated=predictions,
            submitted=submissions,
            skipped=skipped,
        )

    def preview_upcoming(self, group_name: str, *, limit: int) -> list[Prediction]:
        now = self._clock.now()
        upcoming = [
            match
            for match in self._fixtures.list_matches(group_name)
            if match.kickoff is not None and match.kickoff >= now and match.result is None
        ]
        upcoming.sort(key=lambda item: item.kickoff or now)
        return [self.predict_match(match) for match in upcoming[:limit]]


def _prediction_cache_key(match: Match) -> str:
    kickoff = match.kickoff.isoformat() if match.kickoff else "unknown"
    return f"{kickoff}|{match.home.name.casefold()}|{match.away.name.casefold()}"
