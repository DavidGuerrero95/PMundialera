from __future__ import annotations

from dataclasses import dataclass, replace

from mundialera.application.decision_guardrails import apply_prediction_guardrails
from mundialera.application.submission_window import is_submission_window_open
from mundialera.domain.models import Match, Prediction, SubmissionResult
from mundialera.domain.ports import (
    Clock,
    FixtureRepository,
    PredictionModel,
    PredictionRecorder,
    PredictionSink,
    PredictionSubmissionRegistry,
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
        submission_registry: PredictionSubmissionRegistry | None = None,
    ) -> None:
        self._fixtures = fixtures
        self._research_agent = research_agent
        self._prediction_model = prediction_model
        self._sink = sink
        self._clock = clock
        self._submission_window_minutes = submission_window_minutes
        self._prediction_cache: dict[str, Prediction] = {}
        self._recorder = recorder
        self._research_recorder = research_recorder
        self._submission_registry = submission_registry

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

        for raw_match in self._fixtures.list_matches(group_name):
            match = replace(raw_match, group=raw_match.group or group_name)
            if match.kickoff is None:
                skipped.append(f"{match.label}: kickoff unavailable")
                continue

            if is_submission_window_open(
                kickoff=match.kickoff,
                now=now,
                submission_window_minutes=self._submission_window_minutes,
            ):
                if (
                    not dry_run
                    and self._submission_registry is not None
                    and self._submission_registry.has_successful_submission(
                        group_name,
                        match.match_id,
                    )
                ):
                    skipped.append(f"{match.label}: already submitted for {group_name}")
                    continue
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

    def run_groups_window(
        self,
        group_names: list[str],
        *,
        dry_run: bool,
    ) -> list[WindowRunResult]:
        now = self._clock.now()
        predictions_by_group: dict[str, list[Prediction]] = {group: [] for group in group_names}
        submissions_by_group: dict[str, list[SubmissionResult]] = {
            group: [] for group in group_names
        }
        skipped_by_group: dict[str, list[str]] = {group: [] for group in group_names}
        active_by_match: dict[str, list[Match]] = {}

        for group_name in group_names:
            for raw_match in self._fixtures.list_matches(group_name):
                match = replace(raw_match, group=raw_match.group or group_name)
                if match.kickoff is None:
                    skipped_by_group[group_name].append(f"{match.label}: kickoff unavailable")
                    continue

                if not is_submission_window_open(
                    kickoff=match.kickoff,
                    now=now,
                    submission_window_minutes=self._submission_window_minutes,
                ):
                    skipped_by_group[group_name].append(f"{match.label}: outside submission window")
                    continue
                if (
                    not dry_run
                    and self._submission_registry is not None
                    and self._submission_registry.has_successful_submission(
                        group_name,
                        match.match_id,
                    )
                ):
                    skipped_by_group[group_name].append(
                        f"{match.label}: already submitted for {group_name}"
                    )
                    continue
                active_by_match.setdefault(_prediction_cache_key(match), []).append(match)

        for matches in sorted(
            active_by_match.values(),
            key=lambda items: items[0].kickoff or now,
        ):
            prediction = self.predict_match(matches[0])
            for match in matches:
                group_name = match.group or ""
                group_prediction = replace(prediction, match=match)
                predictions_by_group[group_name].append(group_prediction)
                submission = self._sink.submit_prediction(
                    match,
                    group_prediction.primary,
                    dry_run=dry_run,
                )
                submissions_by_group[group_name].append(submission)
                if self._recorder is not None:
                    self._recorder.record_prediction(group_prediction, submission)

        return [
            WindowRunResult(
                group_name=group_name,
                evaluated=predictions_by_group[group_name],
                submitted=submissions_by_group[group_name],
                skipped=skipped_by_group[group_name],
            )
            for group_name in group_names
        ]

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
