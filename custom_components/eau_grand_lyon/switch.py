"""Switch platform for Eau du Grand Lyon."""
from __future__ import annotations
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les switchs depuis une config entry."""
    from .coordinator import EauGrandLyonCoordinator
    
    coordinator: EauGrandLyonCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EauGrandLyonVacationSwitch(coordinator, entry)])

class EauGrandLyonVacationSwitch(SwitchEntity):
    """Switch pour activer le mode vacances (surveillance renforcée)."""

    _attr_has_entity_name = True
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:suitcase"
    _attr_name = "Mode vacances"

    def __init__(self, coordinator: Any, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_vacation_mode"

    @property
    def is_on(self) -> bool:
        return self.hass.data.get(DOMAIN, {}).get("vacation_mode", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hass.data.setdefault(DOMAIN, {})["vacation_mode"] = True
        await self.coordinator.async_refresh()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hass.data.setdefault(DOMAIN, {})["vacation_mode"] = False
        await self.coordinator.async_refresh()
        self.async_write_ha_state()

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "Eau du Grand Lyon",
        }
