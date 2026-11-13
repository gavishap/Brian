"""The worker's job entry points, with Claude disabled and push in dry-run mode."""

from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import select, update

from brian import jobs
from brian.db import get_sessionmaker
from brian.insights.reflection import users_due_for_reflection
from brian.models import Insight, Nudge
from brian.timeutils import utcnow
from tests.conftest import User


async def onboard(client: AsyncClient, user: User) -> None:
    # No quiet hours, so a window is always open whatever time the test runs.
    await client.patch("/v1/me", headers=user.headers, json={"quiet_hours_start": "00:00", "quiet_hours_end": "00:00"})
    await client.post(
        "/v1/devices", headers=user.headers, json={"expo_push_token": "ExponentPushToken[jobs]", "platform": "ios"}
    )
    await client.post("/v1/goals", headers=user.headers, json={"title": "Practice guitar", "why": "Play for my kid"})


async def test_plan_and_send_jobs(client: AsyncClient, user: User) -> None:
    await onboard(client, user)
    reasons = await jobs.plan_nudges()
    assert reasons == {"planned": 1}
    assert await jobs.plan_nudges() == {}  # nobody needs a plan while one is pending

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(update(Nudge).values(scheduled_for=utcnow() - timedelta(minutes=1)))
        await session.commit()
    assert await jobs.send_due_nudges() == {"sent": 1}
    async with sessionmaker() as session:
        nudge = await session.scalar(select(Nudge))
    assert nudge is not None
    assert nudge.copy_source == "template"  # Claude disabled in tests
    assert nudge.body and "Practice guitar" in nudge.body
    assert nudge.push_tickets[0]["ticket_id"].startswith("dry-run-")


async def test_reflection_runs_for_users_with_enough_new_outcomes(client: AsyncClient, user: User) -> None:
    await onboard(client, user)
    sessionmaker = get_sessionmaker()
    now = utcnow()
    async with sessionmaker() as session:
        for i in range(5):
            session.add(
                Nudge(
                    user_id=user.id,
                    source="policy",
                    status="delivered",
                    policy_version="test",
                    arms={"tone": "warm", "time_window": "evening"},
                    scheduled_for=now - timedelta(days=i + 1),
                    expires_at=now - timedelta(days=i + 1) + timedelta(hours=3),
                    sent_at=now - timedelta(days=i + 1),
                    title="Hi",
                    body="Practice?",
                    outcome="completed" if i % 2 else "ignored",
                    reward=1.0 if i % 2 else 0.0,
                    finalized_at=now - timedelta(days=i),
                )
            )
        await session.commit()
        assert await users_due_for_reflection(session, now) == [user.id]

    assert await jobs.reflect() == 1
    async with sessionmaker() as session:
        insight = await session.scalar(select(Insight).where(Insight.user_id == user.id))
        assert insight is not None and insight.model == "heuristic"
        assert insight.stats["nudges_sent"] == 5
        assert await users_due_for_reflection(session, utcnow()) == []  # not again within a week

    insights = (await client.get("/v1/insights", headers=user.headers)).json()
    assert insights["playbook"]["summary"].startswith("Over the last 30 days you engaged with 40%")
