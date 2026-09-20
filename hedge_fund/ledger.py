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

import json
import sys
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
    # Exclusive creation rather than exists()-then-write: two runs racing here
    # would both pass the check and one would land on top of the other.
    suffix = 1
    while True:
        try:
            with path.open("x") as handle:
                handle.write(record.model_dump_json(indent=2))
            return path
        except FileExistsError:
            suffix += 1
            path = paths.MANDATES_DIR / f"{record.fund}-run-{stamp}-{suffix}.json"


def latest_run(fund: str, as_of: str | None = None) -> CycleRecord | None:
    """The newest book *fund* held at or before *as_of*, or None if it has none.

    Ordered by the cycle's own as-of date, not by when the file was written.
    Those differ the moment someone runs a historical date after a recent one,
    and resuming by mtime would hand a 2024 cycle the book from a 2026 run —
    lookahead smuggled in through the ledger, in a pipeline whose whole promise
    is that a cycle sees only what was knowable on its date.

    A receipt is only accepted if it names this fund: the filename can be
    renamed or hand-edited, and resuming the wrong fund's cash and positions
    would be silent. Backtest receipts share the directory but not the -run-
    infix, so they never match.

    If the *newest* eligible receipt turns out to be unreadable, this returns
    None and says so on stderr rather than falling back to an older one. The
    older book predates trades that already happened, so resuming it would
    re-execute them against real cash — quietly, and looking like a normal run.
    Starting fresh from the mandate is the visible failure; silently rewinding
    the fund is not. Receipts that fail the cheap peek are still skipped, since
    one truncated file in a long history should cost the resume, not the run.
    """
    eligible: list[tuple[str, float, Path]] = []
    for path in paths.MANDATES_DIR.glob(f"{fund}-run-*.json"):
        try:
            # Peek at the two fields that decide eligibility rather than
            # validating every receipt in the fund's history on every run.
            peek = json.loads(path.read_text())
            when = peek["as_of"]
            if peek["fund"] != fund or (as_of is not None and when > as_of):
                continue
            eligible.append((when, path.stat().st_mtime, path))
        except (OSError, ValueError, KeyError, TypeError):
            continue

    if not eligible:
        return None

    # mtime breaks ties only: two receipts can share an as-of date when a
    # cycle is re-run, and the later write is the one that stands.
    _, _, newest = max(eligible)
    try:
        return CycleRecord.model_validate_json(newest.read_text())
    except (OSError, ValueError) as exc:
        print(
            f"ledger: {fund}'s newest receipt {newest.name} is unreadable "
            f"({exc.__class__.__name__}); not resuming. Fix or move it aside "
            f"rather than letting this run start from the mandate's capital.",
            file=sys.stderr,
        )
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
