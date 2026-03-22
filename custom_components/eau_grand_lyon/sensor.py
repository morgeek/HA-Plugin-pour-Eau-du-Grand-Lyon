"""Sensors pour Eau du Grand Lyon — toutes les données disponibles."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EauGrandLyonCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée toutes les entités sensor après chargement de la config entry."""
    coordinator: EauGrandLyonCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []

    for ref, _contract in (coordinator.data or {}).get("contracts", {}).items():
        # ── Tableau de bord Énergie HA ────────────────────────────────
        entities.append(EauGrandLyonIndexSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonEnergyWaterSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonEnergyCostSensor(coordinator, entry, ref))
        # ── Consommations mensuelles ──────────────────────────────────
        entities.append(
            EauGrandLyonConsommationSensor(coordinator, entry, ref, "courant")
        )
        entities.append(
            EauGrandLyonConsommationSensor(coordinator, entry, ref, "precedent")
        )
        entities.append(EauGrandLyonConsommationAnnuelleSensor(coordinator, entry, ref))
        # ── Consommations journalières (si compteur compatible) ───────
        entities.append(EauGrandLyonConso7JSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonConso30JSensor(coordinator, entry, ref))
        # ── Coûts estimés ─────────────────────────────────────────────
        entities.append(EauGrandLyonCoutMoisSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonCoutAnnuelSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonCoutCumuleSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonEconomieSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonLeakAlertSensor(coordinator, entry, ref))
        # ── Compte & contrat ──────────────────────────────────────────
        entities.append(EauGrandLyonSoldeSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonStatutSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonDateEcheanceSensor(coordinator, entry, ref))

    # ── Sensors globaux ───────────────────────────────────────────────
    entities.append(EauGrandLyonAlertesSensor(coordinator, entry))
    entities.append(EauGrandLyonLastUpdateSensor(coordinator, entry))
    entities.append(EauGrandLyonHealthSensor(coordinator, entry))

    async_add_entities(entities, update_before_add=True)


# ══════════════════════════════════════════════════════════════════════
# Classe de base
# ══════════════════════════════════════════════════════════════════════

class _EauGrandLyonBase(CoordinatorEntity[EauGrandLyonCoordinator], SensorEntity):
    """Base commune pour tous les sensors Eau du Grand Lyon."""

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


