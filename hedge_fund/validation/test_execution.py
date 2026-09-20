"""Lag and capacity: half an experiment answers nothing."""

from __future__ import annotations

import pytest

from hedge_fund.validation.execution import Scenario, cap_fill, score
from hedge_fund.validation.outcome import Verdict


def _scenario(label="lag-1", lag=1, cap=0.05, sharpe=0.05, total=0.08, n=250):
    return Scenario(
        label=label, lag_bars=lag, participation_cap=cap,
        sharpe=sharpe, total_return=total, n_observations=n,
    )


def _baseline(sharpe=0.09, total=0.30):
    return Scenario(
        label="baseline", lag_bars=0, participation_cap=None,
        sharpe=sharpe, total_return=total, n_observations=250,
    )


def test_fills_are_capped_at_the_bars_volume_share():
    cap = cap_fill(10_000, bar_volume=50_000, participation_cap=0.05)
    assert cap.filled == 2_500
    assert cap.unfilled == 7_500


def test_a_small_order_fills_whole():
    assert cap_fill(100, bar_volume=50_000, participation_cap=0.05).unfilled == 0


def test_the_cap_rounds_down_to_whole_shares():
    assert cap_fill(10, bar_volume=39, participation_cap=0.05).filled == 1


def test_no_volume_means_no_fill():
    cap = cap_fill(500, bar_volume=0, participation_cap=0.1)
    assert (cap.filled, cap.unfilled) == (0, 500)


def test_an_impossible_participation_cap_raises():
    for bad in (0.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="participation_cap"):
            cap_fill(10, 1000, bad)


def test_no_baseline_is_unknown():
    assert score(None, [_scenario()]).verdict is Verdict.UNKNOWN


def test_no_scenarios_is_unknown():
    assert score(_baseline(), []).verdict is Verdict.UNKNOWN


def test_a_rerun_of_the_baseline_is_not_a_robustness_test():
    undegraded = Scenario(
        label="rerun", lag_bars=0, participation_cap=1.0,
        sharpe=0.09, total_return=0.30, n_observations=250,
    )
    result = score(_baseline(), [undegraded])
    assert result.verdict is Verdict.UNKNOWN
    assert "not a robustness test" in result.reason


def test_lag_without_a_volume_cap_is_unknown():
    lag_only = Scenario(
        label="lag-only", lag_bars=1, participation_cap=None,
        sharpe=0.05, total_return=0.08, n_observations=250,
    )
    result = score(_baseline(), [lag_only])
    assert result.verdict is Verdict.UNKNOWN
    assert "volume-capped fill model" in result.reason


def test_a_volume_cap_without_lag_is_unknown():
    cap_only = Scenario(
        label="cap-only", lag_bars=0, participation_cap=0.05,
        sharpe=0.05, total_return=0.08, n_observations=250,
    )
    result = score(_baseline(), [cap_only])
    assert result.verdict is Verdict.UNKNOWN
    assert "injected lag" in result.reason


def test_surviving_scenarios_pass_and_report_the_degradation():
    result = score(_baseline(sharpe=0.10), [_scenario(sharpe=0.05)])
    assert result.verdict is Verdict.PASS
    assert result.evidence["scenarios"][0]["sharpe_degradation"] == pytest.approx(0.5)
    assert "50.0%" in result.reason


def test_a_scenario_that_goes_negative_fails():
    result = score(_baseline(), [_scenario(sharpe=-0.01, total=-0.02)])
    assert result.verdict is Verdict.FAIL
    assert "non-positive" in result.reason


def test_degradation_can_be_gated_when_the_caller_asks():
    survives = [_scenario(sharpe=0.02)]  # 0.09 -> 0.02 is a 78% fall
    assert score(_baseline(), survives).verdict is Verdict.PASS
    gated = score(_baseline(), survives, max_sharpe_degradation=0.5)
    assert gated.verdict is Verdict.FAIL
    assert "exceeds" in gated.reason


def test_a_zero_baseline_sharpe_reports_no_degradation_rather_than_dividing():
    result = score(_baseline(sharpe=0.0), [_scenario(sharpe=0.05)])
    assert result.evidence["scenarios"][0]["sharpe_degradation"] is None
    assert result.verdict is Verdict.PASS


def test_a_negative_baseline_does_not_read_a_worse_result_as_improvement():
    result = score(_baseline(sharpe=-0.2), [_scenario(sharpe=-0.4, total=-0.1)])
    assert result.evidence["scenarios"][0]["sharpe_degradation"] == pytest.approx(1.0)
