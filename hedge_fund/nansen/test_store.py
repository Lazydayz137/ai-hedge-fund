"""The store's promises: nothing overwrites, and nothing reads from the future."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from hedge_fund import paths
from hedge_fund.nansen.client import (
    PROFILER_ADDRESS_LABELS,
    SMART_MONEY_HOLDINGS,
)
from hedge_fund.nansen.store import (
    CorruptSnapshot,
    Snapshot,
    read_as_of,
    write_snapshot,
)

MONDAY = datetime(2026, 9, 14, 0, 17, tzinfo=timezone.utc)

# Hand-written to the schema documented at docs.nansen.ai — a "data" list
# beside a "pagination" object carrying is_last_page. Not captured traffic.
PAGE = {
    "data": [
        {
            "chain": "ethereum",
            "token_address": "0x0000000000000000000000000000000000000001",
            "token_symbol": "WETH",
            "value_usd": 1500000,
            "holders_count": 342,
        }
    ],
    "pagination": {"page": 1, "per_page": 1000, "is_last_page": True},
}


def _snapshot(observed_at, *, endpoint=SMART_MONEY_HOLDINGS, params=None):
    return Snapshot(
        endpoint=endpoint,
        params=params if params is not None else {"chains": ["ethereum"]},
        observed_at=observed_at,
        pages=[PAGE],
        complete=True,
    )


def test_a_snapshot_never_overwrites_another():
    first = write_snapshot(_snapshot(MONDAY))
    second = write_snapshot(_snapshot(MONDAY))
    assert first != second
    assert first.exists() and second.exists()


def test_read_as_of_returns_none_before_the_first_snapshot():
    write_snapshot(_snapshot(MONDAY))
    assert read_as_of(SMART_MONEY_HOLDINGS, MONDAY - timedelta(days=1)) is None


def test_read_as_of_returns_none_when_nothing_was_ever_collected():
    assert read_as_of(SMART_MONEY_HOLDINGS, MONDAY) is None


def test_read_as_of_never_returns_a_snapshot_from_the_future_of_when():
    write_snapshot(_snapshot(MONDAY))
    write_snapshot(_snapshot(MONDAY + timedelta(days=7)))
    found = read_as_of(SMART_MONEY_HOLDINGS, MONDAY + timedelta(days=3))
    assert found is not None
    assert found.observed_at == MONDAY


def test_read_as_of_takes_the_newest_snapshot_at_or_before_when():
    for day in range(4):
        write_snapshot(_snapshot(MONDAY + timedelta(days=day)))
    found = read_as_of(SMART_MONEY_HOLDINGS, MONDAY + timedelta(days=2, hours=5))
    assert found.observed_at == MONDAY + timedelta(days=2)


def test_a_snapshot_observed_exactly_at_when_counts():
    write_snapshot(_snapshot(MONDAY))
    assert read_as_of(SMART_MONEY_HOLDINGS, MONDAY).observed_at == MONDAY


def test_a_naive_when_is_read_as_utc():
    write_snapshot(_snapshot(MONDAY))
    naive = MONDAY.replace(tzinfo=None) + timedelta(hours=1)
    assert read_as_of(SMART_MONEY_HOLDINGS, naive) is not None


def test_ordering_comes_from_the_record_not_the_filename():
    """A renamed file keeps the observation time it was written with."""
    old = write_snapshot(_snapshot(MONDAY))
    write_snapshot(_snapshot(MONDAY + timedelta(days=1)))
    old.rename(old.with_name("2099-01-01T000000Z.json"))
    found = read_as_of(SMART_MONEY_HOLDINGS, MONDAY + timedelta(days=2))
    assert found.observed_at == MONDAY + timedelta(days=1)


def test_ordering_comes_from_the_record_not_the_mtime():
    """A backup restore touches every mtime; it must not reorder history."""
    old = write_snapshot(_snapshot(MONDAY))
    write_snapshot(_snapshot(MONDAY + timedelta(days=1)))
    future = (MONDAY + timedelta(days=365)).timestamp()
    os.utime(old, (future, future))
    found = read_as_of(SMART_MONEY_HOLDINGS, MONDAY + timedelta(days=2))
    assert found.observed_at == MONDAY + timedelta(days=1)


def test_one_addresss_labels_never_answer_for_another():
    alice = {"address": "0xaaa", "chain": "ethereum"}
    bob = {"address": "0xbbb", "chain": "ethereum"}
    write_snapshot(
        _snapshot(MONDAY, endpoint=PROFILER_ADDRESS_LABELS, params=alice)
    )
    write_snapshot(
        _snapshot(
            MONDAY + timedelta(days=1),
            endpoint=PROFILER_ADDRESS_LABELS,
            params=bob,
        )
    )
    found = read_as_of(
        PROFILER_ADDRESS_LABELS, MONDAY + timedelta(days=2), params=alice
    )
    assert found.params == alice
    assert found.observed_at == MONDAY


def test_a_corrupt_snapshot_raises_rather_than_silently_aging_the_answer():
    write_snapshot(_snapshot(MONDAY))
    newer = write_snapshot(_snapshot(MONDAY + timedelta(days=1)))
    newer.write_text('{"endpoint": "truncated')
    with pytest.raises(CorruptSnapshot):
        read_as_of(SMART_MONEY_HOLDINGS, MONDAY + timedelta(days=2))


def test_two_endpoints_do_not_share_a_directory():
    write_snapshot(_snapshot(MONDAY))
    write_snapshot(
        _snapshot(
            MONDAY + timedelta(days=1),
            endpoint=PROFILER_ADDRESS_LABELS,
            params={"address": "0xaaa", "chain": "ethereum"},
        )
    )
    found = read_as_of(SMART_MONEY_HOLDINGS, MONDAY + timedelta(days=2))
    assert found.endpoint == SMART_MONEY_HOLDINGS


def test_snapshots_land_under_the_isolated_archive_dir():
    path = write_snapshot(_snapshot(MONDAY))
    assert paths.NANSEN_DIR in path.parents
