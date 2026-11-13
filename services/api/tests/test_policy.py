from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from brian.nudges import rewards
from brian.nudges.arms import DIMENSIONS, DecisionContext, eligible_arms
from brian.nudges.policy import BetaPosterior, SufficientStats, posterior, thompson_choose


def ctx(**overrides: object) -> DecisionContext:
    base: dict[str, object] = {
        "day_type": "weekday",
        "local_hour": 9,
        "goal_category": "fitness",
        "goal_cadence": "daily",
        "current_streak": 0,
        "period_complete": False,
        "period_count": 0,
        "period_target": 1,
        "total_check_ins": 0,
        "hours_since_check_in": None,
        "consecutive_ignored": 0,
        "days_since_signup": 1,
    }
    base.update(overrides)
    return DecisionContext(**base)  # type: ignore[arg-type]


def test_new_user_inherits_population_mean() -> None:
    population = SufficientStats(successes=80, failures=20, pulls=100)
    prior = posterior(None, population, prior_strength=4.0)
    assert prior.alpha + prior.beta == pytest.approx(4.0)
    assert prior.mean == pytest.approx(81 / 102, rel=1e-6)


def test_own_data_dominates_as_it_accumulates() -> None:
    population = SufficientStats(successes=80, failures=20, pulls=100)
    user = SufficientStats(successes=2, failures=38, pulls=40)
    assert posterior(user, population, prior_strength=4.0).mean < 0.2


def test_time_decay_halves_old_evidence() -> None:
    now = datetime(2026, 11, 13, tzinfo=UTC)
    stats = SufficientStats(10, 6, 16).decayed(now - timedelta(days=30), now, half_life_days=30)
    assert (stats.successes, stats.failures, stats.pulls) == (pytest.approx(5), pytest.approx(3), 16)


def test_thompson_prefers_the_better_arm_and_reports_propensities() -> None:
    rng = np.random.default_rng(7)
    posteriors = {"good": BetaPosterior(40, 10), "bad": BetaPosterior(10, 40), "meh": BetaPosterior(20, 20)}
    picks = Counter(thompson_choose("tone", posteriors, rng, epsilon=0.1).arm for _ in range(400))
    assert picks["good"] > 300
    assert picks["bad"] > 0 or picks["meh"] > 0  # epsilon keeps exploring

    choice = thompson_choose("tone", posteriors, rng, epsilon=0.1)
    assert 0 < choice.propensity <= 1
    assert choice.posterior_means["good"] == pytest.approx(0.8)


def test_propensities_form_a_distribution() -> None:
    rng = np.random.default_rng(1)
    posteriors = {"a": BetaPosterior(3, 2), "b": BetaPosterior(2, 3), "c": BetaPosterior(1, 1)}
    seen: dict[str, float] = {}
    for _ in range(300):
        choice = thompson_choose("framing", posteriors, rng, epsilon=0.2)
        seen.setdefault(choice.arm, choice.propensity)
    assert set(seen) == {"a", "b", "c"}
    assert sum(seen.values()) == pytest.approx(1.0, abs=0.06)
    assert min(seen.values()) >= 0.2 / 3  # epsilon floor


def test_single_arm_is_certain() -> None:
    choice = thompson_choose("length", {"short": BetaPosterior(1, 1)}, np.random.default_rng(0))
    assert (choice.arm, choice.propensity, choice.explored) == ("short", 1.0, False)


def test_eligibility_rules() -> None:
    fresh = ctx()
    assert "streak_save" not in eligible_arms("nudge_type", fresh)
    assert "celebration" not in eligible_arms("nudge_type", fresh)
    assert "loss_aversion" not in eligible_arms("framing", fresh)
    assert "progress" not in eligible_arms("framing", fresh)

    streaking = ctx(current_streak=4, total_check_ins=10, hours_since_check_in=20.0)
    assert set(eligible_arms("nudge_type", streaking)) == set(DIMENSIONS["nudge_type"])
    assert set(eligible_arms("framing", streaking)) == set(DIMENSIONS["framing"])


@pytest.mark.parametrize(
    ("observed", "expected"),
    [
        ([], "ignored"),
        (["opened"], "opened"),
        (["opened", "completed"], "completed"),
        (["opened", "snoozed"], "snoozed"),
        (["completed", "negative_feedback"], "negative_feedback"),
        (["dismissed", None], "dismissed"),
    ],
)
def test_outcome_resolution(observed: list[str | None], expected: str) -> None:
    assert rewards.resolve_outcome(observed) == expected


def test_event_mapping_and_rewards() -> None:
    assert rewards.outcome_for_event("action", "done", False) == "completed"
    assert rewards.outcome_for_event("action", "reply", True) == "replied"
    assert rewards.outcome_for_event("action", "something_new", False) == "opened"
    assert rewards.outcome_for_event("received", None, False) is None
    assert rewards.reward_for("snoozed") == pytest.approx(0.35)
    assert rewards.reward_for("snoozed", "time_window") == pytest.approx(0.1)
    assert rewards.reward_for("completed", "time_window") == 1.0
