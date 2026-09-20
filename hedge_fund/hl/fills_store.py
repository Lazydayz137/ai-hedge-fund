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
    """Every archived data file for this (builder, day), oldest first."""
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


def save_raw(
    builder: str, day: date, *, body: bytes, http_status: int, fetched_at: datetime,
) -> Path | None:
    """Archive one fetch's raw bytes.

    Returns the path written, or None if this exact content is already
    archived (no-op). Raises RestatedFile -- after writing the new
    version -- if *day* was already archived under a different hash.
    """
    builder = builder.lower()
    sha256 = hashlib.sha256(body).hexdigest()
    existing = _versions(builder, day)

    latest_sidecar = None
    for path in existing:
        sidecar = _load_sidecar(path)
        if sidecar is None:
            continue
        if sidecar.sha256 == sha256:
            return None  # identical content already archived: no-op
        latest_sidecar = sidecar

    directory = _builder_dir(builder)
    directory.mkdir(parents=True, exist_ok=True)
    stem = day.strftime("%Y%m%d")
    data_path = (
        directory / f"{stem}.csv.lz4" if not existing
        else directory / f"{stem}-v{len(existing) + 1}.csv.lz4"
    )

    # Exclusive creation: never overwrite an existing snapshot of this file.
    with data_path.open("xb") as handle:
        handle.write(body)

    sidecar = BuilderFillSidecar(
        builder=builder, date=day.isoformat(), fetched_at=fetched_at,
        byte_length=len(body), sha256=sha256, http_status=http_status,
    )
    _sidecar_path(data_path).write_text(sidecar.model_dump_json(indent=2), encoding="utf-8")

    if latest_sidecar is not None:
        raise RestatedFile(data_path, latest_sidecar)
    return data_path


def read_rows(builder: str, day: date, *, version: int | None = None):
    """Yield parsed BuilderFillRow rows for one archived (builder, day) file.

    Reads the LATEST version by default (the most recent restatement);
    pass *version* (1-based, matching the on-disk numbering) to read an
    earlier one instead. Yields nothing if the date was never archived.
    """
    versions = _versions(builder.lower(), day)
    if not versions:
        return
    data_path = versions[version - 1] if version else versions[-1]
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
