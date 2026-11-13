"""Run a synthetic person through the real engine on a simulated clock.

Nothing is stubbed except the outside world: the planner, policy, dispatcher, event ingestion,
check-in attribution and finalization are the production code paths. Pushes go to an in-memory
recorder, copy comes from the templates (or Claude, if asked), and the person's reactions come
from their hidden preferences.
"""

from __future__ import annotations

import heapq
import json
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from brian.config import Settings, get_settings
from brian.goals import add_check_in, create_goal
from brian.insights.analytics import engagement_stats
from brian.models import Device, Goal, Nudge, PolicyStat, Profile
from brian.nudges.copywriter import CopyRequest, CopyResult
from brian.nudges.dispatcher import FINALIZE_GRACE, dispatch_due_nudges, finalize_expired
from brian.nudges.outcomes import ingest_events
from brian.nudges.planner import plan_next_nudge
from brian.nudges.push import PushMessage, PushTicket
from brian.nudges.templates import render_template
from brian.schemas import NudgeEventIn
from brian.sim.personas import Persona, Reaction
from brian.timeutils import zone

CopyFn = Callable[[CopyRequest], Awaitable[CopyResult]]
SIM_TOKEN_PREFIX = "ExponentPushToken[simulation-"  # noqa: S105 - not a secret


class RecordingPush:
    """Accepts every push; nothing leaves the process."""

    def __init__(self) -> None:
        self.sent: list[PushMessage] = []

    async def send(self, messages: list[PushMessage]) -> list[PushTicket]:
        self.sent += messages
        return [PushTicket("ok", f"sim-{uuid.uuid4().hex[:12]}", None, None) for _ in messages]

    async def receipts(self, ticket_ids: list[str]) -> dict[str, dict[str, Any]]:
        return {t: {"status": "ok"} for t in ticket_ids}


async def template_copy(request: CopyRequest) -> CopyResult:
    title, body = render_template(
        request.arms.get("nudge_type", "reminder"),
        request.arms.get("tone", "warm"),
        goal_title=request.goal_title,
        streak=request.progress.current_streak,
        period_count=request.progress.period_count,
        period_target=request.progress.period_target,
        period_label=request.progress.period_label,
    )
    return CopyResult(title, body, "template")


@dataclass
class SimulationResult:
    persona: str
    policy: str
    days: int
    nudges: int = 0
    engaged: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    # Mean *true* engagement probability of the arms the policy chose, per week: a noise-free
    # measure of how good its decisions were (the learning curve).
    weekly_quality: list[float | None] = field(default_factory=list)
    weekly_engagement: list[float | None] = field(default_factory=list)
    learned: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    truth: dict[str, list[str]] = field(default_factory=dict)

    @property
    def engagement_rate(self) -> float:
        return self.engaged / self.nudges if self.nudges else 0.0

    def best_learned(self, dimension: str) -> str | None:
        rows = self.learned.get(dimension) or []
        return rows[0][0] if rows else None


async def create_person(
    sessionmaker: async_sessionmaker[AsyncSession],
    persona: Persona,
    *,
    email: str | None = None,
    onboarded_at: datetime,
    with_device: bool = True,
) -> uuid.UUID:
    """A synthetic account: auth user (the trigger makes the profile), settings, goals, device."""
    user_id = uuid.uuid4()
    async with sessionmaker() as session:
        await session.execute(
            text("insert into auth.users (id, email, raw_user_meta_data) values (:id, :email, cast(:meta as jsonb))"),
            {
                "id": user_id,
                "email": email or f"sim+{persona.key}-{user_id.hex[:6]}@example.invalid",
                "meta": json.dumps({"display_name": persona.display_name}),
            },
        )
        await session.commit()
    await prepare_account(sessionmaker, user_id, persona, onboarded_at=onboarded_at, with_device=with_device)
    return user_id


async def prepare_account(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    persona: Persona,
    *,
    onboarded_at: datetime,
    with_device: bool = True,
    timezone: str | None = None,
) -> list[uuid.UUID]:
    """Settings and goals for a persona on an existing account; returns the goal ids."""
    async with sessionmaker() as session:
        profile = await session.get(Profile, user_id)
        assert profile is not None, "profile missing (is the sign-up trigger installed?)"
        profile.display_name = profile.display_name or persona.display_name
        profile.timezone = timezone or persona.timezone
        profile.quiet_hours_start = time.fromisoformat(persona.quiet_hours[0])
        profile.quiet_hours_end = time.fromisoformat(persona.quiet_hours[1])
        profile.onboarded_at = profile.onboarded_at or onboarded_at
        await session.execute(
            text("update profiles set created_at = least(created_at, :t) where id = :id"),
            {"t": onboarded_at, "id": user_id},
        )
        existing = set(await session.scalars(select(Goal.title).where(Goal.user_id == user_id)))
        goal_ids = []
        for spec in persona.goals:
            if spec.title in existing:
                continue
            goal = await create_goal(
                session,
                user_id,
                title=spec.title,
                why=spec.why,
                category=spec.category,
                cadence=spec.cadence,
                target_per_period=spec.target_per_period,
            )
            await session.execute(
                text("update goals set created_at = :t where id = :id"), {"t": onboarded_at, "id": goal.id}
            )
            goal_ids.append(goal.id)
        if with_device:
            session.add(
                Device(
                    user_id=user_id,
                    expo_push_token=f"{SIM_TOKEN_PREFIX}{uuid.uuid4().hex[:12]}]",
                    platform="ios",
                    device_name="Simulated phone",
                )
            )
        await session.commit()
    return goal_ids


