from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from brian.auth import CurrentProfile, DbSession
from brian.models import Goal, Nudge
from brian.nudges.outcomes import ingest_events
from brian.schemas import NudgeEventsBatch, NudgeEventsResult, NudgeOut

router = APIRouter(prefix="/v1/nudges", tags=["nudges"])

VISIBLE_STATUSES = ("sent", "delivered")


def _out(nudge: Nudge, goal_title: str | None) -> NudgeOut:
    return NudgeOut(
        id=nudge.id,
        goal_id=nudge.goal_id,
        goal_title=goal_title,
        source=nudge.source,
        status=nudge.status,
        title=nudge.title,
        body=nudge.body,
        scheduled_for=nudge.scheduled_for,
        sent_at=nudge.sent_at,
        first_interaction_at=nudge.first_interaction_at,
        outcome=nudge.outcome,
        arms={k: str(v) for k, v in (nudge.arms or {}).items()},
    )


@router.get("", response_model=list[NudgeOut])
async def list_nudges(
    profile: CurrentProfile,
    session: DbSession,
    limit: int = Query(default=30, ge=1, le=100),
    before: datetime | None = Query(default=None, description="Cursor: scheduled_for of the last item seen."),
    include_upcoming: bool = Query(default=False, description="Also return reminders not yet sent."),
) -> list[NudgeOut]:
    statuses = (*VISIBLE_STATUSES, "planned") if include_upcoming else VISIBLE_STATUSES
    query = (
        select(Nudge, Goal.title)
        .outerjoin(Goal, Goal.id == Nudge.goal_id)
        .where(Nudge.user_id == profile.id, Nudge.status.in_(statuses))
    )
    if before is not None:
        query = query.where(Nudge.scheduled_for < before)
    rows = await session.execute(query.order_by(Nudge.scheduled_for.desc()).limit(limit))
    return [_out(nudge, title) for nudge, title in rows]


@router.get("/{nudge_id}", response_model=NudgeOut)
async def get_nudge(nudge_id: uuid.UUID, profile: CurrentProfile, session: DbSession) -> NudgeOut:
    row = (
        await session.execute(
            select(Nudge, Goal.title)
            .outerjoin(Goal, Goal.id == Nudge.goal_id)
            .where(Nudge.id == nudge_id, Nudge.user_id == profile.id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Nudge not found")
    return _out(row[0], row[1])


@router.post("/events", response_model=NudgeEventsResult)
async def report_events(body: NudgeEventsBatch, profile: CurrentProfile, session: DbSession) -> NudgeEventsResult:
    """How the person reacted to nudges (delivered, opened, action buttons, dismissed, replied).
    The app queues these offline and sends them in batches; `client_event_id` makes retries safe."""
    result = await ingest_events(session, profile, body.events)
    await session.commit()
    return result
