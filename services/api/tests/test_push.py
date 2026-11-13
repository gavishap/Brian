from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import httpx
import pytest

from brian.config import get_settings
from brian.nudges.push import ExpoPushClient, PushMessage, simulator_payload

SIM = "ExponentPushToken[simulator-abc123]"
PHONE = "ExponentPushToken[real-device]"


def message(to: str) -> PushMessage:
    return PushMessage(
        to=to,
        title="Two minutes?",
        body="Lace up and go.",
        data={"kind": "nudge", "nudge_id": "n-1", "goal_id": "g-1"},
        category_id="nudge_action",
        ttl_seconds=600,
    )


def expo_transport(calls: list[object]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"data": [{"status": "ok", "id": f"expo-{i}"} for i, _ in enumerate(body)]})

    return httpx.MockTransport(handler)


@pytest.fixture
def fake_xcrun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An `xcrun` that records its arguments and the payload file instead of pushing."""
    log = tmp_path / "xcrun.log"
    script = tmp_path / "xcrun"
    script.write_text(f'#!/bin/sh\necho "$@" >> {log}\ncat "$5" >> {log}\necho >> {log}\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return log


def test_simulator_payload_matches_what_expo_delivers() -> None:
    payload = simulator_payload(message(SIM), "com.example.brian")
    assert payload == {
        "Simulator Target Bundle": "com.example.brian",
        "aps": {
            "alert": {"title": "Two minutes?", "body": "Lace up and go."},
            "sound": "default",
            "category": "nudge_action",
        },
        "body": {"kind": "nudge", "nudge_id": "n-1", "goal_id": "g-1"},  # expo-notifications reads data here
    }


async def test_simulator_tokens_go_to_simctl_and_others_to_expo(
    fake_xcrun: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("PUSH_DRY_RUN", "false")
    monkeypatch.setenv("PUSH_SIMULATOR_BUNDLE_ID", "com.example.brian")
    get_settings.cache_clear()
    calls: list[object] = []
    client = ExpoPushClient(http=httpx.AsyncClient(transport=expo_transport(calls)))

    tickets = await client.send([message(PHONE), message(SIM), message(PHONE)])

    assert [t.status for t in tickets] == ["ok", "ok", "ok"]
    assert tickets[0].id == "expo-0" and tickets[2].id == "expo-1"  # order preserved around the simulator
    assert tickets[1].id is not None and tickets[1].id.startswith("simulator-")
    assert len(calls) == 1 and [m["to"] for m in calls[0]] == [PHONE, PHONE]  # type: ignore[index]
    recorded = fake_xcrun.read_text().splitlines()  # noqa: ASYNC240 - tiny test fixture file
    assert recorded[0].startswith("simctl push booted com.example.brian ")
    assert json.loads(recorded[1])["body"]["nudge_id"] == "n-1"
    assert (await client.receipts([tickets[1].id]))[tickets[1].id] == {"status": "ok"}
    await client.aclose()


async def test_simulator_tokens_are_unreachable_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("PUSH_DRY_RUN", "false")
    monkeypatch.setenv("PUSH_SIMULATOR_BUNDLE_ID", "com.example.brian")
    get_settings.cache_clear()
    client = ExpoPushClient(http=httpx.AsyncClient(transport=expo_transport([])))
    [ticket] = await client.send([message(SIM)])
    assert (ticket.status, ticket.error) == ("error", "DeviceNotRegistered")  # the dispatcher disables it
    await client.aclose()
