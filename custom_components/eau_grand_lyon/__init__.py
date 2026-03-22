"""Intégration Home Assistant pour Eau du Grand Lyon."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import EauGrandLyonCoordinator
# from .notify import async_setup_services  # Temporarily disabled due to import issues

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialise l'intégration depuis une config entry."""
    coordinator = EauGrandLyonCoordinator(hass, entry)

    # Récupération initiale des données (bloquant jusqu'au premier succès)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Configuration des services de notifications intelligentes
    # await async_setup_services(hass)  # Temporarily disabled

    # Rechargement automatique si les options changent (intervalle de mise à jour)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge une config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: EauGrandLyonCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()
    return unload_ok


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recharge l'intégration quand les options changent.

    Appelé automatiquement par HA lorsque l'utilisateur modifie les options
    (ex. intervalle de mise à jour). Le rechargement recrée le coordinateur
    avec le nouvel intervalle.
    """
    _LOGGER.debug(
        "Options modifiées pour %s, rechargement de l'intégration", entry.title
    )
    await hass.config_entries.async_reload(entry.entry_id)
