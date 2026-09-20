"""One collection pass: native perps + every HIP-3 dex + spot, in one shot.

Every scope is attempted independently and a failure in one never stops the
others -- a dead HIP-3 dex shouldn't cost the native and spot rows this
pass would otherwise have banked. The `perp_dexs` call is the exception:
its result is the only way to know which HIP-3 dexes exist, so if it fails
the HIP-3 fan-out is skipped for this pass (native and spot still run).
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError

from hedge_fund.hl.client import HLClient, HLClientError
from hedge_fund.hl.models import DexConfig, MarketSnapshot, PerpMarketRow, ScopeFailure, SpotMarketRow

# A malformed payload (missing field, wrong type, unparseable price) must
# cost only the scope that raised it -- never abort the pass and lose the
# scopes already collected. HLClientError is the transport/HTTP failure;
# these are the ways a *parsed* JSON body can still fail to become rows.
_PARSE_ERRORS = (KeyError, TypeError, ValueError, IndexError, ValidationError)


def collect_snapshot(client: HLClient | None = None) -> MarketSnapshot:
    """Hit every scope once and return what was actually observed.

    One `observed_at` stamps every row in the pass -- the calls span a few
    seconds of wall clock, not the days/hours that matter for separating
    HIP-3's off-hours EMA regime from live cash-market hours.
    """
    observed_at = datetime.now(timezone.utc)
    owns_client = client is None
    client = client or HLClient()
    try:
        perp_rows: list[PerpMarketRow] = []
        spot_rows: list[SpotMarketRow] = []
        failures: list[ScopeFailure] = []
        raw: dict[str, object] = {}

        try:
            native = client.meta_and_asset_ctxs()
        except HLClientError as exc:
            failures.append(ScopeFailure(scope="native", error=str(exc)))
        else:
            raw["native"] = native
            try:
                perp_rows.extend(_parse_perp_rows(native, dex="", observed_at=observed_at))
            except _PARSE_ERRORS as exc:
                failures.append(ScopeFailure(scope="native", error=f"unparseable payload: {exc}"))

        dexes: list[DexConfig] = []
        dex_names: list[str] = []
        try:
            dexs = client.perp_dexs()
        except HLClientError as exc:
            failures.append(ScopeFailure(scope="perp_dexs", error=str(exc)))
        else:
            try:
                raw["perp_dexs"] = dexs
                for index, entry in enumerate(dexs):
                    if entry is None:
                        continue  # native book: no builder, no config
                    try:
                        name = entry["name"]
                    except (KeyError, TypeError) as exc:
                        # Without a name there's nothing to request market data
                        # for either -- this costs the DEX's instruments too.
                        failures.append(ScopeFailure(scope=f"perp_dexs[{index}]", error=str(exc)))
                        continue
                    dex_names.append(name)
                    try:
                        dexes.append(_parse_dex_config(entry))
                    except (AttributeError, KeyError, TypeError, ValueError) as exc:
                        # The config didn't parse, but the market data is still
                        # worth having -- dropping real observations over one
                        # malformed multiplier would be the worse trade, and
                        # carrying forward the last pass's config would mean
                        # writing down terms that were never actually observed
                        # this pass.
                        failures.append(ScopeFailure(scope=f"{name} (config)", error=str(exc)))
            except _PARSE_ERRORS as exc:
                failures.append(ScopeFailure(scope="perp_dexs", error=f"unparseable payload: {exc}"))

        for name in dex_names:
            try:
                payload = client.meta_and_asset_ctxs(dex=name)
            except HLClientError as exc:
                failures.append(ScopeFailure(scope=f"dex:{name}", error=str(exc)))
                continue
            raw[f"dex:{name}"] = payload
            try:
                perp_rows.extend(_parse_perp_rows(payload, dex=name, observed_at=observed_at))
            except _PARSE_ERRORS as exc:
                failures.append(ScopeFailure(scope=f"dex:{name}", error=f"unparseable payload: {exc}"))

        try:
            spot = client.spot_meta_and_asset_ctxs()
        except HLClientError as exc:
            failures.append(ScopeFailure(scope="spot", error=str(exc)))
        else:
            raw["spot"] = spot
            try:
                spot_rows.extend(_parse_spot_rows(spot, observed_at=observed_at))
            except _PARSE_ERRORS as exc:
                failures.append(ScopeFailure(scope="spot", error=f"unparseable payload: {exc}"))

        return MarketSnapshot(
            observed_at=observed_at,
            perp_rows=perp_rows,
            spot_rows=spot_rows,
            dexes=dexes,
            failures=failures,
            raw=raw,
        )
    finally:
        if owns_client:
            client.close()


def _parse_perp_rows(payload: list, *, dex: str, observed_at: datetime) -> list[PerpMarketRow]:
    """Perp universe and asset ctxs are positionally aligned (unlike spot)."""
    meta, ctxs = payload
    rows = []
    for u, c in zip(meta["universe"], ctxs):
        rows.append(PerpMarketRow(
            observed_at=observed_at,
            dex=dex,
            name=u["name"],
            sz_decimals=u["szDecimals"],
            max_leverage=u["maxLeverage"],
            margin_table_id=u.get("marginTableId"),
            only_isolated=u.get("onlyIsolated"),
            deployer_fee_scale=_opt_float(u.get("deployerFeeScale")),
            growth_mode=u.get("growthMode"),
            last_fee_scale_change_time=u.get("lastFeeScaleChangeTime"),
            funding=float(c["funding"]),
            open_interest=float(c["openInterest"]),
            prev_day_px=float(c["prevDayPx"]),
            day_ntl_vlm=float(c["dayNtlVlm"]),
            day_base_vlm=_opt_float(c.get("dayBaseVlm")),
            premium=_opt_float(c.get("premium")),
            oracle_px=float(c["oraclePx"]),
            mark_px=float(c["markPx"]),
            mid_px=_opt_float(c.get("midPx")),
            impact_pxs=_opt_pair(c.get("impactPxs")),
        ))
    return rows


def _parse_spot_rows(payload: list, *, observed_at: datetime) -> list[SpotMarketRow]:
    """Spot asset ctxs are indexed by each universe entry's `index` field,
    not by its position in the universe list -- the ctx array runs longer
    (it carries slots for pairs the universe list omits), and beyond a low
    prefix the two orderings diverge. Confirmed live 2026-09-19: universe
    entries stay positional through roughly index ~14, then jump ahead of
    their position (e.g. an entry at list position ~300 carrying index 867)
    while the ctx array keeps every index in between. Joining by position
    instead of `index` would silently pair most pairs with the wrong ctx.
    """
    meta, ctxs = payload
    rows = []
    for u in meta["universe"]:
        idx = u["index"]
        if idx >= len(ctxs):
            continue  # this pass's ctx array doesn't cover it; skip, don't guess
        c = ctxs[idx]
        rows.append(SpotMarketRow(
            observed_at=observed_at,
            name=u["name"],
            index=idx,
            is_canonical=u.get("isCanonical", False),
            prev_day_px=float(c["prevDayPx"]),
            day_ntl_vlm=float(c["dayNtlVlm"]),
            day_base_vlm=_opt_float(c.get("dayBaseVlm")),
            mark_px=float(c["markPx"]),
            mid_px=_opt_float(c.get("midPx")),
            circulating_supply=_opt_float(c.get("circulatingSupply")),
            total_supply=_opt_float(c.get("totalSupply")),
        ))
    return rows


def _parse_dex_config(entry: dict) -> DexConfig:
    """Build one builder DEX's config from its perp_dexs entry.

    Raises rather than returning a partial config: a half-read config is a
    config nobody can trust a funding number against.
    """
    return DexConfig(
        name=entry["name"],
        full_name=entry.get("fullName"),
        deployer=entry.get("deployer"),
        oracle_updater=entry.get("oracleUpdater"),
        # [[action, [address, ...]], ...] -- who may do what to this DEX.
        sub_deployers={action: list(addrs) for action, addrs in (entry.get("subDeployers") or [])},
        fee_recipient=entry.get("feeRecipient"),
        asset_to_funding_multiplier=_pairs(entry.get("assetToFundingMultiplier")),
        asset_to_funding_interest_rate=_pairs(entry.get("assetToFundingInterestRate")),
        asset_to_funding_clamp=_pairs(entry.get("assetToFundingClamp")),
        asset_to_streaming_oi_cap=_pairs(entry.get("assetToStreamingOiCap")),
    )


def _pairs(raw: object) -> dict[str, float]:
    """Turn one of the venue's [[key, "1.5"], ...] assoc-lists into a dict."""
    return {key: float(value) for key, value in (raw or [])}


def _opt_float(value: object) -> float | None:
    return float(value) if value is not None else None


def _opt_pair(value: object) -> tuple[float, float] | None:
    return (float(value[0]), float(value[1])) if value else None
