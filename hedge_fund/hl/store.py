"""The archive's write and read halves -- one file per collection pass.

Mirrors the ledger's discipline: exclusive creation (never overwrite an
existing snapshot) and a reader ordered by each snapshot's own observation
timestamp, never file mtime (a retried or clock-skewed write must still
sort by when the market was actually observed).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from hedge_fund import paths
from hedge_fund.hl.models import MarketSnapshot


def _archive_dir() -> Path:
    # Looked up through the module on every call, not bound at import: tests
    # monkeypatch paths.ARCHIVE_DIR, and a snapshot must never land in a
    # real user's history by accident just because this module cached the
    # path once at import time.
    return paths.ARCHIVE_DIR / "hyperliquid"


def save_snapshot(snapshot: MarketSnapshot) -> Path:
    """Write one pass's snapshot. Never overwrites an existing file."""
    archive_dir = _archive_dir()
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = snapshot.observed_at.strftime("%Y%m%dT%H%M%SZ")
    path = archive_dir / f"hl-{stamp}.json"
    # Exclusive creation, not exists()-then-write: two passes racing here
    # would both pass an exists() check and one would land on top of the
    # other. The stamp is second-resolution, so two passes inside the same
    # second is exactly the case this loop exists for.
    suffix = 1
    while True:
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(snapshot.model_dump_json(indent=2))
            return path
        except FileExistsError:
            suffix += 1
            path = archive_dir / f"hl-{stamp}-{suffix}.json"


def read_as_of(when: datetime) -> list[MarketSnapshot]:
    """Every snapshot recorded at or before *when*, oldest first.

    Ordered by each snapshot's own `observed_at`, never by file mtime or
    filename -- a snapshot written late (retry, clock skew) must still sort
    by when the market was actually observed. Nothing after *when* is ever
    returned, even if its file exists on disk.
    """
    archive_dir = _archive_dir()
    eligible: list[tuple[datetime, Path]] = []
    for path in archive_dir.glob("hl-*.json"):
        try:
            # Peek at the one field that decides eligibility rather than
            # fully validating every snapshot in the archive on every read.
            peek = json.loads(path.read_text(encoding="utf-8"))
            observed_at = datetime.fromisoformat(peek["observed_at"])
        except (OSError, ValueError, KeyError, TypeError):
            continue  # unreadable/corrupt file: skip it, don't fail the read
        if observed_at <= when:
            eligible.append((observed_at, path))

    eligible.sort(key=lambda pair: pair[0])
    snapshots = []
    for _, path in eligible:
        try:
            snapshots.append(MarketSnapshot.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue  # failed full parse after passing the peek: skip it
    return snapshots
