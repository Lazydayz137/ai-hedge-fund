"""One round of Nansen snapshots: ask, write down, report what failed.

The five endpoints here are what a perps strategy reads — the smart-money
holdings and perp-trades lists, the perp leaderboard, and, per address, that
address's perp positions and labels. Two of them are address-scoped, so they
are collected once per address and skipped entirely when none is given. The
address list is an input, never derived from the leaderboard snapshot: the
collector records the question it was told to ask, and a universe it picked
for itself would be one more thing to reconstruct later.

Every day this does not run is a day of point-in-time history that cannot be
rebuilt afterwards and cannot be bought from anyone. It belongs in cron.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel

from hedge_fund.nansen.client import (
    PERP_LEADERBOARD,
    PROFILER_ADDRESS_LABELS,
    PROFILER_PERP_POSITIONS,
    SMART_MONEY_HOLDINGS,
    SMART_MONEY_PERP_TRADES,
    NansenClient,
)
from hedge_fund.nansen.store import COLLECTOR_VERSION, Snapshot, write_snapshot

# The documented maximum is 1,000; a page that size keeps a daily round to a
# handful of requests, far under the 300 req/min free-plan limit.
PER_PAGE = 1000

# A cap, not a target: without one a schema change that stopped setting
# is_last_page would page forever. Hitting it marks the snapshot partial.
DEFAULT_MAX_PAGES = 20


class Attempt(BaseModel):
    """What happened to one endpoint this round.

    Exactly one of *path* and *error* is set. An attempt that errored wrote
    nothing at all — there is no half-written snapshot to find later.
    """

    endpoint: str
    params: dict[str, Any]
    path: Path | None = None
    error: str | None = None
    complete: bool = False


class Collection(BaseModel):
    started_at: datetime
    collector_version: str = COLLECTOR_VERSION
    attempts: list[Attempt]

    @property
    def failures(self) -> list[Attempt]:
        return [a for a in self.attempts if a.error is not None]

    @property
    def partial(self) -> list[Attempt]:
        return [a for a in self.attempts if a.error is None and not a.complete]


def planned_requests(
    addresses: Sequence[str] = (),
    chains: Sequence[str] = ("ethereum",),
    *,
    today: date | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """The (endpoint, body) pairs one round asks for, in order."""
    today = today or datetime.now(timezone.utc).date()
    # The leaderboard wants a date range. Yesterday, UTC: the last day that
    # had actually closed when we looked. Asking for today would return a
    # partial day whose ranking changes for hours after the snapshot is
    # written, which is the kind of record that cannot be reasoned about.
    yesterday = (today - timedelta(days=1)).isoformat()

    planned: list[tuple[str, dict[str, Any]]] = [
        (SMART_MONEY_HOLDINGS, {"chains": list(chains)}),
        (SMART_MONEY_PERP_TRADES, {}),
        (PERP_LEADERBOARD, {"date": {"from": yesterday, "to": yesterday}}),
    ]
    for address in addresses:
        planned.append((PROFILER_PERP_POSITIONS, {"address": address}))
        for chain in chains:
            planned.append(
                (PROFILER_ADDRESS_LABELS, {"address": address, "chain": chain})
            )
    return planned


def collect(
    *,
    client: NansenClient | None = None,
    addresses: Sequence[str] = (),
    chains: Sequence[str] = ("ethereum",),
    max_pages: int = DEFAULT_MAX_PAGES,
) -> Collection:
    """Fetch each endpoint once and write down what came back.

    The client is built first on purpose: NansenClient raises MissingAPIKey
    from its constructor, so a keyless run stops here having written nothing
    rather than part of a round.

    One endpoint failing does not discard the others. A snapshot that was
    fetched is a real observation, and throwing it away to make the run look
    tidy destroys point-in-time history that nobody can rebuild. The failures
    come back in the result; the CLI exits non-zero on them.
    """
    started_at = datetime.now(timezone.utc)
    owned = client is None
    client = client or NansenClient()
    try:
        attempts = []
        for endpoint, params in planned_requests(addresses, chains):
            try:
                snapshot = _fetch(client, endpoint, params, max_pages)
            except Exception as exc:
                attempts.append(
                    Attempt(endpoint=endpoint, params=params, error=str(exc))
                )
                continue
            attempts.append(
                Attempt(
                    endpoint=endpoint,
                    params=params,
                    path=write_snapshot(snapshot),
                    complete=snapshot.complete,
                )
            )
        return Collection(started_at=started_at, attempts=attempts)
    finally:
        if owned:
            client.close()


def _fetch(
    client: NansenClient,
    endpoint: str,
    params: dict[str, Any],
    max_pages: int,
) -> Snapshot:
    """Page *endpoint* until it says it is done, or until the cap says stop."""
    # Taken before the first request, not after the last: see Snapshot.
    observed_at = datetime.now(timezone.utc)
    pages: list[Any] = []
    complete = False
    note: str | None = None

    for page in range(1, max_pages + 1):
        body = dict(params, pagination={"page": page, "per_page": PER_PAGE})
        payload = client.post(endpoint, body)
        pages.append(payload)

        marker = _is_last_page(payload)
        if marker is None:
            # No pagination marker in a 200 body means the documented schema
            # moved. Claiming the list is whole would be a guess, so the
            # snapshot keeps what arrived and admits it does not know.
            note = (
                "response carried no pagination.is_last_page; completeness "
                "unknown"
            )
            break
        if marker:
            complete = True
            break
    else:
        note = (
            f"stopped at the {max_pages}-page cap; the API had not yet "
            "reported is_last_page"
        )

    return Snapshot(
        endpoint=endpoint,
        params=dict(params),
        observed_at=observed_at,
        collector_version=COLLECTOR_VERSION,
        pages=pages,
        complete=complete,
        note=note,
    )


def _is_last_page(payload: Any) -> bool | None:
    """The documented pagination marker, or None if the body has none."""
    if not isinstance(payload, dict):
        return None
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict):
        return None
    marker = pagination.get("is_last_page")
    return marker if isinstance(marker, bool) else None
