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
# Market snapshots are an archive, not a cache: nothing here is ever
# refetchable, because no vendor sells the history of a perp's funding and
# basis after the fact. Kept out of CACHE_DIR so that clearing the cache
# can never take the archive with it.
SNAPSHOTS_DIR = USER_DIR / "market-snapshots"
ENV_PATH = USER_DIR / ".env"

# The example mandate ships inside the package; it is copied out (never read
# in place) so users edit their copy, not the install.
EXAMPLE_MANDATE = Path(__file__).resolve().parent / "fund" / "example.yaml"


def ensure_mandates_dir() -> Path:
    """Create the mandates dir on first use, seeded with the example."""
    if not MANDATES_DIR.exists():
        MANDATES_DIR.mkdir(parents=True)
        shutil.copy(EXAMPLE_MANDATE, MANDATES_DIR / "example.yaml")
    return MANDATES_DIR
