from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from mundialera.domain.models import Match


@dataclass(frozen=True, slots=True)
class ScheduleDecision:
    now: datetime
    next_match: Match | None
    in_window: bool
    sleep_seconds: int
    reason: str


def plan_next_wake(
    matches: list[Match],
    *,
    now: datetime,
    submission_window_minutes: int,
    idle_poll_seconds: int,
    active_poll_seconds: int,
    pre_window_buffer_seconds: int,
) -> ScheduleDecision:
    window = timedelta(minutes=submission_window_minutes)
    upcoming = [
        match
        for match in matches
        if match.kickoff is not None and match.result is None and match.kickoff >= now
    ]
    upcoming.sort(key=lambda item: item.kickoff or now)
    active = [
        match
        for match in upcoming
        if match.kickoff is not None and timedelta() <= match.kickoff - now <= window
    ]
    if active:
        return ScheduleDecision(
            now=now,
            next_match=active[0],
            in_window=True,
            sleep_seconds=active_poll_seconds,
            reason="active submission window",
        )
    if not upcoming:
        return ScheduleDecision(
            now=now,
            next_match=None,
            in_window=False,
            sleep_seconds=idle_poll_seconds,
            reason="no upcoming matches found",
        )
    next_match = upcoming[0]
    assert next_match.kickoff is not None
    wake_at = next_match.kickoff - window - timedelta(seconds=pre_window_buffer_seconds)
    seconds_until_wake = int((wake_at - now).total_seconds())
    if seconds_until_wake <= active_poll_seconds:
        sleep_seconds = active_poll_seconds
        reason = "near submission window"
    else:
        sleep_seconds = min(idle_poll_seconds, seconds_until_wake)
        reason = "waiting for next submission window"
    return ScheduleDecision(
        now=now,
        next_match=next_match,
        in_window=False,
        sleep_seconds=max(1, sleep_seconds),
        reason=reason,
    )
