"""Periodic jobs. Run by the worker process on a schedule, or all at once via `POST /internal/tick`
(for hosts where an external cron calls the API instead of running a worker).

Every job is idempotent and safe to run concurrently on several machines (row locks with SKIP
LOCKED, per-user advisory locks), so scaling out the worker needs no coordination.
"""

from __future__ import annotations

import logging
from typing import Any

from brian.db import get_sessionmaker
from brian.insights.reflection import run_due_reflections
from brian.nudges import dispatcher
from brian.nudges.planner import plan_for_user_locked, users_needing_plans
from brian.nudges.push import ExpoPushClient
from brian.timeutils import utcnow

log = logging.getLogger(__name__)


async def plan_nudges() -> dict[str, int]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        user_ids = await users_needing_plans(session)
    reasons: dict[str, int] = {}
    for user_id in user_ids:
        async with sessionmaker() as session:
            try:
                result = await plan_for_user_locked(session, user_id, now=utcnow())
                await session.commit()
            except Exception:
                log.exception("planning failed for user %s", user_id)
                await session.rollback()
                continue
        reasons[result.reason] = reasons.get(result.reason, 0) + 1
    return reasons


async def send_due_nudges(push: ExpoPushClient | None = None) -> dict[str, int]:
    client = push or ExpoPushClient()
    try:
        await dispatcher.recover_stuck_sending(get_sessionmaker())
        return await dispatcher.dispatch_due_nudges(get_sessionmaker(), client)
    finally:
        if push is None:
            await client.aclose()


async def check_push_receipts(push: ExpoPushClient | None = None) -> int:
    client = push or ExpoPushClient()
    try:
        return await dispatcher.check_receipts(get_sessionmaker(), client)
    finally:
        if push is None:
            await client.aclose()


async def finalize_outcomes() -> int:
    return await dispatcher.finalize_expired(get_sessionmaker())


async def reflect() -> int:
    return await run_due_reflections(get_sessionmaker())


async def tick() -> dict[str, Any]:
    """Run one round of everything except reflection (which is daily)."""
    return {
        "finalized": await finalize_outcomes(),
        "receipts_checked": await check_push_receipts(),
        "planned": await plan_nudges(),
        "sent": await send_due_nudges(),
    }
