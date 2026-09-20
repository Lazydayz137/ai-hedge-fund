"""Take one snapshot of Hyperliquid's perps and file it.

Usage::

    hl-snapshot
        Collect every listed perp and write the pass to
        ~/.hedge-fund/market-snapshots/. A one-line summary goes to stderr.

    hl-snapshot --json
        Also print the whole snapshot to stdout, for piping somewhere else.

    hl-snapshot --dry-run
        Collect and summarize, write nothing.

Built to be cron'd — the value of this archive is entirely in its density,
and a snapshot not taken is a row that can never be recovered::

    */5 * * * * /path/to/hl-snapshot

The exit code is 1 if the pass recorded any error, so a scheduler that
watches exit codes notices a venue outage instead of quietly banking hours
of empty archive.
"""

from __future__ import annotations

import argparse
import sys

from hedge_fund.hyperliquid.collector import collect, save_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hl-snapshot",
        description="Snapshot Hyperliquid perp funding, open interest, mark "
        "and oracle — native and HIP-3 builder markets — to "
        "~/.hedge-fund/market-snapshots/.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="print the full snapshot JSON to stdout as well as filing it",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="collect and summarize without writing anything to the archive",
    )
    args = parser.parse_args()

    snapshot = collect()
    builder = [o for o in snapshot.observations if o.dex]
    live = [o for o in snapshot.observations if not o.is_delisted]

    if not args.dry_run:
        path = save_snapshot(snapshot)
        print(f"wrote {path}", file=sys.stderr)
    print(
        f"{snapshot.started_at}  {len(snapshot.observations)} instruments "
        f"({len(snapshot.observations) - len(builder)} native, {len(builder)} HIP-3; "
        f"{len(live)} listed, {len(snapshot.observations) - len(live)} delisted)  "
        f"{len(snapshot.errors)} errors",
        file=sys.stderr,
    )
    for err in snapshot.errors:
        print(f"  ! {err.scope}: {err.reason}", file=sys.stderr)

    if args.json:
        print(snapshot.model_dump_json(indent=2))

    sys.exit(1 if snapshot.errors else 0)


if __name__ == "__main__":
    main()
