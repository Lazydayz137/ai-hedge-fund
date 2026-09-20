"""Pydantic models for one Hyperliquid market-state snapshot.

Field names mirror the wire response verbatim (camelCase strings, mostly)
except where the raw type is unusable for storage/analysis (prices as
strings, e.g.) -- those are coerced to float at parse time. The raw
response is kept alongside the parsed rows in MarketSnapshot.raw, so a
field this module doesn't parse today is still recoverable later.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class PerpMarketRow(BaseModel):
    """One perp market's state at `observed_at` -- native or HIP-3."""

    observed_at: datetime
    # "" for native perps; a HIP-3 dex's short name (e.g. "xyz") otherwise.
    # name already carries the dex prefix for HIP-3 ("xyz:XYZ100"), so dex
    # is redundant with name for those rows -- kept anyway so native and
    # HIP-3 rows can be filtered without string-parsing name.
    dex: str
    name: str
    sz_decimals: int
    max_leverage: int
    margin_table_id: int | None = None
    only_isolated: bool | None = None
    # Per-instrument builder settings that can change under a live position:
    # deployer_fee_scale multiplies the builder's cut of the fee, growth_mode
    # is the venue's own regime label. Both are kept because a row that
    # cannot say what regime it was taken under cannot be reinterpreted once
    # the regime moves.
    deployer_fee_scale: float | None = None
    growth_mode: str | None = None
    # The venue's own answer to "when did the fee last move", verbatim: a
    # naive local-format timestamp, no zone, unlike observed_at. Left as the
    # string it arrives as rather than coerced into a UTC instant it does
    # not claim to be.
    last_fee_scale_change_time: str | None = None

    funding: float
    open_interest: float
    prev_day_px: float
    day_ntl_vlm: float
    day_base_vlm: float | None = None
    # None on a thin/no-book market -- a real observation, not missing data.
    premium: float | None = None
    oracle_px: float
    mark_px: float
    mid_px: float | None = None
    impact_pxs: tuple[float, float] | None = None


class SpotMarketRow(BaseModel):
    """One spot pair's state at `observed_at`."""

    observed_at: datetime
    name: str
    index: int
    is_canonical: bool

    prev_day_px: float
    day_ntl_vlm: float
    day_base_vlm: float | None = None
    mark_px: float
    mid_px: float | None = None
    circulating_supply: float | None = None
    total_supply: float | None = None


class ScopeFailure(BaseModel):
    """One scope's call failed this pass -- no rows were written for it.

    "scope" is "native", "perp_dexs", "dex:<name>", or "spot". A failure
    here is itself a real observation (the API was unreachable / erroring
    at `observed_at`) and is kept, never silently dropped.
    """

    scope: str
    error: str


class DexConfig(BaseModel):
    """One builder-deployed DEX's settings at the time of a pass.

    Recorded per pass rather than copied onto all its observation rows.
    A HIP-3 market's terms are set by its builder and can move: the
    addresses allowed to post its oracle, the multiplier and interest rate
    that turn a premium into the funding actually charged, the open-interest
    caps that bound a position. A funding rate recorded without the
    multiplier that produced it is a number nobody can reinterpret later,
    and if a builder changes either, every earlier observation silently
    means something else. Nothing else is writing this down.

    Only builder DEXs appear here. Hyperliquid's own book has no entry in
    perpDexs at all -- the endpoint returns a literal null in its place --
    so a native pass has no config row, rather than an empty one that would
    read like a builder that set nothing.

    Per-instrument maps are keyed by the full namespaced instrument name
    ("xyz:NVDA"), so they join to PerpMarketRow.name directly.
    """

    name: str
    full_name: str | None = None
    deployer: str | None = None

    # The address posting this DEX's oracle -- null on most of them,
    # including the largest by open interest. sub_deployers is what
    # actually answers "who could post the oracle": its setOracle entry
    # names the authorized addresses, and it is populated where
    # oracle_updater is not. Oracle manipulation is the demonstrated attack
    # on this market class, so both are kept, and neither is inferred from
    # the other.
    oracle_updater: str | None = None
    sub_deployers: dict[str, list[str]] = {}

    fee_recipient: str | None = None

    # Funding inputs, per instrument. The venue computes funding from the
    # premium, the interest rate, and the multiplier; recording the rate
    # alone would be recording an output whose inputs are gone.
    asset_to_funding_multiplier: dict[str, float] = {}
    asset_to_funding_interest_rate: dict[str, float] = {}
    asset_to_funding_clamp: dict[str, float] = {}

    # Notional open-interest ceiling per instrument -- the size bound on
    # any position taken against it.
    asset_to_streaming_oi_cap: dict[str, float] = {}


class BuilderFillSidecar(BaseModel):
    """Immutable record accompanying one archived builder-fill data file.

    Describes the ORIGINAL compressed bytes stored beside it (never the
    decompressed content), so the sidecar alone is enough to verify the
    archived file later without re-fetching or re-decompressing it.
    """

    builder: str
    date: str  # YYYY-MM-DD, the day the file COVERS, not the fetch day
    fetched_at: datetime  # UTC, when this fetch happened
    byte_length: int
    sha256: str
    http_status: int


class BuilderFillRow(BaseModel):
    """One parsed row from a builder's daily fill CSV.

    Field names and order mirror the real CSV header verbatim, confirmed
    live against https://stats-data.hyperliquid.xyz on 2026-09-19:
    time,user,coin,side,px,sz,crossed,special_trade_type,tif,is_trigger,
    counterparty,closed_pnl,twap_id,builder_fee
    """

    time: datetime
    user: str
    coin: str
    side: str
    px: float
    sz: float
    crossed: bool
    special_trade_type: str
    tif: str
    is_trigger: bool
    counterparty: str
    closed_pnl: float
    twap_id: int
    builder_fee: float


class FillFetchResult(BaseModel):
    """Outcome of one (builder, date) archive attempt.

    "new": first time this date's content was archived for this builder.
    "unchanged": identical bytes already archived -- a no-op, nothing written.
    "restated": a DIFFERENT hash for an already-archived date -- a new
      version was written beside the old one rather than replacing it; a
      restated file is itself information and must not be merged away.
    "failed": the fetch didn't return real data (network error or non-200,
      e.g. a day that hasn't published yet); no data file was written.
    """

    builder: str
    date: str
    status: str
    path: str | None = None
    detail: str | None = None


class MarketSnapshot(BaseModel):
    """Everything one collection pass saw, real data only.

    A scope that failed contributes zero rows and one ScopeFailure --
    never a carried-forward or interpolated row. `raw` holds the exact
    response body per scope (keyed the same as ScopeFailure.scope) so a
    field nobody parses today can still be read back later.

    HIP-3 equity oracles are EMAs of the underlying perp's own price
    outside that equity's cash-market hours, not an independent feed --
    so `premium`/`oracle_px` on those rows during off-hours describe the
    perp price tracking itself, not a real dislocation. Hyperliquid's
    asset context carries no explicit staleness flag; `observed_at` here
    is the only handle a later reader has to separate the two regimes
    (join against the underlying's known cash-market calendar).
    """

    observed_at: datetime
    perp_rows: list[PerpMarketRow] = []
    spot_rows: list[SpotMarketRow] = []
    # One entry per builder-deployed DEX; none for the native book, which
    # the venue exposes no config for. A DEX whose config would not parse
    # has no entry here and a ScopeFailure instead -- never a stale one
    # carried forward from an earlier pass.
    dexes: list[DexConfig] = []
    failures: list[ScopeFailure] = []
    raw: dict[str, Any] = {}
