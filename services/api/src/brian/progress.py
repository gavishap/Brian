"""Goal progress: periods, streaks and counts derived from check-ins."""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from brian.models import CheckIn, Goal
from brian.timeutils import to_local, utcnow

ACTIVITY_KINDS = ("done", "progress")
LOOKBACK_DAYS = 180


@dataclass(frozen=True)
class GoalProgress:
    current_streak: int
    best_streak: int
    period_count: int
    period_target: int
    period_label: str
    last_check_in_at: datetime | None
    total_check_ins: int

    @property
    def period_complete(self) -> bool:
        return self.period_count >= self.period_target


def _is_weekly(cadence: str) -> bool:
    return cadence in ("weekly", "flexible")


def period_key(day: date, cadence: str) -> date:
    """The first day of the period that contains `day`."""
    if _is_weekly(cadence):
        return day - timedelta(days=day.weekday())
    if cadence == "weekdays" and day.weekday() >= 5:
        return day - timedelta(days=day.weekday() - 4)  # weekend activity counts toward Friday
    return day


def previous_period(key: date, cadence: str) -> date:
    if _is_weekly(cadence):
        return key - timedelta(days=7)
    prev = key - timedelta(days=1)
    if cadence == "weekdays":
        while prev.weekday() >= 5:
            prev -= timedelta(days=1)
    return prev


def compute_progress(
    *,
    cadence: str,
    target_per_period: int,
    activity_times: list[datetime],
    total_check_ins: int,
    last_check_in_at: datetime | None,
    tz_name: str,
    now: datetime,
) -> GoalProgress:
    counts: Counter[date] = Counter(period_key(to_local(t, tz_name).date(), cadence) for t in activity_times)
    current = period_key(to_local(now, tz_name).date(), cadence)
    target = max(1, target_per_period)

    def complete(key: date) -> bool:
        return counts.get(key, 0) >= target

    # The current period only extends the streak once it is complete; an unfinished current
    # period does not break it yet.
    streak = 0
    cursor = current if complete(current) else previous_period(current, cadence)
    while complete(cursor):
        streak += 1
        cursor = previous_period(cursor, cadence)

    best = 0
    if counts:
        run = 0
        cursor = min(counts)
        while cursor <= current:
            if complete(cursor):
                run += 1
                best = max(best, run)
            elif cursor != current:
                run = 0
            cursor = cursor + timedelta(days=7) if _is_weekly(cadence) else cursor + timedelta(days=1)
            if cadence == "weekdays":
                while cursor.weekday() >= 5:
                    cursor += timedelta(days=1)
    return GoalProgress(
        current_streak=streak,
        best_streak=max(best, streak),
        period_count=counts.get(current, 0),
        period_target=target,
        period_label="this week" if _is_weekly(cadence) else "today",
        last_check_in_at=last_check_in_at,
        total_check_ins=total_check_ins,
    )


async def progress_for_goals(
    session: AsyncSession, goals: list[Goal], tz_name: str, now: datetime | None = None
) -> dict[uuid.UUID, GoalProgress]:
    """Progress for several goals with one query."""
    now = now or utcnow()
    if not goals:
        return {}
    rows = (
        await session.execute(
            select(CheckIn.goal_id, CheckIn.kind, CheckIn.occurred_at)
            .where(CheckIn.goal_id.in_([g.id for g in goals]))
            .where(CheckIn.occurred_at >= now - timedelta(days=LOOKBACK_DAYS))
            .order_by(CheckIn.occurred_at)
        )
    ).all()
    by_goal: dict[uuid.UUID, list[tuple[str, datetime]]] = {g.id: [] for g in goals}
    for goal_id, kind, occurred_at in rows:
        by_goal[goal_id].append((kind, occurred_at))
    result: dict[uuid.UUID, GoalProgress] = {}
    for goal in goals:
        entries = by_goal[goal.id]
        result[goal.id] = compute_progress(
            cadence=goal.cadence,
            target_per_period=goal.target_per_period,
            activity_times=[t for kind, t in entries if kind in ACTIVITY_KINDS],
            total_check_ins=len(entries),
            last_check_in_at=entries[-1][1] if entries else None,
            tz_name=tz_name,
            now=now,
        )
    return result
