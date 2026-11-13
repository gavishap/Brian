"""Template copy: used when Claude is disabled or unavailable, so nudges always go out.

The goal's title is the notification title; bodies never splice it into a sentence, so they read
naturally whatever the goal is called ("Write 500 words", "Meditation", "Save for a house")."""

from __future__ import annotations

TEMPLATES: dict[str, dict[str, str]] = {
    "reminder": {
        "warm": "A gentle reminder: today's step is waiting for you.",
        "direct": "Today's step is still open. Now is a good time.",
        "playful": "Psst... this one has been waiting for you all day. 👀",
        "analytical": "{period_count}/{period_target} {period_label}. One more keeps you on track.",
        "tough_love": "You said this mattered. Today is the day to show it.",
    },
    "check_in": {
        "warm": "How is it going today?",
        "direct": "Quick check: did you get to it yet?",
        "playful": "Status report, captain?",
        "analytical": "Progress check: {period_count}/{period_target} {period_label}. Any update?",
        "tough_love": "Honest answer: done yet today?",
    },
    "micro_step": {
        "warm": "Even two minutes counts. Start tiny.",
        "direct": "Do the smallest possible step, right now.",
        "playful": "Two-minute challenge. Ready, set, go! ⏱️",
        "analytical": "Small steps compound. Two minutes today keeps the trend alive.",
        "tough_love": "Two minutes. No excuses. Start now.",
    },
    "reflection": {
        "warm": "Why does this matter to you? Take a breath and remember.",
        "direct": "What is one thing in the way this week?",
        "playful": "Quick thought experiment: what would future-you thank you for here?",
        "analytical": "What has worked best for this so far?",
        "tough_love": "What is the real reason this keeps slipping?",
    },
    "celebration": {
        "warm": "{streak} in a row. Look at you!",
        "direct": "{streak} in a row. Keep going.",
        "playful": "{streak} in a row! This is officially your thing. 🎉",
        "analytical": "Streak: {streak}. That is real momentum.",
        "tough_love": "{streak} in a row. Good. Don't get comfortable.",
    },
    "streak_save": {
        "warm": "Your {streak}-streak is still alive. One small step keeps it going.",
        "direct": "Streak at risk: one check-in today keeps all {streak}.",
        "playful": "Your {streak}-streak is nervously waiting. Save it?",
        "analytical": "{streak} in a row so far. Today decides the next one.",
        "tough_love": "Don't throw away {streak} in a row.",
    },
    "plan_ahead": {
        "warm": "When will you fit this in today? Picking a time makes it easier.",
        "direct": "Pick a time for this today.",
        "playful": "Calendar Tetris: where does this fit today?",
        "analytical": "People who pick a time follow through far more often. When will you do it?",
        "tough_love": "Decide now when you'll do it. Then do it.",
    },
}

TITLE_MAX = 50


def render_template(
    nudge_type: str,
    tone: str,
    *,
    goal_title: str,
    streak: int,
    period_count: int,
    period_target: int,
    period_label: str,
) -> tuple[str, str]:
    """Return (title, body)."""
    body = TEMPLATES.get(nudge_type, TEMPLATES["reminder"]).get(tone) or TEMPLATES["reminder"]["warm"]
    title = goal_title if len(goal_title) <= TITLE_MAX else goal_title[: TITLE_MAX - 1].rstrip() + "…"
    text = body.format(streak=streak, period_count=period_count, period_target=period_target, period_label=period_label)
    return title, text
