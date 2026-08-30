"""Tests for repairs, diagnostics, and service handlers."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from homeassistant.core import ServiceValidationError
from homeassistant.helpers import issue_registry as ir


class TestLongOutageIssueLogic:
    """Test le vrai comportement de check_long_outage_issue (repairs.py)."""

    @pytest.mark.asyncio
    async def test_creates_issue_at_or_above_7_days(self, monkeypatch) -> None:
        from custom_components.eau_grand_lyon import repairs

        created: list = []
        deleted: list = []
        monkeypatch.setattr(repairs.ir, "async_create_issue", lambda *a, **k: created.append((a, k)))
        monkeypatch.setattr(repairs.ir, "async_delete_issue", lambda *a, **k: deleted.append((a, k)))

        await repairs.check_long_outage_issue(MagicMock(), 7)
        assert len(created) == 1
        assert not deleted

        await repairs.check_long_outage_issue(MagicMock(), 30)
        assert len(created) == 2

    @pytest.mark.asyncio
    async def test_deletes_issue_below_7_days(self, monkeypatch) -> None:
        from custom_components.eau_grand_lyon import repairs

        created: list = []
        deleted: list = []
        monkeypatch.setattr(repairs.ir, "async_create_issue", lambda *a, **k: created.append((a, k)))
        monkeypatch.setattr(repairs.ir, "async_delete_issue", lambda *a, **k: deleted.append((a, k)))

        await repairs.check_long_outage_issue(MagicMock(), 6)
        assert len(deleted) == 1
        assert not created

    @pytest.mark.asyncio
    async def test_create_issue_uses_expected_metadata(self, monkeypatch) -> None:
        """L'issue longue panne : id stable, non-fixable, translation_key correct."""
        from custom_components.eau_grand_lyon import repairs

        captured: dict = {}

        def _capture(hass, domain, issue_id, **kwargs):
            captured.update(kwargs)
            captured["issue_id"] = issue_id

        monkeypatch.setattr(repairs.ir, "async_create_issue", _capture)
        await repairs.check_long_outage_issue(MagicMock(), 10)
        assert captured["issue_id"] == "long_outage"
        assert captured["is_fixable"] is False
        assert captured["translation_key"] == "long_outage"


class TestDiagnosticsModule:
    """Test diagnostics module logic."""

    def test_diagnostics_module_exists(self) -> None:
        """Test that diagnostics module can be imported."""
        from custom_components.eau_grand_lyon import diagnostics

        assert hasattr(diagnostics, "async_get_config_entry_diagnostics")

    @pytest.mark.asyncio
    async def test_diagnostics_omit_title_and_rekey_contracts(self, monkeypatch) -> None:
        """Regression: entry.title contains the account email and contract dicts
        are keyed by contract reference — neither must reach the export."""
        import sys
        import types

        captured = {}

        def _redact(data, to_redact):
            captured["data"] = data
            return data

        sys.modules["homeassistant.components.diagnostics"] = types.SimpleNamespace(async_redact_data=_redact)
        from custom_components.eau_grand_lyon.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        entry = MagicMock()
        entry.title = "Eau du Grand Lyon (user@example.com)"
        entry.version = 2
        entry.options = {}
        coordinator = MagicMock()
        coordinator.data = {"contracts": {"SECRET-REF-123": {"solde_eur": 1.0}}}
        entry.runtime_data = coordinator

        result = await async_get_config_entry_diagnostics(MagicMock(), entry)

        assert "title" not in result["entry"]
        contracts = result["coordinator_data"]["contracts"]
        assert "SECRET-REF-123" not in contracts
        assert contracts == {"contract_1": {"solde_eur": 1.0}}


class TestServiceHandlersExist:
    """Test that service handlers are properly defined."""

    def test_service_handlers_imported_successfully(self) -> None:
        """Test that all service handlers can be imported."""
        from custom_components.eau_grand_lyon import _async_setup_services

        # Just verify the function exists and is callable
        assert callable(_async_setup_services)

    def test_repairs_functions_exist(self) -> None:
        """Test that repairs functions exist and are callable."""
        from custom_components.eau_grand_lyon.repairs import check_long_outage_issue

        assert callable(check_long_outage_issue)


class TestWritePathValidation:
    """Services writing files must reject paths outside allowlist_external_dirs."""

    def test_rejects_empty_path(self) -> None:
        from custom_components.eau_grand_lyon import _validate_write_path

        hass = MagicMock()
        with pytest.raises(ServiceValidationError):
            _validate_write_path(hass, "   ")

    def test_rejects_disallowed_path(self) -> None:
        from custom_components.eau_grand_lyon import _validate_write_path

        hass = MagicMock()
        hass.config.is_allowed_path = MagicMock(return_value=False)
        with pytest.raises(ServiceValidationError):
            _validate_write_path(hass, "/etc/passwd")
        hass.config.is_allowed_path.assert_called_once_with("/etc/passwd")

    def test_accepts_allowed_path(self) -> None:
        from custom_components.eau_grand_lyon import _validate_write_path

        hass = MagicMock()
        hass.config.is_allowed_path = MagicMock(return_value=True)
        _validate_write_path(hass, "/config/exports/eau.csv")


class TestRepairIssueRegistry:
    """Exercise the issue-registry calls (regression for awaiting sync callbacks)."""

    @pytest.mark.asyncio
    async def test_long_outage_issue_create_and_delete(self) -> None:
        from custom_components.eau_grand_lyon.repairs import check_long_outage_issue

        hass = MagicMock()
        ir.async_create_issue.reset_mock()
        ir.async_delete_issue.reset_mock()

        await check_long_outage_issue(hass, 9)
        assert ir.async_create_issue.called

        await check_long_outage_issue(hass, 0)
        assert ir.async_delete_issue.called
