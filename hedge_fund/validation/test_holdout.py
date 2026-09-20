"""The sealed window: too short, already opened, not forward, not net."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hedge_fund.validation import registry
from hedge_fund.validation.holdout import HoldoutWindow, SealedHoldout, score
from hedge_fund.validation.outcome import Verdict

_NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _window(**overrides):
    fields = dict(
        start="2026-02-01",
        end="2026-04-30",
        in_sample_end="2026-01-31",
        holding_period_days=7,
        frequency="daily",
        net_of_costs=True,
        cost_model="0.23% all-taker round trip + 5bp slippage",
    )
    return HoldoutWindow(**(fields | overrides))


def _sealed(returns=None, window=None, strategy_id="carry-v1"):
    return SealedHoldout(
        strategy_id=strategy_id,
        window=window or _window(),
        returns=returns if returns is not None else [0.001] * 60,
        sealed_at=datetime(2026, 1, 31, tzinfo=timezone.utc),
    )


def test_no_holdout_is_unknown():
    assert score(None, revealed_at=_NOW).verdict is Verdict.UNKNOWN


def test_a_positive_unlooked_window_passes():
    result = score(_sealed(), revealed_at=_NOW)
    assert result.verdict is Verdict.PASS
    assert result.evidence["total_return"] > 0
    assert result.evidence["span_days"] == 89


def test_scoring_records_the_reveal():
    score(_sealed(), revealed_at=_NOW)
    assert [r.window_start for r in registry.reveals("carry-v1")] == ["2026-02-01"]


def test_scoring_the_same_window_twice_fails_the_second_time():
    """One look. The second one is recorded and cannot be un-recorded."""
    assert score(_sealed(), revealed_at=_NOW).verdict is Verdict.PASS
    second = score(_sealed(), revealed_at=_NOW)
    assert second.verdict is Verdict.FAIL
    assert "already unsealed" in second.reason


def test_a_hand_reveal_before_scoring_breaks_the_seal():
    sealed = _sealed()
    sealed.reveal(reason="just peeking", revealed_at=_NOW)
    result = score(_sealed(), revealed_at=_NOW)
    assert result.verdict is Verdict.FAIL
    assert result.evidence["first_reveal_reason"] == "just peeking"


def test_a_negative_window_fails():
    result = score(_sealed(returns=[-0.002] * 60), revealed_at=_NOW)
    assert result.verdict is Verdict.FAIL
    assert result.evidence["total_return"] < 0


def test_a_three_day_window_is_unknown_not_fail():
    """Too short to answer is not the same as answering no."""
    window = _window(start="2026-02-01", end="2026-02-03")
    result = score(_sealed(returns=[0.01] * 3, window=window), revealed_at=_NOW)
    assert result.verdict is Verdict.UNKNOWN
    assert result.evidence["span_days"] == 3


def test_sixty_days_is_not_enough_at_a_long_holding_period():
    window = _window(start="2026-02-01", end="2026-04-01", holding_period_days=30)
    result = score(_sealed(returns=[0.001] * 60, window=window), revealed_at=_NOW)
    assert result.verdict is Verdict.UNKNOWN
    assert result.evidence["required_days"] == 90


def test_a_window_overlapping_the_training_data_fails():
    window = _window(in_sample_end="2026-02-15")
    result = score(_sealed(window=window), revealed_at=_NOW)
    assert result.verdict is Verdict.FAIL
    assert "overlaps" in result.reason


def test_gross_returns_are_unknown():
    window = _window(net_of_costs=False, cost_model=None)
    result = score(_sealed(window=window), revealed_at=_NOW)
    assert result.verdict is Verdict.UNKNOWN
    assert "net of costs" in result.reason


def test_a_long_window_sampled_three_times_is_unknown():
    result = score(_sealed(returns=[0.05, 0.05, 0.05]), revealed_at=_NOW)
    assert result.verdict is Verdict.UNKNOWN
    assert result.evidence["n_observations"] == 3


def test_an_unscorable_window_is_not_revealed():
    """A window the check declined to score must still be sealed afterwards."""
    window = _window(start="2026-02-01", end="2026-02-03")
    score(_sealed(returns=[0.01] * 3, window=window), revealed_at=_NOW)
    assert registry.reveals("carry-v1") == []


def test_the_returns_are_not_in_the_repr():
    sealed = _sealed(returns=[0.777] * 60)
    assert "0.777" not in repr(sealed)
    assert "sealed" in repr(sealed)


def test_n_observations_is_available_without_revealing():
    sealed = _sealed(returns=[0.001] * 44)
    assert sealed.n_observations == 44
    assert registry.reveals("carry-v1") == []


def test_a_backwards_window_is_rejected_at_construction():
    with pytest.raises(ValueError, match="ends"):
        _window(start="2026-04-30", end="2026-02-01")


def test_a_non_iso_date_is_rejected_at_construction():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _window(start="Feb 2026")


def test_the_total_return_is_compounded_not_summed():
    result = score(_sealed(returns=[0.01] * 60), revealed_at=_NOW)
    assert result.evidence["total_return"] == pytest.approx(1.01 ** 60 - 1)
