"""Binary sensors pour Eau du Grand Lyon."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EauGrandLyonCoordinator

if TYPE_CHECKING:
    from . import EauGrandLyonConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EauGrandLyonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée les binary sensors Eau du Grand Lyon."""
    coordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = []
    for ref in (coordinator.data or {}).get("contracts", {}):
        entities.append(EauGrandLyonLeakAlertSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonRealTimeLeakSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonLocalLeakSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonBatterySensor(coordinator, entry, ref))
        entities.append(EauGrandLyonLimescaleAlertSensor(coordinator, entry, ref))

    # [FEAT 3] Coupure/Travaux planifiés — capteur global
    entities.append(EauGrandLyonOutageSensor(coordinator, entry))

    async_add_entities(entities, update_before_add=False)


class _EauGrandLyonBinaryBase(
    CoordinatorEntity[EauGrandLyonCoordinator], BinarySensorEntity
):
    """Base pour les binary sensors Eau du Grand Lyon."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: ConfigEntry,
        contract_ref: str,
    ) -> None:
        super().__init__(coordinator)
        self._contract_ref = contract_ref
        self._entry = entry

    @property
    def _contract(self) -> dict:
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get("contracts", {}).get(self._contract_ref, {})

    @property
    def device_info(self) -> DeviceInfo:
        calibre = self._contract.get("calibre_compteur", "")
        usage = self._contract.get("usage", "")
        model_parts = [p for p in [calibre and f"DN{calibre}", usage] if p]
        numero_compteur = (
            self._contract.get("reference_pds")
            or self._contract.get("reference", self._contract_ref)
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_{self._contract_ref}")},
            name="Eau du Grand Lyon",
            manufacturer="Morgeek",
            model=", ".join(model_parts) or "Compteur eau",
            serial_number=numero_compteur,
            configuration_url="https://agence.eaudugrandlyon.com",
        )


class EauGrandLyonLeakAlertSensor(_EauGrandLyonBinaryBase):
    """Alerte possible fuite basée sur surconsommation mensuelle."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    translation_key = "leak_alert"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_leak_alert"

    @property
    def is_on(self) -> bool:
        c = self._contract
        conso_courant = c.get("consommation_mois_courant")
        conso_precedent = c.get("consommation_mois_precedent")
        if conso_courant and conso_precedent:
            return conso_courant > 2 * conso_precedent
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "consommation_courant_m3": c.get("consommation_mois_courant"),
            "consommation_precedent_m3": c.get("consommation_mois_precedent"),
            "seuil_alerte": "Consommation actuelle > 2x précédente",
        }


class EauGrandLyonRealTimeLeakSensor(_EauGrandLyonBinaryBase):
    """Alerte fuite en temps réel basée sur les données journalières (Téléo)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    translation_key = "real_time_leak"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_real_time_leak"

    @property
    def available(self) -> bool:
        """Disponible uniquement si le mode expérimental est actif et données présentes."""
        return (
            super().available
            and (self.coordinator.data or {}).get("experimental_mode")
            and self._contract.get("fuite_estime_30j_m3") is not None
        )

    @property
    def is_on(self) -> bool:
        val = self._contract.get("fuite_estime_30j_m3")
        return val is not None and val > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "volume_fuite_30j_m3": self._contract.get("fuite_estime_30j_m3"),
            "note": "Basé sur l'indicateur 'volumeFuiteEstime' de l'API Grand Lyon",
        }


class EauGrandLyonLocalLeakSensor(_EauGrandLyonBinaryBase):
    """Alerte fuite basée sur une analyse de pattern locale (conso constante)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    translation_key = "local_leak"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_local_leak_pattern"

    @property
    def is_on(self) -> bool:
        return self._contract.get("local_leak_pattern", False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "méthode": "Analyse de pattern (flux constant > 0)",
            "note": "Détecté localement par l'intégration si la consommation ne tombe jamais à 0 sur 24h.",
        }


class EauGrandLyonBatterySensor(_EauGrandLyonBinaryBase):
    """État de la pile du module Téléo."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY
    translation_key = "battery"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_battery_low"

    @property
    def is_on(self) -> bool:
        """True si la batterie est faible."""
        return self._contract.get("battery_ok") is False


class EauGrandLyonLimescaleAlertSensor(_EauGrandLyonBinaryBase):
    """Alerte accumulation excessive de calcaire."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    translation_key = "limescale_alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_limescale_alert"

    @property
    def is_on(self) -> bool:
        """True si le calcaire cumulé dépasse 100kg."""
        return self._contract.get("limescale_alert", False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "seuil_maintenance": "100 kg de calcaire cumulé",
            "note": "Alerte indicative pour entretien chauffe-eau ou adoucisseur.",
        }


# ══════════════════════════════════════════════════════════════════════
# Feat 3 — Capteur global : Interruption / Travaux planifiés
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonOutageSensor(
    CoordinatorEntity[EauGrandLyonCoordinator], BinarySensorEntity
):
    """True si une interruption de service est active ou prévue dans les 48h."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:pipe-wrench"
    translation_key = "outage_alert"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_outage_alert"

    @property
    def is_on(self) -> bool:
        """True si une interruption est imminente (dans les 48h) ou en cours."""
        interruptions = (self.coordinator.data or {}).get("interruptions", [])
        if not interruptions:
            return False
        today = date.today()
        horizon = today + timedelta(hours=48)
        for inter in interruptions:
            debut_str = inter.get("date_debut")
            fin_str   = inter.get("date_fin")
            try:
                debut = date.fromisoformat(debut_str) if debut_str else None
                fin   = date.fromisoformat(fin_str)   if fin_str   else debut
            except (ValueError, TypeError):
                continue
            if debut is None:
                continue
            # En cours ou dans les 48h
            if debut <= horizon and (fin is None or fin >= today):
                return True
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        interruptions = (self.coordinator.data or {}).get("interruptions", [])
        prochaine = (self.coordinator.data or {}).get("prochaine_coupure") or {}
        return {
            "nb_interruptions":     len(interruptions),
            "prochaine_date":       prochaine.get("date_debut"),
            "prochaine_fin":        prochaine.get("date_fin"),
            "prochaine_titre":      prochaine.get("titre"),
            "prochaine_type":       prochaine.get("type"),
            "toutes": [
                {
                    "titre":      i.get("titre"),
                    "date_debut": i.get("date_debut"),
                    "date_fin":   i.get("date_fin"),
                    "type":       i.get("type"),
                }
                for i in interruptions[:10]
            ],
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Eau du Grand Lyon",
            manufacturer="Morgeek",
            configuration_url="https://agence.eaudugrandlyon.com",
        )
