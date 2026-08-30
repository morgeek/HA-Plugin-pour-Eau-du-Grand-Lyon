"""Sensors globaux : alertes, santé API, agrégats multi-contrats, sécheresse, travaux."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory

from ..coordinator import EauGrandLyonCoordinator
from .base import _EauGrandLyonGlobalBase


class EauGrandLyonAlertesSensor(_EauGrandLyonGlobalBase):
    """Nombre d'alertes actives sur l'ensemble des contrats."""

    # Un compteur d'alertes courant est une MEASUREMENT, pas un total cumulatif.
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "alertes"
    _attr_native_unit_of_measurement = "alertes"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_alertes"

    @property
    def native_value(self) -> int:
        if not self.coordinator.data:
            return 0
        return self.coordinator.data.get("nb_alertes", 0)


class EauGrandLyonLastUpdateSensor(_EauGrandLyonGlobalBase):
    """Horodatage de la dernière synchronisation réussie."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "last_update"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_update"

    @property
    def native_value(self) -> datetime | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("last_update_success_time")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "dernière_erreur": data.get("last_error"),
            "type_erreur": data.get("last_error_type"),
            "heure_dernier_echec": data.get("last_failure_time"),
            "raison_dernier_echec": data.get("last_failure_reason"),
            "age_cache_jours": data.get("cache_age_days"),
        }


class EauGrandLyonHealthSensor(_EauGrandLyonGlobalBase):
    """Statut global de l'intégration (API/connexion)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "health"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["ok", "error", "offline", "unknown"]

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_api_status"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        if data.get("offline_mode"):
            return "offline"
        if data.get("last_error"):
            return "error"
        if data.get("last_update_success_time"):
            return "ok"
        return "unknown"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        attrs: dict[str, Any] = {
            "last_update_success_time": data.get("last_update_success_time"),
            "last_error": data.get("last_error"),
            "last_error_type": data.get("last_error_type"),
            "last_failure_time": data.get("last_failure_time"),
            "last_failure_reason": data.get("last_failure_reason"),
            "offline_mode": data.get("offline_mode", False),
            "cache_age_days": data.get("cache_age_days"),
            "experimental_mode": data.get("experimental_mode", False),
            "api_mode": data.get("api_mode", "Legacy"),
            "consecutive_failures": data.get("consecutive_failures", 0),
        }
        contracts = data.get("contracts") or {}
        teleo_contracts = [contract for contract in contracts.values() if contract.get("teleo_compatible")]
        if contracts and not teleo_contracts:
            attrs["teleo_note"] = (
                "Aucun contrat Téléo/TIC compatible détecté — les données journalières "
                "ne sont pas disponibles pour ces compteurs."
            )
        elif contracts and any(
            contract.get("teleo_compatible") is False and contract.get("daily_nb_entries", 0) == 0
            for contract in contracts.values()
        ):
            attrs["teleo_note"] = (
                "Certains contrats ne renvoient pas de données journalières. "
                "Ces compteurs peuvent ne pas être compatibles Téléo/TIC."
            )

        if data.get("offline_mode"):
            attrs["offline_since"] = data.get("offline_since")
            attrs["cached_data_age_days"] = data.get("cache_age_days")
            attrs["note"] = "Données issues du cache local — API indisponible"
        return attrs


class EauGrandLyonGlobalConsoSensor(_EauGrandLyonGlobalBase):
    """Somme des consommations du mois courant pour tous les contrats."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    _attr_translation_key = "global_conso"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_global_conso"

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get("global", {}).get("total_conso_courant")


class EauGrandLyonGlobalCostSensor(_EauGrandLyonGlobalBase):
    """Somme des coûts du mois courant pour tous les contrats."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_translation_key = "global_cost"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_global_cost"

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get("global", {}).get("total_cout_courant_eur")


class EauGrandLyonGlobalPredictionCostSensor(_EauGrandLyonGlobalBase):
    """Somme des prédictions de coût pour tous les contrats."""

    _attr_device_class = SensorDeviceClass.MONETARY
    # Somme de prévisions ponctuelles, pas un compteur cumulatif.
    _attr_state_class = None
    _attr_native_unit_of_measurement = "EUR"
    _attr_translation_key = "global_prediction"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_global_prediction_cost"

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get("global", {}).get("total_prediction_cout_eur")


class EauGrandLyonDroughtSensor(_EauGrandLyonGlobalBase):
    """Indicateur saisonnier de risque sécheresse (heuristique, pas de donnée préfectorale)."""

    _attr_translation_key = "drought"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["normal", "vigilance", "crise"]

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_drought_69"

    @property
    def native_value(self) -> str:
        return (self.coordinator.data or {}).get("drought_level", "normal")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "source": "Heuristique saisonnière (juin à septembre = Vigilance)",
            "note": (
                "Indicateur indicatif — ne reflète pas les arrêtés préfectoraux réels. "
                "Consultez vigieau.gouv.fr pour les restrictions en vigueur."
            ),
        }

    @property
    def icon(self) -> str:
        val = self.native_value
        if val == "normal":
            return "mdi:water-check"
        if val == "crise":
            return "mdi:water-alert"
        return "mdi:water-remove"


class EauGrandLyonNextOutageSensor(_EauGrandLyonGlobalBase):
    """Date de la prochaine interruption de service planifiée."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_translation_key = "next_outage"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_next_outage"

    @property
    def native_value(self) -> date | None:
        outage = (self.coordinator.data or {}).get("prochaine_coupure")
        if not outage:
            return None
        try:
            return date.fromisoformat(outage["date_debut"])
        except (KeyError, ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        outage = (self.coordinator.data or {}).get("prochaine_coupure") or {}
        interruptions = (self.coordinator.data or {}).get("interruptions", [])
        return {
            "titre": outage.get("titre"),
            "type": outage.get("type"),
            "date_fin": outage.get("date_fin"),
            "description": outage.get("description"),
            "nb_interruptions": len(interruptions),
            "toutes_interruptions": [
                {"titre": i.get("titre"), "date_debut": i.get("date_debut"), "type": i.get("type")}
                for i in interruptions[:5]
            ],
        }
