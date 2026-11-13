"""Time-zone aware helpers: local time, quiet hours and the nudge time windows."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Local-time windows the policy chooses between, as [start_hour, end_hour).
TIME_WINDOWS: dict[str, tuple[int, int]] = {
    "early_morning": (6, 8),
    "morning": (8, 11),
    "midday": (11, 14),
    "afternoon": (14, 17),
    "evening": (17, 20),
    "night": (20, 22),
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def zone(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def is_valid_timezone(tz_name: str) -> bool:
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def to_local(moment: datetime, tz_name: str | None) -> datetime:
    return moment.astimezone(zone(tz_name))


def day_type(day: date) -> str:
    return "weekend" if day.weekday() >= 5 else "weekday"


def is_quiet(local_time: time, quiet_start: time, quiet_end: time) -> bool:
    """Whether a local wall-clock time falls in quiet hours (which may wrap past midnight)."""
    if quiet_start == quiet_end:
        return False
    if quiet_start < quiet_end:
        return quiet_start <= local_time < quiet_end
    return local_time >= quiet_start or local_time < quiet_end


def window_of(local_dt: datetime) -> str | None:
    for name, (start, end) in TIME_WINDOWS.items():
        if start <= local_dt.hour < end:
            return name
    return None


def window_slots(
    day: date,
    window: str,
    tz_name: str,
    *,
    quiet_start: time,
    quiet_end: time,
    not_before: datetime,
    step_minutes: int = 5,
) -> list[datetime]:
    """Candidate send times (UTC) inside a window on a local day, skipping quiet hours and the past.

    The last 10 minutes of a window are left out so a nudge is never scheduled right at its edge.
    """
    tz = zone(tz_name)
    start_hour, end_hour = TIME_WINDOWS[window]
    cursor = datetime.combine(day, time(start_hour), tzinfo=tz)
    end = datetime.combine(day, time(end_hour), tzinfo=tz) - timedelta(minutes=10)
    slots: list[datetime] = []
    while cursor < end:
        # Normalising through UTC handles DST gaps (a skipped local hour simply yields no slot twice).
        utc_slot = cursor.astimezone(UTC)
        local = utc_slot.astimezone(tz)
        if utc_slot >= not_before and not is_quiet(local.time(), quiet_start, quiet_end):
            slots.append(utc_slot)
        cursor += timedelta(minutes=step_minutes)
    return slots
