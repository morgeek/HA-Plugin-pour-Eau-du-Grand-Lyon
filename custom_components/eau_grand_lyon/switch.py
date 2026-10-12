"""Switch platform for Eau du Grand Lyon."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import analytics
from .coordinator import EauGrandLyonCoordinator

if TYPE_CHECKING:
    from . import EauGrandLyonConfigEntry
from .device import account_device_info

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EauGrandLyonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les switchs depuis une config entry."""
    coordinator = entry.runtime_data
    async_add_entities([EauGrandLyonVacationSwitch(coordinator, entry)])


ATTR_SINCE = "depuis"


def _restored_since(last_state: Any) -> date:
    """Jour de départ mémorisé dans l'état précédent du switch."""
    attributes = getattr(last_state, "attributes", None) or {}
    try:
        return date.fromisoformat(str(attributes.get(ATTR_SINCE)))
    except (TypeError, ValueError):
        # État enregistré par une version sans date : repartir d'aujourd'hui évite
        # d'alerter sur des journées antérieures au départ.
        return analytics.local_now().date()


class EauGrandLyonVacationSwitch(CoordinatorEntity[EauGrandLyonCoordinator], SwitchEntity, RestoreEntity):
    """Switch pour activer le mode vacances (surveillance renforcée)."""

    _attr_has_entity_name = True
    _attr_translation_key = "vacation_mode"

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: EauGrandLyonConfigEntry) -> None:
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
            # Resynchroniser le coordinator : sans ça, le switch affiche "on"
            # après un redémarrage mais la surveillance vacances reste inactive.
            self.coordinator.vacation_mode = self._attr_is_on
            self.coordinator.vacation_since = _restored_since(last_state) if self._attr_is_on else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        since = self.coordinator.vacation_since
        return {ATTR_SINCE: since.isoformat() if self._attr_is_on and since else None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self._attr_is_on or self.coordinator.vacation_since is None:
            self.coordinator.vacation_since = analytics.local_now().date()
        self._attr_is_on = True
        self.coordinator.vacation_mode = True
        self.async_write_ha_state()
        # Réévalue tout de suite « Consommation pendant l'absence », sans appel réseau.
        self.coordinator.async_update_listeners()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        self.coordinator.vacation_mode = False
        self.coordinator.vacation_since = None
        self.async_write_ha_state()
        self.coordinator.async_update_listeners()

    @property
    def device_info(self) -> DeviceInfo:
        return account_device_info(self.coordinator, self._entry)
