"""fills_store.py tests -- exclusive-creation writes, no-op/restate hash
logic, and the CSV row reader. All from a canned fixture, no network."""

from __future__ import annotations

import hashlib
import json
import uuid
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


def test_orphaned_sidecar_without_data_burns_the_slot_not_wedged():
    """A crash between reserving a version slot (sidecar written) and
    publishing its data file leaves a sidecar with no matching data file.
    That slot is NEVER reclaimed -- reclaiming it is indistinguishable
    from stealing a reservation a live writer still holds, which is the
    corruption this fix closes. The next save must skip the burned slot
    (not wedge, not raise) and write into the next free one, and the
    latest-version/hash comparison must still find the true latest data,
    not the burned gap."""
    first = save_raw(BUILDER, DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)
    orphan_sidecar = first.parent / "20260918-v2.csv.lz4.json"
    orphan_sidecar.write_text("{}", encoding="utf-8")  # crash artifact, no data file

    with pytest.raises(RestatedFile) as exc_info:
        save_raw(BUILDER, DAY, body=RESTATED_BODY, http_status=200, fetched_at=FETCHED_AT)

    new_path = exc_info.value.path
    assert new_path.name == "20260918-v3.csv.lz4"  # v2 is burned forever, not reused
    assert new_path.exists()
    # the burned slot's sidecar is untouched, still there, still invalid --
    # it is not silently repaired or removed by a later writer
    assert orphan_sidecar.read_text(encoding="utf-8") == "{}"
    # the dedupe/"latest" comparison skips the burned gap and reads v1,
    # then correctly treats the new body as a restatement of it
    latest = list(read_rows(BUILDER, DAY))
    assert latest[0].px == 85.999  # the restated content, published as v3
    original = list(read_rows(BUILDER, DAY, version=1))
    assert original[0].px == 85.586  # v1 untouched
    # the burned slot really has no data to read
    assert list(read_rows(BUILDER, DAY, version=2)) == []


def test_two_live_writers_racing_the_same_reservation_both_survive(monkeypatch):
    """Reproduces the exact interleaving from the bug report: writer A
    exclusively creates v2's sidecar (reserving the slot) but has not yet
    written its data file when writer B shows up wanting a slot too. On
    the pre-fix code, B would see A's sidecar, find no data file yet,
    conclude "crash orphan", unlink A's live reservation, take v2 for
    itself, and publish -- then A would finish and its publish would
    silently clobber B's, leaving v2's sidecar hash mismatched against its
    bytes and telling B's caller a version was saved that no longer
    exists. On the fixed code A's reservation is never stolen: B lands on
    the next free slot instead, and both writers' content survives with a
    correct sidecar for each.

    The interleaving is driven deterministically: uuid.uuid4() is called
    by save_raw only once A's sidecar for v2 has been created on disk and
    only right before A writes its data file -- exactly the window the
    bug report describes -- so hooking it lets writer B's full save_raw
    call run synchronously inside that window."""
    v1_path = save_raw(BUILDER, DAY, body=FIXTURE, http_status=200, fetched_at=FETCHED_AT)

    _WRITER_A_ROW = (
        "2026-09-18T00:09:03Z,0xd0eeffa051413174652fa4369bc05296a819c7c0,ETH,Bid,"
        "3200.5,1.5,false,Na,Gtc,false,0x827956612a8700627451204a3ae26268bd1a1526,0.0,0,0.5"
    )
    writer_a_body = lz4.frame.compress(f"{_HEADER}\n{_WRITER_A_ROW}\n".encode("utf-8"))

    real_uuid4 = uuid.uuid4
    state = {"fired": False, "writer_b_path": None}

    def fake_uuid4():
        if not state["fired"]:
            state["fired"] = True
            # Writer A's v2 sidecar reservation exists on disk right now,
            # but A has not written v2's data file yet. Writer B collides
            # on the same (builder, day) here.
            with pytest.raises(RestatedFile) as exc_info:
                save_raw(BUILDER, DAY, body=RESTATED_BODY, http_status=200, fetched_at=FETCHED_AT)
            state["writer_b_path"] = exc_info.value.path
        return real_uuid4()

    monkeypatch.setattr("hedge_fund.hl.fills_store.uuid.uuid4", fake_uuid4)

    with pytest.raises(RestatedFile) as exc_info:
        save_raw(BUILDER, DAY, body=writer_a_body, http_status=200, fetched_at=FETCHED_AT)  # writer A
    writer_a_path = exc_info.value.path

    # Neither writer stole the other's slot.
    assert writer_a_path.name == "20260918-v2.csv.lz4"
    assert state["writer_b_path"].name == "20260918-v3.csv.lz4"

    # Every visible version's sidecar hash matches its own data bytes --
    # no cross-writer clobbering happened.
    for path, body in (
        (v1_path, FIXTURE),
        (writer_a_path, writer_a_body),
        (state["writer_b_path"], RESTATED_BODY),
    ):
        sidecar = json.loads(path.with_name(path.name + ".json").read_text(encoding="utf-8"))
        assert sidecar["sha256"] == hashlib.sha256(body).hexdigest()
        assert path.read_bytes() == body

    # Both writers' content survives -- nothing was silently lost.
    assert list(read_rows(BUILDER, DAY, version=2))[0].coin == "ETH"
    assert list(read_rows(BUILDER, DAY, version=3))[0].px == 85.999
