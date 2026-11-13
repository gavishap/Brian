"""Delivery: claim due nudges, write their copy, push them, and track receipts and expiry."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from brian.models import Device, Goal, Nudge, NudgeEvent, Profile
from brian.nudges.arms import CATEGORY_FOR_TYPE
from brian.nudges.copywriter import CopyRequest, CopyResult, build_copy_request, generate_copy
from brian.nudges.outcomes import finalize_nudge
from brian.nudges.push import ExpoPushClient, PushMessage
from brian.timeutils import is_quiet, to_local, utcnow

log = logging.getLogger(__name__)

CopyFn = Callable[[CopyRequest], Awaitable[CopyResult]]

STALE_AFTER = timedelta(hours=2)  # a policy nudge more than this late is dropped, not sent
RECEIPT_DELAY = timedelta(minutes=15)  # Expo recommends waiting before fetching receipts
FINALIZE_GRACE = timedelta(minutes=30)  # lets offline devices flush late events first


async def claim_due(session: AsyncSession, now: datetime, limit: int) -> list[uuid.UUID]:
    rows = await session.execute(
        text(
            """
            update nudges set status = 'sending'
            where id in (
              select id from nudges
              where status = 'planned' and scheduled_for <= :now
              order by scheduled_for
              limit :limit
              for update skip locked
            )
            returning id
            """
        ),
        {"now": now, "limit": limit},
    )
    return [r[0] for r in rows]


def _skip_reason(nudge: Nudge, profile: Profile, goal: Goal | None, now: datetime) -> str | None:
    if nudge.source != "policy":
        return None  # the user asked for this one
    if profile.nudges_paused_until and profile.nudges_paused_until > now:
        return "paused"
    if goal is None or goal.status != "active":
        return "goal_inactive"
    if now - nudge.scheduled_for > STALE_AFTER:
        return "stale"
    local = to_local(now, profile.timezone).time()
    if is_quiet(local, profile.quiet_hours_start, profile.quiet_hours_end):
        return "quiet_hours"
    return None


async def send_nudge(
    session: AsyncSession,
    nudge_id: uuid.UUID,
    push: ExpoPushClient,
    *,
    now: datetime,
    copy_fn: CopyFn = generate_copy,
) -> str:
    nudge = await session.get(Nudge, nudge_id, with_for_update=True)
    if nudge is None or nudge.status != "sending":
        return "skipped"
    profile = await session.get(Profile, nudge.user_id)
    goal = await session.get(Goal, nudge.goal_id) if nudge.goal_id else None
    assert profile is not None

    reason = _skip_reason(nudge, profile, goal, now)
    if reason:
        nudge.status, nudge.error = "cancelled", reason
        session.add(
            NudgeEvent(nudge_id=nudge.id, user_id=nudge.user_id, event_type="cancelled", payload={"reason": reason})
        )
        await session.commit()
        return f"cancelled:{reason}"

    if nudge.title is None or nudge.body is None:
        if nudge.requested_text:
            nudge.title, nudge.body, nudge.copy_source = (goal.title if goal else "Brian"), nudge.requested_text, "user"
        elif goal is not None:
            copy = await copy_fn(await build_copy_request(session, nudge, profile, goal, now))
            nudge.title, nudge.body, nudge.copy_source = copy.title, copy.body, copy.source
        else:
            nudge.title, nudge.body, nudge.copy_source = "Brian", "Checking in. How are your goals going?", "template"
    nudge.category_id = nudge.category_id or CATEGORY_FOR_TYPE.get(
        (nudge.arms or {}).get("nudge_type", ""), "nudge_action"
    )

    devices = list(await session.scalars(select(Device).where(Device.user_id == nudge.user_id, Device.enabled)))
    if not devices:
        nudge.status, nudge.error = "failed", "no_devices"
        await session.commit()
        return "failed:no_devices"

    ttl = max(60, int((nudge.expires_at - now).total_seconds()))
    messages = [
        PushMessage(
            to=device.expo_push_token,
            title=nudge.title or "Brian",
            body=nudge.body or "",
            data={"kind": "nudge", "nudge_id": str(nudge.id), "goal_id": str(nudge.goal_id) if nudge.goal_id else None},
            category_id=nudge.category_id,
            ttl_seconds=ttl,
        )
        for device in devices
    ]
    try:
        tickets = await push.send(messages)
    except Exception as exc:  # network / Expo outage: retry on the next tick
        log.warning("push send failed for nudge %s: %s", nudge.id, exc)
        nudge.status, nudge.error = "planned", f"send_error: {exc}"[:500]
        await session.commit()
        return "retry"

    records = []
    for device, ticket in zip(devices, tickets, strict=False):
        records.append(
            {"device_id": str(device.id), "ticket_id": ticket.id, "status": ticket.status, "error": ticket.error}
        )
        if ticket.error == "DeviceNotRegistered":
            device.enabled = False
    ok = any(t.status == "ok" for t in tickets)
    nudge.push_tickets = records
    nudge.status = "sent" if ok else "failed"
    nudge.sent_at = now
    nudge.expires_at = max(nudge.expires_at, now + timedelta(minutes=30))
    nudge.error = None if ok else "all_tickets_failed"
    session.add(
        NudgeEvent(
            nudge_id=nudge.id,
            user_id=nudge.user_id,
            event_type="sent" if ok else "failed",
            payload={"tickets": records, "copy_source": nudge.copy_source},
            occurred_at=now,
        )
    )
    await session.commit()
    return nudge.status


async def dispatch_due_nudges(
    sessionmaker: async_sessionmaker[AsyncSession],
    push: ExpoPushClient,
    *,
    now: datetime | None = None,
    limit: int = 50,
    copy_fn: CopyFn = generate_copy,
) -> dict[str, int]:
    now = now or utcnow()
    async with sessionmaker() as session:
        ids = await claim_due(session, now, limit)
        await session.commit()
    results: dict[str, int] = {}
    for nudge_id in ids:
        async with sessionmaker() as session:
            try:
                status = await send_nudge(session, nudge_id, push, now=now, copy_fn=copy_fn)
            except Exception:
                log.exception("failed to send nudge %s", nudge_id)
                await session.rollback()
                await session.execute(
                    update(Nudge).where(Nudge.id == nudge_id).values(status="failed", error="internal_error")
                )
                await session.commit()
                status = "failed"
        results[status] = results.get(status, 0) + 1
    return results


async def recover_stuck_sending(sessionmaker: async_sessionmaker[AsyncSession], now: datetime | None = None) -> int:
    """Nudges left in `sending` by a crashed worker go back to `planned` (stale ones get dropped)."""
    now = now or utcnow()
    async with sessionmaker() as session:
        result = await session.execute(
            update(Nudge)
            .where(Nudge.status == "sending", Nudge.updated_at < now - timedelta(minutes=10))
            .values(status="planned")
        )
        await session.commit()
        return int(getattr(result, "rowcount", 0) or 0)


async def check_receipts(
    sessionmaker: async_sessionmaker[AsyncSession],
    push: ExpoPushClient,
    *,
    now: datetime | None = None,
    limit: int = 500,
) -> int:
    """Mark sent nudges delivered or failed from Expo receipts; disable dead push tokens."""
    now = now or utcnow()
    async with sessionmaker() as session:
        nudges = list(
            await session.scalars(
                select(Nudge)
                .where(
                    Nudge.status == "sent", Nudge.receipts_checked_at.is_(None), Nudge.sent_at <= now - RECEIPT_DELAY
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        ticket_ids = [t["ticket_id"] for n in nudges for t in n.push_tickets if t.get("ticket_id")]
        if not ticket_ids:
            return 0
        receipts = await push.receipts(ticket_ids)
        for nudge in nudges:
            statuses = []
            for ticket in nudge.push_tickets:
                receipt = receipts.get(ticket.get("ticket_id") or "")
                if receipt is None:
                    continue
                statuses.append(receipt.get("status"))
                if (receipt.get("details") or {}).get("error") == "DeviceNotRegistered" and ticket.get("device_id"):
                    await session.execute(
                        update(Device).where(Device.id == uuid.UUID(ticket["device_id"])).values(enabled=False)
                    )
            nudge.receipts_checked_at = now
            if "ok" in statuses:
                nudge.status = "delivered"
                nudge.delivered_at = nudge.delivered_at or now
            elif statuses and all(s == "error" for s in statuses):
                nudge.status = "failed"
                nudge.error = "receipt_error"
        await session.commit()
        return len(nudges)


async def finalize_expired(
    sessionmaker: async_sessionmaker[AsyncSession], *, now: datetime | None = None, limit: int = 500
) -> int:
    """Close attribution windows that have ended: no reaction counts as `ignored`."""
    now = now or utcnow()
    async with sessionmaker() as session:
        ids = list(
            await session.scalars(
                select(Nudge.id)
                .where(
                    Nudge.finalized_at.is_(None),
                    Nudge.status.in_(("sent", "delivered")),
                    Nudge.expires_at < now - FINALIZE_GRACE,
                )
                .limit(limit)
            )
        )
    count = 0
    for nudge_id in ids:
        async with sessionmaker() as session:
            if await finalize_nudge(session, nudge_id, now=now):
                count += 1
            await session.commit()
    return count
