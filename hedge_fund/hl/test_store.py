"""store.py tests -- exclusive-creation writes and observed_at-ordered reads."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from hedge_fund import paths
from hedge_fund.hl.models import MarketSnapshot, PerpMarketRow
from hedge_fund.hl.store import read_as_of, save_snapshot

T0 = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)


def _snapshot(observed_at=T0, **over) -> MarketSnapshot:
    base = dict(observed_at=observed_at, perp_rows=[], spot_rows=[], failures=[], raw={})
    base.update(over)
    return MarketSnapshot(**base)


def _row(observed_at=T0) -> PerpMarketRow:
    return PerpMarketRow(
        observed_at=observed_at, dex="", name="BTC", sz_decimals=5,
        max_leverage=40, funding=0.0000125, open_interest=1.0,
        prev_day_px=1.0, day_ntl_vlm=1.0, oracle_px=1.0, mark_px=1.0,
    )


def _age(path, seconds):
    """Backdate a file's mtime so an mtime-based reader would misorder it."""
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime - seconds))


def test_save_writes_under_archive_dir():
    path = save_snapshot(_snapshot())
    assert path.parent == paths.ARCHIVE_DIR / "hyperliquid"
    assert path.exists()


def test_save_never_overwrites_same_second():
    """Two snapshots stamped the same second both land on disk."""
    first = save_snapshot(_snapshot())
    second = save_snapshot(_snapshot())
    assert first != second
    assert first.exists() and second.exists()


def test_round_trip_preserves_rows():
    saved = save_snapshot(_snapshot(perp_rows=[_row()]))
    [loaded] = read_as_of(T0)
    assert loaded.perp_rows[0].name == "BTC"
    assert loaded.observed_at == T0


def test_read_as_of_excludes_snapshots_after_when():
    save_snapshot(_snapshot(observed_at=T0))
    save_snapshot(_snapshot(observed_at=T0 + timedelta(hours=1)))
    result = read_as_of(T0)
    assert len(result) == 1
    assert result[0].observed_at == T0


def test_read_as_of_orders_by_observed_at_not_mtime():
    """Write newer-observed_at first but make it the OLDER file on disk --
    an mtime-sorted reader would get this backwards.
    """
    later_path = save_snapshot(_snapshot(observed_at=T0 + timedelta(minutes=10)))
    _age(later_path, 3600)  # make it look like the oldest file by mtime
    save_snapshot(_snapshot(observed_at=T0))

    result = read_as_of(T0 + timedelta(hours=1))
    assert [s.observed_at for s in result] == [T0, T0 + timedelta(minutes=10)]


def test_corrupt_file_is_skipped_not_fatal():
    good = save_snapshot(_snapshot())
    (good.parent / "hl-20260101T000000Z-garbage.json").write_text("not json")
    result = read_as_of(T0 + timedelta(days=1))
    assert len(result) == 1
