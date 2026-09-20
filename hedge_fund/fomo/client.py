"""A thin reader over a Solana JSON-RPC endpoint. Reads only."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

RPC_URL_ENV = "SOLANA_RPC_URL"

# The public cluster works and needs no key, which is why it is the default —
# but it is rate limited hard enough that a full historical walk will not
# finish on it. Point SOLANA_RPC_URL at a paid endpoint for backfills; the
# incremental passes this collector is built for fit inside the public tier.
DEFAULT_RPC = "https://api.mainnet-beta.solana.com"

TIMEOUT_SECONDS = 30

# getSignaturesForAddress caps at 1000 per call and returns newest first.
SIGNATURE_PAGE = 1000


class SolanaError(RuntimeError):
    """The endpoint could not be read, or answered with an error."""


class SolanaClient:
    """One endpoint, one timeout, no retry.

    No backoff on purpose: a retry here would paper over someone else's rate
    limit and put a stale reading under a fresh timestamp. A pass that could
    not finish says so and stops at a cursor the next pass resumes from.
    """

    def __init__(self, url: str | None = None, *, timeout: int = TIMEOUT_SECONDS):
        self.url = url or os.environ.get(RPC_URL_ENV) or DEFAULT_RPC
        self.timeout = timeout

    def call(self, method: str, params: list[Any]) -> Any:
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        ).encode()
        request = urllib.request.Request(
            self.url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise SolanaError(f"{method}: HTTP {response.status}")
                payload = json.loads(response.read())
        except urllib.error.URLError as exc:
            raise SolanaError(f"{method}: {exc}") from exc
        except ValueError as exc:
            raise SolanaError(f"{method}: response was not JSON: {exc}") from exc

        if "error" in payload:
            raise SolanaError(f"{method}: {payload['error']}")
        if "result" not in payload:
            raise SolanaError(f"{method}: response carried neither result nor error")
        return payload["result"]

    def signatures(
        self, address: str, *, before: str | None = None, until: str | None = None,
        limit: int = SIGNATURE_PAGE,
    ) -> list[dict]:
        """One page of signatures for *address*, newest first.

        `until` is the resume cursor: the endpoint stops when it reaches that
        signature, so an incremental pass never re-walks history it already has.
        """
        options: dict[str, Any] = {"limit": limit}
        if before:
            options["before"] = before
        if until:
            options["until"] = until
        return self.call("getSignaturesForAddress", [address, options]) or []

    def transaction(self, signature: str) -> dict:
        result = self.call(
            "getTransaction",
            [signature, {"maxSupportedTransactionVersion": 0, "encoding": "jsonParsed"}],
        )
        if result is None:
            # A signature the cluster knows about but will not serve — pruned
            # from this endpoint's history, most often. Not the same as a
            # parse failure, and the caller records it as its own error.
            raise SolanaError(f"getTransaction: {signature} returned null")
        return result
