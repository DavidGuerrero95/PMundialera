from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from mundialera.domain.models import Scoreline
from mundialera.domain.ports import FixtureRepository, PredictionSubmissionRegistry


@dataclass(frozen=True, slots=True)
class SubmissionCoverageIssue:
    group_name: str
    match_id: str
    match_label: str
    kickoff: datetime
    status: str
    platform_prediction: Scoreline | None


def audit_submission_coverage(
    groups: list[str],
    *,
    fixtures: FixtureRepository,
    submission_registry: PredictionSubmissionRegistry,
    now: datetime,
    submission_window_minutes: int,
    lookback_hours: int = 36,
) -> list[SubmissionCoverageIssue]:
    window = timedelta(minutes=submission_window_minutes)
    oldest_kickoff = now - timedelta(hours=lookback_hours)
    issues: list[SubmissionCoverageIssue] = []
    for group_name in groups:
        for match in fixtures.list_matches(group_name):
            if (
                match.kickoff is None
                or match.kickoff < oldest_kickoff
                or now < match.kickoff - window
            ):
                continue
            if submission_registry.has_successful_submission(group_name, match.match_id):
                continue
            status = (
                "platform_prediction_without_local_record"
                if match.prediction is not None
                else "missing_submission"
            )
            issues.append(
                SubmissionCoverageIssue(
                    group_name=group_name,
                    match_id=match.match_id,
                    match_label=match.label,
                    kickoff=match.kickoff,
                    status=status,
                    platform_prediction=match.prediction,
                )
            )
    return issues
