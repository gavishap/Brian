"""The engine learns hidden preferences from reactions alone (synthetic people, real code paths)."""

from __future__ import annotations

from argparse import Namespace
from datetime import timedelta

import asyncpg
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from brian.db import get_sessionmaker
from brian.devtools import cmd_nudge_now, cmd_seed, cmd_simulate
from brian.models import Device, Goal, Insight, Memory, Nudge, PolicyStat, Profile
from brian.nudges.arms import DIMENSIONS
from brian.sim.personas import PERSONAS
from brian.sim.runner import create_person, restore_population_stats, simulate_person
from brian.timeutils import utcnow
from tests.conftest import User, create_auth_user, make_token


async def test_policy_learns_hidden_preferences_and_beats_random() -> None:
    sessionmaker = get_sessionmaker()
    persona = PERSONAS["sam"]
    start = utcnow() - timedelta(days=23)

    learner = await create_person(sessionmaker, persona, onboarded_at=start)
    learning = await simulate_person(sessionmaker, learner, persona, start=start, days=21, seed=3)
    async with sessionmaker() as session:
        await restore_population_stats(session, [])  # the baseline starts from the same (empty) prior
    baseline_user = await create_person(sessionmaker, persona, onboarded_at=start)
    baseline = await simulate_person(
        sessionmaker, baseline_user, persona, start=start, days=21, seed=3, policy="random"
    )

    assert learning.nudges >= 25 and baseline.nudges >= 20
    assert learning.engagement_rate > baseline.engagement_rate + 0.1
    true_windows = persona.ranking("time_window", list(DIMENSIONS["time_window"]))
    assert learning.best_learned("time_window") in true_windows[:2]
    random_quality = [q for q in baseline.weekly_quality if q is not None]
    assert (learning.weekly_quality[-1] or 0) > sum(random_quality) / len(random_quality)
    assert sum(learning.outcomes.values()) == learning.nudges


async def test_simulate_command_cleans_up_after_itself(capsys: pytest.CaptureFixture[str], database: str) -> None:
    code = await cmd_simulate(Namespace(personas="jordan", days=5, seed=1, baseline=False, keep=False))
    assert code == 0
    assert "Jordan" in capsys.readouterr().out
    conn = await asyncpg.connect(database)
    try:
        assert await conn.fetchval("select count(*) from auth.users") == 0
        assert await conn.fetchval("select count(*) from policy_stats where user_id is null") == 0  # restored
    finally:
        await conn.close()


async def test_seed_fills_an_existing_account(client: AsyncClient, database: str) -> None:
    user_id = await create_auth_user(database, display_name=None)
    conn = await asyncpg.connect(database)
    email = await conn.fetchval("select email from auth.users where id = $1", user_id)
    await conn.close()

    code = await cmd_seed(
        Namespace(email=email, persona="maya", days=7, seed=1, timezone=None, llm=False, create=False)
    )
    assert code == 0
    async with get_sessionmaker()() as session:
        profile = await session.get(Profile, user_id)
        assert profile is not None and profile.onboarded_at is not None
        assert profile.display_name == "Maya" and profile.timezone == "America/Los_Angeles"
        assert await session.scalar(select(func.count()).select_from(Goal).where(Goal.user_id == user_id)) == 2
        nudges = list(await session.scalars(select(Nudge).where(Nudge.user_id == user_id)))
        assert len([n for n in nudges if n.outcome]) >= 5
        assert not [n for n in nudges if n.status == "planned" and n.scheduled_for < utcnow()]
        assert await session.scalar(select(func.count()).select_from(Insight).where(Insight.user_id == user_id)) == 1
        assert await session.scalar(select(func.count()).select_from(Memory).where(Memory.user_id == user_id)) == 3
        devices = list(await session.scalars(select(Device).where(Device.user_id == user_id)))
        assert devices and not any(d.enabled for d in devices)  # the stand-in phone is switched off
        assert await session.scalar(select(func.count()).select_from(PolicyStat).where(PolicyStat.user_id == user_id))

    headers = {"Authorization": f"Bearer {make_token(user_id)}"}
    insights = (await client.get("/v1/insights", headers=headers)).json()
    assert insights["stats"]["nudges_sent"] >= 5
    assert insights["playbook"] is not None
    history = (await client.get("/v1/nudges", headers=headers)).json()
    assert history and history[0]["title"]


async def test_seed_requires_an_account(capsys: pytest.CaptureFixture[str]) -> None:
    code = await cmd_seed(
        Namespace(email="nobody@example.com", persona="maya", days=3, seed=1, timezone=None, llm=False, create=False)
    )
    assert code == 1
    assert "Sign in once in the app" in capsys.readouterr().err


async def test_nudge_now_sends_immediately_without_teaching_the_policy(client: AsyncClient, user: User) -> None:
    await client.post("/v1/goals", headers=user.headers, json={"title": "Stretch", "why": "Back pain"})
    await client.post(
        "/v1/devices", headers=user.headers, json={"expo_push_token": "ExponentPushToken[now]", "platform": "ios"}
    )
    conn_email = f"{user.id.hex[:8]}@example.com"
    assert await cmd_nudge_now(Namespace(email=conn_email, llm=False)) == 0
    async with get_sessionmaker()() as session:
        nudge = await session.scalar(select(Nudge).where(Nudge.user_id == user.id))
    assert nudge is not None
    assert (nudge.status, nudge.source, nudge.copy_source) == ("sent", "agent", "template")
    assert "time_window" not in nudge.arms and set(nudge.arms) == set(DIMENSIONS) - {"time_window"}
