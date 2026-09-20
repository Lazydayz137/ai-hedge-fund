"""The archive's promises: nothing overwrites, nothing reads from the future."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hedge_fund import paths
from hedge_fund.fomo.models import CollectionResult, Cursor, SponsoredTx
from hedge_fund.fomo.store import (
    CorruptCursor,
    read_as_of,
    read_cursor,
    save_pass,
    write_cursor,
)

NOON = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _result(observed_at, *, signature="sig-a"):
    return CollectionResult(
        started_at=observed_at - timedelta(seconds=5),
        observed_at=observed_at,
        newest_signature=signature,
        until_signature=None,
        reached_cursor=True,
        transactions=[SponsoredTx(
            signature=signature, slot=1, block_time=observed_at, user="U1",
            signers=["S", "U1"], fee_lamports=410000, programs=["P"], failed=False,
        )],
        errors=[],
    )


def test_a_pass_never_overwrites_another():
    first = save_pass(_result(NOON, signature="a"))
    second = save_pass(_result(NOON, signature="b"))
    assert first != second
    assert first.exists() and second.exists()


def test_read_as_of_never_returns_a_pass_from_the_future_of_when():
    save_pass(_result(NOON))
    assert read_as_of(NOON - timedelta(seconds=1)) is None
    assert read_as_of(NOON) is not None


def test_read_as_of_takes_the_newest_pass_at_or_before_when():
    save_pass(_result(NOON - timedelta(hours=2), signature="old"))
    save_pass(_result(NOON, signature="new"))
    assert read_as_of(NOON).newest_signature == "new"
    assert read_as_of(NOON - timedelta(hours=1)).newest_signature == "old"


def test_an_unreadable_pass_does_not_hide_a_readable_older_one():
    save_pass(_result(NOON - timedelta(hours=1), signature="good"))
    broken = save_pass(_result(NOON, signature="bad"))
    broken.write_text("{ not json", encoding="utf-8")
    assert read_as_of(NOON).newest_signature == "good"


def test_a_corrupt_cursor_raises_rather_than_restarting_silently():
    """Resuming from the newest signature instead would leave a hole in the
    middle of the archive and report success."""
    write_cursor(Cursor(signature="a", slot=1, recorded_at=NOON))
    (paths.ARCHIVE_DIR / "fomo" / "cursor.json").write_text("{ no", encoding="utf-8")
    with pytest.raises(CorruptCursor):
        read_cursor()


def test_the_cursor_is_the_one_file_here_that_moves():
    write_cursor(Cursor(signature="a", slot=1, recorded_at=NOON))
    write_cursor(Cursor(signature="b", slot=2, recorded_at=NOON))
    assert read_cursor().signature == "b"
    assert len(list((paths.ARCHIVE_DIR / "fomo").glob("cursor*.json"))) == 1


def test_no_cursor_reads_as_never_collected():
    assert read_cursor() is None
