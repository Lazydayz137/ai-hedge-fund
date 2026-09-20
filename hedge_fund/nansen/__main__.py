"""Collect one round of Nansen snapshots. Built to be cron'd.

Usage::

    nansen-snapshot
    poetry run python -m hedge_fund.nansen

    nansen-snapshot --address 0xa312... --address 0xb4f1... --chain ethereum

The full Collection prints to stdout as JSON — pipe it into a log — and a
short human summary goes to stderr, the same split `aihf` uses.

Exit codes: 0 every endpoint answered, 1 at least one failed (the snapshots
that did arrive were still written), 2 there was no API key and so nothing
was attempted or written.

A daily crontab line, which is the only way this is worth anything::

    17 0 * * *  cd /path/to/ai-hedge-fund && poetry run nansen-snapshot >> ~/.hedge-fund/nansen.log 2>&1
"""

from __future__ import annotations

import argparse
import sys

from hedge_fund.nansen.client import API_KEY_ENV, MissingAPIKey
from hedge_fund.nansen.collect import DEFAULT_MAX_PAGES, collect


def _page_cap(value: str) -> int:
    """An argparse type that refuses a cap no page could satisfy."""
    pages = int(value)
    if pages < 1:
        raise argparse.ArgumentTypeError(
            f"must be at least 1, got {pages}"
        )
    return pages


def main() -> None:
    """Run one snapshot round, and exit non-zero if any endpoint failed.

    Built to be cron'd, so the exit code is the whole interface: 0 wrote
    everything asked for, 1 something failed and the archive has a hole in
    it, 2 there is no API key and nothing was attempted.
    """
    parser = argparse.ArgumentParser(
        prog="nansen-snapshot",
        description="Snapshot Nansen's smart-money and perp endpoints, keyed "
        "by the time they were observed, so a backtest can read the labels "
        "as they stood rather than as they were later recomputed.",
    )
    parser.add_argument(
        "--address", action="append", default=[], metavar="0x...",
        help="an address to snapshot perp positions and labels for; repeat "
        "for more. Omit and the two address-scoped endpoints are skipped.",
    )
    parser.add_argument(
        "--chain", action="append", default=[], metavar="CHAIN",
        help="chain to ask about, e.g. ethereum or solana; repeat for more "
        "(default: ethereum)",
    )
    parser.add_argument(
        "--max-pages", type=_page_cap, default=DEFAULT_MAX_PAGES,
        help=f"stop paging an endpoint after this many pages and record the "
        f"snapshot as partial (default: {DEFAULT_MAX_PAGES})",
    )
    args = parser.parse_args()

    try:
        result = collect(
            addresses=args.address,
            chains=args.chain or ("ethereum",),
            max_pages=args.max_pages,
        )
    except MissingAPIKey as exc:
        print(f"{exc}", file=sys.stderr)
        print(f"Set {API_KEY_ENV} and run again.", file=sys.stderr)
        raise SystemExit(2)

    print(result.model_dump_json(indent=2))

    written = [a for a in result.attempts if a.error is None]
    print(
        f"{len(written)}/{len(result.attempts)} endpoints snapshotted at "
        f"{result.started_at.isoformat()}",
        file=sys.stderr,
    )
    for attempt in result.partial:
        print(f"  partial: {attempt.endpoint}", file=sys.stderr)
    for attempt in result.failures:
        print(f"  FAILED:  {attempt.endpoint}: {attempt.error}", file=sys.stderr)

    raise SystemExit(1 if result.failures else 0)


if __name__ == "__main__":
    main()
