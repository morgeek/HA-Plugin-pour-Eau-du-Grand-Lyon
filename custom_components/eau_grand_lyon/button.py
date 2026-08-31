"""Bouton de rafraîchissement manuel pour Eau du Grand Lyon."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EauGrandLyonCoordinator

if TYPE_CHECKING:
    from . import EauGrandLyonConfigEntry
from .device import account_device_info

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EauGrandLyonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée les boutons de l'intégration."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EauGrandLyonRefreshButton(coordinator, entry),
            EauGrandLyonDownloadInvoiceButton(coordinator, entry),
        ]
    )


class EauGrandLyonRefreshButton(CoordinatorEntity[EauGrandLyonCoordinator], ButtonEntity):
    """Bouton pour forcer la mise à jour immédiate des données."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh"

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: EauGrandLyonConfigEntry,
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
        entry: EauGrandLyonConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_download_invoice"

    @property
    def device_info(self) -> DeviceInfo:
        return account_device_info(self.coordinator, self._entry)

    @property
    def available(self) -> bool:
        """Disponible si au moins une facture possède un document téléchargeable."""
        if not super().available:
            return False
        for contract in (self.coordinator.data or {}).get("contracts", {}).values():
            if any(
                invoice.get("id") not in (None, "") and invoice.get("telechargeable") is not False
                for invoice in contract.get("factures", [])
            ):
                return True
        return False

    async def async_press(self) -> None:
        """Déclenche le téléchargement via le service."""
        _LOGGER.debug("Invoice download triggered by button")
        await self.hass.services.async_call(
            DOMAIN,
            "download_latest_invoice",
            {},
            blocking=True,
        )
