"""The store: what cannot be overwritten, and what cannot be forgotten."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hedge_fund import paths
from hedge_fund.validation import registry

_T0 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def _prereg(strategy_id="carry-v1", **overrides):
    fields = dict(
        strategy_id=strategy_id,
        declared_at=_T0,
        hypothesis="cross-sectional funding carry on liquid perps",
        universe=["BTC", "ETH", "SOL"],
        features=["funding_8h", "basis"],
        horizon_days=7,
        success_threshold="abandon below DSR 0.95 at logged trials",
    )
    return registry.Preregistration(**(fields | overrides))


def _trial(n, strategy_id="carry-v1", sharpe=0.05, **overrides):
    fields = dict(
        strategy_id=strategy_id,
        evaluated_at=_T0 + timedelta(days=n),
        label=f"variant-{n}",
        sharpe=sharpe,
        frequency="daily",
        n_observations=250,
    )
    return registry.Trial(**(fields | overrides))


def test_registering_twice_is_refused():
    registry.register(_prereg())
    with pytest.raises(registry.AlreadyRegistered):
        registry.register(_prereg(hypothesis="actually it was momentum"))


def test_the_first_declaration_survives_the_second_attempt():
    registry.register(_prereg())
    with pytest.raises(registry.AlreadyRegistered):
        registry.register(_prereg(hypothesis="rewritten"))
    assert "funding carry" in registry.registration("carry-v1").hypothesis


def test_reading_an_unregistered_strategy_raises():
    with pytest.raises(registry.NotRegistered):
        registry.registration("never-declared")


def test_path_traversal_in_a_strategy_id_is_refused():
    for bad in ("../escape", "a/b", "", "." * 3, "x" * 90):
        with pytest.raises(registry.BadStrategyId):
            registry.strategy_dir(bad)


def test_trial_count_persists_across_readers():
    for n in range(4):
        registry.record_trial(_trial(n))
    assert registry.trial_count("carry-v1") == 4


def test_two_trials_in_the_same_microsecond_both_survive():
    """A collision must cost a suffix, never an observation."""
    registry.record_trial(_trial(0, sharpe=0.1))
    registry.record_trial(_trial(0, sharpe=0.2))
    assert registry.trial_count("carry-v1") == 2
    assert sorted(t.sharpe for t in registry.trials("carry-v1")) == [0.1, 0.2]


def test_trials_are_ordered_by_their_own_stamp_not_by_mtime():
    later = _trial(9, sharpe=0.9)
    earlier = _trial(1, sharpe=0.1)
    registry.record_trial(later)    # written first
    registry.record_trial(earlier)  # written second, but dated earlier
    assert [t.sharpe for t in registry.trials("carry-v1")] == [0.1, 0.9]


def test_abandoned_trials_still_count():
    """Dropping a variant is the selection the deflation corrects for."""
    registry.record_trial(_trial(0))
    registry.record_trial(_trial(1, abandoned=True))
    assert registry.trial_count("carry-v1") == 2


def test_trial_sharpe_variance_is_none_below_two_trials():
    assert registry.trial_sharpe_variance("carry-v1") is None
    registry.record_trial(_trial(0))
    assert registry.trial_sharpe_variance("carry-v1") is None


def test_trial_sharpe_variance_is_the_sample_variance():
    for n, sharpe in enumerate([0.0, 0.2, 0.4]):
        registry.record_trial(_trial(n, sharpe=sharpe))
    assert registry.trial_sharpe_variance("carry-v1") == pytest.approx(0.04)


def test_a_corrupt_trial_raises_rather_than_lowering_the_count():
    registry.record_trial(_trial(0))
    junk = registry.strategy_dir("carry-v1") / "trials" / "2026-01-09T000000000000Z.json"
    junk.write_text("{not json")
    with pytest.raises(registry.CorruptRecord):
        registry.trials("carry-v1")


def test_records_are_frozen():
    prereg = _prereg()
    with pytest.raises(ValueError):
        prereg.hypothesis = "something else"


def test_reveals_round_trip_in_order():
    for n in (3, 1):
        registry.record_reveal(registry.Reveal(
            strategy_id="carry-v1",
            revealed_at=_T0 + timedelta(days=n),
            window_start="2026-02-01",
            window_end="2026-04-30",
            reason=f"look {n}",
        ))
    assert [r.reason for r in registry.reveals("carry-v1")] == ["look 1", "look 3"]


def test_nothing_here_touches_the_real_user_dir(tmp_path):
    """The isolation fixture is doing its job, not the home directory."""
    registry.register(_prereg())
    assert paths.VALIDATION_DIR.is_relative_to(tmp_path)
    assert (paths.VALIDATION_DIR / "carry-v1" / "preregistration.json").is_file()
