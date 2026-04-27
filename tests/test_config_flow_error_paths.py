"""Tests for config flow error paths and recovery steps."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.eau_grand_lyon.api import (
    ApiError,
    AuthenticationError,
    NetworkError,
    WafBlockedError,
)
from custom_components.eau_grand_lyon.config_flow import (
    EauGrandLyonConfigFlow,
    _authenticate_and_handle_errors,
)
from custom_components.eau_grand_lyon.const import CONF_EMAIL, CONF_PASSWORD, CONF_TARIF_M3


class _FakeClientSession:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def patch_config_flow_runtime(monkeypatch):
    monkeypatch.setattr(
        "custom_components.eau_grand_lyon.config_flow.aiohttp.ClientSession",
        _FakeClientSession,
        raising=False,
    )
    monkeypatch.setattr(
        "custom_components.eau_grand_lyon.config_flow.aiohttp.CookieJar",
        lambda unsafe=True: MagicMock(),
        raising=False,
    )
    monkeypatch.setattr(
        "custom_components.eau_grand_lyon.config_flow.vol.Required",
        lambda key, default=None: key,
    )
    monkeypatch.setattr(
        "custom_components.eau_grand_lyon.config_flow.vol.Optional",
        lambda key, default=None: key,
    )


class TestAuthenticateAndHandleErrors:
    @pytest.mark.asyncio
    async def test_authentication_error_maps_to_invalid_auth(self):
        with patch(
            "custom_components.eau_grand_lyon.config_flow.EauGrandLyonApi.authenticate",
            new=AsyncMock(side_effect=AuthenticationError("bad creds")),
        ):
            errors = await _authenticate_and_handle_errors("user@example.com", "secret")
        assert errors == {"base": "invalid_auth"}

    @pytest.mark.asyncio
    async def test_waf_error_maps_to_waf_blocked(self):
        with patch(
            "custom_components.eau_grand_lyon.config_flow.EauGrandLyonApi.authenticate",
            new=AsyncMock(side_effect=WafBlockedError("blocked")),
        ):
            errors = await _authenticate_and_handle_errors("user@example.com", "secret")
        assert errors == {"base": "waf_blocked"}

    @pytest.mark.asyncio
    async def test_network_error_maps_to_cannot_connect(self):
        with patch(
            "custom_components.eau_grand_lyon.config_flow.EauGrandLyonApi.authenticate",
            new=AsyncMock(side_effect=NetworkError("offline")),
        ):
            errors = await _authenticate_and_handle_errors("user@example.com", "secret")
        assert errors == {"base": "cannot_connect"}

    @pytest.mark.asyncio
    async def test_api_error_maps_to_api_error(self):
        with patch(
            "custom_components.eau_grand_lyon.config_flow.EauGrandLyonApi.authenticate",
            new=AsyncMock(side_effect=ApiError("bad api")),
        ):
            errors = await _authenticate_and_handle_errors("user@example.com", "secret")
        assert errors == {"base": "api_error"}

    @pytest.mark.asyncio
    async def test_unexpected_error_maps_to_unknown(self):
        with patch(
            "custom_components.eau_grand_lyon.config_flow.EauGrandLyonApi.authenticate",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            errors = await _authenticate_and_handle_errors("user@example.com", "secret")
        assert errors == {"base": "unknown"}


def _make_flow(entry: MagicMock | None = None) -> tuple[EauGrandLyonConfigFlow, MagicMock]:
    flow = EauGrandLyonConfigFlow()
    flow.context = {"entry_id": "entry-1"}
    flow.hass = MagicMock()
    config_entry = entry or MagicMock()
    config_entry.entry_id = "entry-1"
    config_entry.data = {CONF_EMAIL: "old@example.com", CONF_PASSWORD: "oldpw"}
    config_entry.options = {}
    flow.hass.config_entries.async_get_entry.return_value = config_entry
    flow.hass.config_entries.async_reload = AsyncMock()
    flow.async_abort = MagicMock(side_effect=lambda **kw: {"type": "abort", **kw})
    flow.async_show_form = MagicMock(side_effect=lambda **kw: {"type": "form", **kw})
    flow.async_create_entry = MagicMock(side_effect=lambda **kw: {"type": "create_entry", **kw})
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    return flow, config_entry


class TestReauthFlow:
    @pytest.mark.asyncio
    async def test_reauth_missing_entry_aborts(self):
        flow, _ = _make_flow()
        flow.hass.config_entries.async_get_entry.return_value = None
        result = await flow.async_step_reauth_confirm()
        assert result == {"type": "abort", "reason": "reauth_failed"}

    @pytest.mark.asyncio
    async def test_reauth_form_prefills_current_email(self):
        flow, _ = _make_flow()
        result = await flow.async_step_reauth_confirm()
        assert result["step_id"] == "reauth_confirm"
        assert result["errors"] == {}

    @pytest.mark.asyncio
    async def test_reauth_invalid_auth_shows_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "invalid_auth"}),
        ):
            result = await flow.async_step_reauth_confirm(
                {CONF_EMAIL: "new@example.com", CONF_PASSWORD: "secret"}
            )
        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_auth"}

    @pytest.mark.asyncio
    async def test_reauth_waf_error_shows_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "waf_blocked"}),
        ):
            result = await flow.async_step_reauth_confirm(
                {CONF_EMAIL: "new@example.com", CONF_PASSWORD: "secret"}
            )
        assert result["errors"] == {"base": "waf_blocked"}

    @pytest.mark.asyncio
    async def test_reauth_network_error_shows_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "cannot_connect"}),
        ):
            result = await flow.async_step_reauth_confirm(
                {CONF_EMAIL: "new@example.com", CONF_PASSWORD: "secret"}
            )
        assert result["errors"] == {"base": "cannot_connect"}

    @pytest.mark.asyncio
    async def test_reauth_success_updates_entry_and_reloads(self):
        flow, entry = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={}),
        ):
            result = await flow.async_step_reauth_confirm(
                {CONF_EMAIL: "new@example.com", CONF_PASSWORD: "secret"}
            )
        assert result == {"type": "abort", "reason": "reauth_successful"}
        flow.hass.config_entries.async_update_entry.assert_called_once()
        flow.hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)


class TestReconfigureFlow:
    @pytest.mark.asyncio
    async def test_reconfigure_missing_entry_aborts(self):
        flow, _ = _make_flow()
        flow.hass.config_entries.async_get_entry.return_value = None
        result = await flow.async_step_reconfigure()
        assert result == {"type": "abort", "reason": "reconfigure_failed"}

    @pytest.mark.asyncio
    async def test_reconfigure_form_renders_without_errors(self):
        flow, _ = _make_flow()
        result = await flow.async_step_reconfigure()
        assert result["step_id"] == "reconfigure"
        assert result["errors"] == {}

    @pytest.mark.asyncio
    async def test_reconfigure_invalid_auth_shows_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "invalid_auth"}),
        ):
            result = await flow.async_step_reconfigure(
                {
                    CONF_EMAIL: "new@example.com",
                    CONF_PASSWORD: "secret",
                    CONF_TARIF_M3: 5.2,
                }
            )
        assert result["errors"] == {"base": "invalid_auth"}

    @pytest.mark.asyncio
    async def test_reconfigure_api_error_shows_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "api_error"}),
        ):
            result = await flow.async_step_reconfigure(
                {
                    CONF_EMAIL: "new@example.com",
                    CONF_PASSWORD: "secret",
                    CONF_TARIF_M3: 5.2,
                }
            )
        assert result["errors"] == {"base": "api_error"}

    @pytest.mark.asyncio
    async def test_reconfigure_success_updates_entry_and_reloads(self):
        flow, entry = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={}),
        ):
            result = await flow.async_step_reconfigure(
                {
                    CONF_EMAIL: "new@example.com",
                    CONF_PASSWORD: "secret",
                    CONF_TARIF_M3: 5.2,
                }
            )
        assert result == {"type": "abort", "reason": "reconfigure_successful"}
        flow.hass.config_entries.async_update_entry.assert_called_once()
        flow.hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)


class TestUserFlowErrors:
    @pytest.mark.asyncio
    async def test_user_flow_invalid_auth_returns_form_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "invalid_auth"}),
        ):
            result = await flow.async_step_user(
                {
                    CONF_EMAIL: "new@example.com",
                    CONF_PASSWORD: "secret",
                    CONF_TARIF_M3: 5.2,
                }
            )
        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_auth"}

    @pytest.mark.asyncio
    async def test_user_flow_api_error_returns_form_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "api_error"}),
        ):
            result = await flow.async_step_user(
                {
                    CONF_EMAIL: "new@example.com",
                    CONF_PASSWORD: "secret",
                    CONF_TARIF_M3: 5.2,
                }
            )
        assert result["errors"] == {"base": "api_error"}