def _organic_check_ins(
    persona: Persona, goal_ids: list[uuid.UUID], start: datetime, days: int, rng: np.random.Generator
) -> list[tuple[datetime, uuid.UUID]]:
    tz = zone(persona.timezone)
    first_day = start.astimezone(tz).date()
    events = []
    for offset in range(days + 1):
        day = first_day + timedelta(days=offset)
        for goal_id in goal_ids:
            if rng.random() < persona.organic_check_in_rate:
                hour = int(rng.integers(persona.active_hours[0], persona.active_hours[1]))
                moment = datetime.combine(day, time(hour, int(rng.integers(60))), tzinfo=tz)
                if start <= moment:
                    events.append((moment, goal_id))
    return sorted(events)


def _events_for(nudge_id: uuid.UUID, sent_at: datetime, reaction: Reaction) -> list[NudgeEventIn]:
    def event(kind: str, minutes: float, **extra: Any) -> NudgeEventIn:
        return NudgeEventIn(
            nudge_id=nudge_id,
            type=kind,
            occurred_at=sent_at + timedelta(minutes=minutes),
            client_event_id=f"sim-{uuid.uuid4().hex}",
            **extra,
        )

    events = [event("received", 0.2)]
    if reaction.kind == "done":
        events.append(event("action", reaction.delay_minutes, action_id="done"))
    elif reaction.kind == "reply":
        events.append(event("action", reaction.delay_minutes, action_id="reply", text=reaction.text))
    elif reaction.kind == "snooze":
        events.append(event("action", reaction.delay_minutes, action_id="snooze"))
    elif reaction.kind == "opened":
        events.append(event("opened", reaction.delay_minutes))
    elif reaction.kind == "dismissed":
        events.append(event("dismissed", reaction.delay_minutes))
    return events


async def _next_engine_time(session: AsyncSession, user_id: uuid.UUID) -> datetime | None:
    planned = await session.scalar(
        select(func.min(Nudge.scheduled_for)).where(Nudge.user_id == user_id, Nudge.status == "planned")
    )
    expiring = await session.scalar(
        select(func.min(Nudge.expires_at)).where(
            Nudge.user_id == user_id, Nudge.finalized_at.is_(None), Nudge.status.in_(("sent", "delivered"))
        )
    )
    candidates = [t for t in (planned, expiring + FINALIZE_GRACE + timedelta(seconds=1) if expiring else None) if t]
    return min(candidates) if candidates else None


