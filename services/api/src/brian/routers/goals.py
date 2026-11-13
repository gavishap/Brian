from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, select

from brian import goals as goal_service
from brian.auth import CurrentProfile, DbSession
from brian.models import CheckIn, Goal, Milestone, Nudge
from brian.progress import progress_for_goals
from brian.schemas import (
    CheckInCreate,
    CheckInOut,
    GoalCreate,
    GoalDetail,
    GoalOut,
    GoalUpdate,
    MilestoneCreate,
    MilestoneOut,
    MilestoneUpdate,
)
from brian.timeutils import utcnow

router = APIRouter(prefix="/v1/goals", tags=["goals"])

STATUS_FILTERS = {
    "current": ("active", "paused"),
    "active": ("active",),
    "all": ("active", "paused", "completed", "archived"),
}


async def _goal(session: DbSession, profile: CurrentProfile, goal_id: uuid.UUID) -> Goal:
    try:
        return await goal_service.get_goal(session, profile.id, goal_id)
    except goal_service.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Goal not found") from exc


@router.get("", response_model=list[GoalOut])
async def list_goals(
    profile: CurrentProfile,
    session: DbSession,
    filter: Literal["current", "active", "all"] = Query(default="current"),
) -> list[GoalOut]:
    return await goal_service.list_goals_out(session, profile, STATUS_FILTERS[filter])


@router.post("", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
async def create_goal(body: GoalCreate, profile: CurrentProfile, session: DbSession) -> GoalOut:
    goal = await goal_service.create_goal(session, profile.id, **body.model_dump())
    await session.commit()
    progress = await progress_for_goals(session, [goal], profile.timezone)
    return goal_service.goal_out(goal, progress[goal.id])


@router.get("/{goal_id}", response_model=GoalDetail)
async def get_goal(goal_id: uuid.UUID, profile: CurrentProfile, session: DbSession) -> GoalDetail:
    return await goal_service.goal_detail(session, profile, await _goal(session, profile, goal_id))


@router.patch("/{goal_id}", response_model=GoalOut)
async def update_goal(goal_id: uuid.UUID, body: GoalUpdate, profile: CurrentProfile, session: DbSession) -> GoalOut:
    goal = await _goal(session, profile, goal_id)
    await goal_service.update_goal(session, goal, body.model_dump(exclude_unset=True))
    await session.commit()
    progress = await progress_for_goals(session, [goal], profile.timezone)
    return goal_service.goal_out(goal, progress[goal.id])


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    goal_id: uuid.UUID,
    profile: CurrentProfile,
    session: DbSession,
    hard: bool = Query(default=False, description="Permanently delete instead of archiving."),
) -> None:
    goal = await _goal(session, profile, goal_id)
    if hard:
        await session.execute(delete(Goal).where(Goal.id == goal.id))
    else:
        goal.status = "archived"
    await session.commit()


@router.post("/{goal_id}/milestones", response_model=MilestoneOut, status_code=status.HTTP_201_CREATED)
async def add_milestone(
    goal_id: uuid.UUID, body: MilestoneCreate, profile: CurrentProfile, session: DbSession
) -> Milestone:
    goal = await _goal(session, profile, goal_id)
    [milestone] = await goal_service.add_milestones(session, goal, [(body.title, body.due_date)])
    await session.commit()
    return milestone


@router.patch("/{goal_id}/milestones/{milestone_id}", response_model=MilestoneOut)
async def update_milestone(
    goal_id: uuid.UUID, milestone_id: uuid.UUID, body: MilestoneUpdate, profile: CurrentProfile, session: DbSession
) -> Milestone:
    goal = await _goal(session, profile, goal_id)
    milestone = await session.get(Milestone, milestone_id)
    if milestone is None or milestone.goal_id != goal.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Milestone not found")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("title"):
        milestone.title = changes["title"]
    if "due_date" in changes:
        milestone.due_date = changes["due_date"]
    if "completed" in changes:
        milestone.completed_at = utcnow() if changes["completed"] else None
    await session.commit()
    await session.refresh(milestone)
    return milestone


@router.delete("/{goal_id}/milestones/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_milestone(
    goal_id: uuid.UUID, milestone_id: uuid.UUID, profile: CurrentProfile, session: DbSession
) -> None:
    goal = await _goal(session, profile, goal_id)
    await session.execute(delete(Milestone).where(Milestone.id == milestone_id, Milestone.goal_id == goal.id))
    await session.commit()


@router.post("/{goal_id}/check-ins", response_model=CheckInOut, status_code=status.HTTP_201_CREATED)
async def create_check_in(
    goal_id: uuid.UUID, body: CheckInCreate, profile: CurrentProfile, session: DbSession
) -> CheckIn:
    goal = await _goal(session, profile, goal_id)
    if body.nudge_id is not None:
        nudge = await session.get(Nudge, body.nudge_id)
        if nudge is None or nudge.user_id != profile.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Nudge not found")
    check_in = await goal_service.add_check_in(
        session,
        goal,
        kind=body.kind,
        value=body.value,
        note=body.note,
        nudge_id=body.nudge_id,
        source="app",
        occurred_at=body.occurred_at,
    )
    await session.commit()
    return check_in


@router.get("/{goal_id}/check-ins", response_model=list[CheckInOut])
async def list_check_ins(
    goal_id: uuid.UUID,
    profile: CurrentProfile,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[CheckIn]:
    goal = await _goal(session, profile, goal_id)
    rows = await session.scalars(
        select(CheckIn).where(CheckIn.goal_id == goal.id).order_by(CheckIn.occurred_at.desc()).limit(limit)
    )
    return list(rows)
