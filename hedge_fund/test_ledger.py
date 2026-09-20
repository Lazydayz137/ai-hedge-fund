"""Ledger tests — saving a run's receipt and resuming the book from it."""

import os

import pytest

from hedge_fund import paths
from hedge_fund.fund.spec import FundSpec
from hedge_fund.ledger import latest_run, resume_broker, save_run
from hedge_fund.pipeline.models import CycleRecord

SPEC = FundSpec(
    name="ledger-test",
    strategies=[{"name": "solo", "models": [{"name": "a"}]}],
    risk={"max_position_pct": 1.0, "max_gross_exposure": 1.0},
    capital=100_000.0,
)


def _record(**over) -> CycleRecord:
    base = dict(
        fund="ledger-test", as_of="2024-06-03", spec=SPEC, universe=["AAPL"],
        marks={"AAPL": 100.0}, skipped=[], strategies=[], target_weights={},
        clamps=[], final_weights={}, equity_before=100_000.0,
        cash_before=100_000.0, orders=[], fills=[],
        positions={"AAPL": 10}, cost_basis={"AAPL": 95.0},
        cash=99_050.0, nav=100_050.0, realized_pnl=0.0,
    )
    base.update(over)
    return CycleRecord(**base)


def _age(path, seconds):
    """Backdate a receipt so newest-first ordering is testable.

    The filename stamp is second-resolution, so two saves in one test would
    otherwise be indistinguishable by mtime.
    """
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime - seconds))


# --- finding a receipt ------------------------------------------------------


def test_no_receipts_means_no_prior_book():
    assert latest_run("never-run") is None


def test_saved_run_round_trips():
    saved = save_run(_record())
    assert saved.parent == paths.MANDATES_DIR
    loaded = latest_run("ledger-test")
    assert loaded is not None
    assert loaded.positions == {"AAPL": 10}
    assert loaded.cost_basis == {"AAPL": 95.0}


def test_newest_receipt_wins():
    _age(save_run(_record(as_of="2024-06-03")), 600)
    save_run(_record(as_of="2024-06-10", positions={"AAPL": 25}))
    loaded = latest_run("ledger-test")
    assert loaded.as_of == "2024-06-10"
    assert loaded.positions == {"AAPL": 25}


def test_unreadable_receipt_is_skipped_not_fatal():
    """A truncated file should cost the resume, not the run."""
    older = save_run(_record(as_of="2024-06-03"))
    _age(older, 600)
    newer = save_run(_record(as_of="2024-06-10"))
    newer.write_text("{ this is not json")
    loaded = latest_run("ledger-test")
    assert loaded is not None
    assert loaded.as_of == "2024-06-03"


def test_backtest_receipts_are_not_run_receipts():
    (paths.MANDATES_DIR).mkdir(parents=True, exist_ok=True)
    (paths.MANDATES_DIR / "ledger-test-backtest-2024.json").write_text("{}")
    assert latest_run("ledger-test") is None


def test_another_funds_receipts_are_not_borrowed():
    save_run(_record(fund="other-fund"))
    assert latest_run("ledger-test") is None


# --- rebuilding the book ----------------------------------------------------


def test_resume_restores_cash_shares_and_basis():
    broker = resume_broker(_record())
    assert broker.cash() == pytest.approx(99_050.0)
    position = broker.positions()["AAPL"]
    assert position.shares == 10
    assert position.cost_basis == pytest.approx(95.0)


def test_resume_carries_a_short():
    broker = resume_broker(_record(positions={"AAPL": -4}, cost_basis={"AAPL": 120.0}))
    position = broker.positions()["AAPL"]
    assert position.shares == -4
    assert position.cost_basis == pytest.approx(120.0)


def test_resume_drops_closed_positions():
    broker = resume_broker(_record(positions={"AAPL": 10, "MSFT": 0},
                                   cost_basis={"AAPL": 95.0, "MSFT": 50.0}))
    assert set(broker.positions()) == {"AAPL"}


def test_resume_rebases_receipts_that_predate_cost_basis():
    """Old receipts carry shares but no basis; the mark is the honest stand-in.

    A basis of zero would book the whole position as profit on the next sale.
    """
    broker = resume_broker(_record(cost_basis={}, marks={"AAPL": 100.0}))
    assert broker.positions()["AAPL"].cost_basis == pytest.approx(100.0)


def test_resumed_book_realizes_from_the_resume_point():
    broker = resume_broker(_record())  # 10 AAPL at 95
    from hedge_fund.brokers.models import Order
    fill = broker.place_order(Order(ticker="AAPL", side="sell", quantity=10, price=105.0))
    assert fill.realized_pnl == pytest.approx(10 * 10.0)
    assert broker.realized_pnl() == pytest.approx(100.0)


def test_resume_starts_realized_pnl_at_zero():
    """Each session reports what it realized, not what it inherited."""
    assert resume_broker(_record(realized_pnl=4_321.0)).realized_pnl() == 0.0


def test_two_runs_in_one_second_both_survive():
    """Second-resolution stamps collide; neither entry may be lost."""
    first = save_run(_record(as_of="2024-06-03"))
    second = save_run(_record(as_of="2024-06-04"))
    assert first != second
    assert first.exists() and second.exists()
    assert len(list(paths.MANDATES_DIR.glob("ledger-test-run-*.json"))) == 2
