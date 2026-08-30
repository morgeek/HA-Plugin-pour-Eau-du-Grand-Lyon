"""Regression tests for config-entry lifecycle and HTTP session ownership."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.eau_grand_lyon import (
    _async_update_options,
    _local_invoice_url,
    _async_setup_services,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.eau_grand_lyon.api.auth import _compute_code_challenge
from custom_components.eau_grand_lyon.const import CONF_EMAIL, CONF_PASSWORD
from custom_components.eau_grand_lyon import coordinator as coordinator_module
from custom_components.eau_grand_lyon.coordinator import EauGrandLyonCoordinator


def _entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"}
    entry.options = {}
    return entry


class TestSetupLifecycle:
    @pytest.mark.asyncio
    async def test_component_setup_registers_services(self):
        hass = MagicMock()
        hass.services.has_service.return_value = False
        assert await async_setup(hass, {}) is True
        assert hass.services.async_register.call_count == 4

    @pytest.mark.asyncio
    async def test_setup_registers_options_listener_after_success(self):
        hass = MagicMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        entry = _entry()
        coordinator = MagicMock()
        coordinator.async_initialize = AsyncMock()
        coordinator.async_config_entry_first_refresh = AsyncMock()
        coordinator.async_close = AsyncMock()

        with patch(
            "custom_components.eau_grand_lyon.EauGrandLyonCoordinator",
            return_value=coordinator,
        ), patch("custom_components.eau_grand_lyon._async_cleanup_legacy_device") as cleanup:
            assert await async_setup_entry(hass, entry) is True

        assert entry.runtime_data is coordinator
        entry.add_update_listener.assert_called_once_with(_async_update_options)
        entry.async_on_unload.assert_called_once_with(entry.add_update_listener.return_value)
        cleanup.assert_called_once_with(hass, entry)
        coordinator.async_close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_setup_always_closes_owned_session(self):
        hass = MagicMock()
        entry = _entry()
        coordinator = MagicMock()
        coordinator.async_initialize = AsyncMock()
        coordinator.async_config_entry_first_refresh = AsyncMock(side_effect=RuntimeError("setup failed"))
        coordinator.async_close = AsyncMock()

        with patch("custom_components.eau_grand_lyon.EauGrandLyonCoordinator", return_value=coordinator), pytest.raises(
            RuntimeError, match="setup failed"
        ):
            await async_setup_entry(hass, entry)

        coordinator.async_close.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_successful_unload_closes_owned_session(self):
        hass = MagicMock()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        entry = _entry()
        entry.runtime_data = MagicMock()
        entry.runtime_data.async_close = AsyncMock()

        assert await async_unload_entry(hass, entry) is True
        entry.runtime_data.async_close.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_options_listener_triggers_exactly_one_reload(self):
        hass = MagicMock()
        hass.config_entries.async_reload = AsyncMock()
        entry = _entry()

        await _async_update_options(hass, entry)

        hass.config_entries.async_reload.assert_awaited_once_with("entry-1")


class TestHttpSessionSecurity:
    def test_coordinator_uses_safe_cookie_jar(self, monkeypatch):
        jar = MagicMock()
        timeout = MagicMock()
        session = MagicMock()
        cookie_jar_factory = MagicMock(return_value=jar)
        timeout_factory = MagicMock(return_value=timeout)
        session_factory = MagicMock(return_value=session)
        monkeypatch.setattr(coordinator_module.aiohttp, "CookieJar", cookie_jar_factory, raising=False)
        monkeypatch.setattr(coordinator_module.aiohttp, "ClientTimeout", timeout_factory, raising=False)
        monkeypatch.setattr(coordinator_module, "async_create_clientsession", session_factory)
        monkeypatch.setattr(coordinator_module, "_RebuildableStore", MagicMock())

        hass = MagicMock()
        EauGrandLyonCoordinator(hass, _entry())

        cookie_jar_factory.assert_called_once_with()
        timeout_factory.assert_called_once_with(total=30)
        session_factory.assert_called_once_with(hass, cookie_jar=jar, timeout=timeout)

    def test_pkce_challenge_matches_rfc_7636_vector(self):
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        assert _compute_code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def _service_hass(coordinator: MagicMock) -> tuple[MagicMock, dict[str, object]]:
    hass = MagicMock()
    hass.services.has_service.return_value = False
    handlers: dict[str, object] = {}
    hass.services.async_register.side_effect = lambda domain, name, handler: handlers.__setitem__(name, handler)
    entry = MagicMock()
    entry.runtime_data = coordinator
    hass.config_entries.async_entries.return_value = [entry]

    async def run_executor(func):
        return func()

    hass.async_add_executor_job = run_executor
    _async_setup_services(hass)
    return hass, handlers


class TestServiceHandlers:
    @staticmethod
    def _invoice_coordinator() -> MagicMock:
        coordinator = MagicMock()
        coordinator.data = {
            "contracts": {"REF1": {"factures": [{"id": "API-ID-1", "reference": "INV-1", "telechargeable": True}]}}
        }
        coordinator.api.get_invoice_pdf = AsyncMock(return_value=b"%PDF-test")
        return coordinator

    @pytest.mark.asyncio
    async def test_clear_cache_and_update_now_reach_every_coordinator(self):
        coordinator = MagicMock()
        coordinator.async_clear_cache = AsyncMock()
        coordinator.async_refresh = AsyncMock()
        hass, handlers = _service_hass(coordinator)

        await handlers["clear_cache"](MagicMock(data={}))
        await handlers["update_now"](MagicMock(data={}))

        coordinator.async_clear_cache.assert_awaited_once_with()
        coordinator.async_refresh.assert_awaited_once_with()
        assert hass.config_entries.async_entries.call_count == 2

    @pytest.mark.asyncio
    async def test_export_data_writes_monthly_and_daily_history(self, tmp_path):
        coordinator = MagicMock()
        coordinator.data = {
            "contracts": {
                "REF1": {
                    "consommations": [{"label": "Août 2026", "consommation_m3": 3.2, "annee": 2026}],
                    "consommations_journalieres": [{"date": "2026-08-01", "consommation_m3": 0.1, "index_m3": 42.0}],
                }
            }
        }
        hass, handlers = _service_hass(coordinator)
        hass.config.is_allowed_path.return_value = True
        target = tmp_path / "history.csv"

        await handlers["export_data"](MagicMock(data={"path": str(target)}))

        content = target.read_text(encoding="utf-8")
        assert "REF1,MENSUEL,Août 2026,3.2,Année 2026" in content
        assert "REF1,JOURNALIER,2026-08-01,0.1,Index 42.0" in content

    @pytest.mark.asyncio
    async def test_download_invoice_under_www_writes_pdf_and_links_local_url(self, tmp_path):
        coordinator = self._invoice_coordinator()
        hass, handlers = _service_hass(coordinator)
        hass.config.is_allowed_path.return_value = True
        www_root = tmp_path / "config" / "www"
        hass.config.path.return_value = str(www_root)
        hass.services.async_call = AsyncMock()
        target = www_root / "eau_grand_lyon" / "invoice.pdf"

        await handlers["download_latest_invoice"](MagicMock(data={"path": str(target), "contract_reference": "REF1"}))

        assert target.read_bytes() == b"%PDF-test"
        coordinator.api.get_invoice_pdf.assert_awaited_once_with("API-ID-1")
        hass.services.async_call.assert_awaited_once()
        notification = hass.services.async_call.await_args.args[2]
        assert "/local/eau_grand_lyon/invoice.pdf" in notification["message"]
        assert ".." not in notification["message"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("directory", ["exports", "www_fake"])
    async def test_download_invoice_outside_www_saves_without_local_url(self, tmp_path, directory):
        coordinator = self._invoice_coordinator()
        hass, handlers = _service_hass(coordinator)
        hass.config.is_allowed_path.return_value = True
        config_root = tmp_path / "config"
        hass.config.path.return_value = str(config_root / "www")
        hass.services.async_call = AsyncMock()
        target = config_root / directory / "invoice.pdf"

        await handlers["download_latest_invoice"](MagicMock(data={"path": str(target), "contract_reference": "REF1"}))

        assert target.read_bytes() == b"%PDF-test"
        notification = hass.services.async_call.await_args.args[2]
        assert "/local/" not in notification["message"]
        assert "/local/../" not in notification["message"]
        assert str(target.resolve()) in notification["message"]

    def test_local_invoice_url_rejects_normalized_traversal(self, tmp_path):
        hass = MagicMock()
        www_root = tmp_path / "config" / "www"
        hass.config.path.return_value = str(www_root)
        target = www_root / "nested" / ".." / ".." / "exports" / "invoice.pdf"

        assert _local_invoice_url(hass, str(target)) is None

    @pytest.mark.asyncio
    async def test_download_invoice_reports_invoice_without_downloadable_document(self, tmp_path):
        coordinator = MagicMock()
        coordinator.data = {
            "contracts": {"REF1": {"factures": [{"id": "API-ID-1", "reference": "INV-1", "telechargeable": False}]}}
        }
        coordinator.api.get_invoice_pdf = AsyncMock()
        hass, handlers = _service_hass(coordinator)
        hass.config.is_allowed_path.return_value = True

        with pytest.raises(HomeAssistantError) as err:
            await handlers["download_latest_invoice"](
                MagicMock(
                    data={
                        "path": str(tmp_path / "invoice.pdf"),
                        "contract_reference": "REF1",
                    }
                )
            )

        assert err.value.translation_key == "no_downloadable_invoices"
        coordinator.api.get_invoice_pdf.assert_not_awaited()
