"""Archive for Hyperliquid's per-builder daily fill files.

Stores the ORIGINAL compressed bytes exactly as served -- exclusive
creation, never overwritten, mirroring store.py's discipline for market
snapshots. A date already archived with an identical hash is a no-op; a
DIFFERENT hash for an already-archived date is a genuine restatement and
gets a new version beside the old one, never a silent replace.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import uuid
from datetime import date, datetime
from pathlib import Path

import lz4.frame

from hedge_fund import paths
from hedge_fund.hl.models import BuilderFillRow, BuilderFillSidecar


def _builder_dir(builder: str) -> Path:
    # Looked up through the module on every call, not bound at import --
    # tests monkeypatch paths.ARCHIVE_DIR (see store.py for why).
    return paths.ARCHIVE_DIR / "hyperliquid" / "builder_fills" / builder.lower()


def _sidecar_path(data_path: Path) -> Path:
    return data_path.with_name(data_path.name + ".json")


def _versions(builder: str, day: date) -> list[Path]:
    """Every PUBLISHED data file for this (builder, day), oldest first.

    A reserved-but-never-published (burned) slot has a sidecar but no data
    file, so it never shows up here -- this globs actual .csv.lz4 files,
    which means gaps left by burned slots are simply skipped rather than
    needing special handling by any reader.
    """
    directory = _builder_dir(builder)
    if not directory.exists():
        return []
    stem = day.strftime("%Y%m%d")
    exact = directory / f"{stem}.csv.lz4"
    numbered = sorted(
        directory.glob(f"{stem}-v*.csv.lz4"),
        key=lambda p: int(p.name.removeprefix(f"{stem}-v").split(".")[0]),
    )
    return ([exact] if exact.exists() else []) + numbered


def _reserved_slots(directory: Path, stem: str) -> set[int]:
    """Every slot number with a sidecar on disk, published or burned.

    Used to pick the next free slot without ever choosing one another
    writer -- live or crashed -- has already reserved.
    """
    if not directory.exists():
        return set()
    slots = {1} if (directory / f"{stem}.csv.lz4.json").exists() else set()
    for sidecar in directory.glob(f"{stem}-v*.csv.lz4.json"):
        slots.add(int(sidecar.name.removeprefix(f"{stem}-v").split(".")[0]))
    return slots


def _data_path(directory: Path, stem: str, index: int) -> Path:
    return directory / f"{stem}.csv.lz4" if index == 1 else directory / f"{stem}-v{index}.csv.lz4"


def _slot_number(data_path: Path) -> int:
    """The on-disk version number a data path was published under."""
    stem = data_path.name.removesuffix(".csv.lz4")
    return int(stem.rsplit("-v", 1)[1]) if "-v" in stem else 1


def _load_sidecar(data_path: Path) -> BuilderFillSidecar | None:
    try:
        return BuilderFillSidecar.model_validate_json(
            _sidecar_path(data_path).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None


class RestatedFile(Exception):
    """Raised after saving a date that was already archived under a
    different hash. The new version IS saved by the time this raises --
    it exists to make the caller surface the restatement loudly rather
    than let it pass as a quiet background write.
    """

    def __init__(self, path: Path, previous: BuilderFillSidecar) -> None:
        super().__init__(f"{path} restates {previous.date} for {previous.builder} (hash changed)")
        self.path = path
        self.previous = previous


_MAX_VERSION_ATTEMPTS = 8


def save_raw(
    builder: str, day: date, *, body: bytes, http_status: int, fetched_at: datetime,
) -> Path | None:
    """Archive one fetch's raw bytes.

    Returns the path written, or None if this exact content matches the
    LATEST archived version already (no-op) -- a hash that only matches an
    OLDER, superseded version is a genuine restatement, not a no-op (an
    A -> B -> A sequence must record the second A, not silently agree with
    the first). Raises RestatedFile -- after writing the new version -- if
    *day* was already archived under a different hash than its latest.

    Concurrency-safe for any number of writers racing the same (builder,
    day). A version slot is claimed by exclusively creating its sidecar,
    and once claimed a slot is NEVER reclaimed -- not even when it turns
    out later to be a crash orphan (a sidecar with no data file). A live
    writer mid-publish and a writer that crashed right after reserving
    look identical on disk, so guessing which one it is would be the
    corruption this closes: reclaiming a live writer's slot lets a second
    writer publish into it, and the first writer's own publish then lands
    on top of the second writer's file. Instead a burned slot's number is
    skipped forever and writers move on to the next free one -- a crash
    costs a version number, never correctness or a wedged future write.
    Publishing the data file itself uses a hard link (os.link), which
    fails rather than overwriting if the destination already exists, so a
    slot's data can only ever be written once, by whoever reserved it.
    """
    builder = builder.lower()
    sha256 = hashlib.sha256(body).hexdigest()
    directory = _builder_dir(builder)
    directory.mkdir(parents=True, exist_ok=True)
    stem = day.strftime("%Y%m%d")

    for _ in range(_MAX_VERSION_ATTEMPTS):
        existing = _versions(builder, day)
        latest_sidecar = _load_sidecar(existing[-1]) if existing else None
        if latest_sidecar is not None and latest_sidecar.sha256 == sha256:
            return None  # unchanged from the latest archived version: no-op

        reserved = _reserved_slots(directory, stem)
        index = 1
        while index in reserved:
            index += 1
        data_path = _data_path(directory, stem, index)
        sidecar_path = _sidecar_path(data_path)
        sidecar = BuilderFillSidecar(
            builder=builder, date=day.isoformat(), fetched_at=fetched_at,
            byte_length=len(body), sha256=sha256, http_status=http_status,
        )

        try:
            with sidecar_path.open("x", encoding="utf-8") as handle:
                handle.write(sidecar.model_dump_json(indent=2))
        except FileExistsError:
            # Someone else claimed this exact slot between our scan and
            # our attempt (a genuine race, not a reclaim candidate --
            # never reclaim). Rescan and move on to the next free slot.
            continue

        tmp_path = data_path.with_name(f"{data_path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            with tmp_path.open("xb") as handle:
                handle.write(body)
            # A hard link fails with FileExistsError instead of silently
            # overwriting if data_path already exists (unlike
            # Path.replace/os.rename) -- the no-overwrite publish this
            # needs. It should never collide given the sidecar reservation
            # above; if it ever does, that's a real invariant violation,
            # not something to paper over by taking someone else's slot.
            os.link(tmp_path, data_path)
        except BaseException:
            sidecar_path.unlink(missing_ok=True)
            raise
        finally:
            tmp_path.unlink(missing_ok=True)

        if latest_sidecar is not None:
            raise RestatedFile(data_path, latest_sidecar)
        return data_path

    raise RuntimeError(
        f"could not claim a version slot for {builder} {day} after {_MAX_VERSION_ATTEMPTS} attempts"
    )


def read_rows(builder: str, day: date, *, version: int | None = None):
    """Yield parsed BuilderFillRow rows for one archived (builder, day) file.

    Reads the LATEST version by default (the most recent restatement);
    pass *version* (matching the on-disk numbering, e.g. 2 for a
    "-v2.csv.lz4" file) to read an earlier one instead. Yields nothing if
    the date was never archived, or if *version* names a slot that was
    reserved but never published (a burned crash-orphan slot).
    """
    versions = _versions(builder.lower(), day)
    if not versions:
        return
    if version is None:
        data_path = versions[-1]
    else:
        data_path = next((p for p in versions if _slot_number(p) == version), None)
        if data_path is None:
            return
    text = lz4.frame.decompress(data_path.read_bytes()).decode("utf-8")
    for row in csv.DictReader(io.StringIO(text)):
        yield BuilderFillRow(
            time=row["time"],
            user=row["user"],
            coin=row["coin"],
            side=row["side"],
            px=float(row["px"]),
            sz=float(row["sz"]),
            crossed=row["crossed"] == "true",
            special_trade_type=row["special_trade_type"],
            tif=row["tif"],
            is_trigger=row["is_trigger"] == "true",
            counterparty=row["counterparty"],
            closed_pnl=float(row["closed_pnl"]),
            twap_id=int(row["twap_id"]),
            builder_fee=float(row["builder_fee"]),
        )
