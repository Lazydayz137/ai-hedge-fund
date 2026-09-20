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


def test_unparseable_receipt_is_skipped_not_fatal():
    """A truncated file names no as-of date, so it was never a candidate."""
    older = save_run(_record(as_of="2024-06-03"))
    _age(older, 600)
    newer = save_run(_record(as_of="2024-06-10"))
    newer.write_text("{ this is not json")
    loaded = latest_run("ledger-test")
    assert loaded is not None
    assert loaded.as_of == "2024-06-03"


def test_newest_receipt_failing_validation_refuses_to_resume(capsys):
    """Rewinding to an older book would re-execute trades that already happened.

    The file parses and names a newer date, so it IS the book to resume — it
    just cannot be loaded. Falling back to 06-03 would hand the fund a book
    from before a week of fills, and nothing on screen would say so.
    """
    _age(save_run(_record(as_of="2024-06-03")), 600)
    newer = save_run(_record(as_of="2024-06-10"))
    newer.write_text('{"fund": "ledger-test", "as_of": "2024-06-10"}')

    assert latest_run("ledger-test") is None
    assert newer.name in capsys.readouterr().err


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


def test_resume_refuses_a_position_with_neither_basis_nor_mark():
    """The zero-basis case the test above exists to avoid, reached the other way.

    run_cycle will not write this receipt — it raises rather than mark a held
    name it cannot price — but a reader cannot lean on the writer's promise.
    Booking the whole position as profit on its next sale is a wrong number
    that looks like a return, so refuse the resume instead.
    """
    orphan = _record(positions={"AAPL": 10}, cost_basis={}, marks={"MSFT": 50.0})
    with pytest.raises(ValueError, match="AAPL"):
        resume_broker(orphan)


def test_resume_keeps_a_basis_of_zero_rather_than_falling_back_to_the_mark():
    """A recorded basis is a fact about the receipt, falsy or not."""
    broker = resume_broker(_record(cost_basis={"AAPL": 0.0}, marks={"AAPL": 100.0}))
    assert broker.positions()["AAPL"].cost_basis == pytest.approx(0.0)


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


# --- picking the right receipt ----------------------------------------------


def test_cutoff_refuses_a_book_from_after_the_cycle():
    """A historical run must not resume a book from a later date.

    Receipts are ordered by the cycle's as-of date, not by when the file landed.
    Run today, then run a 2024 date, and mtime ordering would hand the 2024
    cycle today's positions — lookahead arriving through the ledger.
    """
    save_run(_record(as_of="2024-01-10", positions={"AAPL": 5}))
    save_run(_record(as_of="2026-09-20", positions={"AAPL": 999}))
    resumed = latest_run("ledger-test", as_of="2024-06-01")
    assert resumed is not None
    assert resumed.as_of == "2024-01-10"
    assert resumed.positions == {"AAPL": 5}


def test_cutoff_is_inclusive_of_its_own_date():
    save_run(_record(as_of="2024-06-01"))
    assert latest_run("ledger-test", as_of="2024-06-01").as_of == "2024-06-01"


def test_no_eligible_receipt_reads_as_no_prior_book():
    save_run(_record(as_of="2026-09-20"))
    assert latest_run("ledger-test", as_of="2024-01-01") is None


def test_as_of_beats_write_order():
    """Written second, dated earlier — the later-dated book still wins."""
    save_run(_record(as_of="2026-01-01", positions={"AAPL": 7}))
    save_run(_record(as_of="2024-01-01", positions={"AAPL": 3}))
    assert latest_run("ledger-test").positions == {"AAPL": 7}


def test_a_receipt_naming_another_fund_is_refused():
    """The filename can lie; the record cannot.

    A renamed or hand-edited receipt that matches the glob but carries another
    fund's book would otherwise be resumed as this fund's cash and positions.
    """
    impostor = _record(fund="someone-else", positions={"AAPL": 999})
    (paths.MANDATES_DIR).mkdir(parents=True, exist_ok=True)
    (paths.MANDATES_DIR / "ledger-test-run-2026-01-01-000000.json").write_text(
        impostor.model_dump_json()
    )
    assert latest_run("ledger-test") is None
