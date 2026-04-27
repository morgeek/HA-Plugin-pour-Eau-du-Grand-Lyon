"""Tests for API authentication and transport error paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.eau_grand_lyon.api.auth import (
    ApiError,
    AuthenticationError,
    EauGrandLyonAuth,
    NetworkError,
    WafBlockedError,
)
from custom_components.eau_grand_lyon.api.client import EauGrandLyonApi


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        text: str = "{}",
        url: str = "https://example.test/callback?code=abc",
        json_error: Exception | None = None,
    ) -> None:
        self.status = status
        self._text = text
        self.url = url
        self._json_error = json_error

    async def text(self) -> str:
        return self._text

    async def read(self) -> bytes:
        return self._text.encode()

    def raise_for_status(self) -> None:
        if self._json_error is not None:
            raise self._json_error


class _FakeContextManager:
    def __init__(self, response: _FakeResponse | None = None, error: Exception | None = None):
        self._response = response
        self._error = error

    async def __aenter__(self):
        if self._error is not None:
            raise self._error
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, responses: list[_FakeContextManager] | None = None) -> None:
        self._responses = responses or []
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return self._responses.pop(0)

    def post(self, url: str, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._responses.pop(0)

    def get(self, url: str, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self._responses.pop(0)


class _ClientError(Exception):
    """aiohttp.ClientError replacement for tests."""


class _ClientResponseError(_ClientError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@pytest.fixture
def patched_aiohttp(monkeypatch):
    fake = SimpleNamespace(
        ClientError=_ClientError,
        ClientResponseError=_ClientResponseError,
        ClientTimeout=lambda total=None: SimpleNamespace(total=total),
    )
    monkeypatch.setattr("custom_components.eau_grand_lyon.api.auth.aiohttp", fake)
    monkeypatch.setattr("custom_components.eau_grand_lyon.api.client.aiohttp", fake)
    return fake


class TestAuthPaths:
    @pytest.mark.asyncio
    async def test_authenticate_login_401_raises_authentication_error(self, patched_aiohttp):
        auth = EauGrandLyonAuth(
            _FakeSession([_FakeContextManager(_FakeResponse(status=401, text="bad creds"))]),
            "user@example.com",
            "secret",
        )
        with pytest.raises(AuthenticationError):
            await auth.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_login_403_raises_waf_blocked(self, patched_aiohttp):
        auth = EauGrandLyonAuth(
            _FakeSession([_FakeContextManager(_FakeResponse(status=403, text="blocked"))]),
            "user@example.com",
            "secret",
        )
        with pytest.raises(WafBlockedError):
            await auth.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_login_404_raises_api_error(self, patched_aiohttp):
        auth = EauGrandLyonAuth(
            _FakeSession([_FakeContextManager(_FakeResponse(status=404, text="missing"))]),
            "user@example.com",
            "secret",
        )
        with pytest.raises(ApiError):
            await auth.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_login_client_error_raises_network_error(self, patched_aiohttp):
        auth = EauGrandLyonAuth(
            _FakeSession([_FakeContextManager(error=_ClientError("down"))]),
            "user@example.com",
            "secret",
        )
        with pytest.raises(NetworkError):
            await auth.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_authorize_403_raises_waf_blocked(self, patched_aiohttp):
        auth = EauGrandLyonAuth(
            _FakeSession(
                [
                    _FakeContextManager(_FakeResponse(status=200)),
                    _FakeContextManager(_FakeResponse(status=403)),
                ]
            ),
            "user@example.com",
            "secret",
        )
        with pytest.raises(WafBlockedError):
            await auth.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_authorize_missing_code_raises_authentication_error(
        self, patched_aiohttp
    ):
        auth = EauGrandLyonAuth(
            _FakeSession(
                [
                    _FakeContextManager(_FakeResponse(status=200)),
                    _FakeContextManager(_FakeResponse(status=200, url="https://example.test/callback")),
                ]
            ),
            "user@example.com",
            "secret",
        )
        with pytest.raises(AuthenticationError):
            await auth.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_token_403_raises_waf_blocked(self, patched_aiohttp):
        auth = EauGrandLyonAuth(
            _FakeSession(
                [
                    _FakeContextManager(_FakeResponse(status=200)),
                    _FakeContextManager(_FakeResponse(status=200)),
                    _FakeContextManager(_FakeResponse(status=403)),
                ]
            ),
            "user@example.com",
            "secret",
        )
        with pytest.raises(WafBlockedError):
            await auth.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_token_404_raises_api_error(self, patched_aiohttp):
        auth = EauGrandLyonAuth(
            _FakeSession(
                [
                    _FakeContextManager(_FakeResponse(status=200)),
                    _FakeContextManager(_FakeResponse(status=200)),
                    _FakeContextManager(_FakeResponse(status=404)),
                ]
            ),
            "user@example.com",
            "secret",
        )
        with pytest.raises(ApiError):
            await auth.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_token_non_200_raises_authentication_error(self, patched_aiohttp):
        auth = EauGrandLyonAuth(
            _FakeSession(
                [
                    _FakeContextManager(_FakeResponse(status=200)),
                    _FakeContextManager(_FakeResponse(status=200)),
                    _FakeContextManager(_FakeResponse(status=500, text="oops")),
                ]
            ),
            "user@example.com",
            "secret",
        )
        with pytest.raises(AuthenticationError):
            await auth.authenticate()

    @pytest.mark.asyncio
    async def test_authenticate_token_missing_access_token_raises_authentication_error(
        self, patched_aiohttp
    ):
        auth = EauGrandLyonAuth(
            _FakeSession(
                [
                    _FakeContextManager(_FakeResponse(status=200)),
                    _FakeContextManager(_FakeResponse(status=200)),
                    _FakeContextManager(_FakeResponse(status=200, text='{"refresh_token":"x"}')),
                ]
            ),
            "user@example.com",
            "secret",
        )
        with pytest.raises(AuthenticationError):
            await auth.authenticate()


class TestRequestPaths:
    def _make_api(self, session: _FakeSession) -> EauGrandLyonApi:
        api = EauGrandLyonApi(session, "user@example.com", "secret")
        api._auth.access_token = "token"
        api.authenticate = AsyncMock(return_value="token")
        api._auth.authenticate = AsyncMock(return_value="token")
        return api

    @pytest.mark.asyncio
    async def test_request_403_raises_waf_blocked(self, patched_aiohttp):
        api = self._make_api(_FakeSession([_FakeContextManager(_FakeResponse(status=403))]))
        with pytest.raises(WafBlockedError):
            await api._request("GET", "https://example.test/data")

    @pytest.mark.asyncio
    async def test_request_client_response_error_maps_to_api_error(self, patched_aiohttp):
        api = self._make_api(
            _FakeSession(
                [
                    _FakeContextManager(
                        _FakeResponse(json_error=_ClientResponseError(500, "boom"))
                    )
                ]
            )
        )
        with pytest.raises(ApiError):
            await api._request("GET", "https://example.test/data")

    @pytest.mark.asyncio
    async def test_request_client_error_maps_to_network_error(self, patched_aiohttp):
        api = self._make_api(_FakeSession([_FakeContextManager(error=_ClientError("timeout"))]))
        with pytest.raises(NetworkError):
            await api._request("GET", "https://example.test/data")

    @pytest.mark.asyncio
    async def test_request_401_reauth_then_403_raises_waf_blocked(self, patched_aiohttp):
        api = self._make_api(
            _FakeSession(
                [
                    _FakeContextManager(_FakeResponse(status=401)),
                    _FakeContextManager(_FakeResponse(status=403)),
                ]
            )
        )
        with pytest.raises(WafBlockedError):
            await api._request("GET", "https://example.test/data")
        api._auth.authenticate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_invoice_pdf_non_200_raises_network_error(self, patched_aiohttp):
        session = _FakeSession([_FakeContextManager(_FakeResponse(status=500, text="bad"))])
        api = self._make_api(session)
        with pytest.raises(NetworkError):
            await api.get_invoice_pdf("INV-1")

    @pytest.mark.asyncio
    async def test_get_invoice_pdf_client_error_raises_network_error(self, patched_aiohttp):
        session = _FakeSession([_FakeContextManager(error=_ClientError("broken"))])
        api = self._make_api(session)
        with pytest.raises(NetworkError):
            await api.get_invoice_pdf("INV-1")
