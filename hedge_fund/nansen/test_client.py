"""The client's whole job: send the key, and refuse anything that isn't 200."""

from __future__ import annotations

import pytest
import requests

from hedge_fund.nansen.client import (
    SMART_MONEY_HOLDINGS,
    MissingAPIKey,
    NansenClient,
    NansenError,
)


class _Response:
    def __init__(self, status_code: int, body=None, text: str = "") -> None:
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


class _Session:
    """Stands in for requests.Session. Nothing here touches the network."""

    def __init__(self, response=None, raises=None) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple] = []
        self._response = response
        self._raises = raises

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json, timeout))
        if self._raises is not None:
            raise self._raises
        return self._response

    def close(self) -> None:
        pass


def _client(session: _Session) -> NansenClient:
    client = NansenClient(api_key="test-key")
    client._session = session
    session.headers["apikey"] = "test-key"
    return client


def test_no_api_key_refuses_to_build_a_client(monkeypatch):
    monkeypatch.delenv("NANSEN_API_KEY", raising=False)
    with pytest.raises(MissingAPIKey):
        NansenClient()


def test_the_key_travels_in_the_apikey_header():
    client = NansenClient(api_key="test-key")
    assert client._session.headers["apikey"] == "test-key"
    client.close()


def test_a_200_returns_the_decoded_body():
    # Hand-written to the documented response shape (a "data" list beside a
    # "pagination" object), not captured traffic.
    body = {"data": [{"chain": "ethereum"}], "pagination": {"is_last_page": True}}
    session = _Session(_Response(200, body))
    with _client(session) as client:
        assert client.post(SMART_MONEY_HOLDINGS, {"chains": ["ethereum"]}) == body
    url, sent, _ = session.calls[0]
    assert url.endswith("/api/v1/smart-money/holdings")
    assert sent == {"chains": ["ethereum"]}


@pytest.mark.parametrize("status", [401, 404, 429, 500])
def test_any_non_200_raises(status):
    session = _Session(_Response(status, text="nope"))
    with _client(session) as client:
        with pytest.raises(NansenError) as caught:
            client.post(SMART_MONEY_HOLDINGS, {})
    assert caught.value.status_code == status


def test_a_network_failure_raises_rather_than_returning_empty():
    session = _Session(raises=requests.ConnectionError("no route"))
    with _client(session) as client:
        with pytest.raises(NansenError):
            client.post(SMART_MONEY_HOLDINGS, {})


def test_a_200_that_is_not_json_raises():
    session = _Session(_Response(200, None, text="<html>maintenance</html>"))
    with _client(session) as client:
        with pytest.raises(NansenError):
            client.post(SMART_MONEY_HOLDINGS, {})
