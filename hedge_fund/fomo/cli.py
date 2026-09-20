"""`fomo-collect` — one pass over FOMO's sponsored flow, built to be cron'd."""

from __future__ import annotations

import argparse
import sys

from hedge_fund.fomo.client import RPC_URL_ENV, SolanaClient
from hedge_fund.fomo.collect import DEFAULT_MAX_TRANSACTIONS, collect_and_save
from hedge_fund.fomo.store import CorruptCursor


def _positive(value: str) -> int:
    """An argparse type that refuses a cap no transaction could satisfy."""
    count = int(value)
    if count < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {count}")
    return count


def main() -> None:
    """Collect one pass and exit non-zero if anything was missed.

    The exit code is the whole interface for a scheduled run: 0 collected
    everything back to the cursor, 1 something failed or the cap cut the
    window short and the archive has a hole this pass did not fill.
    """
    parser = argparse.ArgumentParser(
        prog="fomo-collect",
        description="Archive FOMO's Solana flow from its gas-sponsor address. "
                    "Reads the chain only — no FOMO API, no scraping, no key.",
    )
    parser.add_argument(
        "--max-transactions", type=_positive, default=DEFAULT_MAX_TRANSACTIONS,
        help=f"stop after this many and leave the cursor where it was "
             f"(default: {DEFAULT_MAX_TRANSACTIONS})",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="ignore the stored cursor and walk back from the newest signature",
    )
    parser.add_argument(
        "--rpc", default=None,
        help=f"Solana JSON-RPC endpoint (or set {RPC_URL_ENV}); the public "
             "default is rate limited too hard for a historical backfill",
    )
    args = parser.parse_args()

    try:
        result, path = collect_and_save(
            client=SolanaClient(args.rpc),
            max_transactions=args.max_transactions,
            resume=not args.fresh,
        )
    except CorruptCursor as exc:
        print(f"{exc}", file=sys.stderr)
        print("Fix or remove the cursor; resuming from the newest signature "
              "would leave a hole in the middle of the archive.", file=sys.stderr)
        raise SystemExit(2)

    users = {t.user for t in result.transactions if t.user}
    print(f"wrote {path}")
    print(
        f"{result.observed_at:%Y-%m-%dT%H:%M:%SZ}  "
        f"{len(result.transactions)} transactions, {len(users)} distinct users, "
        f"{len(result.errors)} errors"
        + ("" if result.reached_cursor else "  [CAPPED — cursor not advanced]"),
        file=sys.stderr,
    )
    raise SystemExit(0 if result.reached_cursor and not result.errors else 1)
