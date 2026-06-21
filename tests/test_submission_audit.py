from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mundialera.application.submission_audit import audit_submission_coverage
from mundialera.domain.models import Match, Scoreline, Team


class FakeFixtures:
    def __init__(self, matches: list[Match]) -> None:
        self._matches = matches

    def list_groups(self) -> list[str]:
        return ["Mundial CoreX"]

    def list_matches(self, group_name: str) -> list[Match]:
        return self._matches


class FakeSubmissionRegistry:
    def __init__(self, submitted_match_ids: set[tuple[str, str]]) -> None:
        self._submitted_match_ids = submitted_match_ids

    def has_successful_submission(self, group_name: str, match_id: str) -> bool:
        return (group_name, match_id) in self._submitted_match_ids


def test_submission_audit_reports_due_match_without_prediction() -> None:
    tz = ZoneInfo("America/Bogota")
    now = datetime(2026, 6, 21, 0, 30, tzinfo=tz)
    match = Match(
        match_id="36",
        kickoff=datetime(2026, 6, 20, 23, 0, tzinfo=tz),
        home=Team("Tunez"),
        away=Team("Japon"),
    )

    issues = audit_submission_coverage(
        ["Mundial CoreX"],
        fixtures=FakeFixtures([match]),
        submission_registry=FakeSubmissionRegistry(set()),
        now=now,
        submission_window_minutes=35,
    )

    assert len(issues) == 1
    assert issues[0].match_id == "36"
    assert issues[0].status == "missing_submission"


def test_submission_audit_marks_platform_prediction_without_local_record() -> None:
    tz = ZoneInfo("America/Bogota")
    now = datetime(2026, 6, 21, 0, 30, tzinfo=tz)
    match = Match(
        match_id="36",
        kickoff=now - timedelta(hours=1),
        home=Team("Tunez"),
        away=Team("Japon"),
        prediction=Scoreline(1, 1),
    )

    issues = audit_submission_coverage(
        ["Mundial FIFA 2026"],
        fixtures=FakeFixtures([match]),
        submission_registry=FakeSubmissionRegistry(set()),
        now=now,
        submission_window_minutes=35,
    )

    assert issues[0].status == "platform_prediction_without_local_record"
    assert issues[0].platform_prediction == Scoreline(1, 1)


def test_submission_audit_ignores_not_due_and_already_submitted_matches() -> None:
    tz = ZoneInfo("America/Bogota")
    now = datetime(2026, 6, 20, 22, 0, tzinfo=tz)
    not_due = Match(
        match_id="38",
        kickoff=now + timedelta(hours=2),
        home=Team("Espana"),
        away=Team("Arabia Saudita"),
    )
    submitted = Match(
        match_id="36",
        kickoff=now + timedelta(minutes=15),
        home=Team("Tunez"),
        away=Team("Japon"),
    )

    issues = audit_submission_coverage(
        ["Mundial CoreX"],
        fixtures=FakeFixtures([not_due, submitted]),
        submission_registry=FakeSubmissionRegistry({("Mundial CoreX", "36")}),
        now=now,
        submission_window_minutes=35,
    )

    assert issues == []
