"""FundamentalsSnapshot tests — mocked data client, no network."""

import pytest

from hedge_fund.data.models import CompanyFacts, FinancialMetrics
from hedge_fund.features.snapshot import InsufficientData, build_snapshot


class MockDataClient:
    """Returns canned metrics; records what it was asked for."""

    def __init__(self, metrics=None, facts=None):
        self._metrics = metrics or []
        self._facts = facts
        self.metrics_calls = []

    def get_financial_metrics(self, ticker, end_date, period="ttm", limit=10):
        self.metrics_calls.append(
            {"ticker": ticker, "end_date": end_date, "period": period, "limit": limit}
        )
        return self._metrics

    def get_company_facts(self, ticker):
        return self._facts


def _metric(report_period, **kwargs):
    """One metrics row with plausible defaults; override any field by keyword."""
    defaults = {
        "ticker": "TEST",
        "period": "ttm",
        "filing_date": report_period,  # simplification for tests
        "return_on_equity": 0.20,
        "net_margin": 0.25,
        "gross_margin": 0.40,
        "book_value_per_share": 10.0,
        "debt_to_equity": 0.5,
        "market_cap": 1e9,
    }
    defaults.update(kwargs)
    return FinancialMetrics(report_period=report_period, **defaults)


def _history(n=8):
    """n periods, newest first, quarter-spaced."""
    quarters = ["2024-12-31", "2024-09-30", "2024-06-30", "2024-03-31",
                "2023-12-31", "2023-09-30", "2023-06-30", "2023-03-31"]
    return [_metric(q) for q in quarters[:n]]


def test_as_of_passes_through_to_data_client():
    """as_of reaches the data layer verbatim, so the server-side filing_date cut
    is applied to the same date the caller asked about."""
    client = MockDataClient(metrics=_history())
    build_snapshot("TEST", "2025-01-15", client)
    call = client.metrics_calls[0]
    assert call["end_date"] == "2025-01-15"
    assert call["ticker"] == "TEST"


def test_insufficient_data_raises():
    """Too little history raises rather than prompting an analyst on thin data."""
    client = MockDataClient(metrics=_history(3))  # below MIN_PERIODS
    with pytest.raises(InsufficientData):
        build_snapshot("TEST", "2025-01-15", client)


def test_aggregates():
    """The derived numbers are computed here in Python, so the LLM is handed facts
    instead of being asked to do arithmetic it is bad at."""
    metrics = _history(4)
    # oldest gross margin 0.30, newest 0.40 -> trend +0.10
    metrics[-1] = _metric("2024-03-31", gross_margin=0.30)
    # BVPS oldest 8.0 -> newest 10.0 over 3 quarters (0.75y)
    metrics[-1].book_value_per_share = 8.0
    client = MockDataClient(metrics=metrics)

    snap = build_snapshot("TEST", "2025-01-15", client)

    assert snap.roe_avg == pytest.approx(0.20)
    assert snap.gross_margin_trend == pytest.approx(0.10)
    assert snap.debt_to_equity_latest == pytest.approx(0.5)
    assert snap.market_cap_latest == pytest.approx(1e9)
    assert snap.bvps_cagr == pytest.approx((10.0 / 8.0) ** (1 / 0.75) - 1, abs=1e-4)


def test_market_cap_comes_from_pit_metrics_not_facts():
    """company_facts market cap is latest-only (lookahead); the snapshot must
    use the most recent FILED metrics row instead."""
    facts = CompanyFacts(ticker="TEST", sector="Tech")
    client = MockDataClient(metrics=_history(), facts=facts)

    # as_of must post-date the canned rows: the mock ignores end_date, so the
    # point-in-time cut is applied in build_snapshot, not by this client.
    snap = build_snapshot("TEST", "2025-01-15", client)

    assert snap.market_cap_latest == pytest.approx(1e9)  # from metrics row
    assert snap.sector == "Tech"  # facts used only for slow-moving attributes


def test_same_day_filing_is_excluded():
    """A row filed on the cycle date itself is not point-in-time knowable at the
    as-of close the cycle trades at, so it must not reach the LLM prompt."""
    metrics = _history(5)
    metrics[0] = _metric("2024-12-31", filing_date="2025-01-15")
    client = MockDataClient(metrics=metrics)

    snap = build_snapshot("TEST", "2025-01-15", client)

    assert [p.filing_date for p in snap.periods] == [
        m.filing_date for m in metrics[1:]
    ]
    assert snap.market_cap_latest == pytest.approx(metrics[1].market_cap)


def test_prior_day_filing_is_included():
    """The day-before filing IS knowable and stays — the cut is strict, not a
    blanket one-period haircut."""
    metrics = _history(5)
    metrics[0] = _metric("2024-12-31", filing_date="2025-01-14")
    client = MockDataClient(metrics=metrics)

    snap = build_snapshot("TEST", "2025-01-15", client)

    assert snap.periods[0].filing_date == "2025-01-14"
    assert len(snap.periods) == 5


def test_same_day_filings_can_starve_the_snapshot():
    """Dropping same-day rows can push history below MIN_PERIODS; that must
    raise InsufficientData rather than quietly prompting on a short history."""
    metrics = [_metric(q, filing_date="2025-01-15") for q in
               ("2024-12-31", "2024-09-30")] + _history(2)
    client = MockDataClient(metrics=metrics)

    with pytest.raises(InsufficientData):
        build_snapshot("TEST", "2025-01-15", client)


def test_content_hash_stable_and_sensitive():
    """The cache key turns on the data alone: identical history is a free hit, a
    changed filing is a genuine miss."""
    client_a = MockDataClient(metrics=_history())
    client_b = MockDataClient(metrics=_history())
    snap_a = build_snapshot("TEST", "2025-01-15", client_a)
    snap_b = build_snapshot("TEST", "2025-01-15", client_b)
    assert snap_a.content_hash == snap_b.content_hash  # same data -> same key

    changed = _history()
    changed[0] = _metric("2024-12-31", return_on_equity=0.35)
    snap_c = build_snapshot("TEST", "2025-01-15", MockDataClient(metrics=changed))
    assert snap_c.content_hash != snap_a.content_hash  # new filing -> new key


def test_same_data_different_as_of_same_render_and_hash():
    """Between filings the snapshot is unchanged — the hash and the rendered
    prompt must be identical on any as-of date, or the LLM cache never hits."""
    snap_jan = build_snapshot("TEST", "2025-01-15", MockDataClient(metrics=_history()))
    snap_feb = build_snapshot("TEST", "2025-02-15", MockDataClient(metrics=_history()))

    assert snap_jan.as_of != snap_feb.as_of  # the field itself still differs
    assert snap_jan.content_hash == snap_feb.content_hash
    assert snap_jan.render() == snap_feb.render()


def test_render_contains_the_facts():
    """The prompt carries the filed history but never the as-of date, which would
    both break the cache and let the model anchor on post-date world events."""
    snap = build_snapshot("TEST", "2025-01-15", MockDataClient(metrics=_history()))
    text = snap.render()
    assert "2025-01-15" not in text  # as_of must never leak into the prompt
    assert "2024-12-31" in text
    assert "publicly filed" in text
