"""Sensors des seuils d'alerte surconsommation configurés côté serveur.

Ces seuils sont récupérés depuis l'espace client Eau du Grand Lyon
(endpoints `seuilAlerteSurconsommation/journaliere` et `.../mensuelle`).
Ils reflètent la configuration réelle de l'abonné plutôt qu'une heuristique
locale, et servent de référence aux binary_sensors de dépassement.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory

from .base import _EauGrandLyonBase


class _EauGrandLyonSeuilBase(_EauGrandLyonBase):
    """Base commune aux capteurs de seuil de surconsommation (m³, diagnostic)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "m³"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 1

    _data_key: str = ""

    @property
    def available(self) -> bool:
        return super().available and self._contract.get(self._data_key) is not None

    @property
    def native_value(self) -> float | None:
        return self._contract.get(self._data_key)


class EauGrandLyonSeuilSurconsoJourSensor(_EauGrandLyonSeuilBase):
    """Seuil d'alerte surconsommation journalier configuré côté serveur."""

    _attr_translation_key = "seuil_surconso_jour"
    _data_key = "seuil_surconso_jour_m3"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_seuil_surconso_jour"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "consommation_jour_m3": c.get("derniere_conso_jour_m3"),
            "depassement": c.get("surconso_jour_depassee"),
            "source": "Seuil configuré dans l'espace Eau du Grand Lyon",
        }


class EauGrandLyonSeuilSurconsoMoisSensor(_EauGrandLyonSeuilBase):
    """Seuil d'alerte surconsommation mensuel configuré côté serveur."""

    _attr_translation_key = "seuil_surconso_mois"
    _data_key = "seuil_surconso_mois_m3"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_seuil_surconso_mois"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "consommation_mois_m3": c.get("consommation_mois_courant"),
            "depassement": c.get("surconso_mois_depassee"),
            "source": "Seuil configuré dans l'espace Eau du Grand Lyon",
        }
