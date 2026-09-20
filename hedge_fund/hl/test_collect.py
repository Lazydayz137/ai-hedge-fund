"""collect_snapshot tests -- fixtures only, no network.

Fixtures under fixtures/ are trimmed responses captured from the live
https://api.hyperliquid.xyz/info endpoint on 2026-09-19 (spot_meta_and_asset_ctxs.json
is additionally re-indexed down from the real divergent index it was
captured with, to keep the fixture small -- see its inline comment).
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hedge_fund.hl.client import HLClientError
from hedge_fund.hl.collect import collect_snapshot

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


NATIVE = _load("native_meta_and_asset_ctxs.json")
HIP3_XYZ = _load("hip3_xyz_meta_and_asset_ctxs.json")
PERP_DEXS = _load("perp_dexs.json")
SPOT = _load("spot_meta_and_asset_ctxs.json")
EMPTY_SPOT = [{"tokens": [], "universe": []}, []]


class FakeClient:
    """Duck-types HLClient; returns canned payloads or raises per scope."""

    def __init__(self, *, native=NATIVE, dexs=None, dex_payloads=None,
                 spot=EMPTY_SPOT, raise_scopes=()):
        self._native = native
        self._dexs = dexs if dexs is not None else [None]
        self._dex_payloads = dex_payloads or {}
        self._spot = spot
        self._raise_scopes = set(raise_scopes)

    def meta_and_asset_ctxs(self, dex=None):
        scope = "native" if dex is None else f"dex:{dex}"
        if scope in self._raise_scopes:
            raise HLClientError(f"{scope} unreachable")
        return self._native if dex is None else self._dex_payloads[dex]

    def perp_dexs(self):
        if "perp_dexs" in self._raise_scopes:
            raise HLClientError("perp_dexs unreachable")
        return self._dexs

    def spot_meta_and_asset_ctxs(self):
        if "spot" in self._raise_scopes:
            raise HLClientError("spot unreachable")
        return self._spot


def test_native_rows_parsed_with_empty_dex():
    snap = collect_snapshot(FakeClient())
    assert len(snap.perp_rows) == 3
    assert all(r.dex == "" for r in snap.perp_rows)
    btc = next(r for r in snap.perp_rows if r.name == "BTC")
    assert btc.funding == 0.0000125
    assert btc.open_interest == 42171.7735
    assert btc.mark_px == 81010.6
    assert btc.impact_pxs == (81012.0, 81013.0)
    assert not snap.failures
    assert snap.raw["native"] == NATIVE


def test_hip3_rows_carry_dex_name():
    snap = collect_snapshot(FakeClient(
        dexs=PERP_DEXS,
        dex_payloads={d["name"]: HIP3_XYZ for d in PERP_DEXS if d},
    ))
    hip3_rows = [r for r in snap.perp_rows if r.dex != ""]
    assert {r.dex for r in hip3_rows} == {d["name"] for d in PERP_DEXS if d}
    xyz100 = next(r for r in hip3_rows if r.name == "xyz:XYZ100")
    assert xyz100.dex == "xyz"
    assert xyz100.mark_px == 29652.0


def test_spot_rows_join_by_index_not_position():
    """The regression test for the real gotcha: ctx lookup must use the
    universe entry's own `index` field, not its position in the list.
    Position-based lookup would pair "@367" with the dummy placeholder at
    ctx position 1 (markPx 1.0) instead of its real ctx at index 5.
    """
    snap = collect_snapshot(FakeClient(spot=SPOT))
    assert len(snap.spot_rows) == 2
    row = next(r for r in snap.spot_rows if r.name == "@367")
    assert row.index == 5
    assert row.mark_px == 0.00063
    assert row.circulating_supply == 184467440737.0535888672


def test_builder_config_is_recorded_once_per_pass():
    snap = collect_snapshot(FakeClient(
        dexs=PERP_DEXS,
        dex_payloads={d["name"]: HIP3_XYZ for d in PERP_DEXS if d},
    ))
    xyz = next(d for d in snap.dexes if d.name == "xyz")
    assert xyz.full_name == "XYZ"
    assert xyz.deployer == "0x88806a71d74ad0a510b350545c9ae490912f0888"
    assert xyz.fee_recipient == "0x83ffcfb1f2ad843c474b2e28df86c721cb869d3a"
    assert len(snap.dexes) == len([d for d in PERP_DEXS if d])


def test_native_book_gets_no_config_entry():
    """The venue sends a literal null for its own book, not an empty config."""
    snap = collect_snapshot(FakeClient(dexs=PERP_DEXS, dex_payloads={d["name"]: HIP3_XYZ for d in PERP_DEXS if d}))
    assert "" not in [d.name for d in snap.dexes]


def test_who_could_post_the_oracle_is_kept_even_when_oracle_updater_is_null():
    """oracleUpdater is null on xyz; subDeployers.setOracle is not."""
    snap = collect_snapshot(FakeClient(
        dexs=PERP_DEXS,
        dex_payloads={d["name"]: HIP3_XYZ for d in PERP_DEXS if d},
    ))
    xyz = next(d for d in snap.dexes if d.name == "xyz")
    assert xyz.oracle_updater is None
    assert xyz.sub_deployers["setOracle"] == ["0x1234567890545d1df9ee64b35fdd16966e08acec"]
    assert len(xyz.sub_deployers["registerAsset"]) == 2


def test_funding_inputs_and_oi_caps_join_to_instruments_by_name():
    snap = collect_snapshot(FakeClient(
        dexs=PERP_DEXS,
        dex_payloads={d["name"]: HIP3_XYZ for d in PERP_DEXS if d},
    ))
    xyz = next(d for d in snap.dexes if d.name == "xyz")
    xyz100 = next(r for r in snap.perp_rows if r.name == "xyz:XYZ100")
    assert xyz.asset_to_funding_multiplier[xyz100.name] == 0.5
    assert xyz.asset_to_streaming_oi_cap[xyz100.name] == 1000000000.0
    # Absent maps stay empty rather than being invented from a default.
    assert xyz.asset_to_funding_interest_rate == {}
    assert xyz.asset_to_funding_clamp == {}


def test_per_instrument_builder_settings_are_recorded():
    snap = collect_snapshot(FakeClient(
        dexs=PERP_DEXS,
        dex_payloads={d["name"]: HIP3_XYZ for d in PERP_DEXS if d},
    ))
    xyz100 = next(r for r in snap.perp_rows if r.name == "xyz:XYZ100")
    assert xyz100.deployer_fee_scale == 1.0
    assert xyz100.growth_mode == "enabled"
    assert xyz100.margin_table_id == 30
    # Kept as the venue's own naive string, not coerced to a UTC instant.
    assert xyz100.last_fee_scale_change_time == "2025-11-23T17:37:10.033211662"


def test_unparseable_config_costs_the_config_not_the_market_data():
    dexs = json.loads(json.dumps(PERP_DEXS))
    xyz = next(d for d in dexs if d and d["name"] == "xyz")
    xyz["assetToFundingMultiplier"] = [["xyz:XYZ100", "not-a-number"]]

    snap = collect_snapshot(FakeClient(dexs=dexs, dex_payloads={d["name"]: HIP3_XYZ for d in dexs if d}))

    assert "xyz" not in {d.name for d in snap.dexes}
    assert any(f.scope == "xyz (config)" for f in snap.failures)
    assert "xyz:XYZ100" in {r.name for r in snap.perp_rows}  # market data still collected


def test_nameless_dex_entry_costs_its_instruments_too():
    """Without a name there is nothing to request."""
    dexs = json.loads(json.dumps(PERP_DEXS))
    xyz_index = next(i for i, d in enumerate(dexs) if d and d["name"] == "xyz")
    del dexs[xyz_index]["name"]

    snap = collect_snapshot(FakeClient(
        dexs=dexs,
        dex_payloads={d["name"]: HIP3_XYZ for d in dexs if d and "name" in d},
    ))

    assert "xyz" not in {d.name for d in snap.dexes}
    assert not [r for r in snap.perp_rows if r.dex == "xyz"]
    assert any(f.scope == f"perp_dexs[{xyz_index}]" for f in snap.failures)


def test_failed_dex_writes_no_rows_but_others_still_run():
    snap = collect_snapshot(FakeClient(
        dexs=[None, {"name": "xyz"}, {"name": "flx"}],
        dex_payloads={"xyz": HIP3_XYZ},  # "flx" deliberately missing
        raise_scopes={"dex:flx"},
        spot=SPOT,
    ))
    assert any(f.scope == "dex:flx" for f in snap.failures)
    assert "flx" not in {r.dex for r in snap.perp_rows}
    assert "xyz" in {r.dex for r in snap.perp_rows}  # unaffected
    assert len(snap.spot_rows) == 2  # unaffected


def test_perp_dexs_failure_skips_hip3_but_native_and_spot_still_run():
    snap = collect_snapshot(FakeClient(raise_scopes={"perp_dexs"}, spot=SPOT))
    assert any(f.scope == "perp_dexs" for f in snap.failures)
    assert len(snap.perp_rows) == 3  # native still ran
    assert all(r.dex == "" for r in snap.perp_rows)
    assert len(snap.spot_rows) == 2  # spot still ran


def test_native_failure_writes_no_perp_rows_but_spot_still_runs():
    snap = collect_snapshot(FakeClient(raise_scopes={"native"}, spot=SPOT))
    assert any(f.scope == "native" for f in snap.failures)
    assert snap.perp_rows == []
    assert len(snap.spot_rows) == 2


def test_unparseable_native_payload_costs_native_only_not_the_whole_pass():
    """A parsing error (missing field, bad shape) must record a ScopeFailure
    for that scope, not raise out of collect_snapshot and lose every scope
    collected before it -- only HLClientError used to be caught here."""
    broken = copy.deepcopy(NATIVE)
    del broken[0]["universe"][0]["szDecimals"]

    snap = collect_snapshot(FakeClient(native=broken, spot=SPOT))
    assert any(f.scope == "native" for f in snap.failures)
    assert snap.perp_rows == []
    assert len(snap.spot_rows) == 2  # spot still ran despite native's parse failure


def test_unparseable_spot_payload_costs_spot_only():
    broken_spot = copy.deepcopy(SPOT)
    del broken_spot[0]["universe"][0]["index"]

    snap = collect_snapshot(FakeClient(spot=broken_spot))
    assert any(f.scope == "spot" for f in snap.failures)
    assert snap.spot_rows == []
    assert len(snap.perp_rows) == 3  # native still ran despite spot's parse failure


def test_all_rows_share_one_observed_at():
    before = datetime.now(timezone.utc)
    snap = collect_snapshot(FakeClient(spot=SPOT))
    after = datetime.now(timezone.utc)
    assert before <= snap.observed_at <= after
    assert all(r.observed_at == snap.observed_at for r in snap.perp_rows)
    assert all(r.observed_at == snap.observed_at for r in snap.spot_rows)
