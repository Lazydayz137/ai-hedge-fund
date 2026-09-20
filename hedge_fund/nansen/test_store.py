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


def test_a_write_that_dies_midway_leaves_no_file_behind(monkeypatch):
    """A round that dies mid-write must cost its own snapshot and nothing else.

    Publishing the final name before the bytes are complete would strand a
    truncated file there, and read_as_of parses every .json it finds — so one
    interrupted round would raise CorruptSnapshot for every later read, and no
    later round could repair it because the occupied name pushes it to a
    suffix.
    """
    snapshot = _snapshot(MONDAY)
    real = Snapshot.model_dump_json
    failed_once = False

    def explode_once(self, **kwargs):
        # One-shot rather than monkeypatch.undo(): the autouse fixture that
        # redirects the archive shares this test's monkeypatch instance, so
        # undo() would put NANSEN_DIR back to the user's real archive and the
        # write below would land in it. A test for not corrupting the archive
        # must not be the thing that writes to it.
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError("connection reset mid-serialization")
        return real(self, **kwargs)

    monkeypatch.setattr(Snapshot, "model_dump_json", explode_once)
    with pytest.raises(RuntimeError):
        write_snapshot(snapshot)

    directory = paths.NANSEN_DIR / SMART_MONEY_HOLDINGS.strip("/").replace("/", "__")
    assert list(directory.glob("*")) == []

    # And the archive is still usable afterwards.
    write_snapshot(snapshot)
    assert read_as_of(SMART_MONEY_HOLDINGS, MONDAY) is not None


def test_the_bytes_are_on_disk_before_the_name_appears(monkeypatch):
    """Ordering, not just presence: fsync of the file must precede the link.

    Reversed, a host that lost power between them would leave a published
    name pointing at bytes that never landed — a snapshot the collector
    already reported as written, and which cannot be refetched.
    """
    order: list[str] = []
    real_fsync, real_link = os.fsync, os.link

    monkeypatch.setattr(os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(os, "link", lambda src, dst: (order.append("link"), real_link(src, dst))[1])

    write_snapshot(_snapshot(MONDAY))

    assert order[0] == "fsync", order
    assert "link" in order
    assert order.index("fsync") < order.index("link")


def test_a_platform_that_will_not_sync_a_directory_still_publishes(monkeypatch):
    """Windows cannot open a directory read-only. Losing the durability
    guarantee there is honest; losing the snapshot would not be."""
    real_open = os.open

    def refuse_directories(path, flags, *args, **kwargs):
        if os.path.isdir(path):
            raise PermissionError("directories are not openable here")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", refuse_directories)

    path = write_snapshot(_snapshot(MONDAY))
    assert path.exists()
    assert read_as_of(SMART_MONEY_HOLDINGS, MONDAY) is not None
