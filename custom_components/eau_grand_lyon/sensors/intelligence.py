"""Sensors d'intelligence : tendance, prédiction, eco-score, coaching, CO2, signal."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory

from .base import _EauGrandLyonBase


class EauGrandLyonTrendSensor(_EauGrandLyonBase):
    """Sensor de tendance N-1 (%)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:trending-up"
    translation_key = "trend"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_trend_n1"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("tendance_n1_pct")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "conso_actuelle": self._contract.get("consommation_mois_courant"),
            "conso_n1":       self._contract.get("consommation_n1"),
            "mois_n1":        self._contract.get("label_n1"),
        }


class EauGrandLyonPredictionConsoSensor(_EauGrandLyonBase):
    """Sensor de prédiction de consommation fin de mois (m³)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:chart-bell-curve-cumulative"
    translation_key = "prediction_conso"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_prediction_conso"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("prediction_conso_mois")


class EauGrandLyonPredictionCostSensor(_EauGrandLyonBase):
    """Sensor de prédiction de coût mensuel (EUR)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "€"
    _attr_icon = "mdi:cash-clock"
    translation_key = "prediction_cost"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_prediction_cost"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("prediction_cout_mois")


class EauGrandLyonEcoScoreSensor(_EauGrandLyonBase):
    """Note de performance environnementale (A-G)."""

    _attr_icon = "mdi:leaf"
    translation_key = "eco_score"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_eco_score"

    @property
    def native_value(self) -> str:
        return self._contract.get("eco_score_grade", "Inconnu")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "m3_par_personne": self._contract.get("eco_score_m3_pers"),
            "nb_habitants":    self._contract.get("nb_habitants"),
            "méthode":         "Barème national (A < 2.5m3/pers/mois)",
        }


class EauGrandLyonCO2FootprintSensor(_EauGrandLyonBase):
    """Empreinte carbone de la consommation d'eau (kg CO2e)."""

    _attr_icon = "mdi:molecule-co2"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_entity_registry_enabled_default = False
    translation_key = "co2_footprint"
    _attr_native_unit_of_measurement = "kg CO2e"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_co2_footprint"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("co2_footprint_kg")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "méthode": "Facteur ADEME (0.52 kg/m3)",
            "note": "Inclut le pompage, le traitement et la distribution.",
        }


class EauGrandLyonLimescaleSensor(_EauGrandLyonBase):
    """Estimation de l'accumulation de calcaire (g)."""

    _attr_device_class = SensorDeviceClass.WEIGHT
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "g"
    _attr_icon = "mdi:shimmer"
    _attr_entity_registry_enabled_default = False
    translation_key = "limescale"
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_limescale"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("limescale_g")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "dureté_appliquée_fh": self._contract.get("hardness_fh"),
            "note": "Basé sur le volume total et la dureté configurée.",
        }


class EauGrandLyonCoachingSensor(_EauGrandLyonBase):
    """Conseils personnalisés basés sur l'analyse de consommation."""

    _attr_icon = "mdi:account-voice"
    translation_key = "coaching"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_coaching"

    @property
    def native_value(self) -> str:
        c = self._contract
        score = c.get("eco_score_grade", "Inconnu")
        trend = c.get("tendance_n1_pct", 0)

        if score == "A":
            return "Excellent ! Votre consommation est exemplaire. Continuez ainsi."
        if score == "B":
            return "Bonne performance. Vous êtes sous la moyenne lyonnaise."
        if trend > 20:
            return "Attention : votre consommation a bondi de 20% par rapport à l'an dernier."
        if c.get("local_leak_pattern"):
            return "Alerte : Un flux constant est détecté. Vérifiez vos robinets ou chasses d'eau."
        if score in ["F", "G"]:
            return "Consommation élevée. Pensez à installer des mousseurs ou réduire la durée des douches."
        return "Consommation stable. Pensez à vérifier régulièrement l'absence de fuites."


class EauGrandLyonSignalSensor(_EauGrandLyonBase):
    """Niveau de signal radio du module Téléo (%)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:signal-variant"
    translation_key = "signal"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_signal_pct"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("signal_pct")

    @property
    def icon(self) -> str:
        val = self.native_value
        if val is None: return "mdi:signal-off"
        if val < 20:    return "mdi:signal-cellular-outline"
        if val < 50:    return "mdi:signal-cellular-1"
        if val < 80:    return "mdi:signal-cellular-2"
        return "mdi:signal-cellular-3"
