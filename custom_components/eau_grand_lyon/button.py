"""Bouton de rafraîchissement manuel pour Eau du Grand Lyon."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EauGrandLyonCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée les boutons de l'intégration."""
    coordinator = entry.runtime_data
    entities = [EauGrandLyonRefreshButton(coordinator, entry)]
    
    # Bouton facture (si expérimental)
    if entry.options.get("experimental_api"):
        entities.append(EauGrandLyonDownloadInvoiceButton(coordinator, entry))
        
    async_add_entities(entities)


class EauGrandLyonRefreshButton(
    CoordinatorEntity[EauGrandLyonCoordinator], ButtonEntity
):
    """Bouton pour forcer la mise à jour immédiate des données."""

    _attr_has_entity_name = True
    _attr_name = "Forcer la mise à jour"
    _attr_icon = "mdi:refresh"

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
        """Rattache le bouton au premier appareil (contrat) trouvé."""
        contracts = (self.coordinator.data or {}).get("contracts", {})
        first_ref = next(iter(contracts), None)
        if first_ref:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry.entry_id}_{first_ref}")},
            )
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Eau du Grand Lyon",
            manufacturer="Morgeek",
        )

    async def async_press(self) -> None:
        """Déclenche immédiatement une mise à jour des données."""
        _LOGGER.debug("Rafraîchissement manuel déclenché par l'utilisateur")
        await self.coordinator.async_request_refresh()


class EauGrandLyonDownloadInvoiceButton(
    CoordinatorEntity[EauGrandLyonCoordinator], ButtonEntity
):
    """Bouton pour télécharger la dernière facture PDF."""

    _attr_has_entity_name = True
    translation_key = "download_invoice"
    _attr_icon = "mdi:file-download"

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
        contracts = (self.coordinator.data or {}).get("contracts", {})
        first_ref = next(iter(contracts), None)
        if first_ref:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry.entry_id}_{first_ref}")},
            )
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Eau du Grand Lyon",
        )

    async def async_press(self) -> None:
        """Déclenche le téléchargement via le service."""
        _LOGGER.debug("Téléchargement de facture déclenché par bouton")
        await self.hass.services.async_call(
            DOMAIN,
            "download_latest_invoice",
            {},
            blocking=True,
        )
