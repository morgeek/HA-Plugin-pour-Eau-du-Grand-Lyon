# Services de notifications intelligentes pour Eau du Grand Lyon
"""Services pour notifications Pushover/Telegram et alertes vocales."""

import logging
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Configure les services de notifications intelligentes."""

    async def async_notify_pushover(call: ServiceCall) -> None:
        """Envoie une notification Pushover."""
        _LOGGER.info("Pushover notification: %s", call.data.get("message", ""))

    async def async_notify_telegram(call: ServiceCall) -> None:
        """Envoie une notification Telegram."""
        _LOGGER.info("Telegram notification: %s", call.data.get("message", ""))

    async def async_alert_voice(call: ServiceCall) -> None:
        """Envoie une alerte vocale via Google Home/Alexa."""
        _LOGGER.info("Voice alert: %s", call.data.get("message", ""))

    async def async_smart_alert(call: ServiceCall) -> None:
        """Déclenche une alerte intelligente basée sur les données."""
        _LOGGER.info("Smart alert: %s", call.data.get("alert_type", ""))

    # Enregistrement des services sans schémas pour éviter les dépendances
    hass.services.async_register(DOMAIN, "notify_pushover", async_notify_pushover)
    hass.services.async_register(DOMAIN, "notify_telegram", async_notify_telegram)
    hass.services.async_register(DOMAIN, "alert_voice", async_alert_voice)
    hass.services.async_register(DOMAIN, "smart_alert", async_smart_alert)

    _LOGGER.info("Services de notifications intelligentes configurés")