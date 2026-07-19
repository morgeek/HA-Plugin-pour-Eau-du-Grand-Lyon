"""Tests pour les correctifs v3.4.1 au niveau __init__ (migration, stale-devices, exceptions)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.eau_grand_lyon import (
    async_migrate_entry,
    async_remove_config_entry_device,
    _validate_write_path,
)
from custom_components.eau_grand_lyon.const import DOMAIN
from homeassistant.exceptions import ServiceValidationError


class TestMigrateEntry:
    @pytest.mark.asyncio
    async def test_v1_to_v2_updates_version(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.version = 1
        assert await async_migrate_entry(hass, entry) is True
        hass.config_entries.async_update_entry.assert_called_once()
        _, kwargs = hass.config_entries.async_update_entry.call_args
        assert kwargs.get("version") == 2

    @pytest.mark.asyncio
    async def test_unknown_version_fails(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.version = 99
        assert await async_migrate_entry(hass, entry) is False


class TestStaleDeviceRemoval:
    def _entry_with_contracts(self, *refs):
        entry = MagicMock()
        entry.entry_id = "e1"
        coord = MagicMock()
        coord.data = {"contracts": {ref: {} for ref in refs}}
        entry.runtime_data = coord
        return entry

    @pytest.mark.asyncio
    async def test_orphan_device_is_removable(self):
        entry = self._entry_with_contracts("REF1")
        device = MagicMock()
        device.identifiers = {(DOMAIN, "e1_OLD_CONTRACT")}
        assert await async_remove_config_entry_device(MagicMock(), entry, device) is True

    @pytest.mark.asyncio
    async def test_active_device_is_not_removable(self):
        entry = self._entry_with_contracts("REF1")
        device = MagicMock()
        device.identifiers = {(DOMAIN, "e1_REF1")}
        assert await async_remove_config_entry_device(MagicMock(), entry, device) is False

    @pytest.mark.asyncio
    async def test_account_device_is_not_removable(self):
        entry = self._entry_with_contracts()
        device = MagicMock()
        device.identifiers = {(DOMAIN, "e1")}
        assert await async_remove_config_entry_device(MagicMock(), entry, device) is False


class TestServiceExceptionTranslations:
    """Les exceptions de service portent un translation_key (Gold exception-translations)."""

    def test_empty_path_uses_invalid_path_key(self):
        hass = MagicMock()
        try:
            _validate_write_path(hass, "   ")
        except ServiceValidationError as err:
            assert err.translation_key == "invalid_path"
            assert err.translation_domain == DOMAIN
        else:
            pytest.fail("expected ServiceValidationError")

    def test_disallowed_path_uses_path_not_allowed_key(self):
        hass = MagicMock()
        hass.config.is_allowed_path.return_value = False
        try:
            _validate_write_path(hass, "/etc/passwd")
        except ServiceValidationError as err:
            assert err.translation_key == "path_not_allowed"
            assert err.translation_placeholders == {"path": "/etc/passwd"}
        else:
            pytest.fail("expected ServiceValidationError")
