"""One fetch of a single builder's daily fill file: download, hash, archive.

Real data only -- a failed download writes no data file, and a restated
day (same date, new hash) is surfaced loudly rather than merged silently
into the existing version.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from hedge_fund.hl.fills_client import FillDownloadError, fetch_raw
from hedge_fund.hl.fills_store import RestatedFile, save_raw
from hedge_fund.hl.models import FillFetchResult


def collect_fills(builder: str, day: date) -> FillFetchResult:
    """Fetch and archive one (builder, day). Never raises -- every outcome,
    including a failed fetch, comes back as a FillFetchResult for the
    caller to report.
    """
    fetched_at = datetime.now(timezone.utc)
    try:
        status, body = fetch_raw(builder, day)
    except FillDownloadError as exc:
        return FillFetchResult(builder=builder, date=day.isoformat(), status="failed", detail=str(exc))

    if status != 200:
        return FillFetchResult(
            builder=builder, date=day.isoformat(), status="failed",
            detail=f"HTTP {status}",
        )

    try:
        path = save_raw(builder, day, body=body, http_status=status, fetched_at=fetched_at)
    except RestatedFile as restated:
        return FillFetchResult(
            builder=builder, date=day.isoformat(), status="restated",
            path=str(restated.path), detail=str(restated),
        )

    if path is None:
        return FillFetchResult(builder=builder, date=day.isoformat(), status="unchanged")

    return FillFetchResult(builder=builder, date=day.isoformat(), status="new", path=str(path))
