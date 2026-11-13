"""The full proactive loop: plan -> write -> push -> react -> learn."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

import asyncpg
import numpy as np
from httpx import AsyncClient
from sqlalchemy import select

from brian.db import get_sessionmaker
from brian.models import Nudge, PolicyStat, Profile
from brian.nudges.copywriter import CopyRequest, CopyResult
from brian.nudges.dispatcher import check_receipts, dispatch_due_nudges, finalize_expired
from brian.nudges.planner import plan_next_nudge
from brian.nudges.push import PushMessage, PushTicket
from brian.timeutils import is_quiet, to_local
from tests.conftest import User

NOW = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)  # Friday 10:00 in New York


class FakePush:
    def __init__(self) -> None:
        self.sent: list[PushMessage] = []

    async def send(self, messages: list[PushMessage]) -> list[PushTicket]:
        self.sent += messages
        return [PushTicket("ok", f"ticket-{uuid.uuid4().hex[:6]}", None, None) for _ in messages]

    async def receipts(self, ticket_ids: list[str]) -> dict[str, dict[str, Any]]:
        return {t: {"status": "ok"} for t in ticket_ids}


async def fake_copy(request: CopyRequest) -> CopyResult:
    return CopyResult(f"{request.arms['tone']} title", f"Time for {request.goal_title}", "test")


async def setup_user(client: AsyncClient, user: User) -> dict[str, Any]:
    await client.patch(
        "/v1/me",
        headers=user.headers,
        json={"timezone": "America/New_York", "quiet_hours_start": "22:00", "quiet_hours_end": "07:30"},
    )
    await client.post(
        "/v1/devices", headers=user.headers, json={"expo_push_token": "ExponentPushToken[t1]", "platform": "ios"}
    )
    response = await client.post(
        "/v1/goals", headers=user.headers, json={"title": "Meditate 10 minutes", "why": "Calmer mornings"}
    )
    return dict(response.json())


async def plan(user: User, now: datetime = NOW, seed: int = 3) -> Nudge | None:
    async with get_sessionmaker()() as session:
        profile = await session.get(Profile, user.id)
        assert profile is not None
        result = await plan_next_nudge(session, profile, now=now, rng=np.random.default_rng(seed))
        await session.commit()
        return result.nudge


async def test_full_loop_learns_from_a_done_tap(client: AsyncClient, user: User, database: str) -> None:
    goal = await setup_user(client, user)

    nudge = await plan(user)
    assert nudge is not None
    assert set(nudge.arms) == {"time_window", "nudge_type", "tone", "framing", "length"}
    assert all(0 < p <= 1 for p in nudge.propensities.values())
    assert nudge.context["context_keys"]["time_window"] == "day_type:weekday"
    local = to_local(nudge.scheduled_for, "America/New_York")
    assert not is_quiet(local.time(), time(22, 0), time(7, 30))
    assert nudge.scheduled_for > NOW
    assert await plan(user) is None  # one pending policy nudge at a time

    # Nothing is due yet; then time passes and it goes out.
    push = FakePush()
    sessionmaker = get_sessionmaker()
    assert await dispatch_due_nudges(sessionmaker, push, now=NOW, copy_fn=fake_copy) == {}  # type: ignore[arg-type]
    send_time = nudge.scheduled_for + timedelta(minutes=1)
    assert await dispatch_due_nudges(sessionmaker, push, now=send_time, copy_fn=fake_copy) == {"sent": 1}  # type: ignore[arg-type]
    [message] = push.sent
    assert message.data["nudge_id"] == str(nudge.id)
    assert message.body == "Time for Meditate 10 minutes"
    assert message.category_id in {"nudge_action", "nudge_reflect"}

    assert await check_receipts(sessionmaker, push, now=send_time + timedelta(minutes=20)) == 1  # type: ignore[arg-type]

    # The person taps "Done" on the notification (event sent twice: retries are idempotent).
    event = {
        "nudge_id": str(nudge.id),
        "type": "action",
        "action_id": "done",
        "occurred_at": (send_time + timedelta(minutes=7)).isoformat(),
        "client_event_id": "evt-done-0001",
    }
    first = await client.post("/v1/nudges/events", headers=user.headers, json={"events": [event]})
    assert first.json() == {"accepted": 1, "duplicates": 0, "unknown_nudges": 0}
    again = await client.post("/v1/nudges/events", headers=user.headers, json={"events": [event]})
    assert again.json() == {"accepted": 0, "duplicates": 1, "unknown_nudges": 0}

    history = (await client.get("/v1/nudges", headers=user.headers)).json()
    assert history[0]["outcome"] == "completed"
    detail = (await client.get(f"/v1/goals/{goal['id']}", headers=user.headers)).json()
    assert detail["progress"]["period_count"] == 1  # the Done tap logged a check-in
    assert detail["recent_check_ins"][0]["source"] == "notification"

    async with sessionmaker() as session:
        stats = list(await session.scalars(select(PolicyStat)))
    user_rows = [s for s in stats if s.user_id == user.id]
    global_rows = [s for s in stats if s.user_id is None]
    assert len(user_rows) == len(global_rows) == 5  # one per dimension, for the user and the population
    assert all(s.successes == 1.0 and s.failures == 0.0 and s.pulls == 1 for s in user_rows)

    conn = await asyncpg.connect(database)
    types = [r["event_type"] for r in await conn.fetch("select event_type from nudge_events order by id")]
    await conn.close()
    assert types == ["sent", "action", "finalized"]


async def test_ignored_nudges_teach_the_policy_and_reduce_frequency(client: AsyncClient, user: User) -> None:
    await setup_user(client, user)
    sessionmaker = get_sessionmaker()
    push = FakePush()
    now = NOW
    for round_ in range(3):
        nudge = await plan(user, now=now, seed=round_)
        assert nudge is not None
        send_time = nudge.scheduled_for + timedelta(minutes=1)
        await dispatch_due_nudges(sessionmaker, push, now=send_time, copy_fn=fake_copy)  # type: ignore[arg-type]
        now = send_time + timedelta(hours=4)
        assert await finalize_expired(sessionmaker, now=now) == 1

    async with sessionmaker() as session:
        outcomes = list(await session.scalars(select(Nudge.outcome).where(Nudge.finalized_at.is_not(None))))
        tone_rows = list(await session.scalars(select(PolicyStat).where(PolicyStat.dimension == "tone")))
    assert outcomes == ["ignored"] * 3
    assert sum(r.failures for r in tone_rows if r.user_id == user.id) > 2.9

    from brian.nudges.planner import daily_budget

    assert daily_budget("balanced", 3) == 1  # three ignored in a row costs a nudge per day


async def test_snooze_reschedules_outside_quiet_hours(client: AsyncClient, user: User) -> None:
    await setup_user(client, user)
    nudge = await plan(user)
    assert nudge is not None
    sessionmaker = get_sessionmaker()
    send_time = nudge.scheduled_for + timedelta(minutes=1)
    await dispatch_due_nudges(sessionmaker, FakePush(), now=send_time, copy_fn=fake_copy)  # type: ignore[arg-type]
    await client.post(
        "/v1/nudges/events",
        headers=user.headers,
        json={
            "events": [
                {
                    "nudge_id": str(nudge.id),
                    "type": "action",
                    "action_id": "snooze",
                    "occurred_at": send_time.isoformat(),
                    "client_event_id": "evt-snooze-01",
                }
            ]
        },
    )
    async with sessionmaker() as session:
        follow_up = await session.scalar(select(Nudge).where(Nudge.source == "user_scheduled"))
    assert follow_up is not None
    assert follow_up.requested_text == "Time for Meditate 10 minutes"
    assert follow_up.scheduled_for >= send_time + timedelta(minutes=59)


async def test_no_nudges_without_devices_or_when_paused(client: AsyncClient, user: User) -> None:
    await client.post("/v1/goals", headers=user.headers, json={"title": "Write"})
    assert await plan(user) is None  # no push device yet
    await client.post(
        "/v1/devices", headers=user.headers, json={"expo_push_token": "ExponentPushToken[t2]", "platform": "android"}
    )
    await client.patch("/v1/me", headers=user.headers, json={"nudges_paused_until": "2026-12-01T00:00:00Z"})
    assert await plan(user) is None
    await client.patch("/v1/me", headers=user.headers, json={"nudges_paused_until": None})
    assert await plan(user) is not None
