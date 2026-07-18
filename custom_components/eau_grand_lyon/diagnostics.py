"""Diagnostics support for Eau du Grand Lyon."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Retourne les diagnostics pour une config entry (redacté)."""
    from homeassistant.components.diagnostics import async_redact_data

    # Champs à masquer dans les exports de diagnostic pour préserver la vie privée
    from .const import (
        CONF_EMAIL,
        CONF_HOUSEHOLD_SIZE,
        CONF_LEAK_MULTIPLIER,
        CONF_PASSWORD,
        CONF_SUBSCRIPTION_ANNUAL,
        CONF_TARIF_M3,
        CONF_WATER_QUALITY_COMMUNE,
    )

    to_redact = {
        CONF_EMAIL,
        CONF_PASSWORD,
        CONF_TARIF_M3,
        CONF_HOUSEHOLD_SIZE,
        CONF_WATER_QUALITY_COMMUNE,
        CONF_SUBSCRIPTION_ANNUAL,
        CONF_LEAK_MULTIPLIER,
        "reference",
        "reference_pds",
        "id",
        "contrat_id",
    }

    coordinator = entry.runtime_data
    coordinator_data: dict[str, Any] = dict(coordinator.data or {})
    if coordinator_data:
        # Le dict contracts est indexé par référence de contrat : async_redact_data
        # ne masque que les valeurs, pas les clés — on ré-indexe en contract_N.
        contracts = coordinator_data.get("contracts") or {}
        coordinator_data["contracts"] = {
            f"contract_{i}": contract for i, contract in enumerate(contracts.values(), start=1)
        }
    else:
        coordinator_data = {"status": "no_data_available"}

    # entry.title contient l'email du compte — ne pas l'exporter
    diagnostics_data = {
        "entry": {
            "version": entry.version,
            "options": entry.options,
        },
        "coordinator_data": coordinator_data,
    }

    return async_redact_data(diagnostics_data, to_redact)
