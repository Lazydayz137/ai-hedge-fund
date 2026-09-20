"""HLClient contract tests -- mocked HTTP, no network.

Pins the fail-loud contract: infrastructure failures (network error, HTTP
4xx/5xx, non-JSON body) raise HLClientError rather than returning empty --
a silent empty here would read as "this market has no state" instead of
"the call failed", and the collector's whole no-rows-on-failure discipline
depends on the client actually raising.
"""

from __future__ import annotations

import requests
import pytest

from hedge_fund.hl.client import HLClient, HLClientError


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON object could be decoded")
        return self._payload


@pytest.fixture
def client():
    c = HLClient()
    yield c
    c.close()


def _stub(client, response):
    calls = []

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if isinstance(response, Exception):
            raise response
        return response

    client._session.post = fake_post
    return calls


def test_network_error_raises(client):
    _stub(client, requests.ConnectionError("refused"))
    with pytest.raises(HLClientError):
        client.meta_and_asset_ctxs()


def test_http_500_raises(client):
    _stub(client, _FakeResponse(500, text="internal error"))
    with pytest.raises(HLClientError) as exc_info:
        client.meta_and_asset_ctxs()
    assert exc_info.value.status_code == 500


def test_non_json_body_raises(client):
    _stub(client, _FakeResponse(200, payload=None))
    with pytest.raises(HLClientError):
        client.perp_dexs()


def test_success_returns_parsed_json(client):
    _stub(client, _FakeResponse(200, payload=[{"universe": []}, []]))
    result = client.meta_and_asset_ctxs()
    assert result == [{"universe": []}, []]


def test_dex_param_included_when_given(client):
    calls = _stub(client, _FakeResponse(200, payload=[{}, []]))
    client.meta_and_asset_ctxs(dex="xyz")
    assert calls[0]["json"] == {"type": "metaAndAssetCtxs", "dex": "xyz"}


def test_dex_param_omitted_for_native(client):
    calls = _stub(client, _FakeResponse(200, payload=[{}, []]))
    client.meta_and_asset_ctxs()
    assert calls[0]["json"] == {"type": "metaAndAssetCtxs"}


def test_request_body_types():
    """Each call type sends the exact body Hyperliquid's /info expects."""
    client = HLClient()
    calls = _stub(client, _FakeResponse(200, payload=[{}, []]))
    client.perp_dexs()
    assert calls[0]["json"] == {"type": "perpDexs"}

    calls = _stub(client, _FakeResponse(200, payload=[{}, []]))
    client.spot_meta_and_asset_ctxs()
    assert calls[0]["json"] == {"type": "spotMetaAndAssetCtxs"}
    client.close()
