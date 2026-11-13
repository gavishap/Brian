"""Reflection: Claude reviews a user's engagement data and writes a "nudge playbook" - what works,
what to avoid and how to phrase things. The copywriter reads it on every nudge, and the user sees
the summary on the Insights screen. Runs weekly per user (daily job picks who is due)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Literal

import anthropic
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from brian.agent.llm import LLMUnavailableError, request_extras, require_client
from brian.config import get_settings
from brian.insights.analytics import engagement_stats
from brian.models import Goal, Insight, Memory, Nudge, Profile
from brian.nudges.arms import ARM_DESCRIPTIONS
from brian.schemas import EngagementStats
from brian.timeutils import to_local, utcnow

log = logging.getLogger(__name__)

MIN_NEW_OUTCOMES = 5
REFLECTION_INTERVAL = timedelta(days=7)

REFLECTION_SYSTEM = """\
You are the analyst behind Brian, an AI coach that sends people proactive nudges about their \
long-term goals. You review one person's data: which nudges they acted on, replied to, opened, \
dismissed or ignored, along with each nudge's timing, type, tone, framing, length and wording.

Find the patterns that should change how Brian nudges this person, and write them as a playbook:
- Ground every claim in the data provided. With only a few data points, say what looks promising \
rather than stating it as fact. Never invent numbers.
- Prefer specific, actionable guidance ("short questions about the 'why' get replies; streak \
reminders get dismissed") over generic coaching advice.
- language_guidelines are instructions for the copywriter: concrete phrasing, words or angles \
to use or avoid for this person.
- experiments are small hypotheses worth testing next, e.g. a time window or tone that has \
little data but early promise.
- summary_for_user is shown to the person in the app: 2-4 warm, plain-language sentences in the \
second person about what Brian has learned and will do differently. No jargon like "arms" or \
"reward"."""


class PlaybookModel(BaseModel):
    summary_for_user: str = Field(description="2-4 sentences addressed to the person, plain language.")
    what_works: list[str] = Field(description="Patterns that drove engagement.")
    what_to_avoid: list[str] = Field(description="Patterns that were ignored, dismissed or disliked.")
    language_guidelines: list[str] = Field(description="Concrete wording guidance for future nudges.")
    best_times: list[str] = Field(description="When this person responds best, if the data shows it.")
    experiments: list[str] = Field(description="Hypotheses to test next.")
    recommended_intensity: Literal["gentle", "balanced", "intense", "keep"]


def _describe_arms(arms: dict[str, str]) -> str:
    return ", ".join(f"{k}={v}" for k, v in arms.items())


async def _evidence(session: AsyncSession, profile: Profile, stats: EngagementStats, now: datetime) -> str:
    nudges = list(
        await session.scalars(
            select(Nudge)
            .where(Nudge.user_id == profile.id, Nudge.finalized_at.is_not(None), Nudge.sent_at.is_not(None))
            .order_by(Nudge.sent_at.desc())
            .limit(30)
        )
    )
    goals = list(await session.scalars(select(Goal).where(Goal.user_id == profile.id, Goal.status == "active")))
    memories = list(await session.scalars(select(Memory.content).where(Memory.user_id == profile.id).limit(10)))
    previous = await session.scalar(
        select(Insight.playbook).where(Insight.user_id == profile.id).order_by(Insight.created_at.desc()).limit(1)
    )
    lines = ["<goals>"]
    lines += [f"- {g.title} ({g.category}, {g.cadence} x{g.target_per_period}); why: {g.why or 'n/a'}" for g in goals]
    lines += ["</goals>", "<known_facts>", *(f"- {m}" for m in memories), "</known_facts>"]
    lines += ["<aggregate_stats>", stats.model_dump_json(indent=1), "</aggregate_stats>"]
    lines += ["<arm_meanings>", json.dumps(ARM_DESCRIPTIONS, indent=1), "</arm_meanings>"]
    lines.append("<nudges newest_first='true'>")
    for n in nudges:
        sent_local = to_local(n.sent_at, profile.timezone) if n.sent_at else None
        minutes = (
            round((n.first_interaction_at - n.sent_at).total_seconds() / 60)
            if n.first_interaction_at and n.sent_at
            else None
        )
        lines.append(
            f"- {sent_local:%a %H:%M} | {_describe_arms(n.arms or {})} | "
            f'"{n.title}: {n.body}" | outcome={n.outcome} | minutes_to_first_interaction={minutes}'
            if sent_local
            else f"- {_describe_arms(n.arms or {})} | outcome={n.outcome}"
        )
    lines.append("</nudges>")
    if previous:
        lines += ["<previous_playbook>", json.dumps(previous, indent=1), "</previous_playbook>"]
    lines.append(f"Today is {to_local(now, profile.timezone):%A %Y-%m-%d}. Write the updated playbook.")
    return "\n".join(lines)


def heuristic_playbook(stats: EngagementStats) -> PlaybookModel:
    """Data-only playbook used when Claude is not available."""

    def top(dimension: str) -> str | None:
        rows = [r for r in stats.by_dimension.get(dimension, []) if r.sent >= 2]
        return rows[0].arm if rows else None

    works = [f"{dim.replace('_', ' ')}: {arm}" for dim in ("tone", "framing", "nudge_type") if (arm := top(dim))]
    times = [ARM_DESCRIPTIONS["time_window"][stats.best_time_window]] if stats.best_time_window else []
    rate = f"{round((stats.engagement_rate or 0) * 100)}%"
    summary = (
        f"Over the last {stats.window_days} days you engaged with {rate} of Brian's nudges. "
        "Brian keeps adjusting when and how it reaches out based on what you respond to."
        if stats.nudges_sent
        else "Brian is still getting to know you. Respond to a few nudges and patterns will show up here."
    )
    return PlaybookModel(
        summary_for_user=summary,
        what_works=works,
        what_to_avoid=[],
        language_guidelines=[],
        best_times=times,
        experiments=[],
        recommended_intensity="keep",
    )


async def run_reflection(session: AsyncSession, profile: Profile, *, now: datetime | None = None) -> Insight:
    settings = get_settings()
    now = now or utcnow()
    stats = await engagement_stats(session, profile.id, window_days=30, now=now)
    playbook: PlaybookModel | None = None
    model_name: str | None = None
    try:
        client = require_client(settings)
        response = await client.beta.messages.parse(
            model=settings.reflection_model,
            max_tokens=16000,
            system=REFLECTION_SYSTEM,
            messages=[{"role": "user", "content": await _evidence(session, profile, stats, now)}],
            output_format=PlaybookModel,
            output_config={"effort": settings.reflection_effort},
            **request_extras(settings),
        )
        if response.stop_reason not in ("refusal", "max_tokens") and response.parsed_output is not None:
            playbook, model_name = response.parsed_output, response.model
        else:
            log.warning("reflection returned no playbook (stop_reason=%s)", response.stop_reason)
    except LLMUnavailableError:
        pass
    except anthropic.AnthropicError as exc:
        log.warning("reflection failed for %s: %s", profile.id, exc)

    if playbook is None:
        playbook, model_name = heuristic_playbook(stats), "heuristic"

    insight = Insight(
        user_id=profile.id,
        period_start=now - timedelta(days=stats.window_days),
        period_end=now,
        stats=stats.model_dump(mode="json"),
        playbook=playbook.model_dump(mode="json"),
        summary=playbook.summary_for_user,
        model=model_name,
    )
    session.add(insight)
    await session.flush()
    return insight


async def users_due_for_reflection(session: AsyncSession, now: datetime, limit: int = 100) -> list[uuid.UUID]:
    last_insight = (
        select(Insight.user_id, func.max(Insight.created_at).label("last_at")).group_by(Insight.user_id).subquery()
    )
    rows = await session.execute(
        select(Nudge.user_id)
        .outerjoin(last_insight, last_insight.c.user_id == Nudge.user_id)
        .where(
            Nudge.finalized_at.is_not(None),
            (last_insight.c.last_at.is_(None)) | (Nudge.finalized_at > last_insight.c.last_at),
            (last_insight.c.last_at.is_(None)) | (last_insight.c.last_at < now - REFLECTION_INTERVAL),
        )
        .group_by(Nudge.user_id)
        .having(func.count() >= MIN_NEW_OUTCOMES)
        .limit(limit)
    )
    return [r[0] for r in rows]


async def run_due_reflections(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    now = utcnow()
    async with sessionmaker() as session:
        user_ids = await users_due_for_reflection(session, now)
    done = 0
    for user_id in user_ids:
        async with sessionmaker() as session:
            profile = await session.get(Profile, user_id)
            if profile is None:
                continue
            try:
                await run_reflection(session, profile, now=now)
                await session.commit()
                done += 1
            except Exception:
                log.exception("reflection failed for %s", user_id)
                await session.rollback()
    return done
