"""Helpers DeviceInfo partagés par toutes les plateformes.

Garantit qu'un même device (compteur) reçoit des métadonnées identiques quelle
que soit la plateforme qui le déclare (sensor, binary_sensor, button, ...).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN

MANUFACTURER = "Eau du Grand Lyon"
CONFIGURATION_URL = "https://agence.eaudugrandlyon.com"


def contract_device_info(
    coordinator: DataUpdateCoordinator,
    entry: ConfigEntry,
    contract_ref: str,
) -> DeviceInfo:
    """DeviceInfo du device par contrat (le compteur d'eau)."""
    contracts = (coordinator.data or {}).get("contracts", {})
    contract = contracts.get(contract_ref, {})
    calibre = contract.get("calibre_compteur", "")
    usage = contract.get("usage", "")
    model_parts = [p for p in [calibre and f"DN{calibre}", usage] if p]
    serial = contract.get("reference_pds") or contract.get("reference", contract_ref)
    # Avec plusieurs contrats, suffixer la référence pour distinguer les devices
    name = MANUFACTURER if len(contracts) <= 1 else f"{MANUFACTURER} {contract_ref}"
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{contract_ref}")},
        name=name,
        manufacturer=MANUFACTURER,
        model=", ".join(model_parts) or "Compteur eau",
        serial_number=serial,
        configuration_url=CONFIGURATION_URL,
    )


def account_device_info(
    coordinator: DataUpdateCoordinator,
    entry: ConfigEntry,
) -> DeviceInfo:
    """DeviceInfo des entités globales — rattachées au device du premier contrat."""
    contracts = (coordinator.data or {}).get("contracts", {})
    first_ref = next(iter(contracts), None)
    if first_ref:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{first_ref}")},
        )
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=MANUFACTURER,
        manufacturer=MANUFACTURER,
        configuration_url=CONFIGURATION_URL,
    )
