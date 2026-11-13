"""The decision space: each nudge is a combination of one arm per dimension.

The policy learns a separate (factorized) preference per dimension, so every nudge teaches it
something about timing, nudge type, tone, framing and length at once.
"""

from __future__ import annotations

from dataclasses import dataclass

from brian.timeutils import TIME_WINDOWS

DIMENSIONS: dict[str, tuple[str, ...]] = {
    "time_window": tuple(TIME_WINDOWS),
    "nudge_type": ("reminder", "check_in", "micro_step", "reflection", "celebration", "streak_save", "plan_ahead"),
    "tone": ("warm", "direct", "playful", "analytical", "tough_love"),
    "framing": ("gain", "identity", "progress", "loss_aversion", "curiosity", "future_self"),
    "length": ("short", "medium"),
}

# Plain-language descriptions, used in the copywriting prompt and shown in the insights screen.
ARM_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "time_window": {
        "early_morning": "6-8am",
        "morning": "8-11am",
        "midday": "11am-2pm",
        "afternoon": "2-5pm",
        "evening": "5-8pm",
        "night": "8-10pm",
    },
    "nudge_type": {
        "reminder": "A plain reminder of the goal and what today's step is.",
        "check_in": "Ask how it is going; invite a quick status reply.",
        "micro_step": "Suggest one tiny, concrete action that takes under two minutes.",
        "reflection": "Ask a short reflective question about the goal or the user's 'why'.",
        "celebration": "Celebrate recent progress or a streak, specifically.",
        "streak_save": "The streak is at risk today; make keeping it feel easy.",
        "plan_ahead": "Help the user decide when and where they will do it (implementation intention).",
    },
    "tone": {
        "warm": "Kind, encouraging, supportive.",
        "direct": "Brief and matter-of-fact, no fluff.",
        "playful": "Light, witty, a little fun; an emoji is fine.",
        "analytical": "Numbers and facts about their progress.",
        "tough_love": "Candid, challenging, holds them to their word (never shaming).",
    },
    "framing": {
        "gain": "Focus on what they gain by doing it.",
        "identity": "Tie the action to who they are becoming.",
        "progress": "Show how far they have come.",
        "loss_aversion": "Point out what they would lose by skipping (e.g. the streak).",
        "curiosity": "Open a small curiosity gap or interesting question.",
        "future_self": "Speak to how their future self will feel.",
    },
    "length": {
        "short": "One short sentence (under 70 characters).",
        "medium": "One or two sentences (under 160 characters).",
    },
}

# Notification categories the app registers with expo-notifications (action buttons).
CATEGORY_FOR_TYPE: dict[str, str] = {
    "reminder": "nudge_action",
    "check_in": "nudge_action",
    "micro_step": "nudge_action",
    "streak_save": "nudge_action",
    "plan_ahead": "nudge_action",
    "reflection": "nudge_reflect",
    "celebration": "nudge_reflect",
}


@dataclass(frozen=True)
class DecisionContext:
    """Features of the situation a nudge is decided in. Stored with the nudge for later analysis."""

    day_type: str
    local_hour: int
    goal_category: str
    goal_cadence: str
    current_streak: int
    period_complete: bool
    period_count: int
    period_target: int
    total_check_ins: int
    hours_since_check_in: float | None
    consecutive_ignored: int
    days_since_signup: int

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


def eligible_arms(dimension: str, ctx: DecisionContext) -> list[str]:
    """Arms that make sense in this context (e.g. no streak-saving without a streak)."""
    arms = list(DIMENSIONS[dimension])
    if dimension == "nudge_type":
        if not (ctx.current_streak >= 2 and not ctx.period_complete):
            arms.remove("streak_save")
        recent_progress = ctx.hours_since_check_in is not None and ctx.hours_since_check_in <= 36
        if not (ctx.current_streak >= 2 or recent_progress):
            arms.remove("celebration")
    elif dimension == "framing":
        if ctx.current_streak < 2:
            arms.remove("loss_aversion")
        if ctx.total_check_ins < 3:
            arms.remove("progress")
    return arms


def context_key(dimension: str, ctx: DecisionContext) -> str:
    """Which slice of statistics a dimension learns in. Timing preferences differ by day type."""
    if dimension == "time_window":
        return f"day_type:{ctx.day_type}"
    return "all"
