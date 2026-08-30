"""Tests pour les correctifs v3.4.1 au niveau __init__ (migration, stale-devices, exceptions)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.eau_grand_lyon import (
    _async_cleanup_legacy_device,
    async_migrate_entry,
    async_remove_config_entry_device,
    _validate_write_path,
)
from custom_components.eau_grand_lyon.const import (
    CONF_PRICE_ENTITY,
    CONF_TARIF_M3,
    CONF_TARIFF_MODE,
    DOMAIN,
    TARIFF_MODE_DYNAMIC,
    TARIFF_MODE_MANUAL,
    TARIFF_MODE_OFFICIAL_2026,
)
from homeassistant.exceptions import ServiceValidationError


class TestMigrateEntry:
    @pytest.mark.asyncio
    async def test_v1_to_v4_moves_tariff_to_manual_options(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.version = 1
        entry.data = {"email": "user@example.com", "password": "secret", CONF_TARIF_M3: 4.2}
        entry.options = {"experimental": True}
        assert await async_migrate_entry(hass, entry) is True
        hass.config_entries.async_update_entry.assert_called_once_with(
            entry,
            data={"email": "user@example.com", "password": "secret"},
            options={
                "experimental": True,
                CONF_TARIF_M3: 4.2,
                CONF_TARIFF_MODE: TARIFF_MODE_MANUAL,
            },
            version=4,
        )

    @pytest.mark.asyncio
    async def test_v2_migration_keeps_existing_option_tariff(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.version = 2
        entry.data = {"email": "user@example.com", "password": "secret", CONF_TARIF_M3: 3.1}
        entry.options = {CONF_TARIF_M3: 5.7}
        assert await async_migrate_entry(hass, entry) is True
        hass.config_entries.async_update_entry.assert_called_once_with(
            entry,
            data={"email": "user@example.com", "password": "secret"},
            options={CONF_TARIF_M3: 5.7, CONF_TARIFF_MODE: TARIFF_MODE_MANUAL},
            version=4,
        )

    @pytest.mark.asyncio
    async def test_v3_dynamic_price_entity_keeps_dynamic_behaviour(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.version = 3
        entry.data = {"email": "user@example.com", "password": "secret"}
        entry.options = {CONF_PRICE_ENTITY: "sensor.water_price"}

        assert await async_migrate_entry(hass, entry) is True

        hass.config_entries.async_update_entry.assert_called_once_with(
            entry,
            data=entry.data,
            options={
                CONF_PRICE_ENTITY: "sensor.water_price",
                CONF_TARIFF_MODE: TARIFF_MODE_DYNAMIC,
            },
            version=4,
        )

    @pytest.mark.asyncio
    async def test_v3_explicit_mode_is_preserved(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.version = 3
        entry.data = {"email": "user@example.com", "password": "secret"}
        entry.options = {CONF_TARIFF_MODE: TARIFF_MODE_OFFICIAL_2026}

        assert await async_migrate_entry(hass, entry) is True

        options = hass.config_entries.async_update_entry.call_args.kwargs["options"]
        assert options[CONF_TARIFF_MODE] == TARIFF_MODE_OFFICIAL_2026

    @pytest.mark.asyncio
    async def test_unknown_version_fails(self):
        hass = MagicMock()
        entry = MagicMock()
        entry.version = 99
        assert await async_migrate_entry(hass, entry) is False

    @pytest.mark.asyncio
    async def test_current_v4_entry_needs_no_migration(self):
        hass = MagicMock()
        entry = MagicMock(version=4)
        assert await async_migrate_entry(hass, entry) is True
        hass.config_entries.async_update_entry.assert_not_called()


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
    async def test_legacy_account_device_is_removable_when_contract_exists(self):
        entry = self._entry_with_contracts("REF1")
        device = MagicMock()
        device.identifiers = {(DOMAIN, "e1")}
        assert await async_remove_config_entry_device(MagicMock(), entry, device) is True

    @pytest.mark.asyncio
    async def test_account_device_is_not_removable(self):
        entry = self._entry_with_contracts()
        device = MagicMock()
        device.identifiers = {(DOMAIN, "e1")}
        assert await async_remove_config_entry_device(MagicMock(), entry, device) is False

    @pytest.mark.asyncio
    async def test_multiple_contract_devices_are_valid_and_legacy_is_stale(self):
        entry = self._entry_with_contracts("A", "B")
        for identifier in ("e1_A", "e1_B"):
            device = MagicMock()
            device.identifiers = {(DOMAIN, identifier)}
            assert await async_remove_config_entry_device(MagicMock(), entry, device) is False
        legacy = MagicMock()
        legacy.identifiers = {(DOMAIN, "e1")}
        assert await async_remove_config_entry_device(MagicMock(), entry, legacy) is True


class _FakeDeviceRegistry:
    def __init__(self, *devices):
        self.devices = {device.id: device for device in devices}
        self.removed: list[str] = []

    def async_get_device(self, identifiers):
        return next(
            (device for device in self.devices.values() if device.identifiers & identifiers),
            None,
        )

    def async_remove_device(self, device_id):
        self.removed.append(device_id)
        self.devices.pop(device_id)


class TestLegacyDeviceCleanup:
    @staticmethod
    def _device(device_id, identifier, *, config_entries=None, via_device_id=None):
        return SimpleNamespace(
            id=device_id,
            identifiers={(DOMAIN, identifier)},
            config_entries=set(config_entries or {"e1"}),
            via_device_id=via_device_id,
        )

    def _setup_registries(self, monkeypatch, *, refs=("REF1",), legacy_entities=None):
        legacy = self._device("legacy", "e1")
        current_devices = [self._device(f"device-{ref}", f"e1_{ref}") for ref in refs]
        device_registry = _FakeDeviceRegistry(legacy, *current_devices)
        current_entities = {
            device.id: [
                SimpleNamespace(
                    entity_id=f"sensor.{device.id}",
                    unique_id=f"unique-{device.id}",
                    config_entry_id="e1",
                    device_id=device.id,
                )
            ]
            for device in current_devices
        }
        entity_registry = SimpleNamespace(
            entries={
                **current_entities,
                "legacy": list(legacy_entities or []),
            },
            async_remove=MagicMock(),
        )
        monkeypatch.setattr("custom_components.eau_grand_lyon.dr.async_get", lambda hass: device_registry)
        monkeypatch.setattr("custom_components.eau_grand_lyon.er.async_get", lambda hass: entity_registry)
        monkeypatch.setattr(
            "custom_components.eau_grand_lyon.er.async_entries_for_device",
            lambda registry, device_id, include_disabled_entities=False: registry.entries.get(device_id, []),
        )
        entry = MagicMock()
        entry.entry_id = "e1"
        entry.runtime_data.data = {"contracts": {ref: {} for ref in refs}}
        return entry, device_registry, entity_registry

    def test_orphaned_legacy_device_is_removed_without_touching_entities(self, monkeypatch):
        entry, device_registry, entity_registry = self._setup_registries(monkeypatch)
        entities_before = {device_id: list(entities) for device_id, entities in entity_registry.entries.items()}

        assert _async_cleanup_legacy_device(MagicMock(), entry) is True

        assert device_registry.removed == ["legacy"]
        assert "device-REF1" in device_registry.devices
        assert entity_registry.entries == entities_before
        entity_registry.async_remove.assert_not_called()

    def test_cleanup_keeps_legacy_device_while_any_entity_is_attached(self, monkeypatch):
        legacy_entity = SimpleNamespace(
            entity_id="sensor.legacy",
            unique_id="legacy-unique",
            config_entry_id="e1",
            device_id="legacy",
        )
        entry, device_registry, entity_registry = self._setup_registries(
            monkeypatch,
            legacy_entities=[legacy_entity],
        )

        assert _async_cleanup_legacy_device(MagicMock(), entry) is False
        assert device_registry.removed == []
        assert entity_registry.entries["legacy"] == [legacy_entity]

    def test_cleanup_is_idempotent(self, monkeypatch):
        entry, device_registry, _ = self._setup_registries(monkeypatch)

        assert _async_cleanup_legacy_device(MagicMock(), entry) is True
        assert _async_cleanup_legacy_device(MagicMock(), entry) is False
        assert device_registry.removed == ["legacy"]

    def test_cleanup_supports_multiple_current_contract_devices(self, monkeypatch):
        entry, device_registry, _ = self._setup_registries(monkeypatch, refs=("A", "B"))

        assert _async_cleanup_legacy_device(MagicMock(), entry) is True
        assert set(device_registry.devices) == {"device-A", "device-B"}

    def test_cleanup_keeps_shared_or_parent_legacy_device(self, monkeypatch):
        entry, device_registry, _ = self._setup_registries(monkeypatch)
        device_registry.devices["legacy"].config_entries.add("other-entry")

        assert _async_cleanup_legacy_device(MagicMock(), entry) is False
        assert device_registry.removed == []

        device_registry.devices["legacy"].config_entries = {"e1"}
        child = self._device("child", "other_device", via_device_id="legacy")
        device_registry.devices[child.id] = child
        assert _async_cleanup_legacy_device(MagicMock(), entry) is False
        assert device_registry.removed == []

    def test_cleanup_defers_without_contracts_current_device_or_current_entity(self, monkeypatch):
        empty_entry = MagicMock()
        empty_entry.runtime_data.data = {"contracts": {}}
        assert _async_cleanup_legacy_device(MagicMock(), empty_entry) is False

        entry, device_registry, entity_registry = self._setup_registries(monkeypatch)
        device_registry.devices.pop("device-REF1")
        assert _async_cleanup_legacy_device(MagicMock(), entry) is False

        entry, device_registry, entity_registry = self._setup_registries(monkeypatch)
        entity_registry.entries["device-REF1"] = []
        assert _async_cleanup_legacy_device(MagicMock(), entry) is False
        assert device_registry.removed == []


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
