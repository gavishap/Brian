"""Synthetic people. Each has hidden preferences over the nudge dimensions that decide how likely
they are to engage; the engine never sees them and has to learn them from reactions alone."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class GoalSpec:
    title: str
    why: str
    category: str
    cadence: str = "daily"
    target_per_period: int = 1


@dataclass(frozen=True)
class Reaction:
    kind: str  # done | reply | snooze | opened | dismissed | ignored
    delay_minutes: float
    text: str | None = None


@dataclass(frozen=True)
class Persona:
    key: str
    display_name: str
    timezone: str
    summary: str
    base_logit: float
    # dimension -> arm -> shift in log-odds of engaging. Missing arms are neutral (0).
    weights: dict[str, dict[str, float]]
    goals: tuple[GoalSpec, ...]
    facts: tuple[str, ...]
    reply_lines: tuple[str, ...]
    complete_share: float = 0.55  # of engaged reactions: did it
    reply_share: float = 0.2  # replied
    snooze_share: float = 0.1  # "Later"; the rest just opened
    dismiss_share: float = 0.35  # of non-engaged reactions: swiped away (rest: ignored)
    organic_check_in_rate: float = 0.25  # chance per goal per day of logging without a nudge
    active_hours: tuple[int, int] = (7, 22)
    quiet_hours: tuple[str, str] = ("22:30", "07:00")
    extra: dict[str, str] = field(default_factory=dict)

    def engagement_probability(self, arms: dict[str, str]) -> float:
        logit = self.base_logit + sum(self.weights.get(dim, {}).get(arm, 0.0) for dim, arm in arms.items())
        return 1.0 / (1.0 + math.exp(-logit))

    def ranking(self, dimension: str, arms: list[str]) -> list[str]:
        """Arms from most to least preferred (ground truth)."""
        prefs = self.weights.get(dimension, {})
        return sorted(arms, key=lambda a: prefs.get(a, 0.0), reverse=True)

    def react(self, arms: dict[str, str], rng: np.random.Generator) -> Reaction:
        if rng.random() < self.engagement_probability(arms):
            delay = float(min(150.0, rng.gamma(2.0, 9.0)))
            roll = rng.random()
            if roll < self.complete_share:
                return Reaction("done", delay)
            if roll < self.complete_share + self.reply_share:
                return Reaction("reply", delay, self.reply_lines[int(rng.integers(len(self.reply_lines)))])
            if roll < self.complete_share + self.reply_share + self.snooze_share:
                return Reaction("snooze", delay)
            return Reaction("opened", delay)
        if rng.random() < self.dismiss_share:
            return Reaction("dismissed", float(rng.uniform(0.5, 40.0)))
        return Reaction("ignored", 0.0)


PERSONAS: dict[str, Persona] = {
    p.key: p
    for p in (
        Persona(
            key="maya",
            display_name="Maya",
            timezone="America/Los_Angeles",
            summary=(
                "Night-owl novelist: evenings, playful and curious, short messages; mornings and tough love fall flat."
            ),
            base_logit=-0.9,
            weights={
                "time_window": {"evening": 1.2, "night": 1.0, "afternoon": 0.1, "early_morning": -1.6, "morning": -0.9},
                "tone": {"playful": 1.0, "warm": 0.4, "analytical": -0.5, "tough_love": -1.1},
                "framing": {"curiosity": 0.8, "identity": 0.5, "loss_aversion": -0.8},
                "nudge_type": {"micro_step": 0.6, "reflection": 0.4, "streak_save": -0.5},
                "length": {"short": 0.4, "medium": -0.3},
            },
            goals=(
                GoalSpec("Write 500 words", "Finish the first draft of my novel by spring", "creativity"),
                GoalSpec("Run 3 times a week", "Have energy for long writing nights", "fitness", "weekly", 3),
            ),
            facts=("Writes best late at night", "Works a day job until 6pm", "Prefers short, light-hearted messages"),
            reply_lines=(
                "Did 300 words, the scene finally clicked",
                "Tired today, will do a short session",
                "On it after dinner",
                "Ran 5k by the beach!",
            ),
            organic_check_in_rate=0.2,
            active_hours=(9, 23),
            quiet_hours=("23:30", "08:30"),
        ),
        Persona(
            key="sam",
            display_name="Sam",
            timezone="America/New_York",
            summary=(
                "Early-bird analyst: mornings, numbers and directness, progress framing; playful pings get ignored."
            ),
            base_logit=-0.8,
            weights={
                "time_window": {"early_morning": 1.3, "morning": 0.9, "midday": 0.1, "evening": -0.7, "night": -1.4},
                "tone": {"analytical": 1.1, "direct": 0.8, "playful": -1.0, "warm": -0.2},
                "framing": {"progress": 0.9, "gain": 0.5, "future_self": -0.3, "curiosity": -0.4},
                "nudge_type": {"check_in": 0.5, "plan_ahead": 0.5, "reflection": -0.6},
                "length": {"medium": 0.3, "short": -0.1},
            },
            goals=(
                GoalSpec(
                    "Study Spanish for 20 minutes", "Hold a real conversation on the Madrid trip in June", "learning"
                ),
                GoalSpec("Save $500 this month", "Build a six-month emergency fund", "finance", "weekly", 1),
            ),
            facts=("Commutes by train 7-8am", "Likes seeing numbers and trends", "Hates fluffy motivational talk"),
            reply_lines=("Done on the train", "Skipped yesterday, back on it", "20 min of Duolingo + podcast"),
            organic_check_in_rate=0.3,
            active_hours=(6, 21),
            quiet_hours=("21:30", "06:00"),
        ),
        Persona(
            key="jordan",
            display_name="Jordan",
            timezone="Europe/London",
            summary="Busy parent: quiet midday moments, warm tone, tiny steps and identity; streak pressure backfires.",
            base_logit=-1.0,
            weights={
                "time_window": {"midday": 1.1, "afternoon": 0.7, "early_morning": -1.2, "evening": -0.8},
                "tone": {"warm": 1.0, "direct": 0.2, "tough_love": -1.2, "analytical": -0.3},
                "framing": {"identity": 0.8, "future_self": 0.6, "loss_aversion": -1.0},
                "nudge_type": {"micro_step": 0.9, "celebration": 0.4, "streak_save": -1.0, "check_in": -0.2},
                "length": {"short": 0.5, "medium": -0.4},
            },
            goals=(
                GoalSpec("Meditate for 10 minutes", "Be calmer with the kids in the evening", "mindfulness"),
                GoalSpec("Call a friend", "Not lose touch with the people I love", "relationships", "weekly", 1),
            ),
            facts=(
                "Has two kids under 6",
                "Lunch break is the only quiet time",
                "Feels guilty when reminded of streaks",
            ),
            reply_lines=("Managed 5 minutes in the car", "Kids were up all night, not today", "Called Priya!"),
            dismiss_share=0.5,
            organic_check_in_rate=0.15,
            active_hours=(7, 21),
            quiet_hours=("21:30", "07:00"),
        ),
    )
}
