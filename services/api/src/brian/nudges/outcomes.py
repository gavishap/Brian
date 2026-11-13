"""From raw interaction events to final outcomes, rewards and policy updates."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from brian.config import get_settings
from brian.models import CheckIn, Goal, Nudge, NudgeEvent, Profile
from brian.nudges import rewards
from brian.nudges.stats_store import record_reward
from brian.schemas import NudgeEventIn, NudgeEventsResult
from brian.timeutils import is_quiet, to_local, utcnow

log = logging.getLogger(__name__)

OPEN_STATUSES = ("sent", "delivered")
SNOOZE_MINUTES = 60


async def ingest_events(
    session: AsyncSession, profile: Profile, events: list[NudgeEventIn], *, now: datetime | None = None
) -> NudgeEventsResult:
    """Store device-reported events (idempotently) and apply their side effects. `now` defaults to the
    wall clock (simulations pass their own)."""
    now = now or utcnow()
    accepted = duplicates = unknown = 0
    nudge_ids = {e.nudge_id for e in events}
    nudges = {
        n.id: n
        for n in await session.scalars(select(Nudge).where(Nudge.id.in_(nudge_ids), Nudge.user_id == profile.id))
    }
    for event in sorted(events, key=lambda e: e.occurred_at):
        nudge = nudges.get(event.nudge_id)
        if nudge is None:
            unknown += 1
            continue
        inserted = await session.scalar(
            insert(NudgeEvent)
            .values(
                nudge_id=nudge.id,
                user_id=profile.id,
                event_type=event.type,
                action_id=event.action_id,
                payload={"text": event.text} if event.text else {},
                client_event_id=event.client_event_id,
                occurred_at=event.occurred_at,
            )
            .on_conflict_do_nothing(constraint="nudge_events_client_event_key")
            .returning(NudgeEvent.id)
        )
        if inserted is None:
            duplicates += 1
            continue
        accepted += 1
        await _apply_event(session, profile, nudge, event, now)
    await session.flush()
    return NudgeEventsResult(accepted=accepted, duplicates=duplicates, unknown_nudges=unknown)


async def _apply_event(
    session: AsyncSession, profile: Profile, nudge: Nudge, event: NudgeEventIn, now: datetime
) -> None:
    if event.type == "received":
        if nudge.delivered_at is None:
            nudge.delivered_at = event.occurred_at
        if nudge.status == "sent":
            nudge.status = "delivered"
        return

    if nudge.first_interaction_at is None or event.occurred_at < nudge.first_interaction_at:
        nudge.first_interaction_at = event.occurred_at

    outcome = rewards.outcome_for_event(event.type, event.action_id, bool(event.text))
    goal = await session.get(Goal, nudge.goal_id) if nudge.goal_id else None

    if outcome == "completed" and goal is not None:
        from brian.goals import add_check_in  # local import: goals imports this module

        await add_check_in(
            session, goal, kind="done", nudge_id=nudge.id, source="notification", occurred_at=event.occurred_at, now=now
        )
    elif outcome == "replied" and event.text and goal is not None:
        session.add(
            CheckIn(
                user_id=profile.id,
                goal_id=goal.id,
                nudge_id=nudge.id,
                kind="note",
                note=event.text,
                source="notification",
                occurred_at=event.occurred_at,
            )
        )
    elif outcome == "snoozed":
        await _schedule_snooze(session, profile, nudge, tapped_at=event.occurred_at, now=now)

    if outcome in rewards.TERMINAL_OUTCOMES and event.occurred_at <= nudge.expires_at:
        await finalize_nudge(session, nudge.id, now=now)


async def _schedule_snooze(
    session: AsyncSession, profile: Profile, nudge: Nudge, *, tapped_at: datetime, now: datetime
) -> None:
    """'Later' re-sends the same message an hour after the tap (outside quiet hours). A tap that
    reaches us late from the offline queue is honoured as soon as possible."""
    send_at = max(tapped_at + timedelta(minutes=SNOOZE_MINUTES), now + timedelta(minutes=1))
    for _ in range(48):  # walk forward in 15-minute steps until outside quiet hours
        local = to_local(send_at, profile.timezone).time()
        if not is_quiet(local, profile.quiet_hours_start, profile.quiet_hours_end):
            break
        send_at += timedelta(minutes=15)
    session.add(
        Nudge(
            user_id=profile.id,
            goal_id=nudge.goal_id,
            source="user_scheduled",
            status="planned",
            policy_version="snooze",
            arms={},
            propensities={},
            context={"snoozed_from": str(nudge.id)},
            scheduled_for=send_at,
            expires_at=send_at + timedelta(hours=get_settings().nudge_attribution_hours),
            title=nudge.title,
            body=nudge.body,
            category_id=nudge.category_id,
            requested_text=nudge.body,
        )
    )


async def attribute_check_in(session: AsyncSession, check_in: CheckIn, now: datetime | None = None) -> None:
    """A check-in inside an open nudge's attribution window means the nudge worked: close it."""
    candidates = await session.scalars(
        select(Nudge.id).where(
            Nudge.user_id == check_in.user_id,
            Nudge.finalized_at.is_(None),
            Nudge.status.in_(OPEN_STATUSES),
            or_(
                Nudge.id == check_in.nudge_id,
                (Nudge.goal_id == check_in.goal_id)
                & (Nudge.sent_at <= check_in.occurred_at)
                & (Nudge.expires_at >= check_in.occurred_at),
            ),
        )
    )
    for nudge_id in list(candidates):
        await finalize_nudge(session, nudge_id, now=now or utcnow())


