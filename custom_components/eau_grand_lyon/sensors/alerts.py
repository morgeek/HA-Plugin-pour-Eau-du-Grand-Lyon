"""Sensors des seuils d'alerte surconsommation configurés côté serveur.

Ces seuils sont récupérés depuis l'espace client Eau du Grand Lyon
(endpoints `seuilAlerteSurconsommation/journaliere` et `.../mensuelle`).
Ils reflètent la configuration réelle de l'abonné plutôt qu'une heuristique
locale, et servent de référence aux binary_sensors de dépassement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import EntityCategory

from .base import _EauGrandLyonBase

if TYPE_CHECKING:
    from .. import EauGrandLyonConfigEntry
    from ..coordinator import EauGrandLyonCoordinator


class _EauGrandLyonSeuilBase(_EauGrandLyonBase):
    """Base commune aux capteurs de seuil de surconsommation (m³, diagnostic)."""

    # Pas de device_class WATER : un seuil configuré n'est pas un volume consommé,
    # et WATER interdit la state_class MEASUREMENT (combinaison rejetée par HA).
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "m³"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_suggested_display_precision = 1

    _data_key: str = ""

    @property
    def available(self) -> bool:
        return super().available and self._contract.get(self._data_key) is not None

    @property
    def native_value(self) -> float | None:
        return cast(float | None, self._contract.get(self._data_key))


class EauGrandLyonSeuilSurconsoJourSensor(_EauGrandLyonSeuilBase):
    """Seuil d'alerte surconsommation journalier configuré côté serveur."""

    _attr_translation_key = "seuil_surconso_jour"
    _data_key = "seuil_surconso_jour_m3"

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: EauGrandLyonConfigEntry,
        contract_ref: str,
    ) -> None:
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_seuil_surconso_jour"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
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

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: EauGrandLyonConfigEntry,
        contract_ref: str,
    ) -> None:
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_seuil_surconso_mois"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        c = self._contract
        return {
            "consommation_mois_m3": c.get("consommation_mois_courant"),
            "depassement": c.get("surconso_mois_depassee"),
            "source": "Seuil configuré dans l'espace Eau du Grand Lyon",
        }
