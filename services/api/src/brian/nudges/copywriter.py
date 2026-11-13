"""Write a nudge's words with Claude, in the style the policy chose, personalised with the user's
goal, progress, recent reactions and their learned playbook. Falls back to templates."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from brian.agent.llm import LLMUnavailableError, request_extras, require_client
from brian.config import Settings, get_settings
from brian.models import CheckIn, Goal, Insight, Memory, Nudge, Profile
from brian.nudges.arms import ARM_DESCRIPTIONS
from brian.nudges.templates import render_template
from brian.progress import GoalProgress, progress_for_goals
from brian.timeutils import to_local, utcnow

log = logging.getLogger(__name__)

TITLE_MAX = 50
BODY_MAX = 180

COPYWRITER_SYSTEM = """\
You write the push notifications that Brian, a personal AI coach, sends to help one person follow \
through on their long-term goals. A notification is a tiny intervention: it should make the next \
small action feel obvious, doable and worth it right now.

Write each notification:
- About the one goal given, in the requested nudge type, tone, framing and length.
- Like a coach who knows this person: specific to their goal, their reason for it and their \
recent progress. Generic motivational lines are a failure.
- Without shame, guilt-tripping, threats or fake urgency. "Tough love" is candid and caring, never mean.
- Using only facts present in the context. Never invent numbers, streaks or events.
- In different words from the recent notifications listed, which the person has already seen.
- Following the person's playbook when one is given: it summarises what has and hasn't worked for them.
- With at most one emoji, and only when the tone is playful. No hashtags.

The title is 2-5 words and under 40 characters, specific rather than "Reminder". The body follows \
the length style. Write in the person's language (their locale is given)."""


class NudgeCopyOut(BaseModel):
    title: str = Field(description="2-5 words, under 40 characters.")
    body: str = Field(description="The notification text.")