async def finalize_nudge(session: AsyncSession, nudge_id: uuid.UUID, *, now: datetime) -> str | None:
    """Decide a nudge's outcome once, turn it into a reward and update the policy statistics.

    Safe to call repeatedly and concurrently: the row is locked and already-final nudges are skipped.
    """
    settings = get_settings()
    nudge = await session.scalar(select(Nudge).where(Nudge.id == nudge_id).with_for_update())
    if nudge is None or nudge.finalized_at is not None or nudge.status not in OPEN_STATUSES:
        return None

    window_end = min(nudge.expires_at, now)
    events = await session.execute(
        select(NudgeEvent.event_type, NudgeEvent.action_id, NudgeEvent.payload).where(
            NudgeEvent.nudge_id == nudge.id, NudgeEvent.occurred_at <= window_end
        )
    )
    observed = [rewards.outcome_for_event(t, a, bool((p or {}).get("text"))) for t, a, p in events]

    sent_at = nudge.sent_at or nudge.scheduled_for
    attributed = await session.scalar(
        select(CheckIn.id)
        .where(
            CheckIn.user_id == nudge.user_id,
            CheckIn.kind.in_(("done", "progress")),
            or_(
                CheckIn.nudge_id == nudge.id,
                (CheckIn.goal_id == nudge.goal_id) & CheckIn.occurred_at.between(sent_at, window_end),
            ),
        )
        .limit(1)
    )
    if attributed is not None:
        observed.append("completed")

    outcome = rewards.resolve_outcome(observed)
    nudge.outcome = outcome
    nudge.reward = rewards.reward_for(outcome)
    nudge.finalized_at = now
    session.add(
        NudgeEvent(
            nudge_id=nudge.id,
            user_id=nudge.user_id,
            event_type="finalized",
            payload={"outcome": outcome, "reward": nudge.reward},
            occurred_at=now,
        )
    )

    # Only decisions the policy made itself are learned from (a user-scheduled reminder says
    # nothing about which arm works).
    if nudge.source == "policy":
        context_keys = (nudge.context or {}).get("context_keys", {})
        for dimension, arm in (nudge.arms or {}).items():
            reward = rewards.reward_for(outcome, dimension)
            context_key = context_keys.get(dimension, "all")
            await record_reward(
                session,
                user_id=nudge.user_id,
                dimension=dimension,
                context_key=context_key,
                arm=arm,
                reward=reward,
                now=now,
                half_life_days=settings.policy_user_half_life_days,
            )
            await record_reward(
                session,
                user_id=None,
                dimension=dimension,
                context_key=context_key,
                arm=arm,
                reward=reward,
                now=now,
                half_life_days=settings.policy_global_half_life_days,
            )
    await session.flush()
    log.info("nudge finalized", extra={"nudge_id": str(nudge.id), "outcome": outcome})
    return outcome
