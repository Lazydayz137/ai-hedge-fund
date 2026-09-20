"""Immutable label snapshots — what Nansen said, and when it said it.

Nansen's smart-money endpoints resolve against a set that is continuously
recomputed, and their docs warn that historical snapshots may change after
label-history corrections. A wallet is on today's list *because* it made money
recently, so backtesting "follow smart money" against today's list measures
survivorship and calls it edge. The only fix is to write the list down as it
was observed and never let a simulated date see a list from its own future.

Three rules carry that, and nothing else here matters:

  * Snapshots are written with open(..., "x"). A snapshot that can be
    overwritten is a snapshot that can be silently revised.
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

    ``observed_at`` is the machine clock in UTC at the moment the first
    request went out, recorded here explicitly — never inferred from the
    filename or the file's mtime. A paged fetch spans a little wall time, so
    the start of the observation is the conservative end to record: an as-of
    read can then never hand a simulated date something learned after it.

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
    # Looked up through the module, not bound at import: tests redirect it,
    # and nothing should be able to write into a real archive by accident.
    # "/" becomes "__" so that /a/b-c and /a-b/c cannot share a directory.
    return paths.NANSEN_DIR / endpoint.strip("/").replace("/", "__")


def write_snapshot(snapshot: Snapshot) -> Path:
    """Write *snapshot* where nothing can overwrite it, and say where."""
    directory = _directory(snapshot.endpoint)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = snapshot.observed_at.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H%M%SZ"
    )
    path = directory / f"{stamp}.json"
    suffix = 1
    while True:
        try:
            # "x" rather than checking exists() first: two collectors racing
            # inside one second are both real observations, and the
            # check-then-write version silently drops one of them.
            with open(path, "x") as handle:
                handle.write(snapshot.model_dump_json(indent=2))
            return path
        except FileExistsError:
            suffix += 1
            path = directory / f"{stamp}-{suffix}.json"


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
