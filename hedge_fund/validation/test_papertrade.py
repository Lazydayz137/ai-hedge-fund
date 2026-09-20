"""Paper trading: length, coverage, and the sign of slippage."""

from __future__ import annotations

import pytest

from hedge_fund.validation.outcome import Verdict
from hedge_fund.validation.papertrade import PaperFill, PaperTradeRecord, score


def _fill(n, side="buy", intended=100.0, achieved=100.1):
    return PaperFill(
        order_id=f"o{n}", symbol="BTC", side=side, quantity=1,
        intended_price=intended, achieved_price=achieved,
        placed_on="2026-02-10",
    )


def _record(fills=None, **overrides):
    fills = [_fill(n) for n in range(5)] if fills is None else fills
    fields = dict(
        strategy_id="carry-v1",
        started_on="2026-02-01",
        ended_on="2026-03-15",
        n_orders_placed=len(fills),
        fills=fills,
        venue="hyperliquid-testnet",
    )
    return PaperTradeRecord(**(fields | overrides))


def test_no_record_is_unknown():
    assert score(None).verdict is Verdict.UNKNOWN


def test_a_complete_45_day_record_passes():
    result = score(_record())
    assert result.verdict is Verdict.PASS
    assert result.evidence["span_days"] == 43
    assert result.evidence["mean_slippage_bps"] == pytest.approx(10.0)


def test_a_twelve_day_record_fails_because_the_shortfall_is_measured():
    result = score(_record(ended_on="2026-02-12"))
    assert result.verdict is Verdict.FAIL
    assert result.evidence["span_days"] == 12


def test_orders_without_logged_fills_fail():
    result = score(_record(n_orders_placed=9))
    assert result.verdict is Verdict.FAIL
    assert "4 of 9 orders have no logged fill" in result.reason


def test_more_fills_than_orders_fails_rather_than_averaging():
    result = score(_record(n_orders_placed=2))
    assert result.verdict is Verdict.FAIL
    assert "does not reconcile" in result.reason


def test_a_long_record_with_no_orders_is_unknown():
    result = score(_record(fills=[], n_orders_placed=0))
    assert result.verdict is Verdict.UNKNOWN
    assert "did not trade" in result.reason


def test_adverse_slippage_is_positive_on_both_sides():
    buy = _fill(0, side="buy", intended=100.0, achieved=100.5)
    sell = _fill(1, side="sell", intended=100.0, achieved=99.5)
    assert buy.slippage_bps == pytest.approx(50.0)
    assert sell.slippage_bps == pytest.approx(50.0)


def test_a_two_sided_book_does_not_cancel_its_own_friction():
    """Signing by price direction would report this book as frictionless."""
    fills = [
        _fill(0, side="buy", intended=100.0, achieved=100.5),
        _fill(1, side="sell", intended=100.0, achieved=99.5),
    ]
    result = score(_record(fills=fills))
    assert result.evidence["mean_slippage_bps"] == pytest.approx(50.0)


def test_favourable_fills_are_negative():
    good = _fill(0, side="buy", intended=100.0, achieved=99.9)
    assert good.slippage_bps == pytest.approx(-10.0)


def test_slippage_can_be_gated_when_the_caller_asks():
    fills = [_fill(0, intended=100.0, achieved=101.0)]
    assert score(_record(fills=fills)).verdict is Verdict.PASS
    gated = score(_record(fills=fills), max_mean_slippage_bps=50.0)
    assert gated.verdict is Verdict.FAIL
    assert "exceeds" in gated.reason


def test_the_percentile_is_nearest_rank_not_interpolated():
    fills = [_fill(n, achieved=100.0 + n / 10) for n in range(10)]
    result = score(_record(fills=fills))
    assert result.evidence["p95_slippage_bps"] == pytest.approx(90.0)
    assert result.evidence["worst_slippage_bps"] == pytest.approx(90.0)


def test_a_backwards_record_is_rejected_at_construction():
    with pytest.raises(ValueError, match="ends"):
        _record(started_on="2026-03-15", ended_on="2026-02-01")
