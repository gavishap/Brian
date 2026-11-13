from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from brian.progress import compute_progress
from brian.timeutils import is_quiet, window_slots

NOW = datetime(2026, 11, 13, 18, 0, tzinfo=UTC)  # a Friday


def at(days_ago: int, hour: int = 12) -> datetime:
    return (NOW - timedelta(days=days_ago)).replace(hour=hour)


def progress(cadence: str, target: int, times: list[datetime]):  # type: ignore[no-untyped-def]
    return compute_progress(
        cadence=cadence,
        target_per_period=target,
        activity_times=times,
        total_check_ins=len(times),
        last_check_in_at=max(times) if times else None,
        tz_name="UTC",
        now=NOW,
    )


def test_daily_streak_counts_today_once_done() -> None:
    p = progress("daily", 1, [at(0), at(1), at(2), at(4)])
    assert (p.current_streak, p.period_count, p.period_complete) == (3, 1, True)


def test_unfinished_today_does_not_break_the_streak() -> None:
    p = progress("daily", 1, [at(1), at(2)])
    assert (p.current_streak, p.period_count) == (2, 0)


def test_weekly_target() -> None:
    this_week = [at(0), at(2)]  # Fri, Wed
    last_week = [at(7), at(8), at(9)]
    p = progress("weekly", 3, this_week + last_week)
    assert (p.period_count, p.period_target, p.period_label) == (2, 3, "this week")
    assert p.current_streak == 1  # last week met the target; this week still open


def test_weekdays_cadence_skips_weekends() -> None:
    # Fri (today), Thu, Wed, Tue, Mon, then Fri a week ago: weekend in between is not required.
    p = progress("weekdays", 1, [at(0), at(1), at(2), at(3), at(4), at(7)])
    assert p.current_streak == 6


def test_best_streak() -> None:
    p = progress("daily", 1, [at(1), at(10), at(11), at(12), at(13)])
    assert (p.current_streak, p.best_streak) == (1, 4)


def test_quiet_hours_wrap_midnight() -> None:
    start, end = time(22, 0), time(7, 30)
    assert is_quiet(time(23, 0), start, end)
    assert is_quiet(time(6, 59), start, end)
    assert not is_quiet(time(7, 30), start, end)
    assert not is_quiet(time(12, 0), start, end)
    assert not is_quiet(time(12, 0), time(9, 0), time(9, 0))  # equal = no quiet hours


def test_window_slots_respect_quiet_hours_and_the_past() -> None:
    day = date(2026, 11, 13)
    slots = window_slots(
        day,
        "early_morning",  # 6-8am local
        "America/New_York",
        quiet_start=time(22, 0),
        quiet_end=time(7, 0),
        not_before=datetime(2026, 11, 13, 0, 0, tzinfo=UTC),
    )
    assert all(s.tzinfo is not None for s in slots)
    # Quiet until 7:00 and the window's last 10 minutes are excluded: 7:00, 7:05, ... 7:45 local.
    assert len(slots) == 10

    later = window_slots(
        day,
        "early_morning",
        "America/New_York",
        quiet_start=time(22, 0),
        quiet_end=time(7, 0),
        not_before=datetime(2026, 11, 13, 12, 30, tzinfo=UTC),  # 7:30 local
    )
    assert len(later) == 4  # 7:30 ... 7:45
