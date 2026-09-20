"""HyperliquidClient tests — fake session, no network."""

import pytest

from hedge_fund.hyperliquid.client import HyperliquidClient, HyperliquidError


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """Records what was posted; replies with whatever it was handed."""

    def __init__(self, response):
        self._response = response
        self.headers = {}
        self.posted = []
        self.closed = False

    def post(self, url, json=None, timeout=None):
        self.posted.append((url, json, timeout))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    def close(self):
        self.closed = True


def client_with(response):
    hl = HyperliquidClient()
    hl._session = FakeSession(response)
    return hl


META_OK = [{"universe": [{"name": "BTC"}]}, [{"markPx": "81165.0"}]]


def test_meta_and_asset_ctxs_posts_the_dex_it_was_asked_for():
    hl = client_with(FakeResponse(META_OK))

    meta, ctxs = hl.meta_and_asset_ctxs(dex="xyz")

    assert hl._session.posted[0][1] == {"type": "metaAndAssetCtxs", "dex": "xyz"}
    assert meta["universe"][0]["name"] == "BTC"
    assert ctxs == [{"markPx": "81165.0"}]


def test_native_book_is_the_empty_dex():
    hl = client_with(FakeResponse(META_OK))

    hl.meta_and_asset_ctxs()

    assert hl._session.posted[0][1] == {"type": "metaAndAssetCtxs", "dex": ""}


def test_length_mismatch_is_refused_rather_than_zipped_short():
    """Contexts are paired to assets by index; a mismatch means neither is trustworthy."""
    hl = client_with(FakeResponse([{"universe": [{"name": "BTC"}, {"name": "ETH"}]}, [{}]]))

    with pytest.raises(HyperliquidError, match="2 assets but 1 contexts"):
        hl.meta_and_asset_ctxs()


@pytest.mark.parametrize("body", [
    {"universe": []},
    [{"universe": []}],
    [[], []],
    ["nope", []],
])
def test_unexpected_shapes_raise(body):
    with pytest.raises(HyperliquidError, match="unexpected shape"):
        client_with(FakeResponse(body)).meta_and_asset_ctxs()


def test_non_200_raises_with_the_status():
    hl = client_with(FakeResponse(None, status_code=503, text="upstream unavailable"))

    with pytest.raises(HyperliquidError) as exc:
        hl.perp_dexes()

    assert exc.value.status_code == 503
    assert "upstream unavailable" in str(exc.value)


def test_network_failure_raises():
    import requests

    hl = client_with(requests.ConnectionError("connection reset"))

    with pytest.raises(HyperliquidError, match="connection reset"):
        hl.perp_dexes()


def test_non_json_body_raises():
    hl = client_with(FakeResponse(ValueError("not json")))

    with pytest.raises(HyperliquidError, match="non-JSON"):
        hl.perp_dexes()


def test_perp_dexes_keeps_the_null_native_entry():
    """The leading null is Hyperliquid's own book and must not be dropped."""
    hl = client_with(FakeResponse([None, {"name": "xyz"}]))

    assert hl.perp_dexes() == [None, {"name": "xyz"}]


def test_close_closes_the_session():
    hl = client_with(FakeResponse([]))

    with hl:
        pass

    assert hl._session.closed
