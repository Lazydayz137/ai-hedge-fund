"""Where user data lives: ~/.hedge-fund/.

Everything the user owns — mandates, run/backtest receipts, API caches, and
the .env key file — lives under one home directory, outside the package. The
package directory stays read-only code, so a pipx install behaves exactly
like a checkout.

Textual-free and import-light on purpose: every layer (CLI, TUI, caches)
anchors its paths here, and nothing here may import them back.
"""

from __future__ import annotations

import shutil
from pathlib import Path

USER_DIR = Path.home() / ".hedge-fund"
MANDATES_DIR = USER_DIR / "mandates"
CACHE_DIR = USER_DIR / "cache"
# Nansen label snapshots are an archive, not a cache: the smart-money set
# is continuously recomputed, so a snapshot missed on the day it was true
# cannot be refetched later at any price. Kept out of CACHE_DIR so that
# clearing the cache can never take the archive with it.
NANSEN_DIR = USER_DIR / "nansen-snapshots"
ENV_PATH = USER_DIR / ".env"

# Separate from CACHE_DIR on purpose: a cache entry may be silently evicted
# or refreshed (it's a memo of a request that can be re-fetched). An archive
# entry is a historical observation that can never be re-fetched once its
# moment has passed, so nothing that treats the cache as disposable may
# treat this the same way.
ARCHIVE_DIR = USER_DIR / "archive"

# The validation store: pre-registrations, the trial ledger, and the record of
# every holdout reveal. An archive for the same reason the two above are, and
# for a sharper one: a forgotten trial does not degrade a result, it improves
# it. The Deflated Sharpe threshold rises with the trial count, so losing
# trials is the one storage failure that makes a strategy look better than it
# is, and it looks like nothing at all from the outside.
VALIDATION_DIR = USER_DIR / "validation"

# The example mandate ships inside the package; it is copied out (never read
# in place) so users edit their copy, not the install.
EXAMPLE_MANDATE = Path(__file__).resolve().parent / "fund" / "example.yaml"


def ensure_mandates_dir() -> Path:
    """Create the mandates dir on first use, seeded with the example."""
    if not MANDATES_DIR.exists():
        MANDATES_DIR.mkdir(parents=True)
        shutil.copy(EXAMPLE_MANDATE, MANDATES_DIR / "example.yaml")
    return MANDATES_DIR
