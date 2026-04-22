"""Diagnostics support for Eau du Grand Lyon."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Retourne les diagnostics pour une config entry (redacté)."""
    from homeassistant.components.diagnostics import redact_sensitive_data
    from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN
    from .coordinator import EauGrandLyonCoordinator
    
    # Champs à masquer dans les exports de diagnostic pour préserver la vie privée
    to_redact = {
        CONF_EMAIL,
        CONF_PASSWORD,
        "reference",
        "reference_pds",
        "id",
        "contrat_id",
    }
    
    coordinator: EauGrandLyonCoordinator = hass.data[DOMAIN][entry.entry_id]

    diagnostics_data = {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "options": entry.options,
        },
        "coordinator_data": coordinator.data,
    }

    return redact_sensitive_data(diagnostics_data, to_redact)
