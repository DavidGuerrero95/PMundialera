from __future__ import annotations

from datetime import datetime, timedelta

PLATFORM_SUBMISSION_LOCK_MINUTES = 10


def is_submission_window_open(
    *,
    kickoff: datetime,
    now: datetime,
    submission_window_minutes: int,
) -> bool:
    delta = kickoff - now
    platform_lock = timedelta(minutes=PLATFORM_SUBMISSION_LOCK_MINUTES)
    configured_window = timedelta(minutes=submission_window_minutes)
    return platform_lock <= delta <= configured_window


def is_submission_lock_closed(*, kickoff: datetime, now: datetime) -> bool:
    delta = kickoff - now
    return timedelta() <= delta < timedelta(minutes=PLATFORM_SUBMISSION_LOCK_MINUTES)
