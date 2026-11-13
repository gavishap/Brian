from __future__ import annotations

import uuid

import asyncpg
from httpx import AsyncClient

from tests.conftest import User, create_auth_user, make_token


async def test_requires_a_valid_token(client: AsyncClient, user: User) -> None:
    assert (await client.get("/v1/me")).status_code == 401
    forged = make_token(user.id, secret="not-the-project-secret-but-long-enough")
    assert (await client.get("/v1/me", headers={"Authorization": f"Bearer {forged}"})).status_code == 401
    expired = make_token(user.id, expires_in=-60)
    assert (await client.get("/v1/me", headers={"Authorization": f"Bearer {expired}"})).status_code == 401


async def test_profile_round_trip(client: AsyncClient, user: User) -> None:
    me = (await client.get("/v1/me", headers=user.headers)).json()
    assert me["id"] == str(user.id)
    assert me["display_name"] == "Alex"  # from sign-up metadata via the trigger
    assert me["onboarded_at"] is None

    bad = await client.patch("/v1/me", headers=user.headers, json={"timezone": "Mars/Olympus"})
    assert bad.status_code == 422

    updated = await client.patch(
        "/v1/me",
        headers=user.headers,
        json={
            "timezone": "America/New_York",
            "nudge_intensity": "gentle",
            "quiet_hours_start": "21:30",
            "quiet_hours_end": "08:00",
            "onboarded": True,
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["timezone"] == "America/New_York"
    assert body["quiet_hours_start"] == "21:30:00"
    assert body["onboarded_at"] is not None


async def test_profile_created_lazily_when_trigger_missed(client: AsyncClient, database: str) -> None:
    user_id = await create_auth_user(database)
    conn = await asyncpg.connect(database)
    await conn.execute("delete from public.profiles where id = $1", user_id)
    await conn.close()
    response = await client.get("/v1/me", headers={"Authorization": f"Bearer {make_token(user_id)}"})
    assert response.status_code == 200
    assert response.json()["timezone"] == "UTC"


async def test_goal_lifecycle(client: AsyncClient, user: User) -> None:
    created = await client.post(
        "/v1/goals",
        headers=user.headers,
        json={
            "title": "Run 3 times a week",
            "why": "Feel strong at 40",
            "category": "fitness",
            "cadence": "weekly",
            "target_per_period": 3,
        },
    )
    assert created.status_code == 201, created.text
    goal = created.json()
    assert goal["progress"] == {
        "current_streak": 0,
        "best_streak": 0,
        "period_count": 0,
        "period_target": 3,
        "period_label": "this week",
        "last_check_in_at": None,
        "total_check_ins": 0,
    }

    check_in = await client.post(
        f"/v1/goals/{goal['id']}/check-ins", headers=user.headers, json={"kind": "done", "note": "5k easy"}
    )
    assert check_in.status_code == 201, check_in.text

    milestone = await client.post(
        f"/v1/goals/{goal['id']}/milestones", headers=user.headers, json={"title": "First 10k"}
    )
    assert milestone.status_code == 201
    done = await client.patch(
        f"/v1/goals/{goal['id']}/milestones/{milestone.json()['id']}", headers=user.headers, json={"completed": True}
    )
    assert done.json()["completed_at"] is not None

    detail = (await client.get(f"/v1/goals/{goal['id']}", headers=user.headers)).json()
    assert detail["progress"]["period_count"] == 1
    assert [c["note"] for c in detail["recent_check_ins"]] == ["5k easy"]
    assert [m["title"] for m in detail["milestones"]] == ["First 10k"]

    paused = await client.patch(f"/v1/goals/{goal['id']}", headers=user.headers, json={"status": "paused"})
    assert paused.json()["status"] == "paused"
    assert len((await client.get("/v1/goals?filter=active", headers=user.headers)).json()) == 0
    assert len((await client.get("/v1/goals", headers=user.headers)).json()) == 1

    assert (await client.delete(f"/v1/goals/{goal['id']}", headers=user.headers)).status_code == 204
    assert len((await client.get("/v1/goals", headers=user.headers)).json()) == 0
    assert len((await client.get("/v1/goals?filter=all", headers=user.headers)).json()) == 1


async def test_users_cannot_see_each_others_goals(client: AsyncClient, user: User, database: str) -> None:
    other = User(await create_auth_user(database, display_name="Sam"))
    goal = (await client.post("/v1/goals", headers=other.headers, json={"title": "Secret goal"})).json()
    assert (await client.get(f"/v1/goals/{goal['id']}", headers=user.headers)).status_code == 404
    assert (await client.post(f"/v1/goals/{goal['id']}/check-ins", headers=user.headers, json={})).status_code == 404
    assert (await client.get("/v1/goals", headers=user.headers)).json() == []


async def test_device_registration_moves_tokens_between_accounts(
    client: AsyncClient, user: User, database: str
) -> None:
    token = "ExponentPushToken[abc123]"
    body = {"expo_push_token": token, "platform": "ios", "device_name": "iPhone", "timezone": "Europe/London"}
    first = await client.post("/v1/devices", headers=user.headers, json=body)
    assert first.status_code == 200, first.text
    assert (await client.get("/v1/me", headers=user.headers)).json()["timezone"] == "Europe/London"

    other = User(await create_auth_user(database))
    await client.post("/v1/devices", headers=other.headers, json=body)
    conn = await asyncpg.connect(database)
    owner = await conn.fetchval("select user_id from devices where expo_push_token = $1", token)
    await conn.close()
    assert owner == other.id

    assert (
        await client.post("/v1/devices", headers=user.headers, json={**body, "expo_push_token": "nope"})
    ).status_code == 422
    assert (await client.delete(f"/v1/devices/{token}", headers=other.headers)).status_code == 204


async def test_account_deletion_removes_everything(client: AsyncClient, user: User, database: str) -> None:
    goal = (await client.post("/v1/goals", headers=user.headers, json={"title": "Read daily"})).json()
    await client.post(f"/v1/goals/{goal['id']}/check-ins", headers=user.headers, json={})
    assert (await client.delete("/v1/me", headers=user.headers)).status_code == 204
    conn = await asyncpg.connect(database)
    for table in ("goals", "check_ins", "profiles"):
        column = "id" if table == "profiles" else "user_id"
        assert await conn.fetchval(f"select count(*) from {table} where {column} = $1", user.id) == 0  # noqa: S608
    await conn.close()


async def test_events_for_unknown_nudges_are_counted_not_failed(client: AsyncClient, user: User) -> None:
    response = await client.post(
        "/v1/nudges/events",
        headers=user.headers,
        json={
            "events": [
                {
                    "nudge_id": str(uuid.uuid4()),
                    "type": "opened",
                    "occurred_at": "2026-11-13T10:00:00Z",
                    "client_event_id": "evt-00000001",
                }
            ]
        },
    )
    assert response.json() == {"accepted": 0, "duplicates": 0, "unknown_nudges": 1}


async def test_chat_without_llm_streams_a_clear_error(client: AsyncClient, user: User) -> None:
    async with client.stream("POST", "/v1/chat", headers=user.headers, json={"message": "hi"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join([chunk async for chunk in response.aiter_text()])
    assert '"type":"conversation"' in body.replace(" ", "")
    assert '"type":"error"' in body.replace(" ", "")


async def test_insights_for_a_new_user(client: AsyncClient, user: User) -> None:
    insights = (await client.get("/v1/insights", headers=user.headers)).json()
    assert insights["playbook"] is None
    assert insights["stats"]["nudges_sent"] == 0
    assert set(insights["stats"]["by_dimension"]) == {"time_window", "nudge_type", "tone", "framing", "length"}

    refreshed = await client.post("/v1/insights/refresh", headers=user.headers)
    assert refreshed.status_code == 200
    assert "getting to know you" in refreshed.json()["playbook"]["summary"]
    assert (await client.post("/v1/insights/refresh", headers=user.headers)).status_code == 429


async def test_internal_tick_requires_key(client: AsyncClient) -> None:
    assert (await client.post("/internal/tick")).status_code == 403
    response = await client.post("/internal/tick", headers={"X-Internal-Key": "internal-test-key"})
    assert response.status_code == 200
    assert set(response.json()) == {"finalized", "receipts_checked", "planned", "sent"}
