"""Write down what Hyperliquid's perps looked like, over and over, forever.

Hyperliquid lists hundreds of perps across its own crypto book and ten
builder-deployed (HIP-3) DEXs — equities, index products, FX, metals. Those
builder markets create instrument pairs that did not exist eighteen months
ago: an NVDA perp with a funding leg against actual NVDA, a gold perp against
the COMEX front month. Nobody sells the history of their funding, basis and
open interest, because nobody has been keeping it. It starts existing when
something starts writing it down.

So this is a sensor and nothing else. It reads, it records, and it never
invents. A market it could not read produces an error row and no observation:
no interpolation, no carrying yesterday's mark forward, no placeholder. A gap
in the archive is a fact about the archive, and a fabricated number is a lie
that outlives everyone who could have caught it.

Snapshots live beside the rest of the user's data as one JSON file per pass,
written with exclusive creation so an observation can never land on top of
another, and read back by the pass's own as-of time rather than by file
mtime — the same discipline as the ledger, for the same reason.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from hedge_fund import paths
from hedge_fund.hyperliquid.client import (
    HYPERLIQUID_INFO_URL,
    HyperliquidClient,
    HyperliquidError,
)
from hedge_fund.hyperliquid.models import (
    MarketSnapshot,
    ObservationError,
    PerpObservation,
)


# Without these, a row would be describing a market it cannot price, so a
# missing or unparseable one costs the whole row rather than being defaulted.
_REQUIRED = ("markPx", "oraclePx", "funding", "openInterest")


def _utc_now() -> str:
    """Now, UTC, to the second, with an explicit Z.

    Z-suffixed ISO-8601 sorts lexically in time order, which is what makes
    read_as_of a string comparison instead of a parse of every file.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(raw: object) -> float | None:
    """Parse one of the venue's decimal strings, or None if it sent null."""
    if raw is None:
        return None
    return float(raw)


def observe(asset: dict, ctx: dict, dex: str, observed_at: str) -> PerpObservation:
    """Build one observation from a universe entry and its market context.

    Raises rather than returning a partial row: the caller turns that into an
    ObservationError and writes no row for the instrument.
    """
    name = asset["name"]
    for field in _REQUIRED:
        if ctx.get(field) is None:
            raise ValueError(f"{name}: {field} is null")

    impact = ctx.get("impactPxs")
    return PerpObservation(
        instrument=name,
        dex=dex,
        observed_at=observed_at,
        funding=float(ctx["funding"]),
        open_interest=float(ctx["openInterest"]),
        mark_px=float(ctx["markPx"]),
        oracle_px=float(ctx["oraclePx"]),
        mid_px=_num(ctx.get("midPx")),
        premium=_num(ctx.get("premium")),
        impact_pxs=[float(p) for p in impact] if impact else None,
        prev_day_px=_num(ctx.get("prevDayPx")),
        day_ntl_vlm=_num(ctx.get("dayNtlVlm")),
        day_base_vlm=_num(ctx.get("dayBaseVlm")),
        max_leverage=asset.get("maxLeverage"),
        sz_decimals=asset.get("szDecimals"),
        margin_mode=asset.get("marginMode"),
        only_isolated=asset.get("onlyIsolated"),
        # Absent on native crypto perps, present and true on the builder
        # markets that have been switched off. Absent reads as listed.
        is_delisted=bool(asset.get("isDelisted", False)),
    )


