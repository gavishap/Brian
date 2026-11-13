"""ORM models. The schema itself is owned by `supabase/migrations/*.sql`; these classes mirror it
(a test reflects the migrated database and fails on drift)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any, ClassVar

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    Time,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NOW = text("now()")


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        datetime: DateTime(timezone=True),
    }


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, server_default="UTC")
    locale: Mapped[str] = mapped_column(Text, server_default="en-US")
    nudge_intensity: Mapped[str] = mapped_column(Text, server_default="balanced")
    quiet_hours_start: Mapped[time] = mapped_column(Time, server_default="22:00")
    quiet_hours_end: Mapped[time] = mapped_column(Time, server_default="07:30")
    nudges_paused_until: Mapped[datetime | None]
    onboarded_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(server_default=NOW)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    expo_push_token: Mapped[str] = mapped_column(Text, unique=True)
    platform: Mapped[str] = mapped_column(Text)
    device_name: Mapped[str | None] = mapped_column(Text)
    app_version: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_seen_at: Mapped[datetime] = mapped_column(server_default=NOW)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    why: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, server_default="other")
    cadence: Mapped[str] = mapped_column(Text, server_default="daily")
    target_per_period: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    target_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    priority: Mapped[int] = mapped_column(SmallInteger, server_default="2")
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(server_default=NOW)


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("goals.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    position: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    completed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)


class Nudge(Base):
    __tablename__ = "nudges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    goal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("goals.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(Text, server_default="policy")
    status: Mapped[str] = mapped_column(Text, server_default="planned")

    policy_version: Mapped[str] = mapped_column(Text)
    arms: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    propensities: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    context: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    scheduled_for: Mapped[datetime]
    expires_at: Mapped[datetime]

    title: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[str | None] = mapped_column(Text)
    copy_source: Mapped[str | None] = mapped_column(Text)
    requested_text: Mapped[str | None] = mapped_column(Text)

    sent_at: Mapped[datetime | None]
    delivered_at: Mapped[datetime | None]
    push_tickets: Mapped[list[Any]] = mapped_column(server_default=text("'[]'::jsonb"))
    receipts_checked_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)

    first_interaction_at: Mapped[datetime | None]
    outcome: Mapped[str | None] = mapped_column(Text)
    reward: Mapped[float | None] = mapped_column(REAL)
    finalized_at: Mapped[datetime | None]

    created_at: Mapped[datetime] = mapped_column(server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(server_default=NOW)


class NudgeEvent(Base):
    __tablename__ = "nudge_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    nudge_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("nudges.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(Text)
    action_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    client_event_id: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(server_default=NOW)
    received_at: Mapped[datetime] = mapped_column(server_default=NOW)


class CheckIn(Base):
    __tablename__ = "check_ins"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    goal_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("goals.id", ondelete="CASCADE"))
    nudge_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("nudges.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Numeric(asdecimal=False))
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="app")
    occurred_at: Mapped[datetime] = mapped_column(server_default=NOW)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)


class PolicyStat(Base):
    __tablename__ = "policy_stats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    dimension: Mapped[str] = mapped_column(Text)
    context_key: Mapped[str] = mapped_column(Text, server_default="all")
    arm: Mapped[str] = mapped_column(Text)
    successes: Mapped[float] = mapped_column(Double, server_default="0")
    failures: Mapped[float] = mapped_column(Double, server_default="0")
    pulls: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(server_default=NOW)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    title: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    nudge_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("nudges.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(server_default=NOW)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("conversations.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(Text)
    content: Mapped[Any] = mapped_column(JSONB)  # exact content sent to / received from Claude
    display_text: Mapped[str | None] = mapped_column(Text)
    stop_reason: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="agent")
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    period_start: Mapped[datetime]
    period_end: Mapped[datetime]
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB)
    playbook: Mapped[dict[str, Any]] = mapped_column(JSONB)
    summary: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=NOW)
