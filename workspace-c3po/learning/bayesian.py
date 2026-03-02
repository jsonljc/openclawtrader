#!/usr/bin/env python3
"""Conjugate prior models for small-sample Bayesian inference.

With ~8 trades/month, frequentist tests have almost no power.
Bayesian posteriors honestly represent uncertainty: wide credible
intervals mean "not enough data yet, don't change."
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# BetaBinomial — for rates (hit_rate, win_by_regime, fill_rate)
# ---------------------------------------------------------------------------

@dataclass
class BetaBinomial:
    """Beta-Binomial conjugate model for binary outcomes.

    Prior: Beta(alpha, beta) — default weakly informative (2, 2).
    Posterior after observing k successes in n trials:
        Beta(alpha + k, beta + n - k)
    """

    alpha: float = 2.0
    beta: float = 2.0

    def update(self, successes: int, trials: int) -> "BetaBinomial":
        """Return a new BetaBinomial with updated posterior."""
        if trials < 0 or successes < 0 or successes > trials:
            raise ValueError(
                f"Invalid: successes={successes}, trials={trials}"
            )
        return BetaBinomial(
            alpha=self.alpha + successes,
            beta=self.beta + (trials - successes),
        )

    def mean(self) -> float:
        """Posterior mean E[p]."""
        return self.alpha / (self.alpha + self.beta)

    def variance(self) -> float:
        """Posterior variance."""
        ab = self.alpha + self.beta
        return (self.alpha * self.beta) / (ab * ab * (ab + 1))

    def ci(self, level: float = 0.90) -> tuple[float, float]:
        """Approximate credible interval using normal approximation.

        For Beta distributions with alpha, beta > 1, the normal
        approximation is reasonable. For very small samples, this
        is conservative (wider than exact).
        """
        mu = self.mean()
        sd = math.sqrt(self.variance())
        # z for common levels: 0.90 -> 1.645, 0.95 -> 1.96
        z = {0.80: 1.282, 0.90: 1.645, 0.95: 1.960, 0.99: 2.576}.get(
            level, 1.645
        )
        lo = max(0.0, mu - z * sd)
        hi = min(1.0, mu + z * sd)
        return (round(lo, 6), round(hi, 6))

    def ci_width(self, level: float = 0.90) -> float:
        """Width of the credible interval."""
        lo, hi = self.ci(level)
        return hi - lo

    def sufficient_confidence(self, threshold: float = 0.05) -> bool:
        """True if CI width < threshold (we know enough)."""
        return self.ci_width() < threshold

    @property
    def n_obs(self) -> float:
        """Effective number of observations (excluding prior)."""
        return (self.alpha + self.beta) - 4.0  # subtract prior pseudocounts


# ---------------------------------------------------------------------------
# NormalGamma — for continuous parameters (R multiple, slippage, weights)
# ---------------------------------------------------------------------------

@dataclass
class NormalGamma:
    """Normal-Gamma conjugate model for unknown mean and variance.

    Prior parameters:
        mu0    — prior mean
        kappa0 — prior precision (pseudo-observations for the mean)
        alpha0 — shape of inverse-gamma on variance
        beta0  — rate of inverse-gamma on variance

    Posterior after observing data x_1, ..., x_n:
        kappa_n = kappa0 + n
        mu_n    = (kappa0 * mu0 + n * x_bar) / kappa_n
        alpha_n = alpha0 + n/2
        beta_n  = beta0 + 0.5 * S + (kappa0 * n * (x_bar - mu0)^2) / (2 * kappa_n)
    where S = sum((x_i - x_bar)^2).
    """

    mu0: float = 0.0
    kappa0: float = 1.0
    alpha0: float = 2.0
    beta0: float = 1.0

    def update(self, data: list[float]) -> "NormalGamma":
        """Return a new NormalGamma with updated posterior."""
        n = len(data)
        if n == 0:
            return NormalGamma(
                mu0=self.mu0,
                kappa0=self.kappa0,
                alpha0=self.alpha0,
                beta0=self.beta0,
            )

        x_bar = sum(data) / n
        s = sum((x - x_bar) ** 2 for x in data)

        kappa_n = self.kappa0 + n
        mu_n = (self.kappa0 * self.mu0 + n * x_bar) / kappa_n
        alpha_n = self.alpha0 + n / 2.0
        beta_n = (
            self.beta0
            + 0.5 * s
            + (self.kappa0 * n * (x_bar - self.mu0) ** 2) / (2.0 * kappa_n)
        )

        return NormalGamma(
            mu0=mu_n,
            kappa0=kappa_n,
            alpha0=alpha_n,
            beta0=beta_n,
        )

    def mean(self) -> float:
        """Posterior mean of the data-generating process."""
        return self.mu0

    def variance(self) -> float:
        """Posterior predictive variance (marginal t-distribution variance).

        The predictive distribution is t_{2*alpha}(mu, beta/(kappa*alpha)).
        Its variance = beta / (kappa * (alpha - 1)) for alpha > 1.
        """
        if self.alpha0 <= 1.0:
            return float("inf")
        return self.beta0 / (self.kappa0 * (self.alpha0 - 1.0))

    def ci(self, level: float = 0.90) -> tuple[float, float]:
        """Approximate credible interval using t-distribution.

        The posterior predictive for the mean is:
            t_{2*alpha}(mu, beta / (kappa * alpha))
        We use the normal approximation for the t-distribution
        when 2*alpha > 30 (reasonable for our use case).
        """
        mu = self.mean()
        if self.alpha0 <= 1.0:
            return (float("-inf"), float("inf"))

        # Scale parameter of the marginal t
        scale = math.sqrt(self.beta0 / (self.kappa0 * self.alpha0))
        df = 2.0 * self.alpha0

        # t-distribution quantile approximation
        z = {0.80: 1.282, 0.90: 1.645, 0.95: 1.960, 0.99: 2.576}.get(
            level, 1.645
        )
        # Adjust for t-distribution with finite df
        if df < 30:
            # Cornish-Fisher-like correction for small df
            z = z * (1.0 + 1.0 / (4.0 * df))

        lo = mu - z * scale
        hi = mu + z * scale
        return (round(lo, 6), round(hi, 6))

    def ci_width(self, level: float = 0.90) -> float:
        """Width of the credible interval."""
        lo, hi = self.ci(level)
        if math.isinf(lo) or math.isinf(hi):
            return float("inf")
        return hi - lo

    @property
    def n_obs(self) -> float:
        """Effective number of observations (excluding prior)."""
        return self.kappa0 - 1.0  # subtract prior pseudo-observation
