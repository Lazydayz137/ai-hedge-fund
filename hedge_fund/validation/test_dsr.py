"""Deflated Sharpe: the formula, and the inputs it refuses."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from hedge_fund.validation.dsr import (
    MIN_OBSERVATIONS,
    deflated_sharpe_ratio,
    expected_maximum_sharpe,
    moments,
    probabilistic_sharpe_ratio,
)
from hedge_fund.validation.outcome import DegenerateInput

_EULER = 0.5772156649015329


def _series(n=250, mean=0.001, sigma=0.01, seed=7):
    """A fixed pseudo-random return series. Seeded: the verdict must not move."""
    return list(np.random.default_rng(seed).normal(mean, sigma, n))


def test_moments_match_a_hand_computation():
    sample = [0.01, -0.02, 0.03, 0.0, 0.015] * 10
    m = moments(sample, frequency="daily")
    assert m.n_observations == 50
    assert m.mean == pytest.approx(float(np.mean(sample)))
    assert m.stdev == pytest.approx(float(np.std(sample, ddof=1)))
    assert m.sharpe == pytest.approx(m.mean / m.stdev)
    assert m.skew == pytest.approx(float(stats.skew(sample, bias=False)))
    assert m.kurtosis == pytest.approx(
        float(stats.kurtosis(sample, fisher=False, bias=False))
    )


def test_kurtosis_is_non_excess():
    """A Gaussian sample sits near 3.0, not near 0.0 — the PSR wants the former."""
    m = moments(_series(n=4000, seed=3), frequency="daily")
    assert m.kurtosis == pytest.approx(3.0, abs=0.25)


def test_twelve_observations_is_refused():
    with pytest.raises(DegenerateInput, match="12 observations"):
        moments(_series(n=12), frequency="daily")


def test_the_minimum_cannot_be_argued_downward():
    with pytest.raises(DegenerateInput, match="below the floor"):
        moments(_series(n=200), frequency="daily", min_observations=5)


def test_a_constant_series_has_no_sharpe():
    with pytest.raises(DegenerateInput, match="zero dispersion"):
        moments([0.01] * 100, frequency="daily")


def test_a_hole_in_the_series_is_refused():
    sample = _series(n=100)
    sample[40] = float("nan")
    with pytest.raises(DegenerateInput, match="NaN"):
        moments(sample, frequency="daily")


def test_psr_matches_the_papers_formula():
    m = moments(_series(n=300, seed=11), frequency="daily")
    expected = stats.norm.cdf(
        (m.sharpe - 0.05) * math.sqrt(m.n_observations - 1)
        / math.sqrt(1 - m.skew * m.sharpe + (m.kurtosis - 1) / 4 * m.sharpe ** 2)
    )
    assert probabilistic_sharpe_ratio(m, 0.05) == pytest.approx(float(expected))


def test_psr_falls_as_the_benchmark_rises():
    m = moments(_series(n=300, seed=11), frequency="daily")
    assert probabilistic_sharpe_ratio(m, 0.0) > probabilistic_sharpe_ratio(m, 0.2)


def test_threshold_matches_the_papers_formula():
    variance = 0.04
    expected = math.sqrt(variance) * (
        (1 - _EULER) * stats.norm.ppf(1 - 1 / 20)
        + _EULER * stats.norm.ppf(1 - 1 / (20 * math.e))
    )
    assert expected_maximum_sharpe(20, variance) == pytest.approx(float(expected))


def test_threshold_rises_with_the_trial_count():
    """The whole point: more tries, higher bar."""
    low = expected_maximum_sharpe(5, 0.04)
    high = expected_maximum_sharpe(500, 0.04)
    assert high > low > 0


def test_one_trial_is_not_deflated():
    assert expected_maximum_sharpe(1, 0.04) == 0.0


def test_zero_trials_is_refused():
    with pytest.raises(DegenerateInput, match="evaluated zero times"):
        expected_maximum_sharpe(0, 0.04)


def test_zero_trial_variance_across_many_trials_is_refused():
    """Deflating by nothing is the protection present but not in force."""
    with pytest.raises(DegenerateInput, match="no deflation at all"):
        expected_maximum_sharpe(50, 0.0)


def test_the_same_track_deflates_away_as_trials_pile_up():
    returns = _series(n=500, mean=0.0012, sigma=0.01, seed=5)
    few = deflated_sharpe_ratio(
        returns, frequency="daily", n_trials=2, trial_sharpe_variance=0.01
    )
    many = deflated_sharpe_ratio(
        returns, frequency="daily", n_trials=1000, trial_sharpe_variance=0.01
    )
    assert few.observed_sharpe == many.observed_sharpe
    assert many.threshold_sharpe > few.threshold_sharpe
    assert many.psr < few.psr


def test_the_result_carries_its_own_provenance():
    result = deflated_sharpe_ratio(
        _series(n=120), frequency="weekly", n_trials=9, trial_sharpe_variance=0.02
    )
    assert result.n_trials == 9
    assert result.trial_sharpe_variance == 0.02
    assert result.moments.n_observations == 120
    assert result.moments.frequency == "weekly"


def test_deterministic_across_calls():
    returns = _series(n=400, seed=99)
    kwargs = dict(frequency="daily", n_trials=17, trial_sharpe_variance=0.03)
    assert deflated_sharpe_ratio(returns, **kwargs) == deflated_sharpe_ratio(
        returns, **kwargs
    )


def test_min_observations_default_is_the_floor():
    assert MIN_OBSERVATIONS == 30
