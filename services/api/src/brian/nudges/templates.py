"""Template copy: used when Claude is disabled or unavailable, so nudges always go out."""

from __future__ import annotations

TEMPLATES: dict[str, dict[str, str]] = {
    "reminder": {
        "warm": "A gentle reminder: {goal} is waiting for you today.",
        "direct": "Time for {goal}.",
        "playful": "Psst... {goal} called. It misses you.",
        "analytical": "{goal}: {period_count}/{period_target} {period_label}.",
        "tough_love": "You said {goal} mattered. Prove it today.",
    },
    "check_in": {
        "warm": "How's {goal} going today?",
        "direct": "Quick check: did you do {goal} yet?",
        "playful": "Status report, captain: how's {goal}?",
        "analytical": "Check-in: {period_count}/{period_target} {period_label} on {goal}. Update?",
        "tough_love": "Honest answer: have you done {goal} today?",
    },
    "micro_step": {
        "warm": "Just two minutes on {goal} counts. Start tiny.",
        "direct": "Do the smallest possible step of {goal} now.",
        "playful": "Two-minute challenge: tiny step on {goal}. Go!",
        "analytical": "Small steps compound. Two minutes on {goal} keeps the trend alive.",
        "tough_love": "No excuses: two minutes of {goal}, right now.",
    },
    "reflection": {
        "warm": "Why does {goal} matter to you? Take a breath and remember.",
        "direct": "What's one thing blocking {goal} this week?",
        "playful": "Thought experiment: what would future-you thank you for on {goal}?",
        "analytical": "What's worked best for {goal} so far?",
        "tough_love": "What's the real reason {goal} keeps slipping?",
    },
    "celebration": {
        "warm": "Look at you! {streak} in a row on {goal}.",
        "direct": "{streak} straight on {goal}. Keep going.",
        "playful": "{streak} in a row! {goal} is officially your thing.",
        "analytical": "Streak: {streak}. You're building real momentum on {goal}.",
        "tough_love": "{streak} in a row. Good. Don't get comfortable.",
    },
    "streak_save": {
        "warm": "Your {streak}-day streak on {goal} is still alive. One small step keeps it.",
        "direct": "Streak at risk: do {goal} today to keep {streak}.",
        "playful": "Your {streak}-streak is nervously waiting. Save it?",
        "analytical": "{streak} periods in a row. One check-in today keeps the run going.",
        "tough_love": "Don't throw away {streak} in a row on {goal}.",
    },
    "plan_ahead": {
        "warm": "When will you fit in {goal} today? Picking a time makes it easier.",
        "direct": "Pick a time for {goal} today.",
        "playful": "Calendar Tetris: where does {goal} fit today?",
        "analytical": "People who pick a time are far likelier to follow through. When is {goal}?",
        "tough_love": "Decide now when you'll do {goal}. Then do it.",
    },
}


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
    goal = goal_title if len(goal_title) <= 60 else goal_title[:57] + "..."
    text = body.format(
        goal=goal, streak=streak, period_count=period_count, period_target=period_target, period_label=period_label
    )
    title = (
        "Brian"
        if nudge_type not in ("celebration", "streak_save")
        else ("Nice work" if nudge_type == "celebration" else "Keep the streak")
    )
    return title, text
