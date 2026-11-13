"""Request and response models of the public API (the mobile app's types are generated from these
through the OpenAPI schema)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

GoalCategory = Literal[
    "health", "fitness", "learning", "career", "finance", "relationships", "mindfulness", "creativity", "other"
]
GoalCadence = Literal["daily", "weekdays", "weekly", "flexible"]
GoalStatus = Literal["active", "paused", "completed", "archived"]
CheckInKind = Literal["done", "progress", "skipped", "note"]
NudgeIntensity = Literal["gentle", "balanced", "intense"]
NudgeOutcome = Literal["completed", "replied", "snoozed", "opened", "dismissed", "ignored", "negative_feedback"]
Platform = Literal["ios", "android", "web"]

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Profile --------------------------------------------------------------------------------


class ProfileOut(ApiModel):
    id: uuid.UUID
    display_name: str | None
    timezone: str
    locale: str
    nudge_intensity: NudgeIntensity
    quiet_hours_start: time
    quiet_hours_end: time
    nudges_paused_until: datetime | None
    onboarded_at: datetime | None
    created_at: datetime


class ProfileUpdate(BaseModel):
    display_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    timezone: str | None = Field(default=None, description="IANA time zone, e.g. America/New_York")
    locale: str | None = None
    nudge_intensity: NudgeIntensity | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    nudges_paused_until: datetime | None = None
    onboarded: bool | None = Field(default=None, description="Set true when onboarding finishes.")


# --- Devices --------------------------------------------------------------------------------


class DeviceRegister(BaseModel):
    expo_push_token: Annotated[str, StringConstraints(pattern=r"^Expo(nent)?PushToken\[.+\]$")]
    platform: Platform
    device_name: str | None = None
    app_version: str | None = None
    timezone: str | None = Field(default=None, description="Device time zone; updates the profile.")


class DeviceOut(ApiModel):
    id: uuid.UUID
    platform: Platform
    device_name: str | None
    app_version: str | None
    enabled: bool
    last_seen_at: datetime


# --- Goals ----------------------------------------------------------------------------------


class GoalProgressOut(ApiModel):
    current_streak: int
    best_streak: int
    period_count: int
    period_target: int
    period_label: str
    last_check_in_at: datetime | None
    total_check_ins: int


class GoalCreate(BaseModel):
    title: Title
    description: LongText | None = None
    why: LongText | None = Field(default=None, description="Why this matters to the user; fuels the nudges.")
    category: GoalCategory = "other"
    cadence: GoalCadence = "daily"
    target_per_period: int = Field(default=1, ge=1, le=14)
    target_date: date | None = None
    priority: int = Field(default=2, ge=1, le=3)


class GoalUpdate(BaseModel):
    title: Title | None = None
    description: LongText | None = None
    why: LongText | None = None
    category: GoalCategory | None = None
    cadence: GoalCadence | None = None
    target_per_period: int | None = Field(default=None, ge=1, le=14)
    target_date: date | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    status: GoalStatus | None = None


class GoalOut(ApiModel):
    id: uuid.UUID
    title: str
    description: str | None
    why: str | None
    category: GoalCategory
    cadence: GoalCadence
    target_per_period: int
    target_date: date | None
    status: GoalStatus
    priority: int
    created_at: datetime
    updated_at: datetime
    progress: GoalProgressOut


class MilestoneCreate(BaseModel):
    title: Title
    due_date: date | None = None


class MilestoneUpdate(BaseModel):
    title: Title | None = None
    due_date: date | None = None
    completed: bool | None = None


class MilestoneOut(ApiModel):
    id: uuid.UUID
    goal_id: uuid.UUID
    title: str
    due_date: date | None
    position: int
    completed_at: datetime | None


class CheckInCreate(BaseModel):
    kind: CheckInKind = "done"
    value: float | None = None
    note: LongText | None = None
    nudge_id: uuid.UUID | None = Field(default=None, description="The nudge that prompted this, if any.")
    occurred_at: datetime | None = None


class CheckInOut(ApiModel):
    id: uuid.UUID
    goal_id: uuid.UUID
    nudge_id: uuid.UUID | None
    kind: CheckInKind
    value: float | None
    note: str | None
    source: str
    occurred_at: datetime


class GoalDetail(GoalOut):
    milestones: list[MilestoneOut]
    recent_check_ins: list[CheckInOut]


# --- Nudges ---------------------------------------------------------------------------------


class NudgeOut(ApiModel):
    id: uuid.UUID
    goal_id: uuid.UUID | None
    goal_title: str | None = None
    source: str
    status: str
    title: str | None
    body: str | None
    scheduled_for: datetime
    sent_at: datetime | None
    first_interaction_at: datetime | None
    outcome: NudgeOutcome | None
    arms: dict[str, str]


class NudgeEventIn(BaseModel):
    nudge_id: uuid.UUID
    type: Literal["received", "opened", "action", "dismissed", "replied"]
    action_id: Annotated[str, StringConstraints(max_length=64)] | None = Field(
        default=None, description="Notification action identifier, e.g. done / snooze / not_helpful."
    )
    text: Annotated[str, StringConstraints(max_length=2000)] | None = Field(
        default=None, description="Text the user typed in a notification reply."
    )
    occurred_at: datetime
    client_event_id: Annotated[str, StringConstraints(min_length=8, max_length=128)] = Field(
        description="Idempotency key generated on the device."
    )


class NudgeEventsBatch(BaseModel):
    events: list[NudgeEventIn] = Field(min_length=1, max_length=100)


class NudgeEventsResult(BaseModel):
    accepted: int
    duplicates: int
    unknown_nudges: int


# --- Chat -----------------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    conversation_id: uuid.UUID | None = Field(default=None, description="Omit to start a new conversation.")
    nudge_id: uuid.UUID | None = Field(default=None, description="Set when replying to a nudge.")


class ConversationOut(ApiModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    text: str
    created_at: datetime


class ChatEventConversation(BaseModel):
    type: Literal["conversation"] = "conversation"
    conversation_id: uuid.UUID


class ChatEventText(BaseModel):
    type: Literal["text"] = "text"
    delta: str


class ChatEventTool(BaseModel):
    type: Literal["tool"] = "tool"
    name: str
    status: Literal["started", "finished", "failed"]
    label: str


class ChatEventDone(BaseModel):
    type: Literal["done"] = "done"
    message_id: int | None


class ChatEventError(BaseModel):
    type: Literal["error"] = "error"
    message: str
    retryable: bool


ChatStreamEvent = Annotated[
    ChatEventConversation | ChatEventText | ChatEventTool | ChatEventDone | ChatEventError,
    Field(discriminator="type"),
]


# --- Insights -------------------------------------------------------------------------------


class ArmStatOut(BaseModel):
    arm: str
    sent: int
    engaged: int
    mean_reward: float | None
    learned_score: float = Field(description="Posterior mean the policy currently believes for this arm.")


class EngagementStats(BaseModel):
    window_days: int
    nudges_sent: int
    nudges_engaged: int
    engagement_rate: float | None
    completion_rate: float | None
    median_minutes_to_response: float | None
    best_time_window: str | None
    by_dimension: dict[str, list[ArmStatOut]]
    check_ins: int


class PlaybookOut(BaseModel):
    summary: str
    what_works: list[str]
    what_to_avoid: list[str]
    best_times: list[str]
    experiments: list[str]
    generated_at: datetime


class InsightsOut(BaseModel):
    stats: EngagementStats
    playbook: PlaybookOut | None
