"""One chat turn with Brian, streamed to the app.

The agent loop is the Anthropic SDK's tool runner (it calls Claude, runs the requested tools,
feeds results back and repeats). Around it this module:
- persists every message exactly as sent/received, so later turns replay the history verbatim
  (append-only: keeps thinking blocks valid and the prompt cache warm);
- injects fresh facts about the user as an appended mid-conversation system message each turn,
  instead of editing the system prompt;
- turns SDK stream events into the small event protocol the app renders.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any, cast

import anthropic
from anthropic.types.beta import BetaMessageParam, BetaTextBlockParam
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from brian.agent.llm import LLMUnavailableError, dump_content, request_extras, require_client, text_of
from brian.agent.prompts import COACH_SYSTEM, TOOL_LABELS
from brian.agent.tools import ToolContext, build_tools
from brian.config import get_settings
from brian.db import get_sessionmaker
from brian.goals import list_goals_out
from brian.models import ChatMessage, Conversation, Insight, Memory, Nudge, Profile
from brian.schemas import (
    ChatEventConversation,
    ChatEventDone,
    ChatEventError,
    ChatEventText,
    ChatEventTool,
    ChatRequest,
    ChatStreamEvent,
)
from brian.timeutils import to_local, utcnow

log = logging.getLogger(__name__)

Message = dict[str, Any]


async def build_context_message(
    session: AsyncSession, profile: Profile, nudge_id: uuid.UUID | None, now: datetime
) -> str:
    """Facts for this turn, sent as a mid-conversation system message."""
    local = to_local(now, profile.timezone)
    goals = await list_goals_out(session, profile)
    memories = list(
        await session.scalars(
            select(Memory.content).where(Memory.user_id == profile.id).order_by(Memory.created_at.desc()).limit(20)
        )
    )
    playbook = await session.scalar(
        select(Insight.playbook).where(Insight.user_id == profile.id).order_by(Insight.created_at.desc()).limit(1)
    )
    paused = (
        f"paused until {to_local(profile.nudges_paused_until, profile.timezone):%a %Y-%m-%d %H:%M}"
        if profile.nudges_paused_until and profile.nudges_paused_until > now
        else "active"
    )
    lines = [
        "<context>",
        f"Local time: {local:%A %Y-%m-%d %H:%M} ({profile.timezone})",
        f"Name: {profile.display_name or 'unknown'}",
        f"Nudges: {paused}; intensity {profile.nudge_intensity}; "
        f"quiet hours {profile.quiet_hours_start:%H:%M}-{profile.quiet_hours_end:%H:%M}",
        "Goals:" if goals else "Goals: none yet",
    ]
    for g in goals:
        p = g.progress
        last = to_local(p.last_check_in_at, profile.timezone).strftime("%a %d %b") if p.last_check_in_at else "never"
        lines.append(
            f"- id={g.id} | {g.title} | {g.status} | {g.category}, {g.cadence} x{g.target_per_period} | "
            f"{p.period_count}/{p.period_target} {p.period_label}, streak {p.current_streak}, last check-in {last}"
            + (f" | why: {g.why}" if g.why else "")
        )
    if playbook:
        lines.append(f"What Brian has learned about nudging them: {playbook.get('summary_for_user', '')}")
        for item in playbook.get("what_works", [])[:3]:
            lines.append(f"- works: {item}")
        for item in playbook.get("what_to_avoid", [])[:3]:
            lines.append(f"- avoid: {item}")
    if memories:
        lines.append("Remembered facts:")
        lines += [f"- {m}" for m in memories]
    if nudge_id:
        nudge = await session.get(Nudge, nudge_id)
        if nudge is not None and nudge.user_id == profile.id and nudge.sent_at:
            sent = to_local(nudge.sent_at, profile.timezone)
            lines.append(
                f'They are replying to the nudge sent {sent:%a %H:%M}: "{nudge.title}: {nudge.body}" '
                f"(goal id {nudge.goal_id})."
            )
    lines.append("</context>")
    return "\n".join(lines)


async def _load_history(session: AsyncSession, conversation: Conversation) -> tuple[list[Message], int]:
    """Stored messages ready to replay, repairing turns a crash left unfinished. Returns
    (messages, next_seq)."""
    rows = list(
        await session.scalars(
            select(ChatMessage).where(ChatMessage.conversation_id == conversation.id).order_by(ChatMessage.seq)
        )
    )
    # An unanswered turn (user + context, no reply) was never seen completed by the model: drop it.
    while rows and rows[-1].role == "system":
        dropped = [rows.pop()]
        if rows and rows[-1].role == "user" and rows[-1].display_text is not None:
            dropped.append(rows.pop())
        await session.execute(delete(ChatMessage).where(ChatMessage.id.in_([r.id for r in dropped])))
    next_seq = (rows[-1].seq + 1) if rows else 0
    messages: list[Message] = [{"role": r.role, "content": r.content} for r in rows]

    # A tool call without its result (crash mid-tool) must be answered before anything else.
    if rows and rows[-1].role == "assistant":
        pending = [b["id"] for b in rows[-1].content if isinstance(b, dict) and b.get("type") == "tool_use"]
        if pending:
            repair: Message = {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": "Interrupted before it ran.",
                        "is_error": True,
                    }
                    for tid in pending
                ],
            }
            await _append(session, conversation, next_seq, repair)
            messages.append(repair)
            next_seq += 1
    return messages, next_seq


async def _append(
    session: AsyncSession,
    conversation: Conversation,
    seq: int,
    message: Message,
    *,
    display_text: str | None = None,
    stop_reason: str | None = None,
    usage: dict[str, Any] | None = None,
) -> int:
    # Stored exactly as sent: replaying a different (even equivalent) shape later would change the
    # request prefix, invalidating earlier thinking blocks and the prompt cache.
    content = message["content"]
    row = ChatMessage(
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        seq=seq,
        role=message["role"],
        content=json.loads(json.dumps(content, default=str)),
        display_text=display_text,
        stop_reason=stop_reason,
        usage=usage,
    )
    session.add(row)
    await session.flush()
    return row.id


async def _messages_today(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(ChatMessage)
        .where(
            ChatMessage.user_id == user_id,
            ChatMessage.role == "user",
            ChatMessage.display_text.is_not(None),
            ChatMessage.created_at >= now - timedelta(days=1),
        )
    )
    return int(count or 0)


async def _conversation(session: AsyncSession, profile: Profile, request: ChatRequest) -> Conversation | None:
    settings = get_settings()
    if request.conversation_id is not None:
        conversation = await session.get(Conversation, request.conversation_id)
        if conversation is None or conversation.user_id != profile.id:
            return None
        return conversation
    conversation = Conversation(
        user_id=profile.id,
        title=request.message[:60],
        model=settings.coach_model,  # pinned: thinking blocks are tied to the model that wrote them
        nudge_id=request.nudge_id,
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def stream_chat(user_id: uuid.UUID, request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
    settings = get_settings()
    now = utcnow()
    async with get_sessionmaker()() as session:
        profile = await session.get(Profile, user_id)
        if profile is None:
            yield ChatEventError(message="Profile not found.", retryable=False)
            return
        conversation = await _conversation(session, profile, request)
        if conversation is None:
            yield ChatEventError(message="Conversation not found.", retryable=False)
            return
        await session.commit()
        yield ChatEventConversation(conversation_id=conversation.id)

        if await _messages_today(session, profile.id, now) >= settings.chat_daily_message_limit:
            yield ChatEventError(
                message="You've reached today's message limit. Let's pick this up tomorrow.", retryable=False
            )
            return
        try:
            client = require_client(settings)
        except LLMUnavailableError:
            yield ChatEventError(message="Brian's coach isn't configured on this server yet.", retryable=False)
            return

        history, seq = await _load_history(session, conversation)
        user_message: Message = {"role": "user", "content": [{"type": "text", "text": request.message}]}
        context_text = await build_context_message(session, profile, request.nudge_id, now)
        context_message: Message = {"role": "system", "content": [{"type": "text", "text": context_text}]}
        await _append(session, conversation, seq, user_message, display_text=request.message)
        await _append(session, conversation, seq + 1, context_message)
        seq += 2
        conversation.updated_at = now
        await session.commit()

        runner = client.beta.messages.tool_runner(
            model=conversation.model,
            max_tokens=settings.coach_max_tokens,
            system=[BetaTextBlockParam(type="text", text=COACH_SYSTEM, cache_control={"type": "ephemeral"})],
            tools=build_tools(ToolContext(session=session, profile=profile)),
            messages=cast(list[BetaMessageParam], [*history, user_message, context_message]),
            output_config={"effort": settings.coach_effort},
            cache_control={"type": "ephemeral"},  # also cache the growing conversation prefix
            stream=True,
            max_iterations=settings.coach_max_iterations,
            thread=False,
            **request_extras(settings),
        )
        last_reply_id: int | None = None
        try:
            async for turn in runner:
                tool_names: dict[str, str] = {}
                async for event in turn:
                    if event.type == "content_block_start" and event.content_block.type == "tool_use":
                        name = event.content_block.name
                        tool_names[event.content_block.id] = name
                        yield ChatEventTool(name=name, status="started", label=TOOL_LABELS.get(name, name))
                    elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield ChatEventText(delta=event.delta.text)
                message = await turn.get_final_message()
                content = dump_content(message.content)
                last_reply_id = await _append(
                    session,
                    conversation,
                    seq,
                    {"role": "assistant", "content": content},
                    display_text=text_of(content) or None,
                    stop_reason=message.stop_reason,
                    usage=message.usage.model_dump(mode="json"),
                )
                seq += 1
                await session.commit()

                if message.stop_reason == "refusal":
                    yield ChatEventError(
                        message="I can't help with that one. Let's get back to your goals.", retryable=False
                    )
                    break
                if message.stop_reason != "tool_use":
                    continue  # end_turn / max_tokens: the runner stops by itself
                tool_turn = await runner.generate_tool_call_response()  # runs the tools (cached for the runner)
                if tool_turn is None:
                    continue
                await _append(session, conversation, seq, dict(tool_turn))
                seq += 1
                await session.commit()
                for result in tool_turn["content"]:
                    if not isinstance(result, dict) or result.get("type") != "tool_result":
                        continue
                    name = tool_names.get(str(result.get("tool_use_id")), "tool")
                    yield ChatEventTool(
                        name=name,
                        status="failed" if result.get("is_error") else "finished",
                        label=TOOL_LABELS.get(name, name),
                    )
        except anthropic.RateLimitError:
            yield ChatEventError(message="Brian is busy right now. Try again in a moment.", retryable=True)
            return
        except anthropic.APIConnectionError:
            yield ChatEventError(message="Couldn't reach the coach. Check your connection and retry.", retryable=True)
            return
        except anthropic.APIStatusError as exc:
            log.exception("chat request failed (status %s)", exc.status_code)
            yield ChatEventError(message="Something went wrong on our side.", retryable=exc.status_code >= 500)
            return
        finally:
            await runner.close()
        yield ChatEventDone(message_id=last_reply_id)


async def list_messages(session: AsyncSession, conversation: Conversation, limit: int = 200) -> list[ChatMessage]:
    """Messages the app shows: the person's words and Brian's replies (no tool or context turns)."""
    rows = await session.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.role.in_(("user", "assistant")),
            ChatMessage.display_text.is_not(None),
        )
        .order_by(ChatMessage.seq.desc())
        .limit(limit)
    )
    return list(reversed(list(rows)))
