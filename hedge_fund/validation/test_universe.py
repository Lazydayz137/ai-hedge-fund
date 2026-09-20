"""Survivorship: the one check where absence is a FAIL."""

from __future__ import annotations

import pytest

from hedge_fund.validation.outcome import Verdict
from hedge_fund.validation.universe import Instrument, UniverseManifest, score


def _alive(symbol):
    return Instrument(symbol=symbol, first_date="2026-01-01")


def _dead(symbol, terminal=0.0):
    return Instrument(
        symbol=symbol, first_date="2026-01-01", last_date="2026-03-15",
        terminal_value=terminal, exit_reason="delisted",
    )


def _manifest(**overrides):
    fields = dict(
        window_start="2026-01-01",
        window_end="2026-06-30",
        point_in_time=True,
        instruments=[_alive("BTC"), _alive("ETH"), _dead("LUNA")],
        residual_bias_estimate_pct=0.93,
        source="frozen roster snapshots",
    )
    return UniverseManifest(**(fields | overrides))


def test_no_manifest_is_a_fail_not_a_skip():
    result = score(None)
    assert result.verdict is Verdict.FAIL
    assert "silence is this check's failure mode" in result.reason


def test_a_point_in_time_manifest_with_marked_deaths_passes():
    result = score(_manifest())
    assert result.verdict is Verdict.PASS
    assert result.evidence["n_died"] == 1
    assert result.evidence["n_survived"] == 2


def test_a_roster_taken_from_today_fails():
    result = score(_manifest(point_in_time=False))
    assert result.verdict is Verdict.FAIL
    assert "point-in-time" in result.reason


def test_a_dead_name_marked_to_nothing_fails():
    manifest = _manifest(instruments=[
        _alive("BTC"), _alive("ETH"),
        Instrument(symbol="LUNA", first_date="2026-01-01", last_date="2026-03-15"),
    ])
    result = score(manifest)
    assert result.verdict is Verdict.FAIL
    assert result.evidence["unmarked"] == ["LUNA"]


def test_an_all_survivors_universe_fails_unless_someone_attests_it():
    survivors = [_alive("BTC"), _alive("ETH"), _alive("SOL")]
    assert score(_manifest(instruments=survivors)).verdict is Verdict.FAIL
    attested = _manifest(instruments=survivors, no_deaths_attested=True)
    assert score(attested).verdict is Verdict.PASS


def test_an_unstated_residual_bias_fails():
    result = score(_manifest(residual_bias_estimate_pct=None))
    assert result.verdict is Verdict.FAIL
    assert "residual bias" in result.reason


def test_a_stated_residual_bias_of_zero_is_an_answer():
    assert score(_manifest(residual_bias_estimate_pct=0.0)).verdict is Verdict.PASS


def test_a_universe_of_one_is_unknown():
    """Degenerate input, not a survivorship finding."""
    result = score(_manifest(instruments=[_alive("BTC")]))
    assert result.verdict is Verdict.UNKNOWN
    assert result.evidence["n_instruments"] == 1


def test_an_empty_universe_is_unknown():
    assert score(_manifest(instruments=[])).verdict is Verdict.UNKNOWN


def test_a_caller_may_raise_the_minimum_but_not_lower_it():
    assert score(_manifest(), min_instruments=50).verdict is Verdict.UNKNOWN
    with pytest.raises(ValueError, match="floor"):
        score(_manifest(), min_instruments=1)


def test_a_backwards_window_is_rejected_at_construction():
    with pytest.raises(ValueError, match="ends"):
        _manifest(window_start="2026-06-30", window_end="2026-01-01")


def test_the_terminal_value_may_be_zero_without_reading_as_missing():
    """A rug marked to 0.0 is marked; `if not value` would call it unmarked."""
    manifest = _manifest(instruments=[_alive("BTC"), _alive("ETH"), _dead("X", 0.0)])
    assert score(manifest).verdict is Verdict.PASS
