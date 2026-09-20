"""Tests for alpha models (AlphaModel/QuantModel + PEADModel)."""

from __future__ import annotations

from hedge_fund.data.models import EarningsData, EarningsRecord
from hedge_fund.signals import PEADModel, QuantModel
from hedge_fund.signals.base import AlphaModel
from hedge_fund.models import Signal


class MockFDClient:
    """Returns canned earnings history for testing without API calls."""

    def __init__(self, earnings=None):
        self._earnings = earnings or []

    def get_earnings_history(self, ticker, limit=12):
        return self._earnings


def _rec(report_period, filing_date, surprise, source_type="8-K"):
    """One earnings row; `surprise=None` builds a record with no quarterly data."""
    return EarningsRecord(
        ticker="TEST", report_period=report_period, source_type=source_type,
        filing_date=filing_date,
        quarterly=EarningsData(eps_surprise=surprise) if surprise else None,
    )


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

class TestInterface:
    """The type contract the pipeline relies on to staff quant and LLM models alike."""

    def test_quant_model_is_alpha_model(self):
        """QuantModel plugs into the same AlphaModel slot an LLM persona does."""
        assert issubclass(QuantModel, AlphaModel)
        assert issubclass(PEADModel, QuantModel)

    def test_name(self):
        """The name is the key portfolio construction blends this model's views by."""
        assert PEADModel().name == "pead"

    def test_helpers(self):
        """Shared coercions: missing data reads as 0.0, and convictions clamp to ±1."""
        assert QuantModel._safe_float(None) == 0.0
        assert QuantModel._safe_float("3.5") == 3.5
        assert QuantModel._normalize_to_signal(2.0) == 1.0
        assert QuantModel._normalize_to_signal(-2.0) == -1.0


# ---------------------------------------------------------------------------
# PEADModel.predict
# ---------------------------------------------------------------------------

class TestPEADPredict:
    """When the drift view fires, which direction, and — above all — how recently
    the surprise must have been PUBLIC for the cycle to be allowed to trade it."""

    def test_beat_fires_long(self):
        """A BEAT filed the prior day produces a +1 long view with the
        surprise named in the reasoning."""
        fd = MockFDClient([_rec("2025-06-30", "2025-08-01", "BEAT")])
        sig = PEADModel().predict("TEST", "2025-08-02", fd)
        assert sig.value == 1.0
        assert sig.model_name == "pead"
        assert "BEAT" in sig.reasoning

    def test_miss_fires_short(self):
        """A MISS flips the sign: the drift view is short, not merely absent."""
        fd = MockFDClient([_rec("2025-06-30", "2025-08-01", "MISS")])
        sig = PEADModel().predict("TEST", "2025-08-02", fd)
        assert sig.value == -1.0

    def test_meet_is_neutral(self):
        """Only BEAT/MISS are tradeable — an in-line print is no information."""
        fd = MockFDClient([_rec("2025-06-30", "2025-08-01", "MEET")])
        sig = PEADModel().predict("TEST", "2025-08-02", fd)
        assert sig.value == 0.0

    def test_no_earnings_is_neutral(self):
        """A ticker with no earnings history abstains instead of erroring."""
        fd = MockFDClient([])
        sig = PEADModel().predict("TEST", "2025-08-01", fd)
        assert sig.value == 0.0

    def test_stale_event_is_neutral(self):
        """Drift is a first-few-days effect: a month-old surprise no longer fires."""
        # Event filed 30 days before the query date — outside the freshness window
        fd = MockFDClient([_rec("2025-06-30", "2025-08-01", "BEAT")])
        sig = PEADModel().predict("TEST", "2025-08-31", fd)
        assert sig.value == 0.0

    def test_point_in_time_ignores_future_filings(self):
        """A filing dated after the cycle is invisible — the classic lookahead."""
        # A filing dated after the query date must not be visible (no lookahead)
        fd = MockFDClient([_rec("2025-06-30", "2025-08-01", "BEAT")])
        sig = PEADModel().predict("TEST", "2025-07-15", fd)
        assert sig.value == 0.0

    def test_freshness_window_bridges_weekend(self):
        """The window is calendar days, so a Saturday filing is still live on Monday."""
        # Filed Saturday 2025-08-02; queried Monday 2025-08-04 (2 days) → still fresh
        fd = MockFDClient([_rec("2025-06-30", "2025-08-02", "BEAT")])
        sig = PEADModel().predict("TEST", "2025-08-04", fd)
        assert sig.value == 1.0

    def test_45_day_retrospective_filter(self):
        """Prior-quarter comparison rows parsed out of a current 8-K are dropped,
        not mistaken for a fresh surprise."""
        # Filing is 100+ days after the report period → retrospective, excluded
        fd = MockFDClient([_rec("2025-12-31", "2026-04-13", "BEAT")])
        sig = PEADModel().predict("TEST", "2026-04-13", fd)
        assert sig.value == 0.0

    def test_dedup_prefers_8k(self):
        """One event per report period, dated by the 8-K announcement rather than
        the later 10-Q restatement of the same numbers."""
        # Same report period via 8-K and 10-Q; 8-K should be the chosen source
        fd = MockFDClient([
            _rec("2025-06-30", "2025-08-01", "BEAT", source_type="8-K"),
            _rec("2025-06-30", "2025-08-02", "BEAT", source_type="10-Q"),
        ])
        sig = PEADModel().predict("TEST", "2025-08-03", fd)
        assert sig.value == 1.0
        assert sig.metadata["source_type"] == "8-K"

    def test_same_day_filing_does_not_fire(self):
        """The leak this guards: a cycle marks and fills at the as-of close, so a
        filing dated that same day (8-Ks land after 4pm) must not be tradeable —
        otherwise the fund buys the drift at a pre-announcement price."""
        fd = MockFDClient([_rec("2025-06-30", "2025-08-01", "BEAT")])
        sig = PEADModel().predict("TEST", "2025-08-01", fd)
        assert sig.value == 0.0
        assert sig.metadata == {}

    def test_day_one_filing_is_the_first_tradeable_day(self):
        """The day AFTER the filing is the earliest the drift can be bought, and
        it still fires — the fix narrows the window, it does not close it."""
        fd = MockFDClient([_rec("2025-06-30", "2025-08-01", "BEAT")])
        sig = PEADModel().predict("TEST", "2025-08-02", fd)
        assert sig.value == 1.0
        assert sig.metadata["filing_date"] == "2025-08-01"

    def test_same_day_filing_does_not_mask_an_in_window_event(self):
        """Today's un-actionable filing must not shadow the still-fresh surprise
        from two days ago — the newest-event pick happens after the PIT filter."""
        # Two distinct report periods so dedup keeps both events.
        fd = MockFDClient([
            _rec("2025-06-30", "2025-07-30", "BEAT", source_type="8-K"),
            _rec("2025-07-31", "2025-08-01", "MISS", source_type="8-K"),
        ])
        sig = PEADModel().predict("TEST", "2025-08-01", fd)
        assert sig.value == 1.0
        assert sig.metadata["filing_date"] == "2025-07-30"

    def test_returns_signal_type(self):
        """predict returns the shared Signal model, not a bare float."""
        fd = MockFDClient([_rec("2025-06-30", "2025-08-01", "BEAT")])
        sig = PEADModel().predict("TEST", "2025-08-02", fd)
        assert isinstance(sig, Signal)
