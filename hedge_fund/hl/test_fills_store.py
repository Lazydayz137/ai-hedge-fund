"""fills_store.py tests -- exclusive-creation writes, no-op/restate hash
logic, and the CSV row reader. All from a canned fixture, no network."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import lz4.frame
import pytest

from hedge_fund.hl.fills_store import RestatedFile, read_rows, save_raw

DAY = date(2026, 9, 18)
FETCHED_AT = datetime(2026, 9, 19, 0, 5, 0, tzinfo=timezone.utc)
FIXTURE = (Path(__file__).parent / "fixtures" / "builder_fill_sample.csv.lz4").read_bytes()
BUILDER = "0xB838E4D1C8BCF71FA8E63299D5AA3258C83D6ADB"  # mixed case on purpose

_HEADER = "time,user,coin,side,px,sz,crossed,special_trade_type,tif,is_trigger,counterparty,closed_pnl,twap_id,builder_fee"
_RESTATED_ROW = "2026-09-18T00:07:01Z,0xc0defd9e51413174652fa4369bc05296a819c7c0,HYPE,Ask,85.999,9.99,true,Na,Ioc,false,0x727956612a8700627451204a3ae26268bd1a1525,9.99,0,0.99"
RESTATED_BODY = lz4.frame.compress(f"{_HEADER}\n{_RESTATED_ROW}\n".encode("utf-8"))


def test_save_writes_data_and_sidecar():
    path = save_raw(BUILDER, DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)
    assert path is not None
    assert path.name == "20260918.csv.lz4"
    assert path.exists()
    sidecar = path.with_name(path.name + ".json")
    assert sidecar.exists()
    assert "b838e4d1c8bcf71fa8e63299d5aa3258c83d6adb" in str(path)  # lower-cased dir


def test_save_is_case_insensitive_on_builder():
    lower = save_raw(BUILDER.lower(), DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)
    again = save_raw(BUILDER.upper(), DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)
    assert lower is not None
    assert again is None  # same content under the same lower-cased builder: no-op


def test_refetch_same_hash_is_a_noop():
    first = save_raw(BUILDER, DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)
    second = save_raw(BUILDER, DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)
    assert first is not None
    assert second is None
    # only one data file on disk, not a silent duplicate
    assert len(list(first.parent.glob("20260918*.csv.lz4"))) == 1


def test_different_hash_same_date_creates_new_version_and_raises_loudly():
    save_raw(BUILDER, DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)
    with pytest.raises(RestatedFile) as exc_info:
        save_raw(BUILDER, DAY, body=RESTATED_BODY, http_status=200, fetched_at=FETCHED_AT)

    new_path = exc_info.value.path
    assert new_path.name == "20260918-v2.csv.lz4"
    assert new_path.exists()
    # the original file is untouched, not overwritten
    original = new_path.parent / "20260918.csv.lz4"
    assert original.read_bytes() == FIXTURE


def test_unarchived_date_reads_as_empty():
    # save_raw is only ever called with a real body; a failed fetch (see
    # fills_collect.py) never calls it at all, so nothing lands on disk.
    assert not list(read_rows(BUILDER, DAY))


def test_read_rows_parses_fixture_csv():
    save_raw(BUILDER, DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)
    rows = list(read_rows(BUILDER, DAY))
    assert len(rows) == 2
    assert rows[0].coin == "HYPE"
    assert rows[0].side == "Ask"
    assert rows[0].crossed is True
    assert rows[0].closed_pnl == 1.11852
    assert rows[0].twap_id == 0
    assert rows[1].coin == "BTC"
    assert rows[1].crossed is False
    assert rows[1].twap_id == 5


def test_read_rows_reads_latest_version_by_default():
    save_raw(BUILDER, DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)
    try:
        save_raw(BUILDER, DAY, body=RESTATED_BODY, http_status=200, fetched_at=FETCHED_AT)
    except RestatedFile:
        pass

    latest = list(read_rows(BUILDER, DAY))
    original = list(read_rows(BUILDER, DAY, version=1))
    assert len(latest) == 1 and latest[0].px == 85.999  # the restated content
    assert len(original) == 2 and original[0].px == 85.586  # the original content, untouched


def test_reversion_to_an_older_hash_is_a_new_restatement_not_a_noop():
    """A -> B -> A: the third fetch's hash matches an OLDER archived
    version (v1), not the latest (v2). It must be recorded as a new
    restatement, not silently treated as unchanged just because some past
    version happens to match."""
    save_raw(BUILDER, DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)  # A -> v1
    try:
        save_raw(BUILDER, DAY, body=RESTATED_BODY, http_status=200, fetched_at=FETCHED_AT)  # B -> v2
    except RestatedFile:
        pass

    with pytest.raises(RestatedFile) as exc_info:
        save_raw(BUILDER, DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)  # A again -> v3

    new_path = exc_info.value.path
    assert new_path.name == "20260918-v3.csv.lz4"
    latest = list(read_rows(BUILDER, DAY))
    assert latest[0].px == 85.586  # back to A's content, not stuck reporting B


def test_orphaned_sidecar_without_data_is_reclaimed_not_wedged():
    """A crash between reserving a version slot (sidecar written) and
    publishing its data file leaves a sidecar with no matching data file.
    The next save targeting that same slot must reclaim it, not raise or
    leave the pass permanently stuck on a dead reservation."""
    first = save_raw(BUILDER, DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)
    orphan_sidecar = first.parent / "20260918-v2.csv.lz4.json"
    orphan_sidecar.write_text("{}", encoding="utf-8")  # crash artifact, no data file

    with pytest.raises(RestatedFile) as exc_info:
        save_raw(BUILDER, DAY, body=RESTATED_BODY, http_status=200, fetched_at=FETCHED_AT)

    new_path = exc_info.value.path
    assert new_path.name == "20260918-v2.csv.lz4"
    assert new_path.exists()
    assert new_path.with_name(new_path.name + ".json").read_text(encoding="utf-8") != "{}"
