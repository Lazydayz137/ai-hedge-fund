"""Collector tests — fixture only, no network."""

import json

import pytest

from hedge_fund import paths
from hedge_fund.hyperliquid.client import HyperliquidError
from hedge_fund.hyperliquid.collector import collect, read_as_of, save_snapshot
from hedge_fund.hyperliquid.models import MarketSnapshot


# A real POST https://api.hyperliquid.xyz/info response, captured 2026-09-20
# and trimmed to five instruments: a liquid native perp (BTC), a delisted
# native one (MATIC), two live HIP-3 markets on the xyz DEX (an equity and a
# COMEX-benchmarked metal), and a delisted HIP-3 market whose book is empty
# (vntl:SPACEX — midPx and impactPxs null, which is what an empty book looks
# like on this endpoint). Field names and string-typed numbers are the
# venue's own; nothing here is invented.
CAPTURE = {
    "perpDexs": [
        None,
        {"name": "xyz", "fullName": "XYZ"},
        {"name": "vntl", "fullName": "Ventuals"},
    ],
    "": [
        {"universe": [
            {"szDecimals": 5, "name": "BTC", "maxLeverage": 40, "marginTableId": 56},
            {"szDecimals": 1, "name": "MATIC", "maxLeverage": 20, "marginTableId": 20,
             "isDelisted": True},
        ]},
        [
            {"funding": "0.0000125", "openInterest": "42124.6479", "prevDayPx": "81416.0",
             "dayNtlVlm": "1167895743.0746707916", "premium": "0.0002341487",
             "oraclePx": "81145.0", "markPx": "81165.0", "midPx": "81164.5",
             "impactPxs": ["81164.0", "81165.0"], "dayBaseVlm": "14344.19784"},
            {"funding": "0.0", "openInterest": "0.0", "prevDayPx": "0.37621",
             "dayNtlVlm": "0.0", "premium": None, "oraclePx": "0.3754",
             "markPx": "0.37621", "midPx": None, "impactPxs": None, "dayBaseVlm": "0.0"},
        ],
    ],
    "xyz": [
        {"universe": [
            {"szDecimals": 3, "name": "xyz:NVDA", "maxLeverage": 20, "marginTableId": 20,
             "growthMode": "enabled", "deployerFeeScale": "1.0"},
            {"szDecimals": 4, "name": "xyz:GOLD", "maxLeverage": 25, "marginTableId": 25,
             "deployerFeeScale": "1.0"},
        ]},
        [
            {"funding": "0.00000625", "openInterest": "638380.966", "prevDayPx": "222.25",
             "dayNtlVlm": "2862670.5162800001", "premium": "0.0000653065",
             "oraclePx": "222.03", "markPx": "222.03", "midPx": "222.045",
             "impactPxs": ["222.039", "222.05"], "dayBaseVlm": "12886.595"},
            {"funding": "0.00000625", "openInterest": "67743.1122", "prevDayPx": "4375.7",
             "dayNtlVlm": "4731482.9277600013", "premium": "-0.0003770653",
             "oraclePx": "4375.9", "markPx": "4374.4", "midPx": "4374.25",
             "impactPxs": ["4374.2", "4374.3"], "dayBaseVlm": "1081.0306"},
        ],
    ],
    "vntl": [
        {"universe": [
            {"szDecimals": 3, "name": "vntl:SPACEX", "maxLeverage": 3, "marginTableId": 3,
             "onlyIsolated": True, "isDelisted": True, "marginMode": "strictIsolated",
             "deployerFeeScale": "1.0"},
        ]},
        [
            {"funding": "0.0", "openInterest": "0.0", "prevDayPx": "2109.5",
             "dayNtlVlm": "0.0", "premium": None, "oraclePx": "2417.0",
             "markPx": "2109.5", "midPx": None, "impactPxs": None, "dayBaseVlm": "0.0"},
        ],
    ],
}


class FakeClient:
    """Serves the capture; optionally fails for named DEXs."""

    def __init__(self, capture=None, failing=()):
        self._capture = json.loads(json.dumps(capture or CAPTURE))  # deep copy
        self._failing = set(failing)
        self.calls = []

    def perp_dexes(self):
        if "perpDexs" in self._failing:
            raise HyperliquidError("perpDexs returned 503")
        return self._capture["perpDexs"]

    def meta_and_asset_ctxs(self, dex=""):
        self.calls.append(dex)
        if dex in self._failing:
            raise HyperliquidError(f"metaAndAssetCtxs(dex={dex!r}) returned 502")
        return self._capture[dex]


def test_collect_walks_every_dex_native_and_builder():
    snapshot = collect(FakeClient())

    assert snapshot.errors == []
    assert [o.instrument for o in snapshot.observations] == [
        "BTC", "MATIC", "xyz:NVDA", "xyz:GOLD", "vntl:SPACEX",
    ]
    # "" is the venue's own name for its native book, not a missing value.
    assert [o.dex for o in snapshot.observations] == ["", "", "xyz", "xyz", "vntl"]


