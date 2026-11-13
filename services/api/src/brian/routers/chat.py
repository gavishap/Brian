from __future__ import annotations

import uuid
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.sse import EventSourceResponse
from sqlalchemy import select

from brian.agent.coach import list_messages, stream_chat
from brian.auth import CurrentProfile, CurrentUser, DbSession, get_current_user
from brian.models import Conversation
from brian.schemas import ChatMessageOut, ChatRequest, ChatStreamEvent, ConversationOut

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat", response_class=EventSourceResponse)
async def chat(
    body: ChatRequest, user: Annotated[CurrentUser, Depends(get_current_user)]
) -> AsyncIterable[ChatStreamEvent]:
    """Send a message to Brian and stream the reply as server-sent events.

    Each event's `data` is one JSON object with a `type`: `conversation` (first), then any number
    of `text` deltas and `tool` activity updates, and finally `done` or `error`.
    """
    async for event in stream_chat(user.id, body):
        yield event


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    profile: CurrentProfile, session: DbSession, limit: int = Query(default=20, ge=1, le=100)
) -> list[Conversation]:
    rows = await session.scalars(
        select(Conversation)
        .where(Conversation.user_id == profile.id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    return list(rows)


@router.get("/conversations/{conversation_id}/messages", response_model=list[ChatMessageOut])
async def get_conversation_messages(
    conversation_id: uuid.UUID, profile: CurrentProfile, session: DbSession
) -> list[ChatMessageOut]:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return [
        ChatMessageOut(id=m.id, role=m.role, text=m.display_text or "", created_at=m.created_at)
        for m in await list_messages(session, conversation)
    ]
