"""collect_snapshot tests -- fixtures only, no network.

Fixtures under fixtures/ are trimmed responses captured from the live
https://api.hyperliquid.xyz/info endpoint on 2026-09-19 (spot_meta_and_asset_ctxs.json
is additionally re-indexed down from the real divergent index it was
captured with, to keep the fixture small -- see its inline comment).
"""

from __future__ import annotations

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


def test_all_rows_share_one_observed_at():
    before = datetime.now(timezone.utc)
    snap = collect_snapshot(FakeClient(spot=SPOT))
    after = datetime.now(timezone.utc)
    assert before <= snap.observed_at <= after
    assert all(r.observed_at == snap.observed_at for r in snap.perp_rows)
    assert all(r.observed_at == snap.observed_at for r in snap.spot_rows)
