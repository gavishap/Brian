"""The coach agent end to end, with Claude replaced by a mocked HTTP transport: the real SDK tool
runner, real tools and real persistence, with canned streaming responses."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from brian.agent import llm
from brian.config import get_settings
from brian.db import get_sessionmaker
from brian.models import ChatMessage, Goal
from brian.nudges.copywriter import CopyRequest, generate_copy
from brian.progress import GoalProgress
from tests.conftest import User


def sse(*events: dict[str, Any]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def start(message_id: str) -> dict[str, Any]:
    return {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 120, "output_tokens": 1},
        },
    }


def tool_turn() -> bytes:
    goal_input = {"title": "Run 3 times a week", "cadence": "weekly", "target_per_period": 3, "category": "fitness"}
    return sse(
        start("msg_1"),
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": "", "signature": ""},
        },
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig-abc"}},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "create_goal", "input": {}},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": json.dumps(goal_input)},
        },
        {"type": "content_block_stop", "index": 1},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 40},
        },
        {"type": "message_stop"},
    )


def text_turn(message_id: str, *parts: str) -> bytes:
    return sse(
        start(message_id),
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        *({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": p}} for p in parts),
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 12},
        },
        {"type": "message_stop"},
    )


class MockClaude:
    def __init__(self, responses: list[httpx2.Response]) -> None:
        self.responses = responses
        self.requests: list[tuple[dict[str, str], dict[str, Any]]] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append((dict(request.headers), json.loads(request.content)))
        return self.responses.pop(0)

    def client(self) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(
            api_key="test-key",
            max_retries=0,
            http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(self.handler)),
        )


def streaming(body: bytes) -> httpx2.Response:
    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)


@pytest.fixture
def claude(monkeypatch: pytest.MonkeyPatch) -> Iterator[MockClaude]:
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    mock = MockClaude([])
    monkeypatch.setattr(llm, "get_client", mock.client)
    yield mock


def events_of(body: str) -> list[dict[str, Any]]:
    return [json.loads(line[len("data:") :]) for line in body.splitlines() if line.startswith("data:")]


async def chat(client: AsyncClient, user: User, payload: dict[str, Any]) -> list[dict[str, Any]]:
    async with client.stream("POST", "/v1/chat", headers=user.headers, json=payload) as response:
        assert response.status_code == 200
        return events_of("".join([chunk async for chunk in response.aiter_text()]))


async def test_chat_turn_runs_tools_streams_and_persists(client: AsyncClient, user: User, claude: MockClaude) -> None:
    claude.responses += [streaming(tool_turn()), streaming(text_turn("msg_2", "Done! ", "Your running goal is set."))]

    events = await chat(client, user, {"message": "I want to start running"})
    kinds = [e["type"] for e in events]
    assert kinds[0] == "conversation" and kinds[-1] == "done"
    assert {"type": "tool", "name": "create_goal", "status": "started", "label": "Creating your goal"} in events
    assert {"type": "tool", "name": "create_goal", "status": "finished", "label": "Creating your goal"} in events
    assert "".join(e["delta"] for e in events if e["type"] == "text") == "Done! Your running goal is set."

    # The tool really ran against the database.
    async with get_sessionmaker()() as session:
        goal = await session.scalar(select(Goal).where(Goal.user_id == user.id))
        rows = list(
            await session.scalars(select(ChatMessage).where(ChatMessage.user_id == user.id).order_by(ChatMessage.seq))
        )
    assert goal is not None and (goal.title, goal.cadence, goal.target_per_period) == (
        "Run 3 times a week",
        "weekly",
        3,
    )
    assert [r.role for r in rows] == ["user", "system", "assistant", "user", "assistant"]
    assert rows[2].content[0] == {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    assert rows[3].content[0]["type"] == "tool_result" and rows[3].content[0]["tool_use_id"] == "toolu_1"
    assert rows[4].display_text == "Done! Your running goal is set."

    # Request shape: refusal fallbacks, explicit effort, cached system prompt, per-turn context as
    # an appended system message after the user's words.
    headers, first = claude.requests[0]
    assert "server-side-fallback-2026-07-01" in headers["anthropic-beta"]
    assert first["model"] == "claude-opus-5-5"
    assert first["fallbacks"] == "default"
    assert first["output_config"] == {"effort": "medium"}
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert [m["role"] for m in first["messages"]] == ["user", "system"]
    assert first["messages"][1]["content"][0]["text"].startswith("<context>")
    assert {t["name"] for t in first["tools"]} >= {"create_goal", "log_check_in", "schedule_reminder"}
    assert "temperature" not in first

    # The follow-up request carried the assistant turn back unchanged, thinking signature included.
    _, second = claude.requests[1]
    assert second["messages"][2]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig-abc"}
    assert second["messages"][3]["content"][0]["tool_use_id"] == "toolu_1"


async def test_next_turn_replays_history_verbatim(client: AsyncClient, user: User, claude: MockClaude) -> None:
    claude.responses += [streaming(tool_turn()), streaming(text_turn("msg_2", "Set up!"))]
    events = await chat(client, user, {"message": "Help me run more"})
    conversation_id = events[0]["conversation_id"]
    turn_one = claude.requests[1][1]["messages"]

    claude.responses.append(streaming(text_turn("msg_3", "Nice work today.")))
    events = await chat(client, user, {"message": "Ran 5k!", "conversation_id": conversation_id})
    assert events[-1]["type"] == "done"

    replay = claude.requests[2][1]["messages"]
    assert replay[: len(turn_one)] == turn_one  # append-only: the prefix is byte-identical
    assert [m["role"] for m in replay[len(turn_one) :]] == ["assistant", "user", "system"]
    assert claude.requests[2][1]["system"] == claude.requests[0][1]["system"]

    listed = (await client.get(f"/v1/conversations/{conversation_id}/messages", headers=user.headers)).json()
    assert [(m["role"], m["text"]) for m in listed] == [
        ("user", "Help me run more"),
        ("assistant", "Set up!"),
        ("user", "Ran 5k!"),
        ("assistant", "Nice work today."),
    ]


async def test_refusal_is_reported_not_crashed(client: AsyncClient, user: User, claude: MockClaude) -> None:
    refusal = sse(
        start("msg_r"),
        {
            "type": "message_delta",
            "delta": {"stop_reason": "refusal", "stop_sequence": None},
            "usage": {"output_tokens": 0},
        },
        {"type": "message_stop"},
    )
    claude.responses.append(streaming(refusal))
    events = await chat(client, user, {"message": "something off-limits"})
    assert events[-2]["type"] == "error" and events[-1]["type"] == "done"


async def test_copywriter_uses_structured_output(claude: MockClaude) -> None:
    claude.responses.append(
        httpx2.Response(
            200,
            json={
                "id": "msg_c",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"title": "Two minutes?", "body": "Lace up and walk out the door."}),
                    }
                ],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 300, "output_tokens": 30},
            },
        )
    )
    request = CopyRequest(
        first_name="Alex",
        locale="en-US",
        local_time_label="Friday 18:05",
        goal_title="Run 3 times a week",
        goal_why="Energy for my kids",
        goal_category="fitness",
        cadence_label="3x per week",
        progress=GoalProgress(2, 4, 1, 3, "this week", None, 9),
        arms={"nudge_type": "micro_step", "tone": "playful", "framing": "identity", "length": "short"},
    )
    result = await generate_copy(request)
    assert (result.title, result.body, result.source) == (
        "Two minutes?",
        "Lace up and walk out the door.",
        "claude-opus-5-5",
    )

    _, body = claude.requests[0]
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "micro_step" in body["messages"][0]["content"]


async def test_copywriter_falls_back_to_templates_on_api_errors(claude: MockClaude) -> None:
    claude.responses.append(
        httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
    )
    request = CopyRequest(
        first_name=None,
        locale="en-US",
        local_time_label="Friday 18:05",
        goal_title="Read 20 pages",
        goal_why=None,
        goal_category="learning",
        cadence_label="every day",
        progress=GoalProgress(0, 0, 0, 1, "today", None, 0),
        arms={"nudge_type": "reminder", "tone": "direct", "framing": "gain", "length": "short"},
    )
    result = await generate_copy(request)
    assert (result.title, result.body, result.source) == (
        "Read 20 pages",
        "Today's step is still open. Now is a good time.",
        "template",
    )


@pytest.fixture
def no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_ENABLED", "true")
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    llm.get_client.cache_clear()


async def test_without_credentials_nudges_use_templates_and_chat_says_so(
    no_credentials: None, client: AsyncClient, user: User
) -> None:
    request = CopyRequest(
        first_name=None,
        locale="en-US",
        local_time_label="Friday 18:05",
        goal_title="Read 20 pages",
        goal_why=None,
        goal_category="learning",
        cadence_label="every day",
        progress=GoalProgress(0, 0, 0, 1, "today", None, 0),
        arms={"nudge_type": "micro_step", "tone": "warm", "framing": "gain", "length": "short"},
    )
    assert (await generate_copy(request)).source == "template"
    events = await chat(client, user, {"message": "hi"})
    assert events[-1] == {
        "type": "error",
        "message": "Brian's coach isn't configured on this server yet.",
        "retryable": False,
    }


def test_api_key_in_dotenv_reaches_the_sdk(
    no_credentials: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # .env values are read by the settings loader but are not exported to os.environ, where the SDK
    # would look; the client must get the key explicitly.
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BRIAN_ENV_FILE", ".env")
    get_settings.cache_clear()
    llm.get_client.cache_clear()
    try:
        assert llm.has_credentials()
        assert llm.get_client().api_key == "sk-ant-from-dotenv"
    finally:
        llm.get_client.cache_clear()
