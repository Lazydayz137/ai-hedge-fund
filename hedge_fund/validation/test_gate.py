"""The gate: the checks composed, and the ways a PASS is not available."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from hedge_fund.validation import execution, gate, holdout, papertrade, registry, universe
from hedge_fund.validation.outcome import DegenerateInput, Verdict

_T0 = datetime(2026, 1, 5, tzinfo=timezone.utc)
_NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)
_ID = "carry-v1"


def _returns(n=400, mean=0.0015, sigma=0.01, seed=4):
    return list(np.random.default_rng(seed).normal(mean, sigma, n))


def _declare(strategy_id=_ID, declared_at=_T0):
    registry.register(registry.Preregistration(
        strategy_id=strategy_id,
        declared_at=declared_at,
        hypothesis="cross-sectional funding carry",
        universe=["BTC", "ETH", "SOL"],
        horizon_days=7,
        success_threshold="abandon below DSR 0.95",
    ))


def _log_trials(n, strategy_id=_ID, spread=0.01, start_day=1):
    for i in range(n):
        registry.record_trial(registry.Trial(
            strategy_id=strategy_id,
            evaluated_at=_T0 + timedelta(days=start_day + i),
            label=f"variant-{i}",
            sharpe=0.05 + spread * i,
            frequency="daily",
            n_observations=400,
        ))


# --- returns_from_nav -------------------------------------------------------

def test_returns_from_nav_counts_the_first_cycle():
    assert gate.returns_from_nav(100.0, [110.0, 121.0]) == pytest.approx([0.1, 0.1])


def test_returns_from_nav_refuses_to_continue_past_a_wiped_book():
    with pytest.raises(DegenerateInput, match="wiped book"):
        gate.returns_from_nav(100.0, [0.0, 50.0])


# --- pre-registration -------------------------------------------------------

def test_an_undeclared_strategy_fails_the_preregistration_check():
    result = gate.score_preregistration("never-declared")
    assert result.verdict is Verdict.FAIL
    assert result.evidence["registered"] is False


def test_a_declaration_with_no_logged_trials_fails():
    _declare()
    result = gate.score_preregistration(_ID)
    assert result.verdict is Verdict.FAIL
    assert "zero logged trials" in result.reason


def test_a_declaration_made_after_the_first_trial_fails():
    _log_trials(3, start_day=1)
    _declare(declared_at=_T0 + timedelta(days=30))
    result = gate.score_preregistration(_ID)
    assert result.verdict is Verdict.FAIL
    assert "after the strategy had already been tested" in result.reason


def test_a_declaration_before_the_trials_passes_and_reports_the_count():
    _declare()
    _log_trials(6)
    result = gate.score_preregistration(_ID)
    assert result.verdict is Verdict.PASS
    assert result.evidence["n_trials"] == 6
    assert result.evidence["trial_sharpe_variance"] is not None


# --- deflated Sharpe --------------------------------------------------------

def test_no_returns_is_unknown():
    _declare()
    _log_trials(4)
    result = gate.score_deflated_sharpe(_ID, None, frequency="daily")
    assert result.verdict is Verdict.UNKNOWN


def test_no_logged_trials_is_unknown_not_an_undeflated_pass():
    """Report 02: if you do not know your trial count, your p-value does not exist."""
    result = gate.score_deflated_sharpe(_ID, _returns(), frequency="daily")
    assert result.verdict is Verdict.UNKNOWN
    assert "no logged trials" in result.reason


def test_twelve_observations_is_unknown_with_the_arithmetic_reason_attached():
    _log_trials(4)
    result = gate.score_deflated_sharpe(_ID, _returns(n=12), frequency="daily")
    assert result.verdict is Verdict.UNKNOWN
    assert "12 observations" in result.reason


def test_a_strong_track_at_a_handful_of_trials_passes():
    _log_trials(4)
    result = gate.score_deflated_sharpe(_ID, _returns(), frequency="daily")
    assert result.verdict is Verdict.PASS
    assert result.evidence["n_trials_used"] == 4
    assert result.evidence["psr"] >= 0.95


def test_the_same_track_fails_once_enough_variants_were_tried():
    """The statistic's entire purpose, exercised end to end."""
    returns = _returns()
    _log_trials(4)
    assert gate.score_deflated_sharpe(_ID, returns, frequency="daily").verdict is Verdict.PASS

    _log_trials(300, start_day=100)
    deflated = gate.score_deflated_sharpe(_ID, returns, frequency="daily")
    assert deflated.verdict is Verdict.FAIL
    assert deflated.evidence["n_trials_used"] == 304
    assert deflated.evidence["threshold_sharpe"] > deflated.evidence["observed_sharpe"]


def test_scoring_at_fewer_trials_than_were_logged_fails():
    """Deflating by fewer trials than you ran is the bias, not the correction."""
    _log_trials(50)
    result = gate.score_deflated_sharpe(
        _ID, _returns(), frequency="daily", n_trials=2, trial_sharpe_variance=0.01
    )
    assert result.verdict is Verdict.FAIL
    assert result.evidence["n_trials_logged"] == 50


def test_the_evidence_carries_the_moments_it_deflated_with():
    _log_trials(5)
    evidence = gate.score_deflated_sharpe(_ID, _returns(), frequency="daily").evidence
    assert evidence["n_observations"] == 400
    assert "skew" in evidence and "kurtosis" in evidence
    assert "scipy" in evidence["moment_estimator"]