def collect(client: HyperliquidClient | None = None) -> MarketSnapshot:
    """Snapshot every perp the venue lists, native and builder-deployed, in one pass.

    Walks perpDexs and then one metaAndAssetCtxs per DEX. A DEX whose call
    fails costs that DEX's instruments and nothing else; the pass continues
    and says so in the snapshot's errors.

    Delisted and empty-book markets are collected like any other. They are
    the interesting ones — six of the ten builder DEXs are currently entirely
    switched off — and a collector that filtered them would erase the record
    of when each one stopped.
    """
    owned = client is None
    hl = client or HyperliquidClient()
    snapshot = MarketSnapshot(started_at=_utc_now(), source_url=HYPERLIQUID_INFO_URL)
    try:
        try:
            dexes = hl.perp_dexes()
        except HyperliquidError as exc:
            # Nothing else can be attempted without the DEX list: the native
            # book alone would be a snapshot that silently omits every HIP-3
            # market, which is the exact history this exists to keep.
            snapshot.errors.append(ObservationError(scope="perpDexs", reason=str(exc)))
            return snapshot

        # The null first entry is Hyperliquid's own book; its DEX name is "".
        names = ["" if entry is None else entry.get("name", "") for entry in dexes]
        for dex in names:
            try:
                meta, ctxs = hl.meta_and_asset_ctxs(dex=dex)
            except HyperliquidError as exc:
                snapshot.errors.append(ObservationError(scope=dex or "(native)", reason=str(exc)))
                continue

            # Taken after the response, not before the request: it timestamps
            # what we were told, not when we asked.
            observed_at = _utc_now()
            for asset, ctx in zip(meta["universe"], ctxs):
                try:
                    snapshot.observations.append(observe(asset, ctx, dex, observed_at))
                except (AttributeError, KeyError, TypeError, ValueError) as exc:
                    scope = asset.get("name") if isinstance(asset, dict) else None
                    snapshot.errors.append(
                        ObservationError(scope=scope or (dex or "(native)"), reason=str(exc))
                    )
        return snapshot
    finally:
        if owned:
            hl.close()


def save_snapshot(snapshot: MarketSnapshot) -> Path:
    """Write a pass to the archive under its own start time."""
    # Looked up through the module so tests can redirect it; nothing should be
    # able to write into a real archive by accident.
    paths.SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = snapshot.started_at.replace(":", "")
    path = paths.SNAPSHOTS_DIR / f"perps-{stamp}.json"
    # Exclusive creation rather than exists()-then-write: two collectors
    # started in the same second would both pass the check and one would land
    # on top of the other. An append-only archive that can overwrite an entry
    # is not append-only, and the value of this data is entirely in the fact
    # that nothing is ever restated.
    suffix = 1
    while True:
        try:
            with path.open("x") as handle:
                handle.write(snapshot.model_dump_json(indent=2))
            return path
        except FileExistsError:
            suffix += 1
            path = paths.SNAPSHOTS_DIR / f"perps-{stamp}-{suffix}.json"


def read_as_of(as_of: str | None = None) -> MarketSnapshot | None:
    """The newest snapshot taken at or before *as_of*, or None if there is none.

    Ordered by the pass's own ``started_at``, not by when the file was
    written. Those differ the moment a backfill lands after a live run, and
    ordering by mtime would hand a question about Tuesday the answer from
    Thursday — lookahead smuggled in through the archive, into research whose
    whole promise is that it sees only what was knowable at the time.

    *as_of* is compared lexically against the Z-suffixed timestamps, so it
    must be spelled the same way: a full "2026-09-20T14:03:11Z" for an
    instant, or a bare "2026-09-20", which means that day's midnight UTC and
    therefore excludes the day's own snapshots.

    Unreadable files are skipped rather than raised — a truncated snapshot
    should cost that one reading, not the caller.
    """
    eligible: list[tuple[str, Path]] = []
    for path in paths.SNAPSHOTS_DIR.glob("perps-*.json"):
        try:
            # Peek at the one field that decides eligibility rather than
            # validating hundreds of observations in every snapshot ever
            # taken just to find the newest one.
            when = json.loads(path.read_text())["started_at"]
            if as_of is not None and when > as_of:
                continue
            eligible.append((when, path))
        except (OSError, ValueError, KeyError, TypeError):
            continue

    for _, path in sorted(eligible, reverse=True):
        try:
            return MarketSnapshot.model_validate_json(path.read_text())
        except (OSError, ValueError):
            continue
    return None
