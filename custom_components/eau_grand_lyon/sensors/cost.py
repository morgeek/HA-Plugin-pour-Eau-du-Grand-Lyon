"""Sensors de coûts et économies (estimés et réels)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from .base import _EauGrandLyonBase


class EauGrandLyonCoutMoisSensor(_EauGrandLyonBase):
    """Coût estimé du mois courant (€)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:water-percent"
    translation_key = "cout_mois"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_cout_mois"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("cout_mois_courant_eur")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "période": c.get("label_mois_courant", ""),
            "consommation_m3": c.get("consommation_mois_courant"),
            "tarif_appliqué_eur_m3": c.get("tarif_m3"),
            "note": "Estimation basée sur le tarif configuré. Consultez votre facture.",
        }


class EauGrandLyonCoutAnnuelSensor(_EauGrandLyonBase):
    """Coût estimé des 12 derniers mois (€)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:currency-eur"
    translation_key = "cout_annuel"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_cout_annuel"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("cout_annuel_eur")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "consommation_annuelle_m3": c.get("consommation_annuelle"),
            "tarif_appliqué_eur_m3": c.get("tarif_m3"),
            "note": "Estimation — modifiez le tarif dans les options de l'intégration.",
        }


class EauGrandLyonCoutCumuleSensor(_EauGrandLyonBase):
    """Coût cumulé depuis le début de l'année (€)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:currency-eur"
    translation_key = "cout_cumule"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_cout_cumule"

    @property
    def native_value(self) -> float | None:
        c = self._contract
        conso_cumulee = c.get("consommation_cumulee_annee", 0)
        tarif = c.get("tarif_m3", 0)
        return round(conso_cumulee * tarif, 2) if conso_cumulee and tarif else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "consommation_cumulee_m3": c.get("consommation_cumulee_annee"),
            "tarif_appliqué_eur_m3": c.get("tarif_m3"),
            "last_reset": self._current_year_str,
            "note": "Coût cumulé depuis le 1er janvier",
        }


class EauGrandLyonEconomieSensor(_EauGrandLyonBase):
    """Économie réalisée vs année N-1 (€)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:trending-down"
    translation_key = "economie"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_economie"

    @property
    def native_value(self) -> float | None:
        c = self._contract
        conso_n1_annuelle = c.get("consommation_annuelle_n1")
        conso_annuelle = c.get("consommation_annuelle")
        tarif = c.get("tarif_m3")
        if conso_n1_annuelle is not None and conso_annuelle is not None and tarif:
            return round((conso_n1_annuelle - conso_annuelle) * tarif, 2)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "consommation_n1_annuelle_m3": c.get("consommation_annuelle_n1"),
            "consommation_actuelle_m3": c.get("consommation_annuelle"),
            "tarif_eur_m3": c.get("tarif_m3"),
            "note": "Comparaison basée sur les 12 derniers mois vs les 12 mois précédents.",
        }


class EauGrandLyonSoldeSensor(_EauGrandLyonBase):
    """Solde du compte client (€)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:currency-eur"
    translation_key = "solde"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_solde"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("solde_eur")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "mensualise": c.get("mensualise"),
            "mode_paiement": c.get("mode_paiement", ""),
            "référence_contrat": c.get("reference", ""),
        }


class EauGrandLyonCoutReelMoisSensor(_EauGrandLyonBase):
    """Coût mensuel réel = part variable (conso × tarif) + part fixe (abonnement/12)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:receipt-text-check"
    translation_key = "cout_reel_mois"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_cout_reel_mois"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("cout_reel_mois")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "part_variable_eur": c.get("cout_mois_courant_eur"),
            "part_fixe_eur":     round(c.get("subscription_annual", 0) / 12, 2),
            "abonnement_annuel": c.get("subscription_annual"),
            "tarif_eur_m3":      c.get("tarif_m3"),
            "note": "Coût total = conso × tarif + abonnement mensuel proratisé",
        }


class EauGrandLyonCoutReelAnnuelSensor(_EauGrandLyonBase):
    """Coût annuel réel = part variable (conso 12 mois × tarif) + abonnement annuel."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:receipt-text-outline"
    translation_key = "cout_reel_annuel"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_cout_reel_annuel"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("cout_reel_annuel")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "part_variable_eur": c.get("cout_annuel_eur"),
            "abonnement_annuel": c.get("subscription_annual"),
            "consommation_m3":   c.get("consommation_annuelle"),
            "tarif_eur_m3":      c.get("tarif_m3"),
        }


class EauGrandLyonEnergyWaterSensor(_EauGrandLyonBase):
    """Consommation d'eau pour le tableau de bord Énergie (en m³ cumulés)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water"
    translation_key = "energy_water"
    _attr_suggested_display_precision = 1
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_energy_water"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.get_cumulative_index(self._contract_ref)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "device_class": "water",
            "state_class": "total_increasing",
            "last_reset": c.get("date_reset_conso", self._current_year_str),
            "note": "Sensor optimisé pour le tableau de bord Énergie HA",
        }


class EauGrandLyonEnergyCostSensor(_EauGrandLyonBase):
    """Coûts énergétiques pour le tableau de bord Énergie (€ cumulés)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:currency-eur"
    translation_key = "energy_cost"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_energy_cost"

    @property
    def native_value(self) -> float | None:
        tarif = self._contract.get("tarif_m3", 0)
        if not tarif:
            return None
        index = self.coordinator.get_cumulative_index(self._contract_ref)
        if index is not None:
            return round(index * tarif, 2)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "device_class": "monetary",
            "state_class": "total_increasing",
            "last_reset": c.get("date_reset_cout", self._current_year_str),
            "tarif_eur_m3": c.get("tarif_m3"),
            "note": "Sensor optimisé pour le tableau de bord Énergie HA",
        }
