"""Tests for API authentication and transport error paths."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.eau_grand_lyon.api.auth import (
    ApiError,
    AuthenticationError,
    EauGrandLyonAuth,
    HttpError,
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


class TestDailyFetchMetadata:
    @pytest.mark.asyncio
    async def test_metadata_counts_normalized_entries_only(self):
        api = EauGrandLyonApi.__new__(EauGrandLyonApi)
        api._get_daily_new = AsyncMock(
            return_value=[
                {"date": "2026-08-16", "consommation": 1.2},
                {"date": "not-a-date", "unexpected": True},
            ]
        )
        api._get_daily_legacy = AsyncMock()

        result = await api._fetch_daily_raw("REF1", 365)

        assert result["nb_entries"] == 1
        assert result["last_date"] == "2026-08-16"
        api._get_daily_legacy.assert_not_awaited()

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
    async def test_authenticate_authorize_missing_code_raises_authentication_error(self, patched_aiohttp):
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
    async def test_authenticate_token_missing_access_token_raises_authentication_error(self, patched_aiohttp):
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
            _FakeSession([_FakeContextManager(_FakeResponse(json_error=_ClientResponseError(500, "boom")))])
        )
        with pytest.raises(ApiError):
            await api._request("GET", "https://example.test/data")

    @pytest.mark.asyncio
    async def test_request_client_error_maps_to_network_error(self, patched_aiohttp):
        api = self._make_api(_FakeSession([_FakeContextManager(error=_ClientError("timeout"))]))
        with pytest.raises(NetworkError):
            await api._request("GET", "https://example.test/data")

    @pytest.mark.asyncio
    async def test_request_http_200_bad_json_raises_api_error(self, patched_aiohttp):
        api = self._make_api(_FakeSession([_FakeContextManager(_FakeResponse(status=200, text="<html>WAF</html>"))]))
        with pytest.raises(ApiError, match="non-JSON"):
            await api._request("GET", "https://example.test/data")

    @pytest.mark.asyncio
    async def test_request_401_after_reauth_raises_authentication_error(self, patched_aiohttp):
        api = self._make_api(
            _FakeSession(
                [
                    _FakeContextManager(_FakeResponse(status=401)),
                    _FakeContextManager(_FakeResponse(status=401)),
                ]
            )
        )
        with pytest.raises(AuthenticationError):
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

    @pytest.mark.asyncio
    async def test_get_invoice_pdf_401_reauth_then_success(self, patched_aiohttp):
        """Token expiré (401) : ré-auth puis nouvel essai réussi (fix M6)."""
        session = _FakeSession(
            [
                _FakeContextManager(_FakeResponse(status=401)),
                _FakeContextManager(_FakeResponse(status=200, text="%PDF-test")),
            ]
        )
        api = self._make_api(session)
        result = await api.get_invoice_pdf("INV-1")
        assert result == b"%PDF-test"
        api._auth.authenticate.assert_awaited_once()
        method, url, kwargs = session.calls[-1]
        assert method == "GET"
        assert url.endswith("/factures/INV-1/duplicata")
        assert kwargs["headers"]["Accept"].startswith("application/pdf")

    @pytest.mark.asyncio
    async def test_get_invoice_pdf_rejects_html_success_response(self, patched_aiohttp):
        session = _FakeSession(
            [_FakeContextManager(_FakeResponse(status=200, text="<html>login</html>"))]
        )
        api = self._make_api(session)
        with pytest.raises(NetworkError, match="pas un document PDF"):
            await api.get_invoice_pdf("INV-1")

    @pytest.mark.asyncio
    async def test_get_invoice_pdf_403_raises_waf_blocked(self, patched_aiohttp):
        session = _FakeSession([_FakeContextManager(_FakeResponse(status=403))])
        api = self._make_api(session)
        with pytest.raises(WafBlockedError):
            await api.get_invoice_pdf("INV-1")

    @pytest.mark.asyncio
    async def test_get_monthly_consumptions_forwards_params_to_get(self, patched_aiohttp):
        """Regression: _get must accept params (was crashing get_monthly_consumptions)."""
        session = _FakeSession([_FakeContextManager(_FakeResponse(status=200, text="{}"))])
        api = self._make_api(session)

        # Must not raise "TypeError: _get() got an unexpected keyword argument 'params'".
        result = await api.get_monthly_consumptions("C1", nb_jours=30)

        assert result == []
        method, url, kwargs = session.calls[-1]
        assert method == "GET"
        assert url.endswith("/contrats/C1/consommationsMensuelles")
        assert kwargs.get("params") == {"nbJours": 30}

    @pytest.mark.asyncio
    async def test_get_derniere_releve_siamm_500_is_optional_debug_only(self, patched_aiohttp, caplog):
        session = _FakeSession(
            [_FakeContextManager(_FakeResponse(status=500, json_error=_ClientResponseError(500, "provider down")))]
        )
        api = self._make_api(session)

        with caplog.at_level(logging.WARNING, logger="custom_components.eau_grand_lyon.api.client"):
            result = await api.get_derniere_releve_siamm("C1")

        assert result is None
        assert "api_request_failed" not in caplog.text
        method, url, kwargs = session.calls[-1]
        assert method == "GET"
        assert url.endswith("/application/rest/produits/contrats/C1/derniereReleveSIAMM")
        assert kwargs.get("params") == {"expand": "grandeursPhysiques(modeleGrandeurPhysique)"}


class TestEndpointFallbacks:
    def _make_api(self) -> EauGrandLyonApi:
        return EauGrandLyonApi(MagicMock(), "user@example.com", "secret")

    @pytest.mark.asyncio
    async def test_modern_404_falls_back_to_legacy(self):
        api = self._make_api()
        api._get_produits = AsyncMock(side_effect=HttpError(404, "GET", "modern", "missing"))
        api._get = AsyncMock(return_value={"data": [{"date": "2026-08-01", "consommation": 1.25}]})

        result = await api.get_daily_consumptions("C1", nb_jours=30)

        assert result["source"] == "Legacy (Standard)"
        assert result["entries"] == [{"date": "2026-08-01", "consommation_m3": 1.25}]
        api._get.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("error", [NetworkError("offline"), WafBlockedError("blocked"), AuthenticationError("bad")])
    async def test_modern_significant_errors_are_propagated(self, error):
        api = self._make_api()
        api._get_produits = AsyncMock(side_effect=error)
        api._get = AsyncMock()

        with pytest.raises(type(error)):
            await api.get_daily_consumptions("C1", nb_jours=30)

        api._get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_all_legacy_404s_return_expected_empty_value(self):
        api = self._make_api()
        api._get = AsyncMock(side_effect=HttpError(404, "GET", "legacy", "missing"))

        entries, source = await api._get_daily_legacy("C1", 30)

        assert entries == []
        assert source == "Aucune"
        assert api._get.await_count == 2

    @pytest.mark.asyncio
    async def test_legacy_network_error_is_propagated(self):
        api = self._make_api()
        api._get = AsyncMock(side_effect=NetworkError("offline"))

        with pytest.raises(NetworkError):
            await api._get_daily_legacy("C1", 30)
