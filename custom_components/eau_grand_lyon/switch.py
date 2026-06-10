"""Switch platform for Eau du Grand Lyon."""

from __future__ import annotations
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import EauGrandLyonCoordinator
from .device import account_device_info

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les switchs depuis une config entry."""
    coordinator = entry.runtime_data
    async_add_entities([EauGrandLyonVacationSwitch(coordinator, entry)])


class EauGrandLyonVacationSwitch(CoordinatorEntity[EauGrandLyonCoordinator], SwitchEntity, RestoreEntity):
    """Switch pour activer le mode vacances (surveillance renforcée)."""

    _attr_has_entity_name = True
    _attr_translation_key = "vacation_mode"

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_vacation_mode"
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore previous on/off state across restarts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        self.coordinator.vacation_mode = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.coordinator.vacation_mode = False
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return account_device_info(self.coordinator, self._entry)
