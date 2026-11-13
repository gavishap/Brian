"""The coach's tools: typed async functions over the user's data, turned into Claude tools by the
Anthropic SDK (`beta_async_tool` derives each JSON schema from the signature and docstring and
validates inputs before the function runs). They are built per request, bound to that user.

Eager input streaming is left off on purpose: inputs are a few short fields, and the buffered
default means the server validates them, so already-streamed chat text never has to be retracted.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from anthropic import beta_async_tool
from anthropic.lib.tools import ToolError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from brian import goals as goal_service
from brian.config import get_settings
from brian.insights.analytics import engagement_stats
from brian.models import CheckIn, Goal, Insight, Memory, Nudge, Profile
from brian.progress import progress_for_goals
from brian.timeutils import to_local, utcnow, zone

GoalCategory = Literal[
    "health", "fitness", "learning", "career", "finance", "relationships", "mindfulness", "creativity", "other"
]
GoalCadence = Literal["daily", "weekdays", "weekly", "flexible"]


@dataclass
class ToolContext:
    session: AsyncSession
    profile: Profile


class MilestoneInput(BaseModel):
    title: str = Field(description="Short milestone title.")
    due_date: date | None = Field(default=None, description="Optional due date, YYYY-MM-DD.")


def _json(data: Any) -> str:
    return json.dumps(data, default=str, ensure_ascii=False)


def build_tools(ctx: ToolContext) -> list[Any]:
    session, profile = ctx.session, ctx.profile

    async def _goal(goal_id: str) -> Goal:
        try:
            return await goal_service.get_goal(session, profile.id, uuid.UUID(goal_id))
        except (ValueError, goal_service.NotFoundError) as exc:
            raise ToolError(f"No goal with id {goal_id}. Call list_goals to get valid ids.") from exc

    @beta_async_tool
    async def list_goals(include_inactive: bool = False) -> str:
        """List the person's goals with progress (streak, this period's count vs target, last check-in).

        Call this before answering anything about their goals or progress, and to get goal ids.

        Args:
            include_inactive: Also include paused, completed and archived goals.
        """
        statuses = ("active", "paused", "completed", "archived") if include_inactive else ("active", "paused")
        goals = await goal_service.list_goals_out(session, profile, statuses)
        return _json([g.model_dump(mode="json", exclude={"created_at", "updated_at"}) for g in goals])

    @beta_async_tool
    async def create_goal(
        title: str,
        why: str | None = None,
        category: GoalCategory = "other",
        cadence: GoalCadence = "daily",
        target_per_period: int = 1,
        target_date: date | None = None,
        description: str | None = None,
    ) -> str:
        """Create a new goal once the person has agreed on a concrete version of it.

        Args:
            title: Specific, action-oriented title, e.g. "Run 3 times a week".
            why: The person's own reason this matters; used to personalise nudges.
            category: The life area the goal belongs to.
            cadence: daily, weekdays, weekly (target_per_period times per week) or flexible.
            target_per_period: How many times per period (per day, or per week for weekly).
            target_date: Optional deadline, YYYY-MM-DD.
            description: Optional extra detail.
        """
        goal = await goal_service.create_goal(
            session,
            profile.id,
            title=title.strip()[:200],
            why=why,
            category=category,
            cadence=cadence,
            target_per_period=max(1, min(14, target_per_period)),
            target_date=target_date,
            description=description,
        )
        await session.commit()
        return _json({"created": True, "goal_id": goal.id, "title": goal.title})

    @beta_async_tool
    async def update_goal(
        goal_id: str,
        title: str | None = None,
        why: str | None = None,
        cadence: GoalCadence | None = None,
        target_per_period: int | None = None,
        target_date: date | None = None,
        status: Literal["active", "paused", "completed", "archived"] | None = None,
        priority: int | None = None,
    ) -> str:
        """Change a goal: rename it, adjust cadence or target, pause, complete or archive it.

        Args:
            goal_id: Id from list_goals.
            title: New title.
            why: New reason.
            cadence: New cadence.
            target_per_period: New count per period.
            target_date: New deadline, YYYY-MM-DD.
            status: active, paused, completed or archived.
            priority: 1 (highest) to 3 (lowest).
        """
        goal = await _goal(goal_id)
        changes = {
            k: v
            for k, v in {
                "title": title,
                "why": why,
                "cadence": cadence,
                "target_per_period": target_per_period,
                "target_date": target_date,
                "status": status,
                "priority": priority,
            }.items()
            if v is not None
        }
        await goal_service.update_goal(session, goal, changes)
        await session.commit()
        return _json({"updated": True, "goal_id": goal.id, "changed": sorted(changes)})

    @beta_async_tool
    async def log_check_in(
        goal_id: str,
        kind: Literal["done", "progress", "skipped", "note"] = "done",
        note: str | None = None,
        value: float | None = None,
    ) -> str:
        """Record that the person did something toward a goal (or skipped it, or a note about it).

        Call this whenever they report an action, even casually ("went for a run this morning").

        Args:
            goal_id: Id from list_goals.
            kind: done (did the planned action), progress (partial), skipped, or note.
            note: Their words or details worth keeping.
            value: Optional quantity, e.g. minutes or kilometres.
        """
        goal = await _goal(goal_id)
        await goal_service.add_check_in(session, goal, kind=kind, value=value, note=note, source="chat")
        await session.commit()
        progress = (await progress_for_goals(session, [goal], profile.timezone))[goal.id]
        return _json({"logged": True, "goal": goal.title, "progress": progress.__dict__})

    @beta_async_tool
    async def add_milestones(goal_id: str, milestones: list[MilestoneInput]) -> str:
        """Add milestones that break a long-term goal into steps.

        Args:
            goal_id: Id from list_goals.
            milestones: Milestones in order.
        """
        goal = await _goal(goal_id)
        created = await goal_service.add_milestones(session, goal, [(m.title, m.due_date) for m in milestones])
        await session.commit()
        return _json({"added": [m.title for m in created]})

    @beta_async_tool
    async def get_progress(goal_id: str | None = None, days: int = 14) -> str:
        """Recent check-ins (with notes) for one goal or all goals.

        Args:
            goal_id: Optional goal id; all goals when omitted.
            days: How many days back to look (1-90).
        """
        since = utcnow() - timedelta(days=max(1, min(90, days)))
        query = (
            select(CheckIn, Goal.title)
            .join(Goal, Goal.id == CheckIn.goal_id)
            .where(CheckIn.user_id == profile.id, CheckIn.occurred_at >= since)
        )
        if goal_id:
            query = query.where(CheckIn.goal_id == (await _goal(goal_id)).id)
        rows = await session.execute(query.order_by(CheckIn.occurred_at.desc()).limit(100))
        return _json(
            [
                {
                    "goal": title,
                    "kind": c.kind,
                    "note": c.note,
                    "value": c.value,
                    "when_local": to_local(c.occurred_at, profile.timezone).strftime("%a %Y-%m-%d %H:%M"),
                }
                for c, title in rows
            ]
        )

    @beta_async_tool
    async def get_nudge_insights() -> str:
        """What Brian has learned about nudging this person: engagement rates by timing, type, tone
        and framing over the last 30 days, plus the latest written playbook."""
        stats = await engagement_stats(session, profile.id)
        playbook = await session.scalar(
            select(Insight.playbook).where(Insight.user_id == profile.id).order_by(Insight.created_at.desc()).limit(1)
        )
        return _json({"stats": stats.model_dump(mode="json"), "playbook": playbook})

    @beta_async_tool
    async def update_nudge_preferences(
        intensity: Literal["gentle", "balanced", "intense"] | None = None,
        quiet_hours_start: time | None = None,
        quiet_hours_end: time | None = None,
        pause_days: int | None = None,
        resume: bool = False,
    ) -> str:
        """Change how Brian nudges: how often, when not to, or pause for a while.

        Args:
            intensity: gentle (about 1 a day), balanced (about 2) or intense (about 3).
            quiet_hours_start: Local time nudges stop, HH:MM.
            quiet_hours_end: Local time nudges may resume, HH:MM.
            pause_days: Pause all proactive nudges for this many days (1-60).
            resume: Resume nudges now if they were paused.
        """
        if intensity:
            profile.nudge_intensity = intensity
        if quiet_hours_start:
            profile.quiet_hours_start = quiet_hours_start
        if quiet_hours_end:
            profile.quiet_hours_end = quiet_hours_end
        if pause_days:
            profile.nudges_paused_until = utcnow() + timedelta(days=max(1, min(60, pause_days)))
        if resume:
            profile.nudges_paused_until = None
        await session.commit()
        return _json(
            {
                "intensity": profile.nudge_intensity,
                "quiet_hours": f"{profile.quiet_hours_start:%H:%M}-{profile.quiet_hours_end:%H:%M}",
                "paused_until": profile.nudges_paused_until,
            }
        )

    @beta_async_tool
    async def schedule_reminder(at_local: datetime, message: str, goal_id: str | None = None) -> str:
        """Schedule a one-off reminder notification the person explicitly asked for.

        Args:
            at_local: When to send it, in the person's local time, YYYY-MM-DDTHH:MM.
            message: The reminder text, written to the person (max ~160 characters).
            goal_id: Optional related goal id.
        """
        tz = zone(profile.timezone)
        send_at = (at_local if at_local.tzinfo else at_local.replace(tzinfo=tz)).astimezone(tz)
        if send_at < utcnow() - timedelta(minutes=1):
            raise ToolError("That time is in the past. Ask the person for a future time.")
        goal = await _goal(goal_id) if goal_id else None
        session.add(
            Nudge(
                user_id=profile.id,
                goal_id=goal.id if goal else None,
                source="user_scheduled",
                status="planned",
                policy_version="user_request",
                scheduled_for=send_at,
                expires_at=send_at + timedelta(hours=get_settings().nudge_attribution_hours),
                requested_text=message.strip()[:180],
            )
        )
        await session.commit()
        return _json({"scheduled": True, "at_local": send_at.strftime("%a %Y-%m-%d %H:%M")})

    @beta_async_tool
    async def remember(fact: str) -> str:
        """Save a durable fact about the person that will help coach them later (schedule,
        constraints, preferences, motivations). One fact per call, written in the third person.

        Args:
            fact: E.g. "Works night shifts on weekends" or "Prefers short, blunt messages".
        """
        session.add(Memory(user_id=profile.id, content=fact.strip()[:500], source="agent"))
        await session.commit()
        return _json({"remembered": True})

    return [
        list_goals,
        create_goal,
        update_goal,
        log_check_in,
        add_milestones,
        get_progress,
        get_nudge_insights,
        update_nudge_preferences,
        schedule_reminder,
        remember,
    ]
