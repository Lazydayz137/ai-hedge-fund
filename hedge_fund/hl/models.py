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
    failures: list[ScopeFailure] = []
    raw: dict[str, Any] = {}