# ══════════════════════════════════════════════════════════════════════
# Index cumulatif — Tableau de bord Énergie HA
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonIndexSensor(_EauGrandLyonBase):
    """Index cumulatif (TOTAL_INCREASING) — Tableau de bord Énergie HA."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water-pump"
    _attr_name = "Index cumulatif"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_index_cumulatif"

    @property
    def native_value(self) -> float | None:
        consos = self._contract.get("consommations", [])
        if not consos:
            return None
        return round(sum(e["consommation_m3"] for e in consos), 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        consos = self._contract.get("consommations", [])
        manquants = self._contract.get("mois_manquants", [])
        return {
            "premier_relevé": consos[0]["label"] if consos else None,
            "dernier_relevé": consos[-1]["label"] if consos else None,
            "nb_mois_inclus": len(consos),
            "mois_manquants": manquants,
            "nb_mois_manquants": len(manquants),
            "note": "Somme cumulée — historique injecté dans les statistiques HA.",
        }


# ══════════════════════════════════════════════════════════════════════
# Consommations mensuelles
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonConsommationSensor(_EauGrandLyonBase):
    """Consommation du mois courant ou précédent (m³)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry, contract_ref, period: str):
        super().__init__(coordinator, entry, contract_ref)
        self._period = period
        self._attr_name = (
            "Consommation mois courant"
            if period == "courant"
            else "Consommation mois précédent"
        )
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_conso_{period}"

    @property
    def native_value(self) -> float | None:
        c = self._contract
        return (
            c.get("consommation_mois_courant")
            if self._period == "courant"
            else c.get("consommation_mois_precedent")
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        consos = c.get("consommations", [])
        attrs: dict[str, Any] = {}

        if self._period == "courant":
            attrs["période"] = c.get("label_mois_courant", "")

            prev = c.get("consommation_mois_precedent")
            curr = c.get("consommation_mois_courant")
            if prev is not None and curr is not None:
                attrs["variation_vs_mois_precedent_m3"] = round(curr - prev, 1)
                attrs["variation_vs_mois_precedent_pct"] = (
                    round((curr - prev) / prev * 100, 1) if prev != 0 else None
                )

            n1 = c.get("consommation_n1")
            if n1 is not None and curr is not None:
                attrs["consommation_n1_m3"] = n1
                attrs["période_n1"] = c.get("label_n1", "")
                attrs["variation_vs_n1_m3"] = round(curr - n1, 1)
                attrs["variation_vs_n1_pct"] = (
                    round((curr - n1) / n1 * 100, 1) if n1 != 0 else None
                )
        else:
            attrs["période"] = c.get("label_mois_precedent", "")

        attrs["historique"] = [
            {"période": e["label"], "consommation_m3": e["consommation_m3"]}
            for e in consos
        ]
        attrs["nb_mois_disponibles"] = len(consos)
        return attrs


# ══════════════════════════════════════════════════════════════════════
# Consommation annuelle
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonConsommationAnnuelleSensor(_EauGrandLyonBase):
    """Consommation totale des 12 derniers mois (m³)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water-outline"
    _attr_name = "Consommation annuelle (12 mois)"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_conso_annuelle"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("consommation_annuelle")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        consos = c.get("consommations", [])
        last_12 = consos[-12:] if len(consos) >= 12 else consos
        return {
            "nb_mois_inclus": len(last_12),
            "période_début": last_12[0]["label"] if last_12 else None,
            "période_fin": last_12[-1]["label"] if last_12 else None,
            "détail_mensuel": [
                {"période": e["label"], "consommation_m3": e["consommation_m3"]}
                for e in last_12
            ],
        }


# ══════════════════════════════════════════════════════════════════════
# Consommations journalières (si compteur compatible Téléo/TIC)
# ══════════════════════════════════════════════════════════════════════

class _EauGrandLyonDailyBase(_EauGrandLyonBase):
    """Base pour les sensors journaliers — unavailable si données non dispo."""

    @property
    def available(self) -> bool:
        """Disponible uniquement si le compteur remonte des données journalières."""
        return (
            super().available
            and bool(self._contract.get("consommations_journalieres"))
        )


class EauGrandLyonConso7JSensor(_EauGrandLyonDailyBase):
    """Consommation sur les 7 derniers jours (compteur Téléo/TIC uniquement)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water-sync"
    _attr_name = "Consommation 7 jours"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False  # désactivé par défaut

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_conso_7j"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("consommation_7j")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        daily = self._contract.get("consommations_journalieres", [])
        return {
            "derniers_jours": [
                {"date": e["date"], "consommation_m3": e["consommation_m3"]}
                for e in daily[-7:]
            ],
        }


class EauGrandLyonConso30JSensor(_EauGrandLyonDailyBase):
    """Consommation sur les 30 derniers jours (compteur Téléo/TIC uniquement)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water-sync"
    _attr_name = "Consommation 30 jours"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False  # désactivé par défaut

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_conso_30j"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("consommation_30j")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        daily = self._contract.get("consommations_journalieres", [])
        return {
            "nb_jours_inclus": len(daily[-30:]),
            "derniers_30j": [
                {"date": e["date"], "consommation_m3": e["consommation_m3"]}
                for e in daily[-30:]
            ],
        }


# ══════════════════════════════════════════════════════════════════════
# Coûts estimés
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonCoutMoisSensor(_EauGrandLyonBase):
    """Coût estimé du mois courant (€)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:water-percent"
    _attr_name = "Coût estimé mois courant"
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
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:currency-eur"
    _attr_name = "Coût estimé annuel (12 mois)"
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
    _attr_name = "Coût cumulé année"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False  # désactivé par défaut

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_cout_cumule"

    @property
    def native_value(self) -> float | None:
        # Calcule le coût cumulé depuis le début de l'année
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
            "last_reset": f"{datetime.now().year}-01-01",
            "note": "Coût cumulé depuis le 1er janvier",
        }


# ══════════════════════════════════════════════════════════════════════
# Économie vs N-1
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonEconomieSensor(_EauGrandLyonBase):
    """Économie réalisée vs année N-1 (€)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "€"
    _attr_icon = "mdi:trending-down"
    _attr_name = "Économie vs N-1"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_economie"

    @property
    def native_value(self) -> float | None:
        c = self._contract
        conso_n1 = c.get("consommation_n1")
        conso_annuelle = c.get("consommation_annuelle")
        tarif = c.get("tarif_m3")
        if conso_n1 and conso_annuelle and tarif:
            economie = (conso_n1 - conso_annuelle) * tarif
            return round(economie, 2)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "consommation_n1_m3": c.get("consommation_n1"),
            "consommation_actuelle_m3": c.get("consommation_annuelle"),
            "tarif_eur_m3": c.get("tarif_m3"),
        }


# ══════════════════════════════════════════════════════════════════════
# Alerte fuite (détection surconsommation anormale)
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonLeakAlertSensor(_EauGrandLyonBase, BinarySensorEntity):
    """Alerte possible fuite basée sur surconsommation mensuelle."""

    _attr_device_class = "problem"
    _attr_name = "Alerte fuite possible"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_leak_alert"

    @property
    def is_on(self) -> bool:
        c = self._contract
        conso_courant = c.get("consommation_mois_courant")
        conso_precedent = c.get("consommation_mois_precedent")
        if conso_courant and conso_precedent:
            # Alerte si conso actuelle > 2x la précédente (seuil simple)
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


# ══════════════════════════════════════════════════════════════════════
# Solde du compte client
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonSoldeSensor(_EauGrandLyonBase):
    """Solde du compte client (€)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:currency-eur"
    _attr_name = "Solde compte"
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