def test_a_nonsense_confidence_raises():
    with pytest.raises(ValueError, match="confidence"):
        gate.score_deflated_sharpe(_ID, _returns(), frequency="daily", confidence=1.5)


# --- the whole gate ---------------------------------------------------------

def test_a_caller_who_supplies_nothing_gets_no_passes():
    report = gate.evaluate("nothing-supplied")
    assert report.verdict is Verdict.UNKNOWN
    assert report.permits_risk is False
    assert len(report.checks) == 6
    # Pre-registration and survivorship are the two that FAIL on absence.
    assert {c.check for c in report.checks if c.verdict is Verdict.FAIL} == {
        gate.PREREGISTRATION, universe.CHECK,
    }


def test_no_check_can_pass_without_its_input():
    report = gate.evaluate("nothing-supplied")
    assert Verdict.PASS not in {c.verdict for c in report.checks}


def _full_evidence(strategy_id=_ID):
    """Everything a strategy would have to produce to clear the bar."""
    _declare(strategy_id)
    _log_trials(4, strategy_id)
    return dict(
        returns=_returns(),
        frequency="daily",
        sealed_holdout=holdout.SealedHoldout(
            strategy_id=strategy_id,
            window=holdout.HoldoutWindow(
                start="2026-02-01", end="2026-04-30", in_sample_end="2026-01-31",
                holding_period_days=7, frequency="daily", net_of_costs=True,
                cost_model="0.23% round trip",
            ),
            returns=[0.001] * 60,
            sealed_at=datetime(2026, 1, 31, tzinfo=timezone.utc),
        ),
        revealed_at=_NOW,
        execution_baseline=execution.Scenario(
            label="baseline", lag_bars=0, participation_cap=None,
            sharpe=0.09, total_return=0.30, n_observations=400,
        ),
        execution_scenarios=[
            execution.Scenario(
                label="lag-1-cap-5pct", lag_bars=1, participation_cap=0.05,
                sharpe=0.05, total_return=0.12, n_observations=400,
            ),
        ],
        universe_manifest=universe.UniverseManifest(
            window_start="2026-01-01", window_end="2026-06-30", point_in_time=True,
            instruments=[
                universe.Instrument(symbol="BTC", first_date="2026-01-01"),
                universe.Instrument(symbol="ETH", first_date="2026-01-01"),
                universe.Instrument(
                    symbol="LUNA", first_date="2026-01-01",
                    last_date="2026-03-15", terminal_value=0.0,
                    exit_reason="delisted",
                ),
            ],
            residual_bias_estimate_pct=0.93,
        ),
        paper_record=papertrade.PaperTradeRecord(
            strategy_id=strategy_id, started_on="2026-02-01", ended_on="2026-03-15",
            n_orders_placed=2,
            fills=[
                papertrade.PaperFill(
                    order_id="o1", symbol="BTC", side="buy", quantity=1,
                    intended_price=100.0, achieved_price=100.1,
                    placed_on="2026-02-10",
                ),
                papertrade.PaperFill(
                    order_id="o2", symbol="ETH", side="sell", quantity=1,
                    intended_price=50.0, achieved_price=49.98,
                    placed_on="2026-03-01",
                ),
            ],
        ),
    )


def test_a_complete_dossier_passes_and_permits_risk():
    """The bar is clearable — a gate nothing can pass is not a gate."""
    report = gate.evaluate(_ID, **_full_evidence())
    assert report.verdict is Verdict.PASS, report.summary()
    assert report.permits_risk is True
    assert all(c.verdict is Verdict.PASS for c in report.checks)


def test_removing_any_single_piece_of_evidence_removes_the_pass():
    for missing in (
        "returns", "sealed_holdout", "execution_baseline",
        "universe_manifest", "paper_record",
    ):
        evidence = _full_evidence(f"ablate-{missing.replace('_', '-')}")
        evidence[missing] = None
        if missing == "execution_baseline":
            evidence["execution_scenarios"] = ()
        report = gate.evaluate(f"ablate-{missing.replace('_', '-')}", **evidence)
        assert report.permits_risk is False, missing


def test_a_holdout_without_a_reveal_timestamp_is_unknown_and_stays_sealed():
    evidence = _full_evidence()
    evidence["revealed_at"] = None
    report = gate.evaluate(_ID, **evidence)
    assert report.by_check(holdout.CHECK).verdict is Verdict.UNKNOWN
    assert registry.reveals(_ID) == []


def test_the_verdict_is_deterministic():
    first = gate.evaluate("det-a", **_full_evidence("det-a"))
    second = gate.evaluate("det-b", **_full_evidence("det-b"))
    assert [c.verdict for c in first.checks] == [c.verdict for c in second.checks]


def test_the_summary_names_every_check_and_its_reason():
    report = gate.evaluate("nothing-supplied")
    text = report.summary()
    assert text.splitlines()[0].endswith("UNKNOWN")
    for check in report.checks:
        assert check.check in text
        assert check.reason.split(";")[0][:30] in text


def test_the_report_round_trips_as_json():
    """A verdict nobody can archive is a verdict nobody can audit."""
    report = gate.evaluate(_ID, **_full_evidence())
    again = gate.ValidationReport.model_validate_json(report.model_dump_json())
    assert again.verdict is report.verdict
    assert [c.check for c in again.checks] == [c.check for c in report.checks]
