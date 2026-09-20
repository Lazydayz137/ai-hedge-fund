"""Deflated Sharpe Ratio — Bailey & Lopez de Prado (2014).

A Sharpe ratio is a statement about one strategy. A Sharpe ratio selected as
the best of N tried strategies is a statement about an order statistic, and the
expected maximum of N draws from a zero-skill distribution rises without bound
in N. Bailey & Lopez de Prado show that on five years of daily data roughly 45
trials already put the *selected* strategy's expected out-of-sample Sharpe at
or below zero. So the number that matters is never the Sharpe; it is the Sharpe
next to the trial count that produced it, deflated by the spread of the trials.

Everything here is per-observation, never annualized. Annualizing multiplies
the Sharpe by sqrt(periods) while leaving the track length T alone, which
inflates the statistic without adding evidence. The caller who wants an
annualized figure for a report can compute one; the deflation is done at the
frequency the returns were actually observed, and `ReturnMoments` records which
frequency that was so the two can never be confused in a receipt.

Degenerate input raises DegenerateInput rather than returning a confident
float. A DSR computed from twelve observations is not a weak result, it is not
a result: the PSR's normal approximation and the sample third and fourth
moments it consumes are both estimated from the same short series.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict
from scipy import stats

from hedge_fund.validation.outcome import DegenerateInput

# Euler-Mascheroni. It appears in the expected-maximum-of-N-Gaussians
# approximation the threshold below is built on, not as a fudge factor.
_EULER_MASCHERONI = 0.5772156649015329

# Below this, the estimators stop meaning anything: the PSR is an asymptotic
# normal approximation, and the bias-corrected skew and kurtosis it consumes
# need a sample before they are better than noise. Callers may raise this and
# may not lower it — a floor that an argument can dissolve is not a floor.
MIN_OBSERVATIONS = 30


class ReturnMoments(BaseModel):
    """The four numbers the DSR is computed from, plus the sample behind them.

    Kurtosis is NON-excess (3.0 for a Gaussian), which is what the PSR formula
    wants. Stating that here rather than in a caller's head is the difference
    between a correct deflation and one that is silently off by (gamma_4 - 1)/4
    times the squared Sharpe.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_observations: int
    frequency: str
    mean: float
    stdev: float
    sharpe: float
    skew: float
    kurtosis: float
    estimator: str = "scipy bias-corrected (G1 skew, G2 kurtosis), stdev ddof=1"


