"""A round writes what it got, admits what it didn't, and invents nothing."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from hedge_fund.nansen.client import (
    PERP_LEADERBOARD,
    PROFILER_ADDRESS_LABELS,
    PROFILER_PERP_POSITIONS,
    SMART_MONEY_HOLDINGS,
    SMART_MONEY_PERP_TRADES,
    MissingAPIKey,
    NansenError,
)
from hedge_fund.nansen.collect import collect, planned_requests
from hedge_fund.nansen.store import Snapshot, read_as_of

# Hand-written to the documented response shape, not captured traffic: every
# Nansen list endpoint answers with a "data" array beside a "pagination"
# object whose is_last_page says whether more is waiting.
ROW = {"chain": "ethereum", "token_symbol": "WETH", "value_usd": 1500000}


def page(number: int, *, last: bool) -> dict:
    return {
        "data": [ROW],
        "pagination": {"page": number, "per_page": 1000, "is_last_page": last},
    }


class FakeClient:
    """Answers posts from a script. Never touches the network."""

    def __init__(self, pages_per_endpoint: int = 1, fail: set[str] = frozenset()):
        self._pages = pages_per_endpoint
        self._fail = fail
        self.calls: list[tuple[str, dict]] = []

    def post(self, endpoint: str, body: dict):
        self.calls.append((endpoint, body))
        if endpoint in self._fail:
            raise NansenError(f"POST {endpoint} returned 500: boom", endpoint=endpoint)
        number = body["pagination"]["page"]
        return page(number, last=number >= self._pages)

    def close(self) -> None:
        pass


def test_a_round_covers_the_three_market_wide_endpoints():
    endpoints = [e for e, _ in planned_requests()]
    assert endpoints == [
        SMART_MONEY_HOLDINGS,
        SMART_MONEY_PERP_TRADES,
        PERP_LEADERBOARD,
    ]


def test_the_address_endpoints_are_skipped_when_no_address_is_given():
    endpoints = [e for e, _ in planned_requests()]
    assert PROFILER_PERP_POSITIONS not in endpoints
    assert PROFILER_ADDRESS_LABELS not in endpoints


def test_each_address_gets_its_positions_and_its_labels_per_chain():
    planned = planned_requests(["0xaaa"], ["ethereum", "solana"])
    per_address = [(e, p) for e, p in planned if p.get("address")]
    assert per_address == [
        (PROFILER_PERP_POSITIONS, {"address": "0xaaa"}),
        (PROFILER_ADDRESS_LABELS, {"address": "0xaaa", "chain": "ethereum"}),
        (PROFILER_ADDRESS_LABELS, {"address": "0xaaa", "chain": "solana"}),
    ]


def test_the_leaderboard_asks_for_the_last_day_that_had_closed():
    planned = dict(planned_requests(today=date(2026, 9, 20)))
    assert planned[PERP_LEADERBOARD] == {
        "date": {"from": "2026-09-19", "to": "2026-09-19"}
    }


def test_a_round_writes_one_snapshot_per_endpoint():
    result = collect(client=FakeClient())
    assert [a.error for a in result.attempts] == [None, None, None]
    for attempt in result.attempts:
        assert attempt.path.exists()
        assert attempt.complete


def test_a_written_snapshot_carries_the_payload_the_params_and_the_time():
    before = datetime.now(timezone.utc)
    result = collect(client=FakeClient())
    written = Snapshot.model_validate_json(result.attempts[0].path.read_text())
    assert written.endpoint == SMART_MONEY_HOLDINGS
    assert written.params == {"chains": ["ethereum"]}
    assert written.pages == [page(1, last=True)]
    assert written.collector_version
    assert before <= written.observed_at <= datetime.now(timezone.utc)


def test_the_params_recorded_leave_pagination_out():
    """Two runs asking the same question must compare equal."""
    result = collect(client=FakeClient(pages_per_endpoint=3))
    written = Snapshot.model_validate_json(result.attempts[0].path.read_text())
    assert "pagination" not in written.params


def test_paging_follows_is_last_page_to_the_end():
    client = FakeClient(pages_per_endpoint=3)
    result = collect(client=client)
    written = Snapshot.model_validate_json(result.attempts[0].path.read_text())
    assert len(written.pages) == 3
    assert written.complete


def test_a_page_cap_records_the_snapshot_as_partial_rather_than_whole():
    result = collect(client=FakeClient(pages_per_endpoint=9), max_pages=2)
    written = Snapshot.model_validate_json(result.attempts[0].path.read_text())
    assert len(written.pages) == 2
    assert not written.complete
    assert "cap" in written.note
    assert result.partial


def test_a_body_without_the_pagination_marker_is_recorded_as_unknown():
    class NoMarker(FakeClient):
        def post(self, endpoint, body):
            self.calls.append((endpoint, body))
            return {"data": [ROW]}

    result = collect(client=NoMarker())
    written = Snapshot.model_validate_json(result.attempts[0].path.read_text())
    assert not written.complete
    assert "is_last_page" in written.note


def test_a_failing_endpoint_writes_nothing_for_itself():
    result = collect(client=FakeClient(fail={SMART_MONEY_HOLDINGS}))
    failed = result.failures
    assert [a.endpoint for a in failed] == [SMART_MONEY_HOLDINGS]
    assert failed[0].path is None
    assert read_as_of(SMART_MONEY_HOLDINGS, datetime.now(timezone.utc)) is None


def test_a_failing_endpoint_does_not_discard_the_ones_that_answered():
    result = collect(client=FakeClient(fail={SMART_MONEY_HOLDINGS}))
    kept = [a for a in result.attempts if a.error is None]
    assert [a.endpoint for a in kept] == [
        SMART_MONEY_PERP_TRADES,
        PERP_LEADERBOARD,
    ]
    assert read_as_of(SMART_MONEY_PERP_TRADES, datetime.now(timezone.utc))


def test_no_api_key_writes_nothing_at_all(monkeypatch, tmp_path):
    monkeypatch.delenv("NANSEN_API_KEY", raising=False)
    with pytest.raises(MissingAPIKey):
        collect()
    assert read_as_of(SMART_MONEY_HOLDINGS, datetime.now(timezone.utc)) is None


def test_a_collected_round_is_what_a_later_as_of_read_finds():
    collect(client=FakeClient())
    found = read_as_of(SMART_MONEY_HOLDINGS, datetime.now(timezone.utc))
    assert found is not None
    assert found.pages[0]["data"] == [ROW]
