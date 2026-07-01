from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from mundialera.application.scheduler import plan_next_wake
from mundialera.domain.models import Match, Team


def _match(minutes_from_now: int, *, now: datetime, match_id: str | None = None) -> Match:
    return Match(
        match_id=match_id or str(minutes_from_now),
        kickoff=now + timedelta(minutes=minutes_from_now),
        home=Team("A"),
        away=Team("B"),
    )


def test_schedule_uses_active_poll_inside_submission_window() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("America/Bogota"))

    decision = plan_next_wake(
        [_match(20, now=now)],
        now=now,
        submission_window_minutes=35,
        idle_poll_seconds=21600,
        active_poll_seconds=60,
        pre_window_buffer_seconds=300,
    )

    assert decision.in_window is True
    assert [match.match_id for match in decision.next_matches] == ["20"]
    assert decision.sleep_seconds == 60
    assert decision.reason == "active submission window"


def test_schedule_lists_all_matches_at_next_same_kickoff() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("America/Bogota"))

    decision = plan_next_wake(
        [
            _match(180, now=now, match_id="a"),
            _match(180, now=now, match_id="b"),
            _match(240, now=now, match_id="c"),
        ],
        now=now,
        submission_window_minutes=35,
        idle_poll_seconds=21600,
        active_poll_seconds=60,
        pre_window_buffer_seconds=300,
    )

    assert decision.next_match is not None
    assert decision.next_match.match_id == "a"
    assert [match.match_id for match in decision.next_matches] == ["a", "b"]
    assert decision.sleep_seconds == 8400


def test_schedule_lists_all_active_matches_inside_window() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("America/Bogota"))

    decision = plan_next_wake(
        [
            _match(20, now=now, match_id="a"),
            _match(30, now=now, match_id="b"),
            _match(90, now=now, match_id="c"),
        ],
        now=now,
        submission_window_minutes=35,
        idle_poll_seconds=21600,
        active_poll_seconds=60,
        pre_window_buffer_seconds=300,
    )

    assert decision.in_window is True
    assert [match.match_id for match in decision.next_matches] == ["a", "b"]


def test_schedule_closes_platform_lock_inside_last_ten_minutes() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("America/Bogota"))

    decision = plan_next_wake(
        [_match(9, now=now, match_id="locked")],
        now=now,
        submission_window_minutes=35,
        idle_poll_seconds=21600,
        active_poll_seconds=60,
        pre_window_buffer_seconds=300,
    )

    assert decision.in_window is False
    assert decision.next_match is not None
    assert decision.next_match.match_id == "locked"
    assert decision.sleep_seconds == 60
    assert decision.reason == "submission lock closed"


def test_schedule_sleeps_until_before_next_window() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("America/Bogota"))

    decision = plan_next_wake(
        [_match(180, now=now)],
        now=now,
        submission_window_minutes=35,
        idle_poll_seconds=21600,
        active_poll_seconds=60,
        pre_window_buffer_seconds=300,
    )

    assert decision.in_window is False
    assert decision.sleep_seconds == 8400
    assert decision.reason == "waiting for next submission window"


def test_schedule_uses_idle_poll_when_no_upcoming_matches() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=ZoneInfo("America/Bogota"))

    decision = plan_next_wake(
        [],
        now=now,
        submission_window_minutes=35,
        idle_poll_seconds=21600,
        active_poll_seconds=60,
        pre_window_buffer_seconds=300,
    )

    assert decision.next_match is None
    assert decision.next_matches == ()
    assert decision.sleep_seconds == 21600
    assert decision.reason == "no upcoming matches found"
