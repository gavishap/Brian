"""How user reactions become rewards in [0, 1] for the policy."""

from __future__ import annotations

from collections.abc import Iterable

# Default reward per final outcome.
REWARDS: dict[str, float] = {
    "completed": 1.0,  # tapped "Done" or logged progress within the attribution window
    "replied": 0.85,  # wrote back
    "snoozed": 0.35,  # engaged, but not now
    "opened": 0.5,  # tapped the notification, did nothing else
    "dismissed": 0.0,  # swiped it away (iOS reports this)
    "ignored": 0.0,  # no interaction before it expired
    "negative_feedback": 0.0,  # "Less of these"
}

# A snooze says "right message, wrong moment": it should teach the timing dimension that the
# window was bad while still crediting the message itself.
DIMENSION_OVERRIDES: dict[str, dict[str, float]] = {
    "time_window": {"snoozed": 0.1},
}

# Outcomes that end the attribution window immediately; the others wait for it to close in
# case something better happens (opened -> completed).
TERMINAL_OUTCOMES = frozenset({"completed", "replied", "dismissed", "negative_feedback"})

# Higher rank wins when several outcomes were observed; explicit negative feedback overrides all.
_RANK: dict[str, int] = {
    "ignored": 0,
    "dismissed": 1,
    "opened": 2,
    "snoozed": 3,
    "replied": 4,
    "completed": 5,
}

ACTION_OUTCOMES: dict[str, str] = {
    "done": "completed",
    "snooze": "snoozed",
    "reply": "replied",
    "not_helpful": "negative_feedback",
    "open": "opened",
}


def outcome_for_event(event_type: str, action_id: str | None, has_text: bool) -> str | None:
    if event_type == "action":
        if has_text:
            return "replied"
        return ACTION_OUTCOMES.get(action_id or "", "opened")
    return {"opened": "opened", "dismissed": "dismissed", "replied": "replied"}.get(event_type)


def resolve_outcome(outcomes: Iterable[str | None]) -> str:
    observed = [o for o in outcomes if o]
    if "negative_feedback" in observed:
        return "negative_feedback"
    if not observed:
        return "ignored"
    return max(observed, key=lambda o: _RANK.get(o, 0))


def reward_for(outcome: str, dimension: str | None = None) -> float:
    if dimension is not None and outcome in DIMENSION_OVERRIDES.get(dimension, {}):
        return DIMENSION_OVERRIDES[dimension][outcome]
    return REWARDS[outcome]
