"""Sensors globaux : alertes, santé API, agrégats multi-contrats, sécheresse, travaux."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory

from .base import _EauGrandLyonGlobalBase
from ..coordinator import EauGrandLyonCoordinator


class EauGrandLyonAlertesSensor(_EauGrandLyonGlobalBase):
    """Nombre d'alertes actives sur l'ensemble des contrats."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    translation_key = "alertes"
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
    translation_key = "last_update"

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
    translation_key = "health"

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_api_status"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        if data.get("offline_mode"):
            return "HORS-LIGNE"
        if data.get("last_error"):
            return "KO"
        if data.get("last_update_success_time"):
            return "OK"
        return "INCONNU"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        attrs: dict[str, Any] = {
            "last_update_success_time": data.get("last_update_success_time"),
            "last_error":               data.get("last_error"),
            "last_error_type":          data.get("last_error_type"),
            "last_failure_time":        data.get("last_failure_time"),
            "last_failure_reason":      data.get("last_failure_reason"),
            "offline_mode":             data.get("offline_mode", False),
            "cache_age_days":           data.get("cache_age_days"),
            "experimental_mode":        data.get("experimental_mode", False),
            "api_mode":                 data.get("api_mode", "Legacy"),
            "consecutive_failures":     data.get("consecutive_failures", 0),
        }
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
    translation_key = "global_conso"
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
    _attr_native_unit_of_measurement = "€"
    translation_key = "global_cost"
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
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "€"
    translation_key = "global_prediction"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_global_prediction_cost"

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get("global", {}).get("total_prediction_cout_eur")


class EauGrandLyonDroughtSensor(_EauGrandLyonGlobalBase):
    """Statut des restrictions d'eau (Sécheresse) dans le Rhône."""

    translation_key = "drought"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_drought_69"

    @property
    def native_value(self) -> str:
        return (self.coordinator.data or {}).get("drought_level", "Normal")

    @property
    def icon(self) -> str:
        val = self.native_value
        if val == "Normal": return "mdi:water-check"
        if val == "Crise":  return "mdi:water-alert"
        return "mdi:water-remove"


class EauGrandLyonNextOutageSensor(_EauGrandLyonGlobalBase):
    """Date de la prochaine interruption de service planifiée."""

    _attr_device_class = SensorDeviceClass.DATE
    translation_key = "next_outage"
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
            "titre":       outage.get("titre"),
            "type":        outage.get("type"),
            "date_fin":    outage.get("date_fin"),
            "description": outage.get("description"),
            "nb_interruptions": len(interruptions),
            "toutes_interruptions": [
                {"titre": i.get("titre"), "date_debut": i.get("date_debut"), "type": i.get("type")}
                for i in interruptions[:5]
            ],
        }
