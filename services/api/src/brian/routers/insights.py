from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from brian.auth import CurrentProfile, DbSession
from brian.insights.analytics import engagement_stats
from brian.insights.reflection import run_reflection
from brian.models import Insight
from brian.schemas import InsightsOut, PlaybookOut
from brian.timeutils import utcnow

router = APIRouter(prefix="/v1/insights", tags=["insights"])

REFRESH_COOLDOWN = timedelta(hours=1)


def _playbook(insight: Insight | None) -> PlaybookOut | None:
    if insight is None:
        return None
    data: dict[str, Any] = insight.playbook or {}
    return PlaybookOut(
        summary=insight.summary,
        what_works=data.get("what_works", []),
        what_to_avoid=data.get("what_to_avoid", []),
        best_times=data.get("best_times", []),
        experiments=data.get("experiments", []),
        generated_at=insight.created_at,
    )


async def _latest(session: DbSession, profile: CurrentProfile) -> Insight | None:
    return await session.scalar(
        select(Insight).where(Insight.user_id == profile.id).order_by(Insight.created_at.desc()).limit(1)
    )


@router.get("", response_model=InsightsOut)
async def get_insights(profile: CurrentProfile, session: DbSession) -> InsightsOut:
    """Live engagement stats plus the latest playbook Brian wrote about what works for you."""
    stats = await engagement_stats(session, profile.id)
    return InsightsOut(stats=stats, playbook=_playbook(await _latest(session, profile)))


@router.post("/refresh", response_model=InsightsOut)
async def refresh_insights(profile: CurrentProfile, session: DbSession) -> InsightsOut:
    """Ask Brian to reflect on your data now (at most once an hour)."""
    latest = await _latest(session, profile)
    if latest is not None and utcnow() - latest.created_at < REFRESH_COOLDOWN:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="Insights were refreshed recently")
    insight = await run_reflection(session, profile)
    await session.commit()
    return InsightsOut(stats=await engagement_stats(session, profile.id), playbook=_playbook(insight))
