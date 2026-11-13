"""Factorized Thompson sampling with population priors, time decay and logged propensities.

For every dimension (time window, nudge type, tone, framing, length) each arm has a Beta posterior
over "probability this nudge gets engagement". A user's posterior starts from the population's
mean (empirical-Bayes prior worth `prior_strength` pseudo-observations), so new users benefit from
what worked for everyone else, and moves toward their own data as it accumulates. Old
observations decay with a half-life, so the policy follows people as their routines change.

Each choice also records its propensity (the probability the policy had of making it), which is
what lets a future policy be evaluated offline on logged data (inverse propensity scoring).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class SufficientStats:
    successes: float = 0.0
    failures: float = 0.0
    pulls: int = 0

    def decayed(self, updated_at: datetime, now: datetime, half_life_days: float) -> SufficientStats:
        age_days = max(0.0, (now - updated_at).total_seconds() / 86400.0)
        factor = 0.5 ** (age_days / half_life_days) if half_life_days > 0 else 1.0
        return SufficientStats(self.successes * factor, self.failures * factor, self.pulls)


@dataclass(frozen=True)
class BetaPosterior:
    alpha: float
    beta: float

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)


def posterior(user: SufficientStats | None, population: SufficientStats | None, prior_strength: float) -> BetaPosterior:
    pop = population or SufficientStats()
    pop_mean = (1.0 + pop.successes) / (2.0 + pop.successes + pop.failures)
    own = user or SufficientStats()
    return BetaPosterior(
        alpha=prior_strength * pop_mean + own.successes,
        beta=prior_strength * (1.0 - pop_mean) + own.failures,
    )


@dataclass(frozen=True)
class ArmChoice:
    dimension: str
    arm: str
    propensity: float
    explored: bool
    posterior_means: dict[str, float] = field(default_factory=dict)


def thompson_choose(
    dimension: str,
    posteriors: dict[str, BetaPosterior],
    rng: np.random.Generator,
    *,
    epsilon: float = 0.1,
    propensity_samples: int = 2000,
) -> ArmChoice:
    """Pick an arm: with probability `epsilon` uniformly at random, otherwise by Thompson sampling.

    The propensity is the probability of the chosen arm under that mixture,
    epsilon / K + (1 - epsilon) * P(arm has the highest posterior draw), estimated by Monte Carlo.
    """
    if not posteriors:
        raise ValueError(f"no eligible arms for dimension {dimension!r}")
    arms = list(posteriors)
    means = {arm: round(posteriors[arm].mean, 4) for arm in arms}
    k = len(arms)
    if k == 1:
        return ArmChoice(dimension, arms[0], 1.0, False, means)

    alpha = np.array([posteriors[a].alpha for a in arms])
    beta = np.array([posteriors[a].beta for a in arms])

    draws = rng.beta(alpha[:, None], beta[:, None], size=(k, propensity_samples))
    wins = np.bincount(draws.argmax(axis=0), minlength=k)
    ts_probability = (wins + 0.5) / (propensity_samples + 0.5 * k)  # smoothed: never exactly 0
    probability = epsilon / k + (1.0 - epsilon) * ts_probability

    explored = bool(rng.random() < epsilon)
    index = int(rng.integers(k)) if explored else int(np.argmax(rng.beta(alpha, beta)))
    return ArmChoice(dimension, arms[index], float(probability[index]), explored, means)
