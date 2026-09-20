"""A thin reader for Hyperliquid's public ``info`` endpoint.

One POST, one timeout, one shape of error. No key, no wallet, no signing —
everything here is public market state, and nothing in this package may ever
grow the ability to place an order.

Rate limits: Hyperliquid meters ``info`` by request weight against a
per-IP budget of 1200/minute, and ``metaAndAssetCtxs`` weighs 20. A full
collection pass is one call per perp DEX — eleven today — so a snapshot
every minute sits three orders of magnitude inside the budget. That is why
there is no retry and no backoff here: the only 429 this could plausibly
see would be someone else's traffic from the same IP, and silently
retrying through it would put a stale observation under a fresh timestamp.
Fail, record the failure, write nothing.
"""

from __future__ import annotations

import requests


HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"


class HyperliquidError(Exception):
    """An ``info`` request failed — network, non-200, or unparseable body.

    Never raised to mean "no such market". The endpoint answers an unknown
    DEX with an empty universe, not an error, and that distinction is the
    whole point: a collector must be able to tell "nothing is listed here"
    from "we could not see".
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HyperliquidClient:
    """Reader for the public ``info`` endpoint.

    Usage::

        with HyperliquidClient() as hl:
            dexes = hl.perp_dexes()
            meta, ctxs = hl.meta_and_asset_ctxs(dex="xyz")
    """

    def __init__(self, url: str = HYPERLIQUID_INFO_URL, timeout: float = 20.0) -> None:
        self._url = url
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"

    def __enter__(self) -> HyperliquidClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def perp_dexes(self) -> list[dict | None]:
        """Every perp DEX on the venue, builder-deployed ones included.

        The first entry is ``null``: that is Hyperliquid's own perp DEX, the
        native crypto book, which has no builder and no name. Builder-deployed
        (HIP-3) DEXs follow as objects carrying their short ``name`` — the
        prefix that namespaces their instruments, e.g. ``xyz`` in ``xyz:NVDA``.
        """
        body = self._post({"type": "perpDexs"})
        if not isinstance(body, list):
            raise HyperliquidError(f"perpDexs returned {type(body).__name__}, expected list")
        return body

    def meta_and_asset_ctxs(self, dex: str = "") -> tuple[dict, list[dict]]:
        """The listed perps of one DEX and their current market state.

        Returns ``(meta, contexts)`` positionally aligned: ``meta["universe"][i]``
        describes the instrument whose state is ``contexts[i]``. The pairing is
        by index and nothing else — the contexts carry no name — so a length
        mismatch means the response cannot be trusted and is refused here
        rather than silently zipped short.

        ``dex=""`` is the native crypto book; a builder DEX is named by its
        short prefix.
        """
        body = self._post({"type": "metaAndAssetCtxs", "dex": dex})
        if not (isinstance(body, list) and len(body) == 2):
            raise HyperliquidError(f"metaAndAssetCtxs(dex={dex!r}) returned an unexpected shape")
        meta, ctxs = body
        universe = meta.get("universe") if isinstance(meta, dict) else None
        if not isinstance(universe, list) or not isinstance(ctxs, list):
            raise HyperliquidError(f"metaAndAssetCtxs(dex={dex!r}) returned an unexpected shape")
        if len(universe) != len(ctxs):
            raise HyperliquidError(
                f"metaAndAssetCtxs(dex={dex!r}) returned {len(universe)} assets "
                f"but {len(ctxs)} contexts"
            )
        return meta, ctxs

    def _post(self, payload: dict) -> object:
        try:
            resp = self._session.post(self._url, json=payload, timeout=self._timeout)
        except requests.RequestException as exc:
            raise HyperliquidError(f"POST {self._url} {payload} failed: {exc}") from exc

        if resp.status_code != 200:
            raise HyperliquidError(
                f"POST {self._url} {payload} returned {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )

        try:
            return resp.json()
        except ValueError as exc:
            raise HyperliquidError(f"POST {self._url} {payload} returned non-JSON") from exc
