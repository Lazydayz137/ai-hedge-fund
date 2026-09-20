"""Immutable label snapshots — what Nansen said, and when it said it.

Nansen's smart-money endpoints resolve against a set that is continuously
recomputed, and their docs warn that historical snapshots may change after
label-history corrections. A wallet is on today's list *because* it made money
recently, so backtesting "follow smart money" against today's list measures
survivorship and calls it edge. The only fix is to write the list down as it
was observed and never let a simulated date see a list from its own future.

Three rules carry that, and nothing else here matters:

  * A snapshot is serialized to a temporary file and only then published
    under its final name, with a link that refuses to overwrite. A snapshot
    that can be overwritten is one that can be silently revised, and one
    published before it was finished is one that can be silently truncated.
  * read_as_of takes observed_at out of the record. Not the filename, which is
    a convenience for humans with `ls`, and not the mtime, which a copy, an
    rsync or a backup restore will happily rewrite.
  * A snapshot that could not be fetched to its last page says so. Padding a
    truncated list up to a plausible length is the same class of lie as
    inventing rows.

Textual-free and import-light like paths.py: a backtest reads these, a cron
job writes them, and neither may reach into a UI.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from hedge_fund import paths

# Bumped when the shape of what gets written changes, so a reader can tell a
# record written by an older collector from one it can trust verbatim.
COLLECTOR_VERSION = "1"


class CorruptSnapshot(ValueError):
    """A file under the snapshot store did not parse as a Snapshot.

    Raised, not skipped. The ledger skips an unreadable run receipt because
    the cost is one lost resume; here the cost is a backtest quietly reading
    an older label set and reporting a number nobody can reproduce. A damaged
    immutable record is a human's problem to look at and delete.
    """


class Snapshot(BaseModel):
    """One observation of one endpoint.

    ``observed_at`` is the machine clock in UTC at the moment the LAST page
    arrived, recorded here explicitly — never inferred from the filename or
    the file's mtime.

    The end of the fetch, not the start, and the direction matters. A paged
    fetch spans wall time: page one lands at t0, the last at t1. Stamping t0
    would make read_as_of hand a cutoff between t0 and t1 a snapshot whose
    later pages were not knowable until t1 — the exact leak this store exists
    to close, reintroduced by the store itself. Stamping t1 means every page
    in the snapshot was already public at the time the snapshot claims.

    ``params`` is the request body as the caller asked for it, with pagination
    left out — pagination is transport, it differs per page, and two runs that
    asked the same question must compare equal.
    """

    endpoint: str
    params: dict[str, Any]
    observed_at: datetime
    collector_version: str = COLLECTOR_VERSION
    pages: list[Any]
    complete: bool
    note: str | None = None


def _directory(endpoint: str) -> Path:
    """Where one endpoint's snapshots live, one directory per endpoint."""
    # Looked up through the module, not bound at import: tests redirect it,
    # and nothing should be able to write into a real archive by accident.
    # "/" becomes "__" so that /a/b-c and /a-b/c cannot share a directory.
    return paths.NANSEN_DIR / endpoint.strip("/").replace("/", "__")


def write_snapshot(snapshot: Snapshot) -> Path:
    """Write *snapshot* where nothing can overwrite it, and say where.

    Serialized in full to a temporary file first, then published under its
    real name. Creating the final path up front and writing into it leaves a
    half-written file at that name if anything interrupts the write — and
    read_as_of parses every .json it finds, so one truncated file would raise
    CorruptSnapshot for every later read. A later round cannot repair it
    either: the occupied name pushes that round onto a suffix, and the broken
    file stays. A round that dies mid-write must cost its own snapshot and
    nothing else.
    """
    directory = _directory(snapshot.endpoint)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = snapshot.observed_at.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H%M%SZ"
    )

    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as writer:
            writer.write(snapshot.model_dump_json(indent=2))

        path = directory / f"{stamp}.json"
        suffix = 1
        while True:
            try:
                # os.link, not rename or replace: both of those overwrite
                # silently on POSIX, and this archive's one promise is that
                # they cannot. link fails with FileExistsError instead, which
                # is how two collectors racing inside the same second both
                # keep their observation rather than one erasing the other.
                os.link(temporary, path)
                return path
            except FileExistsError:
                suffix += 1
                path = directory / f"{stamp}-{suffix}.json"
    finally:
        # The temporary is never the archive, published or not: on success it
        # is a second link to the same bytes, on failure it is a fragment.
        with suppress(OSError):
            os.unlink(temporary)


def read_as_of(
    endpoint: str,
    when: datetime,
    *,
    params: dict[str, Any] | None = None,
) -> Snapshot | None:
    """The newest snapshot of *endpoint* observed at or before *when*.

    None when nothing was observed that early. That is the honest answer for a
    date before collection started, and the reason this returns an Optional
    rather than falling back to the nearest snapshot it can find: falling
    forward is exactly the leak the store exists to close.

    *params* narrows the match to snapshots that asked the same question,
    which the per-address endpoints need — one address's labels must never
    answer for another's. Left None it matches any.

    A naive *when* is read as UTC; every observed_at written here is.
    """
    cutoff = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    directory = _directory(endpoint)
    if not directory.is_dir():
        return None

    newest: Snapshot | None = None
    for path in directory.glob("*.json"):
        try:
            snapshot = Snapshot.model_validate_json(path.read_text())
        except (OSError, ValueError) as exc:
            raise CorruptSnapshot(f"{path} did not parse: {exc}") from exc
        if snapshot.endpoint != endpoint:
            continue
        if params is not None and snapshot.params != params:
            continue
        if snapshot.observed_at > cutoff:
            continue
        if newest is None or snapshot.observed_at > newest.observed_at:
            newest = snapshot
    return newest
