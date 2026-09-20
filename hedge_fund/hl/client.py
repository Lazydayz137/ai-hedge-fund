"""Hyperliquid public info-endpoint client.

Public data only -- no wallet, no keys, no orders. Every call is a POST to
the single /info endpoint with a `type` selecting the request; Hyperliquid
has no per-request-type URL.
"""

from __future__ import annotations

import requests


class HLClientError(Exception):
    """An /info request failed for infrastructure reasons (network, HTTP,
    or a body that doesn't parse as JSON). The caller must not read this as
    "no data exists" -- callers write no rows for the scope that raised.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class HLClient:
    """Thin client over https://api.hyperliquid.xyz/info.

    Usage::

        with HLClient() as hl:
            meta, ctxs = hl.meta_and_asset_ctxs()          # native perps
            meta, ctxs = hl.meta_and_asset_ctxs(dex="xyz")  # a HIP-3 dex
            dexs = hl.perp_dexs()                            # HIP-3 listing
            meta, ctxs = hl.spot_meta_and_asset_ctxs()
    """

    BASE_URL = "https://api.hyperliquid.xyz"

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout
        self._session = requests.Session()

    def __enter__(self) -> HLClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def perp_dexs(self) -> list[dict | None]:
        """List every perp DEX: `[null, {native's slot}, {dex1}, {dex2}, ...]`.

        The leading null is the native perp DEX itself (it has no builder
        record); every following entry is a HIP-3 builder-deployed DEX with
        a `name` usable as the `dex` param to `meta_and_asset_ctxs`.
        """
        return self._post({"type": "perpDexs"})

    def meta_and_asset_ctxs(self, dex: str | None = None) -> list:
        """Universe + live asset contexts for one perp DEX.

        Omit *dex* for native perps; pass a HIP-3 DEX's `name` (from
        `perp_dexs()`) for that builder-deployed market. Returns
        `[meta, asset_ctxs]` -- positionally aligned: `asset_ctxs[i]`
        describes `meta["universe"][i]`.
        """
        body: dict = {"type": "metaAndAssetCtxs"}
        if dex is not None:
            body["dex"] = dex
        return self._post(body)

    def spot_meta_and_asset_ctxs(self) -> list:
        """Universe + live asset contexts for spot markets.

        Returns `[meta, asset_ctxs]`, but unlike perps these are NOT
        positionally aligned: `asset_ctxs` is indexed by each universe
        entry's own `index` field (it includes slots for delisted/inactive
        pairs the `universe` list omits, so it runs longer). Callers must
        join on `meta["universe"][i]["index"]`, never on `i` itself.
        """
        return self._post({"type": "spotMetaAndAssetCtxs"})

    def _post(self, body: dict) -> object:
        try:
            resp = self._session.post(
                f"{self.BASE_URL}/info", json=body, timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise HLClientError(
                f"POST /info ({body.get('type')}) failed: {exc}"
            ) from exc

        if not 200 <= resp.status_code < 300:
            raise HLClientError(
                f"POST /info ({body.get('type')}) returned {resp.status_code}: "
                f"{resp.text[:200]}",
                status_code=resp.status_code,
            )

        try:
            return resp.json()
        except ValueError as exc:
            raise HLClientError(
                f"POST /info ({body.get('type')}) returned non-JSON body: {exc}"
            ) from exc
