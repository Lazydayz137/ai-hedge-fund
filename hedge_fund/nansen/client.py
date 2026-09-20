"""Nansen API client — an apikey header, one POST, a loud failure.

Deliberately thin. Everything the collector needs is a POST with a JSON body;
anything cleverer would be a layer between what Nansen said and what gets
written down, which is the one thing this package exists not to have.

No retry and no rate limiter. The documented limits are 15 req/s and 300
req/min on the free plan, 75 req/s and 1,500 req/min on paid
(https://docs.nansen.ai/getting-started/rate-limits); a daily collector makes
single-digit requests per run and cannot reach them. A 429 here therefore
means something other than volume is wrong, and it should surface rather than
be slept off.

Endpoint paths were read off Nansen's public docs on 2026-09-20. Their
overview page lists the leaderboard as /profiler/perp-leaderboard while the
endpoint's own page gives /perp-leaderboard; the endpoint page wins here.
"""

from __future__ import annotations

import os
from typing import Any

import requests

# All five are POST. Verified against docs.nansen.ai, 2026-09-20.
SMART_MONEY_HOLDINGS = "/smart-money/holdings"
SMART_MONEY_PERP_TRADES = "/smart-money/perp-trades"
PERP_LEADERBOARD = "/perp-leaderboard"
PROFILER_PERP_POSITIONS = "/profiler/perp-positions"
PROFILER_ADDRESS_LABELS = "/profiler/address/labels"

API_KEY_ENV = "NANSEN_API_KEY"


class NansenError(Exception):
    """A Nansen request did not come back as a usable 200.

    Never swallowed into an empty result. A collector that turns a failed
    call into "no smart money today" writes a lie into a store whose whole
    value is that it cannot be silently revised.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        endpoint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint


class MissingAPIKey(NansenError):
    """No API key. Raised from the constructor, before anything is written."""


class NansenClient:
    """Usage::

        with NansenClient() as nansen:
            body = nansen.post(SMART_MONEY_HOLDINGS, {"chains": ["ethereum"]})
    """

    BASE_URL = "https://api.nansen.ai/api/v1"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        key = api_key or os.environ.get(API_KEY_ENV, "")
        if not key:
            raise MissingAPIKey(
                f"{API_KEY_ENV} is not set. This collector records what "
                "Nansen said; with no key there is nothing to record, and it "
                "will not invent a round."
            )
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers["apikey"] = key

    def __enter__(self) -> NansenClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def post(self, endpoint: str, body: dict[str, Any]) -> Any:
        """POST *body* to *endpoint* and return the decoded response."""
        try:
            resp = self._session.post(
                self.BASE_URL + endpoint, json=body, timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise NansenError(
                f"POST {endpoint} failed: {exc}", endpoint=endpoint,
            ) from exc

        # Every non-200 is an error, 404 included. Financial Datasets can say
        # "this ticker has no filings" with a 404; a Nansen label list that
        # answers 404 is a broken request, not an empty smart-money set.
        if resp.status_code != 200:
            raise NansenError(
                f"POST {endpoint} returned {resp.status_code}: "
                f"{resp.text[:200]}",
                status_code=resp.status_code,
                endpoint=endpoint,
            )

        try:
            return resp.json()
        except ValueError as exc:
            raise NansenError(
                f"POST {endpoint} returned 200 with a body that is not JSON: "
                f"{resp.text[:200]}",
                status_code=resp.status_code,
                endpoint=endpoint,
            ) from exc
