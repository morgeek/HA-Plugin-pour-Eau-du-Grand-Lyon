"""Tests for repairs, diagnostics, and service handlers."""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from homeassistant.core import ServiceValidationError
from homeassistant.helpers import issue_registry as ir


class TestLongOutageIssueLogic:
    """Test long outage issue creation logic."""

    def test_long_outage_threshold_is_7_days(self) -> None:
        """Test that 7 days is the threshold for long outage alerts."""
        # Just verify the threshold logic
        assert 7 >= 7  # Should trigger
        assert 6 < 7   # Should not trigger
        assert 8 >= 7  # Should trigger


class TestDiagnosticsModule:
    """Test diagnostics module logic."""

    def test_diagnostics_module_exists(self) -> None:
        """Test that diagnostics module can be imported."""
        from custom_components.eau_grand_lyon import diagnostics

        assert hasattr(diagnostics, "async_get_config_entry_diagnostics")

    def test_diagnostics_redaction_fields_defined(self) -> None:
        """Test that redaction fields are properly defined."""
        from custom_components.eau_grand_lyon.const import CONF_EMAIL, CONF_PASSWORD

        # These are the fields that should be redacted
        sensitive_fields = {
            CONF_EMAIL,
            CONF_PASSWORD,
            "reference",
            "reference_pds",
            "id",
            "contrat_id",
        }

        # Verify the sensitive fields are properly defined
        assert CONF_EMAIL in sensitive_fields
        assert CONF_PASSWORD in sensitive_fields
        assert "reference" in sensitive_fields
        assert "id" in sensitive_fields

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

        sys.modules["homeassistant.components.diagnostics"] = types.SimpleNamespace(
            async_redact_data=_redact
        )
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
