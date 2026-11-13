"""Goal domain logic shared by the REST API and the coach agent's tools."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from brian.models import CheckIn, Goal, Milestone, Profile
from brian.progress import GoalProgress, progress_for_goals
from brian.schemas import CheckInOut, GoalDetail, GoalOut, GoalProgressOut, MilestoneOut
from brian.timeutils import utcnow

MUTABLE_GOAL_FIELDS = (
    "title",
    "description",
    "why",
    "category",
    "cadence",
    "target_per_period",
    "target_date",
    "priority",
    "status",
)


class NotFoundError(LookupError):
    pass


def goal_out(goal: Goal, progress: GoalProgress) -> GoalOut:
    return GoalOut.model_validate(
        {**{c: getattr(goal, c) for c in GoalOut.model_fields if c != "progress"}, "progress": progress.__dict__}
    )


async def list_goals(session: AsyncSession, user_id: uuid.UUID, statuses: tuple[str, ...]) -> list[Goal]:
    rows = await session.scalars(
        select(Goal).where(Goal.user_id == user_id, Goal.status.in_(statuses)).order_by(Goal.priority, Goal.created_at)
    )
    return list(rows)


async def list_goals_out(
    session: AsyncSession, profile: Profile, statuses: tuple[str, ...] = ("active", "paused")
) -> list[GoalOut]:
    goals = await list_goals(session, profile.id, statuses)
    progress = await progress_for_goals(session, goals, profile.timezone)
    return [goal_out(g, progress[g.id]) for g in goals]


async def get_goal(session: AsyncSession, user_id: uuid.UUID, goal_id: uuid.UUID) -> Goal:
    goal = await session.get(Goal, goal_id)
    if goal is None or goal.user_id != user_id:
        raise NotFoundError("goal not found")
    return goal


async def goal_detail(session: AsyncSession, profile: Profile, goal: Goal) -> GoalDetail:
    progress = (await progress_for_goals(session, [goal], profile.timezone))[goal.id]
    milestones = await session.scalars(
        select(Milestone).where(Milestone.goal_id == goal.id).order_by(Milestone.position, Milestone.created_at)
    )
    check_ins = await session.scalars(
        select(CheckIn).where(CheckIn.goal_id == goal.id).order_by(CheckIn.occurred_at.desc()).limit(20)
    )
    base = goal_out(goal, progress)
    return GoalDetail(
        **base.model_dump(),
        milestones=[MilestoneOut.model_validate(m) for m in milestones],
        recent_check_ins=[CheckInOut.model_validate(c) for c in check_ins],
    )


async def create_goal(session: AsyncSession, user_id: uuid.UUID, **fields: Any) -> Goal:
    goal = Goal(user_id=user_id, **fields)
    session.add(goal)
    await session.flush()
    await session.refresh(goal)
    return goal


async def update_goal(session: AsyncSession, goal: Goal, changes: dict[str, Any]) -> Goal:
    for key, value in changes.items():
        if key in MUTABLE_GOAL_FIELDS:
            setattr(goal, key, value)
    await session.flush()
    await session.refresh(goal)
    return goal


async def add_milestones(session: AsyncSession, goal: Goal, items: list[tuple[str, Any]]) -> list[Milestone]:
    start = await session.scalar(
        select(func.coalesce(func.max(Milestone.position), -1)).where(Milestone.goal_id == goal.id)
    )
    created = []
    for offset, (title, due_date) in enumerate(items, start=1):
        milestone = Milestone(
            goal_id=goal.id, user_id=goal.user_id, title=title, due_date=due_date, position=int(start or 0) + offset
        )
        session.add(milestone)
        created.append(milestone)
    await session.flush()
    for milestone in created:
        await session.refresh(milestone)
    return created


async def add_check_in(
    session: AsyncSession,
    goal: Goal,
    *,
    kind: str,
    value: float | None = None,
    note: str | None = None,
    nudge_id: uuid.UUID | None = None,
    source: str = "app",
    occurred_at: datetime | None = None,
) -> CheckIn:
    """Record a check-in and credit any open nudge that prompted it (closing its outcome)."""
    from brian.nudges.outcomes import attribute_check_in  # local import: outcomes imports this module

    check_in = CheckIn(
        user_id=goal.user_id,
        goal_id=goal.id,
        kind=kind,
        value=value,
        note=note,
        nudge_id=nudge_id,
        source=source,
        occurred_at=occurred_at or utcnow(),
    )
    session.add(check_in)
    await session.flush()
    await session.refresh(check_in)
    if kind in ("done", "progress"):
        await attribute_check_in(session, check_in)
    return check_in


def progress_out(progress: GoalProgress) -> GoalProgressOut:
    return GoalProgressOut.model_validate(progress.__dict__)
