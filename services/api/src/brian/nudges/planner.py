"""Planning: decide the next proactive nudge for a user.

One nudge is planned at a time per user. The planner picks the goal (rule-based: what needs
attention), then lets the policy choose the time window, nudge type, tone, framing and length.
The words themselves are written later, just before sending, so they reflect the latest progress.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from brian.config import Settings, get_settings
from brian.models import Device, Goal, Nudge, Profile
from brian.nudges.arms import DIMENSIONS, DecisionContext, context_key, eligible_arms
from brian.nudges.policy import ArmChoice, posterior, thompson_choose
from brian.nudges.stats_store import load_stats
from brian.progress import GoalProgress, progress_for_goals
from brian.timeutils import TIME_WINDOWS, day_type, to_local, utcnow, window_of, window_slots

log = logging.getLogger(__name__)

DAILY_BUDGET = {"gentle": 1, "balanced": 2, "intense": 3}
LEAD_TIME = timedelta(minutes=5)


@dataclass(frozen=True)
class PlanResult:
    nudge: Nudge | None
    reason: str


async def consecutive_ignored(session: AsyncSession, user_id: uuid.UUID, limit: int = 10) -> int:
    rewards = await session.scalars(
        select(Nudge.reward)
        .where(Nudge.user_id == user_id, Nudge.source == "policy", Nudge.finalized_at.is_not(None))
        .order_by(Nudge.finalized_at.desc())
        .limit(limit)
    )
    streak = 0
    for reward in rewards:
        if reward is not None and reward > 0:
            break
        streak += 1
    return streak


def daily_budget(intensity: str, ignored_in_a_row: int) -> int:
    """Fewer nudges when they are being ignored: each 3 ignored in a row costs one per day."""
    return max(1, DAILY_BUDGET.get(intensity, 2) - ignored_in_a_row // 3)


def choose_goal(
    goals: list[Goal],
    progress: dict[uuid.UUID, GoalProgress],
    last_nudged: dict[uuid.UUID, datetime],
    now: datetime,
    rng: np.random.Generator,
) -> Goal:
    """Sample a goal, favouring unfinished periods, stale goals, priority, and not-just-nudged ones."""
    scores = []
    for goal in goals:
        p = progress[goal.id]
        need = 0.4 if p.period_complete else 1.0
        reference = p.last_check_in_at or goal.created_at
        stale_hours = min(max((now - reference).total_seconds() / 3600.0, 0.0), 168.0)
        recency = 0.3 if goal.id in last_nudged and now - last_nudged[goal.id] < timedelta(hours=12) else 1.0
        scores.append(need * (1.0 + stale_hours / 24.0) * (4 - goal.priority) * recency)
    weights = np.array(scores) / sum(scores)
    return goals[int(rng.choice(len(goals), p=weights))]


def decision_context(
    profile: Profile, goal: Goal, p: GoalProgress, *, day: date, now: datetime, ignored: int
) -> DecisionContext:
    return DecisionContext(
        day_type=day_type(day),
        local_hour=to_local(now, profile.timezone).hour,
        goal_category=goal.category,
        goal_cadence=goal.cadence,
        current_streak=p.current_streak,
        period_complete=p.period_complete,
        period_count=p.period_count,
        period_target=p.period_target,
        total_check_ins=p.total_check_ins,
        hours_since_check_in=(
            round((now - p.last_check_in_at).total_seconds() / 3600.0, 1) if p.last_check_in_at else None
        ),
        consecutive_ignored=ignored,
        days_since_signup=max(0, (now - profile.created_at).days),
    )


async def choose_arms(
    session: AsyncSession,
    profile: Profile,
    ctx: DecisionContext,
    *,
    windows: list[str] | None,
    now: datetime,
    rng: np.random.Generator,
    settings: Settings,
) -> tuple[dict[str, ArmChoice], dict[str, str]]:
    """Thompson-sample one arm per dimension. `windows=None` skips timing (the caller decides when)."""
    dimensions = [d for d in DIMENSIONS if windows is not None or d != "time_window"]
    keys = {d: context_key(d, ctx) for d in dimensions}
    user_stats, population_stats = await load_stats(
        session,
        profile.id,
        keys.items(),
        now=now,
        user_half_life_days=settings.policy_user_half_life_days,
        global_half_life_days=settings.policy_global_half_life_days,
    )
    choices: dict[str, ArmChoice] = {}
    for dimension in dimensions:
        arms = list(windows or []) if dimension == "time_window" else eligible_arms(dimension, ctx)
        posteriors = {
            arm: posterior(
                user_stats.get((dimension, keys[dimension], arm)),
                population_stats.get((dimension, keys[dimension], arm)),
                settings.policy_prior_strength,
            )
            for arm in arms
        }
        choices[dimension] = thompson_choose(dimension, posteriors, rng, epsilon=settings.policy_epsilon)
    return choices, keys


async def plan_next_nudge(
    session: AsyncSession,
    profile: Profile,
    *,
    now: datetime | None = None,
    rng: np.random.Generator | None = None,
    settings: Settings | None = None,
) -> PlanResult:
    settings = settings or get_settings()
    now = now or utcnow()
    rng = rng or np.random.default_rng()

    if profile.nudges_paused_until and profile.nudges_paused_until > now:
        return PlanResult(None, "paused")
    devices = await session.scalar(
        select(func.count()).select_from(Device).where(Device.user_id == profile.id, Device.enabled)
    )
    if not devices:
        return PlanResult(None, "no_devices")
    goals = list(
        await session.scalars(
            select(Goal).where(Goal.user_id == profile.id, Goal.status == "active").order_by(Goal.created_at, Goal.id)
        )
    )
    if not goals:
        return PlanResult(None, "no_active_goals")
    pending = await session.scalar(
        select(func.count())
        .select_from(Nudge)
        .where(Nudge.user_id == profile.id, Nudge.source == "policy", Nudge.status.in_(("planned", "sending")))
    )
    if pending:
        return PlanResult(None, "already_planned")

    ignored = await consecutive_ignored(session, profile.id)
    budget = daily_budget(profile.nudge_intensity, ignored)
    recent = list(
        await session.execute(
            select(Nudge.scheduled_for, Nudge.goal_id, Nudge.status).where(
                Nudge.user_id == profile.id,
                Nudge.status.not_in(("cancelled", "failed")),
                Nudge.scheduled_for >= now - timedelta(days=2),
            )
        )
    )
    last_nudge_at = max((r.scheduled_for for r in recent), default=None)
    if ignored >= 6 and last_nudge_at is not None and now - last_nudge_at < timedelta(hours=48):
        return PlanResult(None, "backing_off")

    not_before = now + LEAD_TIME
    if last_nudge_at is not None:
        not_before = max(not_before, last_nudge_at + timedelta(minutes=settings.nudge_min_gap_minutes))

    local_today = to_local(now, profile.timezone).date()
    plan_day: date | None = None
    windows: dict[str, list[datetime]] = {}
    for day in (local_today, local_today + timedelta(days=1)):
        same_day = [r for r in recent if to_local(r.scheduled_for, profile.timezone).date() == day]
        if len(same_day) >= budget:
            continue
        used = {window_of(to_local(r.scheduled_for, profile.timezone)) for r in same_day}
        windows = {
            w: slots
            for w in TIME_WINDOWS
            if w not in used
            and (
                slots := window_slots(
                    day,
                    w,
                    profile.timezone,
                    quiet_start=profile.quiet_hours_start,
                    quiet_end=profile.quiet_hours_end,
                    not_before=not_before,
                )
            )
        }
        windows = {w: s for w, s in windows.items() if s[0] <= now + timedelta(hours=settings.planning_horizon_hours)}
        if windows:
            plan_day = day
            break
    if plan_day is None:
        return PlanResult(None, "no_open_window")

    progress = await progress_for_goals(session, goals, profile.timezone, now)
    last_nudged: dict[uuid.UUID, datetime] = {}
    for r in recent:
        if r.goal_id is not None:
            last_nudged[r.goal_id] = max(last_nudged.get(r.goal_id, r.scheduled_for), r.scheduled_for)
    goal = choose_goal(goals, progress, last_nudged, now, rng)
    ctx = decision_context(profile, goal, progress[goal.id], day=plan_day, now=now, ignored=ignored)
    choices, keys = await choose_arms(session, profile, ctx, windows=list(windows), now=now, rng=rng, settings=settings)

    slots = windows[choices["time_window"].arm]
    send_at = slots[int(rng.integers(len(slots)))]
    nudge = Nudge(
        user_id=profile.id,
        goal_id=goal.id,
        source="policy",
        status="planned",
        policy_version=settings.policy_version,
        arms={d: c.arm for d, c in choices.items()},
        propensities={d: round(c.propensity, 5) for d, c in choices.items()},
        context={
            **ctx.as_dict(),
            "context_keys": keys,
            "explored": {d: c.explored for d, c in choices.items()},
            "posterior_means": {d: c.posterior_means for d, c in choices.items()},
            "eligible_windows": sorted(windows),
        },
        scheduled_for=send_at,
        expires_at=send_at + timedelta(hours=settings.nudge_attribution_hours),
    )
    session.add(nudge)
    await session.flush()
    return PlanResult(nudge, "planned")


async def users_needing_plans(session: AsyncSession, limit: int = 500) -> list[uuid.UUID]:
    """Users with an active goal, a push-enabled device and no pending policy nudge."""
    rows = await session.execute(
        text(
            """
            select p.id
            from profiles p
            where (p.nudges_paused_until is null or p.nudges_paused_until < now())
              and exists (select 1 from goals g where g.user_id = p.id and g.status = 'active')
              and exists (select 1 from devices d where d.user_id = p.id and d.enabled)
              and not exists (
                select 1 from nudges n
                where n.user_id = p.id and n.source = 'policy' and n.status in ('planned', 'sending')
              )
            order by p.id
            limit :limit
            """
        ),
        {"limit": limit},
    )
    return [r[0] for r in rows]


async def plan_for_user_locked(session: AsyncSession, user_id: uuid.UUID, now: datetime | None = None) -> PlanResult:
    """Plan inside a per-user advisory lock so concurrent workers never double-plan."""
    locked = await session.scalar(text("select pg_try_advisory_xact_lock(hashtext(:k))"), {"k": f"plan:{user_id}"})
    if not locked:
        return PlanResult(None, "locked")
    profile = await session.get(Profile, user_id)
    if profile is None:
        return PlanResult(None, "no_profile")
    return await plan_next_nudge(session, profile, now=now)
