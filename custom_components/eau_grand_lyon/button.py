"""Bouton de rafraîchissement manuel pour Eau du Grand Lyon."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_EXPERIMENTAL, DOMAIN
from .coordinator import EauGrandLyonCoordinator
from .device import account_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée les boutons de l'intégration."""
    coordinator = entry.runtime_data
    entities = [EauGrandLyonRefreshButton(coordinator, entry)]

    # Bouton facture (si expérimental)
    if entry.options.get(CONF_EXPERIMENTAL):
        entities.append(EauGrandLyonDownloadInvoiceButton(coordinator, entry))

    async_add_entities(entities)


class EauGrandLyonRefreshButton(CoordinatorEntity[EauGrandLyonCoordinator], ButtonEntity):
    """Bouton pour forcer la mise à jour immédiate des données."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh"

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_refresh"

    @property
    def device_info(self) -> DeviceInfo:
        return account_device_info(self.coordinator, self._entry)

    async def async_press(self) -> None:
        """Déclenche immédiatement une mise à jour des données."""
        _LOGGER.debug("Manual refresh triggered by user")
        await self.coordinator.async_request_refresh()


class EauGrandLyonDownloadInvoiceButton(CoordinatorEntity[EauGrandLyonCoordinator], ButtonEntity):
    """Bouton pour télécharger la dernière facture PDF."""

    _attr_has_entity_name = True
    _attr_translation_key = "download_invoice"

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_download_invoice"

    @property
    def device_info(self) -> DeviceInfo:
        return account_device_info(self.coordinator, self._entry)

    async def async_press(self) -> None:
        """Déclenche le téléchargement via le service."""
        _LOGGER.debug("Invoice download triggered by button")
        await self.hass.services.async_call(
            DOMAIN,
            "download_latest_invoice",
            {},
            blocking=True,
        )