# ══════════════════════════════════════════════════════════════════════
# Statut du contrat
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonStatutSensor(_EauGrandLyonBase):
    """Statut du contrat (actif, résilié, etc.)."""

    _attr_icon = "mdi:file-document-check"
    _attr_name = "Statut contrat"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_statut"

    @property
    def native_value(self) -> str | None:
        return self._contract.get("statut")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "référence": c.get("reference", ""),
            "date_effet": c.get("date_effet"),
            "date_fin": c.get("date_echeance"),
            "usage": c.get("usage", ""),
            "calibre_compteur_mm": c.get("calibre_compteur", ""),
            "nombre_habitants": c.get("nombre_habitants", ""),
            "référence_pds": c.get("reference_pds", ""),
        }


# ══════════════════════════════════════════════════════════════════════
# Date de fin de contrat
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonDateEcheanceSensor(_EauGrandLyonBase):
    """Date d'échéance (fin) du contrat."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-end"
    _attr_name = "Fin de contrat"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_date_echeance"

    @property
    def native_value(self) -> date | None:
        raw = self._contract.get("date_echeance")
        if raw:
            try:
                return date.fromisoformat(raw)
            except ValueError:
                return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"date_début": self._contract.get("date_effet")}


# ══════════════════════════════════════════════════════════════════════
# Tableau de bord Énergie HA
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonEnergyWaterSensor(_EauGrandLyonBase):
    """Consommation d'eau pour le tableau de bord Énergie (en m³ cumulés)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water"
    _attr_name = "Consommation eau (Énergie)"
    _attr_suggested_display_precision = 1
    _attr_entity_registry_enabled_default = False  # désactivé par défaut

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_energy_water"

    @property
    def native_value(self) -> float | None:
        # Utilise la consommation annuelle comme valeur totale croissante
        return self._contract.get("consommation_annuelle")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "device_class": "water",
            "state_class": "total_increasing",
            "last_reset": c.get("date_reset_conso", f"{datetime.now().year}-01-01"),
            "note": "Sensor optimisé pour le tableau de bord Énergie HA",
        }


class EauGrandLyonEnergyCostSensor(_EauGrandLyonBase):
    """Coûts énergétiques pour le tableau de bord Énergie (€ cumulés)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:currency-eur"
    _attr_name = "Coûts eau (Énergie)"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False  # désactivé par défaut

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_energy_cost"

    @property
    def native_value(self) -> float | None:
        # Utilise le coût annuel comme valeur totale croissante
        return self._contract.get("cout_annuel_eur")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "device_class": "monetary",
            "state_class": "total_increasing",
            "last_reset": c.get("date_reset_cout", f"{datetime.now().year}-01-01"),
            "tarif_eur_m3": c.get("tarif_m3"),
            "note": "Sensor optimisé pour le tableau de bord Énergie HA",
        }


# ══════════════════════════════════════════════════════════════════════
# Alertes actives (global)
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonAlertesSensor(CoordinatorEntity[EauGrandLyonCoordinator], SensorEntity):
    """Nombre d'alertes actives sur l'ensemble des contrats."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:bell-alert"
    _attr_has_entity_name = True
    _attr_name = "Alertes actives"
    _attr_native_unit_of_measurement = "alertes"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_alertes"

    @property
    def device_info(self) -> DeviceInfo:
        contracts = (self.coordinator.data or {}).get("contracts", {})
        first_ref = next(iter(contracts), None)
        if first_ref:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry.entry_id}_{first_ref}")},
            )
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Eau du Grand Lyon",
            manufacturer="Morgeek",
        )

    @property
    def native_value(self) -> int:
        if not self.coordinator.data:
            return 0
        return self.coordinator.data.get("nb_alertes", 0)


# ══════════════════════════════════════════════════════════════════════
# Dernière mise à jour réussie (global)
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonLastUpdateSensor(
    CoordinatorEntity[EauGrandLyonCoordinator], SensorEntity
):
    """Horodatage de la dernière synchronisation réussie."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"
    _attr_has_entity_name = True
    _attr_name = "Dernière mise à jour"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_update"

    @property
    def device_info(self) -> DeviceInfo:
        contracts = (self.coordinator.data or {}).get("contracts", {})
        first_ref = next(iter(contracts), None)
        if first_ref:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry.entry_id}_{first_ref}")},
            )
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Eau du Grand Lyon",
            manufacturer="Morgeek",
        )

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
        }


class EauGrandLyonHealthSensor(CoordinatorEntity[EauGrandLyonCoordinator], SensorEntity):
    """Statut global de l'intégration (API/connexion)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:heart-pulse"
    _attr_name = "Statut API"

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_api_status"

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        last_error = data.get("last_error")

        if last_error:
            return "KO"
        if data.get("last_update_success_time"):
            return "OK"
        return "INCONNU"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "last_update_success_time": data.get("last_update_success_time"),
            "last_error": data.get("last_error"),
            "last_error_type": data.get("last_error_type"),
        }
