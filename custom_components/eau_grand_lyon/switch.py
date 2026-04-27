"""Switch platform for Eau du Grand Lyon."""
from __future__ import annotations
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EauGrandLyonCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les switchs depuis une config entry."""
    coordinator = entry.runtime_data
    async_add_entities([EauGrandLyonVacationSwitch(coordinator, entry)])


class EauGrandLyonVacationSwitch(
    CoordinatorEntity[EauGrandLyonCoordinator], SwitchEntity
):
    """Switch pour activer le mode vacances (surveillance renforcée)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:suitcase"
    translation_key = "vacation_mode"

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_vacation_mode"

    @property
    def is_on(self) -> bool:
        return self.hass.data.get(DOMAIN, {}).get("vacation_mode", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hass.data.setdefault(DOMAIN, {})["vacation_mode"] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hass.data.setdefault(DOMAIN, {})["vacation_mode"] = False
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Eau du Grand Lyon",
        )
