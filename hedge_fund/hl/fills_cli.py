"""`hl-collect-fills` -- archive one day's builder fill file per configured
builder, or walk a date range with --backfill.

Real data only: a day whose file isn't published yet (403/404 from the
archive host) is reported as a failure, not padded or retried in a loop.
Meant to be invoked on a schedule by something outside this repo/box --
nothing here creates a scheduled task, cron job, or daemon of its own.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone

from hedge_fund.hl.builders import load_builders
from hedge_fund.hl.fills_collect import collect_fills


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _yesterday_utc() -> date:
    # A day's file is only complete once the day itself has ended.
    return (datetime.now(timezone.utc) - timedelta(days=1)).date()


def _daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"--delay must be >= 0, got {value!r}")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date", type=_parse_date, default=None,
        help="day to fetch, UTC (YYYY-MM-DD); default yesterday UTC",
    )
    parser.add_argument(
        "--backfill", nargs=2, metavar=("START", "END"), type=_parse_date,
        help="walk an inclusive UTC date range (YYYY-MM-DD YYYY-MM-DD) instead of one day",
    )
    parser.add_argument(
        "--builder", action="append", dest="builders",
        help="builder address to fetch; repeatable. Overrides the configured list.",
    )
    parser.add_argument(
        "--delay", type=_non_negative_float, default=1.0,
        help="seconds to sleep between requests (default: 1.0)",
    )
    args = parser.parse_args()

    builders = args.builders or load_builders()
    days = list(_daterange(*args.backfill)) if args.backfill else [args.date or _yesterday_utc()]

    first = True
    for builder in builders:
        for day in days:
            if not first:
                time.sleep(args.delay)
            first = False

            result = collect_fills(builder, day)
            suffix = f" {result.path}" if result.path else ""
            print(f"{result.builder} {result.date}: {result.status}{suffix}")
            if result.status == "restated":
                print(f"  RESTATED: {result.detail}", file=sys.stderr)
            elif result.status == "failed":
                print(f"  FAILED: {result.detail}", file=sys.stderr)


if __name__ == "__main__":
    main()
