"""HTTP client for Hyperliquid's per-builder daily fill archive.

A plain unauthenticated GET against a fixed URL template -- not the /info
POST endpoint client.py wraps, and on a different host entirely. Every
response is handed back as-is (status code + body); callers decide what a
non-200 means (a day that hasn't published yet is an expected result, not
an error), so this module only raises for a genuine transport failure.
"""

from __future__ import annotations

from datetime import date

import requests

BASE_URL = "https://stats-data.hyperliquid.xyz/Mainnet/builder_fills"


class FillDownloadError(Exception):
    """The GET itself failed for infrastructure reasons (network, timeout).

    Distinct from a clean non-200 response, which callers read from the
    returned status code instead of an exception.
    """


def fetch_raw(address: str, day: date, *, timeout: float = 30.0) -> tuple[int, bytes]:
    """GET one builder's daily fill file. Returns (status_code, body).

    Never raises for a non-2xx response.
    """
    url = f"{BASE_URL}/{address}/{day:%Y%m%d}.csv.lz4"
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise FillDownloadError(f"GET {url} failed: {exc}") from exc
    return resp.status_code, resp.content