@dataclass
class CopyRequest:
    first_name: str | None
    locale: str
    local_time_label: str
    goal_title: str
    goal_why: str | None
    goal_category: str
    cadence_label: str
    progress: GoalProgress
    arms: dict[str, str]
    playbook: dict[str, Any] | None = None
    recent: list[tuple[str, str | None]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    memories: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CopyResult:
    title: str
    body: str
    source: str


def _clip(value: str, limit: int) -> str:
    value = " ".join(value.split()).strip().strip('"')
    if len(value) <= limit:
        return value
    cut = value[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",;:-") + "…"


def _cadence_label(goal: Goal) -> str:
    if goal.cadence in ("weekly", "flexible"):
        return f"{goal.target_per_period}x per week"
    if goal.cadence == "weekdays":
        return "every weekday"
    return "every day" if goal.target_per_period == 1 else f"{goal.target_per_period}x per day"


def render_prompt(req: CopyRequest) -> str:
    p = req.progress
    last = p.last_check_in_at.isoformat(timespec="minutes") if p.last_check_in_at else "never"
    style = "\n".join(
        f"- {dim}: {arm} ({ARM_DESCRIPTIONS.get(dim, {}).get(arm, '')})"
        for dim, arm in req.arms.items()
        if dim != "time_window"
    )
    lines = [
        "<person>",
        f"First name: {req.first_name or 'unknown'}",
        f"Locale: {req.locale}",
        f"Their local time now: {req.local_time_label}",
        *(f"Known fact: {m}" for m in req.memories),
        "</person>",
        "<goal>",
        f"Title: {req.goal_title}",
        f"Why it matters to them: {req.goal_why or 'not stated'}",
        f"Category: {req.goal_category}; target: {req.cadence_label}",
        f"Progress {p.period_label}: {p.period_count} of {p.period_target}",
        f"Current streak: {p.current_streak} (best {p.best_streak}); last check-in: {last}",
        *(f'Recent note from them: "{n}"' for n in req.notes),
        "</goal>",
        "<style>",
        style,
        "</style>",
    ]
    if req.playbook:
        lines += ["<playbook>"]
        for key in ("what_works", "what_to_avoid", "language_guidelines"):
            for item in req.playbook.get(key, [])[:5]:
                lines.append(f"- {key.replace('_', ' ')}: {item}")
        lines += ["</playbook>"]
    if req.recent:
        lines += ["<recent_notifications>"]
        lines += [f'- "{text}" -> {outcome or "pending"}' for text, outcome in req.recent]
        lines += ["</recent_notifications>"]
    lines.append("Write the notification.")
    return "\n".join(lines)


async def generate_copy(req: CopyRequest, settings: Settings | None = None) -> CopyResult:
    settings = settings or get_settings()
    fallback_title, fallback_body = render_template(
        req.arms.get("nudge_type", "reminder"),
        req.arms.get("tone", "warm"),
        goal_title=req.goal_title,
        streak=req.progress.current_streak,
        period_count=req.progress.period_count,
        period_target=req.progress.period_target,
        period_label=req.progress.period_label,
    )
    try:
        client = require_client(settings)
        response = await client.beta.messages.parse(
            model=settings.copy_model,
            max_tokens=8000,  # thinking counts toward max_tokens
            system=[{"type": "text", "text": COPYWRITER_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": render_prompt(req)}],
            output_format=NudgeCopyOut,
            output_config={"effort": settings.copy_effort},
            **request_extras(settings),
        )
    except LLMUnavailableError:
        return CopyResult(fallback_title, fallback_body, "template")
    except anthropic.AnthropicError as exc:
        log.warning("copywriter failed, using template: %s", exc)
        return CopyResult(fallback_title, fallback_body, "template")

    parsed = response.parsed_output
    if response.stop_reason in ("refusal", "max_tokens") or parsed is None:
        log.warning("copywriter returned no usable copy (stop_reason=%s)", response.stop_reason)
        return CopyResult(fallback_title, fallback_body, "template")
    title = _clip(parsed.title, TITLE_MAX) or fallback_title
    body = _clip(parsed.body, BODY_MAX) or fallback_body
    return CopyResult(title, body, response.model)


async def build_copy_request(
    session: AsyncSession, nudge: Nudge, profile: Profile, goal: Goal, now: datetime | None = None
) -> CopyRequest:
    now = now or utcnow()
    progress = (await progress_for_goals(session, [goal], profile.timezone, now))[goal.id]
    recent_rows = await session.execute(
        select(Nudge.body, Nudge.outcome)
        .where(Nudge.user_id == profile.id, Nudge.sent_at.is_not(None), Nudge.id != nudge.id)
        .order_by(Nudge.sent_at.desc())
        .limit(6)
    )
    notes = await session.scalars(
        select(CheckIn.note)
        .where(CheckIn.goal_id == goal.id, CheckIn.note.is_not(None))
        .order_by(CheckIn.occurred_at.desc())
        .limit(3)
    )
    memories = await session.scalars(
        select(Memory.content).where(Memory.user_id == profile.id).order_by(Memory.created_at.desc()).limit(8)
    )
    playbook = await session.scalar(
        select(Insight.playbook).where(Insight.user_id == profile.id).order_by(Insight.created_at.desc()).limit(1)
    )
    local = to_local(now, profile.timezone)
    first_name = (profile.display_name or "").split(" ")[0] or None
    return CopyRequest(
        first_name=first_name,
        locale=profile.locale,
        local_time_label=local.strftime("%A %H:%M"),
        goal_title=goal.title,
        goal_why=goal.why,
        goal_category=goal.category,
        cadence_label=_cadence_label(goal),
        progress=progress,
        arms=dict(nudge.arms or {}) or {"nudge_type": "reminder", "tone": "warm", "length": "medium"},
        playbook=playbook,
        recent=[(body, outcome) for body, outcome in recent_rows if body],
        notes=[n for n in notes if n],
        memories=list(memories),
    )