async def simulate_person(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    persona: Persona,
    *,
    start: datetime,
    days: int,
    seed: int = 0,
    policy: str = "learning",
    copy_fn: CopyFn = template_copy,
    finalize_tail: bool = True,
) -> SimulationResult:
    """Simulate `days` of nudges and reactions starting at `start`. `policy="random"` makes every
    choice uniformly at random (epsilon = 1), the baseline the learning policy should beat."""
    base_settings = get_settings()
    settings: Settings = (
        base_settings.model_copy(update={"policy_epsilon": 1.0}) if policy == "random" else base_settings
    )
    rng = np.random.default_rng(seed)
    push = RecordingPush()
    end = start + timedelta(days=days)
    async with sessionmaker() as session:
        goal_ids = list(await session.scalars(select(Goal.id).where(Goal.user_id == user_id, Goal.status == "active")))
    organic = _organic_check_ins(persona, goal_ids, start, days, rng)
    queue: list[tuple[datetime, int, NudgeEventIn]] = []
    counter = 0
    clock = start

    while clock < end:
        # Reactions and organic check-ins that are due.
        due: list[NudgeEventIn] = []
        while queue and queue[0][0] <= clock:
            due.append(heapq.heappop(queue)[2])
        for item in due:
            async with sessionmaker() as session:
                profile = await session.get(Profile, user_id)
                assert profile is not None
                await ingest_events(session, profile, [item], now=item.occurred_at)
                await session.commit()
        while organic and organic[0][0] <= clock:
            moment, goal_id = organic.pop(0)
            async with sessionmaker() as session:
                goal = await session.get(Goal, goal_id)
                if goal is not None:
                    await add_check_in(session, goal, kind="done", source="app", occurred_at=moment, now=moment)
                    await session.commit()

        await finalize_expired(sessionmaker, now=clock, user_id=user_id)

        # Send what is due, and have the person react to it.
        await dispatch_due_nudges(sessionmaker, push, now=clock, copy_fn=copy_fn, user_id=user_id)  # type: ignore[arg-type]
        async with sessionmaker() as session:
            sent = list(
                await session.execute(
                    select(Nudge.id, Nudge.arms).where(Nudge.user_id == user_id, Nudge.sent_at == clock)
                )
            )
        for nudge_id, arms in sent:
            reaction = persona.react(dict(arms or {}), rng)
            for event in _events_for(nudge_id, clock, reaction):
                counter += 1
                heapq.heappush(queue, (event.occurred_at, counter, event))

        # Plan the next one.
        async with sessionmaker() as session:
            profile = await session.get(Profile, user_id)
            assert profile is not None
            await plan_next_nudge(session, profile, now=clock, rng=rng, settings=settings)
            await session.commit()
            engine_next = await _next_engine_time(session, user_id)

        wake = [clock + timedelta(hours=6)]
        if engine_next:
            wake.append(engine_next)
        if queue:
            wake.append(queue[0][0])
        if organic:
            wake.append(organic[0][0])
        clock = max(min(wake), clock + timedelta(minutes=1))

    if finalize_tail:
        tail = end + timedelta(hours=settings.nudge_attribution_hours) + FINALIZE_GRACE + timedelta(minutes=1)
        while queue:
            item = heapq.heappop(queue)[2]
            async with sessionmaker() as session:
                profile = await session.get(Profile, user_id)
                assert profile is not None
                await ingest_events(session, profile, [item], now=item.occurred_at)
                await session.commit()
        await finalize_expired(sessionmaker, now=tail, user_id=user_id)
        report_time = tail
    else:
        report_time = end
    return await summarize(sessionmaker, user_id, persona, start=start, days=days, policy=policy, now=report_time)


async def summarize(
    sessionmaker: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    persona: Persona,
    *,
    start: datetime,
    days: int,
    policy: str,
    now: datetime,
) -> SimulationResult:
    result = SimulationResult(persona=persona.key, policy=policy, days=days)
    async with sessionmaker() as session:
        nudges = list(
            await session.scalars(
                select(Nudge).where(Nudge.user_id == user_id, Nudge.source == "policy", Nudge.finalized_at.is_not(None))
            )
        )
        stats = await engagement_stats(session, user_id, window_days=days + 2, now=now)
    weeks = max(1, (days + 6) // 7)
    quality: list[list[float]] = [[] for _ in range(weeks)]
    engaged: list[list[float]] = [[] for _ in range(weeks)]
    for nudge in nudges:
        result.nudges += 1
        result.outcomes[nudge.outcome or "unknown"] += 1
        if (nudge.reward or 0) >= 0.5:
            result.engaged += 1
        week = min(weeks - 1, max(0, ((nudge.sent_at or nudge.scheduled_for) - start).days // 7))
        quality[week].append(persona.engagement_probability(dict(nudge.arms or {})))
        engaged[week].append(1.0 if (nudge.reward or 0) >= 0.5 else 0.0)
    result.weekly_quality = [round(float(np.mean(w)), 3) if w else None for w in quality]
    result.weekly_engagement = [round(float(np.mean(w)), 3) if w else None for w in engaged]
    for dimension, rows in stats.by_dimension.items():
        tried = [r for r in rows if r.sent > 0]
        result.learned[dimension] = [(r.arm, r.learned_score) for r in sorted(tried, key=lambda r: -r.learned_score)]
        result.truth[dimension] = persona.ranking(dimension, [r.arm for r in rows])
    return result


async def snapshot_population_stats(session: AsyncSession) -> list[dict[str, Any]]:
    rows = await session.scalars(select(PolicyStat).where(PolicyStat.user_id.is_(None)))
    return [
        {
            "user_id": None,
            "dimension": r.dimension,
            "context_key": r.context_key,
            "arm": r.arm,
            "successes": r.successes,
            "failures": r.failures,
            "pulls": r.pulls,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


async def restore_population_stats(session: AsyncSession, snapshot: list[dict[str, Any]]) -> None:
    """Put the population statistics back, so simulated people don't shape real users' priors."""
    await session.execute(delete(PolicyStat).where(PolicyStat.user_id.is_(None)))
    if snapshot:
        await session.execute(insert(PolicyStat), snapshot)
    await session.commit()


async def delete_people(sessionmaker: async_sessionmaker[AsyncSession], user_ids: list[uuid.UUID]) -> None:
    if not user_ids:
        return
    async with sessionmaker() as session:
        # Every table references auth.users with ON DELETE CASCADE.
        await session.execute(text("delete from auth.users where id = any(:ids)"), {"ids": user_ids})
        await session.commit()


def week_label(start: date, index: int) -> str:
    return f"week {index + 1}"
