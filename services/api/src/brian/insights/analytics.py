"""Deterministic engagement analytics over a user's nudge history."""

from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from brian.config import get_settings
from brian.models import CheckIn, Nudge, PolicyStat
from brian.nudges.arms import DIMENSIONS
from brian.nudges.policy import SufficientStats, posterior
from brian.schemas import ArmStatOut, EngagementStats
from brian.timeutils import utcnow

ENGAGED_THRESHOLD = 0.5


async def engagement_stats(
    session: AsyncSession, user_id: uuid.UUID, *, window_days: int = 30, now: datetime | None = None
) -> EngagementStats:
    settings = get_settings()
    now = now or utcnow()
    since = now - timedelta(days=window_days)
    nudges = list(
        await session.scalars(
            select(Nudge).where(
                Nudge.user_id == user_id,
                Nudge.sent_at >= since,
                Nudge.status.in_(("sent", "delivered")),
            )
        )
    )
    finalized = [n for n in nudges if n.finalized_at is not None and n.reward is not None]
    engaged = [n for n in finalized if (n.reward or 0) >= ENGAGED_THRESHOLD]
    completed = [n for n in finalized if n.outcome == "completed"]
    response_minutes = [
        (n.first_interaction_at - n.sent_at).total_seconds() / 60.0
        for n in nudges
        if n.first_interaction_at and n.sent_at and n.first_interaction_at >= n.sent_at
    ]

    # What the policy currently believes, per arm (user stats with the population prior).
    stat_rows = list(
        await session.scalars(select(PolicyStat).where((PolicyStat.user_id == user_id) | PolicyStat.user_id.is_(None)))
    )
    user_agg: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    pop_agg: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for row in stat_rows:
        half_life = (
            settings.policy_global_half_life_days if row.user_id is None else settings.policy_user_half_life_days
        )
        decayed = SufficientStats(row.successes, row.failures, row.pulls).decayed(row.updated_at, now, half_life)
        target = pop_agg if row.user_id is None else user_agg
        acc = target[(row.dimension, row.arm)]  # summed over context slices for display
        acc[0] += decayed.successes
        acc[1] += decayed.failures
        acc[2] += decayed.pulls

    by_dimension: dict[str, list[ArmStatOut]] = {}
    for dimension, arms in DIMENSIONS.items():
        rows = []
        for arm in arms:
            sent = [n for n in finalized if (n.arms or {}).get(dimension) == arm]
            u = user_agg.get((dimension, arm))
            p = pop_agg.get((dimension, arm))
            post = posterior(
                SufficientStats(u[0], u[1], int(u[2])) if u else None,
                SufficientStats(p[0], p[1], int(p[2])) if p else None,
                settings.policy_prior_strength,
            )
            rows.append(
                ArmStatOut(
                    arm=arm,
                    sent=len(sent),
                    engaged=sum(1 for n in sent if (n.reward or 0) >= ENGAGED_THRESHOLD),
                    mean_reward=round(statistics.fmean(n.reward or 0 for n in sent), 3) if sent else None,
                    learned_score=round(post.mean, 3),
                )
            )
        by_dimension[dimension] = sorted(rows, key=lambda r: r.learned_score, reverse=True)

    best_window = None
    timing = [r for r in by_dimension["time_window"] if r.sent >= 3]
    if timing:
        best_window = max(timing, key=lambda r: r.learned_score).arm

    check_ins = await session.scalar(
        select(func.count()).select_from(CheckIn).where(CheckIn.user_id == user_id, CheckIn.occurred_at >= since)
    )
    return EngagementStats(
        window_days=window_days,
        nudges_sent=len(nudges),
        nudges_engaged=len(engaged),
        engagement_rate=round(len(engaged) / len(finalized), 3) if finalized else None,
        completion_rate=round(len(completed) / len(finalized), 3) if finalized else None,
        median_minutes_to_response=round(statistics.median(response_minutes), 1) if response_minutes else None,
        best_time_window=best_window,
        by_dimension=by_dimension,
        check_ins=int(check_ins or 0),
    )