class DeflatedSharpe(BaseModel):
    """A deflated Sharpe and every input that produced it.

    `psr` is a probability in [0, 1]: P(true Sharpe > threshold) given the
    observed track. `threshold_sharpe` is the Sharpe a zero-skill strategy is
    expected to reach as the best of `n_trials` tries; the whole point of the
    statistic is that it rises with the trial count, so a report that quotes
    `psr` without `n_trials` beside it has quoted nothing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    psr: float
    observed_sharpe: float
    threshold_sharpe: float
    n_trials: int
    trial_sharpe_variance: float
    moments: ReturnMoments


def moments(
    returns: Sequence[float],
    *,
    frequency: str,
    min_observations: int = MIN_OBSERVATIONS,
) -> ReturnMoments:
    """Sample moments of *returns*, or a refusal.

    *frequency* is a label ("daily", "weekly", ...) carried through to the
    receipt. It is required rather than defaulted because a Sharpe whose period
    nobody wrote down is the single easiest number in this codebase to
    misread by a factor of sixteen.
    """
    if min_observations < MIN_OBSERVATIONS:
        raise DegenerateInput(
            f"min_observations={min_observations} is below the floor of "
            f"{MIN_OBSERVATIONS}; the PSR is an asymptotic approximation and "
            "lowering its sample requirement does not make the sample larger"
        )
    sample = np.asarray(list(returns), dtype=float)
    if sample.size < min_observations:
        raise DegenerateInput(
            f"{sample.size} observations is below the {min_observations} "
            "required; a Sharpe this short carries no information about its "
            "own third and fourth moments"
        )
    if not np.all(np.isfinite(sample)):
        raise DegenerateInput(
            "returns contain NaN or inf; a dead instrument belongs in the "
            "series at its terminal value, not as a hole"
        )

    stdev = float(sample.std(ddof=1))
    # Relative, not `<= 0`. A constant series of 0.01 does not have a float
    # standard deviation of exactly zero — it has one around 1e-18, the
    # rounding residue of summing the same number a hundred times — and an
    # absolute test lets that through as a Sharpe of ten million. Checked
    # before the third and fourth moments so the degenerate case raises here
    # rather than emerging as a scipy cancellation warning.
    scale = float(np.mean(np.abs(sample))) or 1.0
    if stdev <= 0.0 or stdev < 1e-12 * scale:
        raise DegenerateInput(
            f"returns have zero dispersion (stdev {stdev:.3g} against a scale "
            f"of {scale:.3g}); a Sharpe ratio does not exist for a constant "
            "series, and one computed from rounding residue is worse than none"
        )

    mean = float(sample.mean())
    return ReturnMoments(
        n_observations=int(sample.size),
        frequency=frequency,
        mean=mean,
        stdev=stdev,
        sharpe=mean / stdev,
        skew=float(stats.skew(sample, bias=False)),
        kurtosis=float(stats.kurtosis(sample, fisher=False, bias=False)),
    )


def probabilistic_sharpe_ratio(
    observed: ReturnMoments, benchmark_sharpe: float
) -> float:
    """P(true Sharpe > *benchmark_sharpe*), Bailey & Lopez de Prado eq. (1).

        PSR(SR*) = Z[ (SR_hat - SR*) * sqrt(T - 1)
                      / sqrt(1 - g3*SR_hat + (g4 - 1)/4 * SR_hat^2) ]

    where Z is the standard normal CDF, SR_hat the observed per-observation
    Sharpe, T the track length, g3 the skew and g4 the non-excess kurtosis.
    The denominator is the standard error of the Sharpe under non-normal
    returns: negative skew and fat tails both widen it, which is why a crypto
    or short-vol track with a flattering Sharpe deflates so hard.
    """
    sharpe = observed.sharpe
    variance = (
        1.0
        - observed.skew * sharpe
        + (observed.kurtosis - 1.0) / 4.0 * sharpe * sharpe
    )
    if variance <= 0.0:
        # Reachable with strongly positive skew at a high Sharpe. The formula
        # has left its domain; returning Z of a complex number's worth of
        # nonsense, or of an arbitrary clamp, would be a confident answer from
        # input that cannot support one.
        raise DegenerateInput(
            "the Sharpe's estimated variance is non-positive "
            f"({variance:.6g}) at skew={observed.skew:.4g}, "
            f"kurtosis={observed.kurtosis:.4g}, sharpe={sharpe:.4g}; the PSR "
            "approximation does not hold on this sample"
        )
    z = (sharpe - benchmark_sharpe) * math.sqrt(observed.n_observations - 1)
    return float(stats.norm.cdf(z / math.sqrt(variance)))


def expected_maximum_sharpe(n_trials: int, trial_sharpe_variance: float) -> float:
    """The Sharpe a zero-skill strategy reaches as best-of-*n_trials*.

    Bailey & Lopez de Prado eq. (2), the false-strategy threshold:

        SR*_0 = sqrt(V[SR_n]) * [ (1 - gamma) * Z^-1(1 - 1/N)
                                  + gamma * Z^-1(1 - 1/(N*e)) ]

    with gamma the Euler-Mascheroni constant, N the trial count, V[SR_n] the
    variance of the trials' Sharpes, and Z^-1 the standard normal quantile.

    N = 1 is special-cased to 0.0. The approximation is for the expected
    maximum of N > 1 draws and its first term is Z^-1(0) at N = 1; the exact
    answer there is the mean of a single standard normal draw, which is zero.
    A single trial is not deflated because nothing was selected.
    """
    if n_trials < 1:
        raise DegenerateInput(
            f"n_trials={n_trials}; a strategy that was evaluated zero times "
            "has no observed Sharpe to deflate"
        )
    if n_trials == 1:
        return 0.0
    if trial_sharpe_variance <= 0.0:
        raise DegenerateInput(
            f"trial_sharpe_variance={trial_sharpe_variance!r} across "
            f"{n_trials} trials; the deflation is made of that variance, so "
            "zero means no deflation at all — which is the protection being "
            "present but not in force"
        )
    spread = math.sqrt(trial_sharpe_variance)
    upper = float(stats.norm.ppf(1.0 - 1.0 / n_trials))
    inner = float(stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e)))
    return spread * (
        (1.0 - _EULER_MASCHERONI) * upper + _EULER_MASCHERONI * inner
    )


def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    frequency: str,
    n_trials: int,
    trial_sharpe_variance: float,
    min_observations: int = MIN_OBSERVATIONS,
) -> DeflatedSharpe:
    """The deflated Sharpe of *returns* at *n_trials*, or a refusal.

    Every argument is mandatory on purpose. A default trial count would be a
    number the caller did not write down, and report 02 is explicit that if you
    do not know your trial count your p-value does not exist.
    """
    observed = moments(
        returns, frequency=frequency, min_observations=min_observations
    )
    threshold = expected_maximum_sharpe(n_trials, trial_sharpe_variance)
    return DeflatedSharpe(
        psr=probabilistic_sharpe_ratio(observed, threshold),
        observed_sharpe=observed.sharpe,
        threshold_sharpe=threshold,
        n_trials=n_trials,
        trial_sharpe_variance=trial_sharpe_variance,
        moments=observed,
    )
