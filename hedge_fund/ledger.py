"""The ledger's read half — resuming a fund's book from its last receipt.

Every run writes a CycleRecord. Writing alone leaves a pile of unrelated
snapshots, each starting over from the mandate's capital; reading the newest
one back is what makes NAV a track record instead of a number that resets.

Receipts live beside mandates under ~/.hedge-fund/ as {fund}-run-{stamp}.json,
the convention the TUI's history pane already globs, so a CLI run and a TUI
run land in the same history and can resume from each other.

Textual-free like paths.py: resuming is a CLI concern too, and nothing here
may reach back into the UI that happens to share the directory.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hedge_fund.brokers.models import Commission
from hedge_fund.brokers.sim import SimBroker
from hedge_fund import paths
from hedge_fund.pipeline.models import CycleRecord


def save_run(record: CycleRecord) -> Path:
    """Write a run's receipt where the next run — and the TUI — will find it."""
    # Looked up through the module, not bound at import: tests redirect it,
    # and nothing should be able to write a receipt into a real fund's
    # history by accident.
    paths.MANDATES_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    path = paths.MANDATES_DIR / f"{record.fund}-run-{stamp}.json"
    # The stamp only resolves to the second, so two runs inside one second
    # would land on the same name. A ledger that quietly overwrites an entry
    # is not a ledger, and a scripted caller hits this far sooner than a human
    # clicking through the app does.
    suffix = 2
    while path.exists():
        path = paths.MANDATES_DIR / f"{record.fund}-run-{stamp}-{suffix}.json"
        suffix += 1
    path.write_text(record.model_dump_json(indent=2))
    return path


def latest_run(fund: str) -> CycleRecord | None:
    """The newest run receipt for *fund*, or None if it has never run.

    An unreadable receipt is skipped rather than raised: a hand-edited or
    truncated file should cost a fund the resume, not the run. Backtest
    receipts share the directory but not the -run- infix, so they never match.
    """
    receipts = sorted(
        paths.MANDATES_DIR.glob(f"{fund}-run-*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in receipts:
        try:
            return CycleRecord.model_validate_json(path.read_text())
        except (OSError, ValueError):
            continue
    return None


def resume_broker(
    record: CycleRecord, commission: Commission | None = None
) -> SimBroker:
    """Rebuild the book *record* ended with: its cash, shares, and cost basis.

    Receipts written before cost basis existed carry shares but no basis. Those
    positions are re-based at the marks the receipt already stores, so the
    resumed book earns from the resume point forward. The alternative — a basis
    of zero — would book the entire position as profit the first time it sold,
    which is worse than merely losing the history.

    Realized P&L is deliberately not carried: each receipt records its own
    cycle's realized gains, and a fund's lifetime total is the sum across its
    receipts. That keeps one number from being restated by every resume.
    """
    held = {t: s for t, s in record.positions.items() if s != 0}
    basis = {
        t: record.cost_basis.get(t) or record.marks.get(t, 0.0) for t in held
    }
    return SimBroker.resume(
        cash=record.cash, positions=held, cost_basis=basis, commission=commission
    )