def test_observation_carries_what_a_basis_trade_needs():
    btc = collect(FakeClient()).observations[0]

    assert btc.funding == 0.0000125
    assert btc.open_interest == 42124.6479
    assert btc.mark_px == 81165.0
    assert btc.oracle_px == 81145.0
    assert btc.mid_px == 81164.5
    assert btc.premium == 0.0002341487
    assert btc.impact_pxs == [81164.0, 81165.0]
    assert btc.day_ntl_vlm == 1167895743.0746708
    assert btc.max_leverage == 40
    assert btc.basis_bps == pytest.approx(2.4647, abs=1e-4)


def test_observed_at_is_utc_to_the_second():
    snapshot = collect(FakeClient())

    assert snapshot.started_at.endswith("Z")
    assert all(o.observed_at.endswith("Z") for o in snapshot.observations)
    assert all(o.observed_at >= snapshot.started_at for o in snapshot.observations)


def test_empty_book_is_recorded_not_filtered():
    """vntl:SPACEX has no quotes at all — that is an observation, not a gap."""
    spacex = collect(FakeClient()).observations[-1]

    assert spacex.is_delisted is True
    assert spacex.mid_px is None
    assert spacex.impact_pxs is None
    assert spacex.premium is None
    assert spacex.open_interest == 0.0
    # Still marked and still oracled, and 12.7% apart — the kind of reading
    # that only means something if you can tell it came from a dead market.
    assert spacex.mark_px == 2109.5
    assert spacex.oracle_px == 2417.0


def test_listed_market_is_not_flagged_delisted():
    """isDelisted is absent, not false, on a live market."""
    assert collect(FakeClient()).observations[0].is_delisted is False


def test_failed_dex_costs_only_its_own_instruments():
    snapshot = collect(FakeClient(failing={"xyz"}))

    assert [o.instrument for o in snapshot.observations] == ["BTC", "MATIC", "vntl:SPACEX"]
    assert [e.scope for e in snapshot.errors] == ["xyz"]
    assert "502" in snapshot.errors[0].reason


def test_unreadable_instrument_writes_an_error_and_no_row():
    capture = json.loads(json.dumps(CAPTURE))
    capture["xyz"][1][0]["markPx"] = None

    snapshot = collect(FakeClient(capture))

    assert "xyz:NVDA" not in [o.instrument for o in snapshot.observations]
    assert "xyz:GOLD" in [o.instrument for o in snapshot.observations]
    assert [e.scope for e in snapshot.errors] == ["xyz:NVDA"]
    assert "markPx" in snapshot.errors[0].reason


def test_dex_list_failure_gives_up_rather_than_snapshot_native_only():
    """A native-only pass would silently omit every HIP-3 market."""
    snapshot = collect(FakeClient(failing={"perpDexs"}))

    assert snapshot.observations == []
    assert [e.scope for e in snapshot.errors] == ["perpDexs"]


def test_save_never_overwrites_a_snapshot_from_the_same_second():
    first = collect(FakeClient())
    second = collect(FakeClient())
    second.started_at = first.started_at

    path_a = save_snapshot(first)
    path_b = save_snapshot(second)

    assert path_a != path_b
    assert len(list(paths.SNAPSHOTS_DIR.glob("perps-*.json"))) == 2


def test_round_trips_through_the_archive():
    original = collect(FakeClient())

    save_snapshot(original)
    restored = read_as_of()

    assert restored is not None
    assert restored.model_dump() == original.model_dump()


def test_read_as_of_never_returns_the_future():
    for stamp in ("2026-09-18T12:00:00Z", "2026-09-19T12:00:00Z", "2026-09-20T12:00:00Z"):
        snapshot = collect(FakeClient())
        snapshot.started_at = stamp
        save_snapshot(snapshot)

    assert read_as_of("2026-09-19T23:59:59Z").started_at == "2026-09-19T12:00:00Z"
    assert read_as_of().started_at == "2026-09-20T12:00:00Z"
    assert read_as_of("2026-09-17T00:00:00Z") is None


def test_read_as_of_orders_by_the_pass_not_the_file():
    """The older pass is written second; mtime order and time order disagree."""
    newer = collect(FakeClient())
    newer.started_at = "2026-09-20T12:00:00Z"
    save_snapshot(newer)
    older = collect(FakeClient())
    older.started_at = "2026-09-19T12:00:00Z"
    save_snapshot(older)

    assert read_as_of().started_at == "2026-09-20T12:00:00Z"


def test_empty_archive_reads_as_none():
    assert read_as_of() is None


def test_unreadable_snapshot_is_skipped_not_raised():
    good = collect(FakeClient())
    good.started_at = "2026-09-19T12:00:00Z"
    save_snapshot(good)
    paths.SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    (paths.SNAPSHOTS_DIR / "perps-2026-09-20T120000Z.json").write_text('{"started_at": ')

    assert read_as_of().started_at == "2026-09-19T12:00:00Z"


def test_snapshot_json_round_trips():
    snapshot = collect(FakeClient())

    assert MarketSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot
