"""Loads the configured list of builder addresses for fill archiving.

The list is data, not code -- see builders.json alongside this module.
Addresses are lower-cased on load so callers never have to think about
casing when joining against archive directory names.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "builders.json"


def load_builders(path: Path | None = None) -> list[str]:
    """Every configured builder address, lower-cased."""
    entries = json.loads((path or DEFAULT_CONFIG_PATH).read_text(encoding="utf-8"))
    return [entry["address"].lower() for entry in entries]
