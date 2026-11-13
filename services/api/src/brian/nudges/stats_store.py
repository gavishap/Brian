"""Persistence for the policy's sufficient statistics (`policy_stats`)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from brian.models import PolicyStat
from brian.nudges.policy import SufficientStats

StatKey = tuple[str, str, str]  # (dimension, context_key, arm)


async def load_stats(
    session: AsyncSession,
    user_id: uuid.UUID,
    keys: Iterable[tuple[str, str]],
    *,
    now: datetime,
    user_half_life_days: float,
    global_half_life_days: float,
) -> tuple[dict[StatKey, SufficientStats], dict[StatKey, SufficientStats]]:
    """Decayed (user, population) statistics for the given (dimension, context_key) slices."""
    slices = list(set(keys))
    if not slices:
        return {}, {}
    conditions = [(PolicyStat.dimension == d) & (PolicyStat.context_key == c) for d, c in slices]
    rows = await session.scalars(
        select(PolicyStat).where(
            or_(PolicyStat.user_id == user_id, PolicyStat.user_id.is_(None)),
            or_(*conditions),
        )
    )
    user: dict[StatKey, SufficientStats] = {}
    population: dict[StatKey, SufficientStats] = {}
    for row in rows:
        key = (row.dimension, row.context_key, row.arm)
        raw = SufficientStats(row.successes, row.failures, row.pulls)
        if row.user_id is None:
            population[key] = raw.decayed(row.updated_at, now, global_half_life_days)
        else:
            user[key] = raw.decayed(row.updated_at, now, user_half_life_days)
    return user, population


_UPSERT = text(
    """
    with params as (
      select cast(:user_id as uuid) as user_id,
             cast(:reward as double precision) as reward,
             cast(:now as timestamptz) as now,
             cast(:half_life as double precision) as half_life
    )
    insert into policy_stats as ps (user_id, dimension, context_key, arm, successes, failures, pulls, updated_at)
    select user_id, :dimension, :context_key, :arm, reward, 1 - reward, 1, now from params
    on conflict on constraint policy_stats_key do update set
      successes = ps.successes * power(
                    0.5,
                    greatest(extract(epoch from ((select now from params) - ps.updated_at))::double precision, 0)
                    / (select half_life from params))
                  + excluded.successes,
      failures = ps.failures * power(
                   0.5,
                   greatest(extract(epoch from ((select now from params) - ps.updated_at))::double precision, 0)
                   / (select half_life from params))
                 + excluded.failures,
      pulls = ps.pulls + 1,
      updated_at = greatest(ps.updated_at, excluded.updated_at)
    """
)


async def record_reward(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    dimension: str,
    context_key: str,
    arm: str,
    reward: float,
    now: datetime,
    half_life_days: float,
) -> None:
    """Decay the existing statistics to `now`, then add one observation."""
    await session.execute(
        _UPSERT,
        {
            "user_id": user_id,
            "dimension": dimension,
            "context_key": context_key,
            "arm": arm,
            "reward": float(min(1.0, max(0.0, reward))),
            "now": now,
            "half_life": half_life_days * 86400.0,
        },
    )
