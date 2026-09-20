"""`hl-collect` -- run one Hyperliquid market-state collection pass.

Hits native perps, every HIP-3 builder-deployed perp DEX, and spot once,
writes the snapshot, and prints what it wrote. Meant to be invoked on a
schedule by something outside this repo/box -- nothing here creates a
scheduled task, cron job, or daemon of its own.
"""

from __future__ import annotations

import sys

from hedge_fund.hl.collect import collect_snapshot
from hedge_fund.hl.store import save_snapshot


def main() -> None:
    snapshot = collect_snapshot()
    path = save_snapshot(snapshot)

    n_native = sum(1 for r in snapshot.perp_rows if r.dex == "")
    n_hip3 = sum(1 for r in snapshot.perp_rows if r.dex != "")
    n_spot = len(snapshot.spot_rows)

    print(f"wrote {path}")
    print(
        f"perp native={n_native} hip3={n_hip3} spot={n_spot} "
        f"dex_configs={len(snapshot.dexes)} failures={len(snapshot.failures)}"
    )
    for failure in snapshot.failures:
        print(f"  FAILED {failure.scope}: {failure.error}", file=sys.stderr)


if __name__ == "__main__":
    main()
