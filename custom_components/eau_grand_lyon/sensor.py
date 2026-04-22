"""Sensors pour Eau du Grand Lyon — toutes les données disponibles."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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
    contracts = (coordinator.data or {}).get("contracts", {})

    entities: list[SensorEntity] = []

    experimental = bool((coordinator.data or {}).get("experimental_mode", False))

    for ref, _contract in contracts.items():
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
        # ── Compte & contrat ──────────────────────────────────────────
        entities.append(EauGrandLyonSoldeSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonStatutSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonDateEcheanceSensor(coordinator, entry, ref))
        if experimental:
            entities.append(EauGrandLyonDerniereFactureSensor(coordinator, entry, ref))
            entities.append(EauGrandLyonFuiteEstimeeSensor(coordinator, entry, ref))
        # ── [INTELLIGENCE] Sensors ────────────────────────────────────
        entities.append(EauGrandLyonTrendSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonPredictionConsoSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonPredictionCostSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonEcoScoreSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonCO2FootprintSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonSignalSensor(coordinator, entry, ref))

    # ── Sensors globaux ───────────────────────────────────────────────
    entities.append(EauGrandLyonAlertesSensor(coordinator, entry))
    entities.append(EauGrandLyonLastUpdateSensor(coordinator, entry))
    entities.append(EauGrandLyonHealthSensor(coordinator, entry))

    # Agrégats si plusieurs contrats
    if (coordinator.data or {}).get("global", {}).get("nb_contracts", 0) > 1:
        entities.append(EauGrandLyonGlobalConsoSensor(coordinator, entry))
        entities.append(EauGrandLyonGlobalCostSensor(coordinator, entry))
        entities.append(EauGrandLyonGlobalPredictionCostSensor(coordinator, entry))
    
    # Sensors régionaux
    entities.append(EauGrandLyonDroughtSensor(coordinator, entry))

    # Coaching sensors
    for ref in contracts:
        entities.append(EauGrandLyonLimescaleSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonCoachingSensor(coordinator, entry, ref))

    async_add_entities(entities, update_before_add=False)


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
    def _current_year_str(self) -> str:
        return f"{datetime.now().year}-01-01"

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
        # Priorité à l'index réel (SIAMM/Téléo) si disponible
        real = self._contract.get("real_index")
        if real is not None:
            return round(real, 1)

        # Fallback : somme des consommations mensuelles
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
    _attr_state_class = SensorStateClass.TOTAL
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
    def icon(self) -> str:
        """Icone dynamique selon le volume."""
        val = self.native_value
        if val is None or val == 0:
            return "mdi:water-outline"
        if val < 5:  return "mdi:water-minus"
        if val < 15: return "mdi:water"
        return "mdi:water-percent"

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

        # Cap l'historique à 24 mois pour éviter de saturer les attributs (DB bloat)
        consos_capped = consos[-24:] if len(consos) > 24 else consos
        attrs["historique"] = [
            {"période": e["label"], "consommation_m3": e["consommation_m3"]}
            for e in consos_capped
        ]
        attrs["nb_mois_disponibles"] = len(consos)
        return attrs


# ══════════════════════════════════════════════════════════════════════
# Consommation annuelle
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonConsommationAnnuelleSensor(_EauGrandLyonBase):
    """Consommation totale des 12 derniers mois (m³)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
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
        # Attributs limités aux 14 derniers jours pour limiter le volume en BDD
        recent_14 = daily[-14:]
        return {
            "nb_jours_inclus": min(len(daily), 30),
            "derniers_jours": [
                {"date": e["date"], "consommation_m3": e["consommation_m3"]}
                for e in recent_14
            ],
        }


# ══════════════════════════════════════════════════════════════════════
# Coûts estimés
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonCoutMoisSensor(_EauGrandLyonBase):
    """Coût estimé du mois courant (€)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
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
    _attr_state_class = SensorStateClass.TOTAL
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
            "last_reset": self._current_year_str,
            "note": "Coût cumulé depuis le 1er janvier",
        }


# ══════════════════════════════════════════════════════════════════════
# Économie vs N-1
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonEconomieSensor(_EauGrandLyonBase):
    """Économie réalisée vs année N-1 (€)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
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
# Solde du compte client
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonSoldeSensor(_EauGrandLyonBase):
    """Solde du compte client (€)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
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
        # Priorité à l'index réel (SIAMM/Téléo) si disponible
        real = self._contract.get("real_index")
        if real is not None:
            return round(real, 1)

        # Fallback : somme des consommations mensuelles
        consos = self._contract.get("consommations", [])
        if not consos:
            return None
        return round(sum(e["consommation_m3"] for e in consos), 1)

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
    _attr_name = "Coûts eau (Énergie)"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = False  # désactivé par défaut

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_energy_cost"

    @property
    def native_value(self) -> float | None:
        tarif = self._contract.get("tarif_m3", 0)
        if not tarif:
            return None

        # Priorité à l'index réel (SIAMM/Téléo) si disponible
        real = self._contract.get("real_index")
        if real is not None:
            return round(real * tarif, 2)

        # Fallback : somme des consommations mensuelles
        consos = self._contract.get("consommations", [])
        if not consos:
            return None
        return round(sum(e["consommation_m3"] for e in consos) * tarif, 2)

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


# ══════════════════════════════════════════════════════════════════════
# Classe de base pour sensors globaux (non liés à un contrat)
# ══════════════════════════════════════════════════════════════════════

class _EauGrandLyonGlobalBase(CoordinatorEntity[EauGrandLyonCoordinator], SensorEntity):
    """Base commune pour les sensors globaux (alertes, dernière MAJ, santé API)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

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


# ══════════════════════════════════════════════════════════════════════
# Alertes actives (global)
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonAlertesSensor(_EauGrandLyonGlobalBase):
    """Nombre d'alertes actives sur l'ensemble des contrats."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:bell-alert"
    _attr_name = "Alertes actives"
    _attr_native_unit_of_measurement = "alertes"

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_alertes"

    @property
    def native_value(self) -> int:
        if not self.coordinator.data:
            return 0
        return self.coordinator.data.get("nb_alertes", 0)


# ══════════════════════════════════════════════════════════════════════
# Dernière mise à jour réussie (global)
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonLastUpdateSensor(_EauGrandLyonGlobalBase):
    """Horodatage de la dernière synchronisation réussie."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"
    _attr_name = "Dernière mise à jour"

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
        }


class EauGrandLyonHealthSensor(_EauGrandLyonGlobalBase):
    """Statut global de l'intégration (API/connexion)."""

    _attr_icon = "mdi:heart-pulse"
    _attr_name = "Statut API"

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
            "offline_mode":             data.get("offline_mode", False),
            "experimental_mode":        data.get("experimental_mode", False),
            "api_mode":                 data.get("api_mode", "Legacy"),
        }
        if data.get("offline_mode"):
            attrs["offline_since"] = data.get("offline_since")
            attrs["note"] = "Données issues du cache local — API indisponible"
        return attrs


# ══════════════════════════════════════════════════════════════════════
# [EXPÉRIMENTAL] Dernière facture
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonDerniereFactureSensor(_EauGrandLyonBase):
    """[EXPÉRIMENTAL] Montant TTC de la dernière facture.

    Disponible uniquement si le mode expérimental est activé dans les options.
    Source : GET /rest/produits/factures (bundle Angular 2026).
    """

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class  = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:receipt-text"
    _attr_name = "Dernière facture (€ TTC)"
    _attr_suggested_display_precision = 2
    # Désactivé par défaut — l'utilisateur active manuellement après vérification
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_derniere_facture"

    @property
    def available(self) -> bool:
        """Disponible uniquement si une facture a été remontée par l'API."""
        return (
            super().available
            and self._contract.get("derniere_facture") is not None
        )

    @property
    def native_value(self) -> float | None:
        facture = self._contract.get("derniere_facture")
        if not facture:
            return None
        return facture.get("montant_ttc")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        facture = self._contract.get("derniere_facture") or {}
        factures = self._contract.get("factures", [])
        return {
            "référence":          facture.get("reference", ""),
            "date_édition":       facture.get("date_edition"),
            "date_exigibilité":   facture.get("date_exigibilite"),
            "montant_ht_eur":     facture.get("montant_ht"),
            "montant_ttc_eur":    facture.get("montant_ttc"),
            "volume_m3":          facture.get("volume_m3"),
            "statut_paiement":    facture.get("statut_paiement", ""),
            "nb_factures_total":  len(factures),
            "historique_factures": [
                {
                    "référence":        f.get("reference"),
                    "date_édition":     f.get("date_edition"),
                    "montant_ttc_eur":  f.get("montant_ttc"),
                    "statut_paiement":  f.get("statut_paiement"),
                }
                for f in factures[:12]  # 12 dernières factures max en attribut
            ],
            "source": "expérimental — /rest/produits/factures",
        }


# ══════════════════════════════════════════════════════════════════════
# [EXPÉRIMENTAL] Volume de fuite estimé
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonFuiteEstimeeSensor(_EauGrandLyonBase):
    """[EXPÉRIMENTAL] Volume de fuite estimé sur les 30 derniers jours (m³).

    Ce champ (volumeFuiteEstime) est remontré par le nouvel endpoint
    /rest/produits/contrats/{id}/consommationsJournalieres, uniquement sur
    les compteurs Téléo récents qui calculent la fuite nocturne.

    Une valeur > 0 peut indiquer une fuite sur le circuit intérieur.
    Le binary_sensor "Alerte fuite possible" reste basé sur la surconsommation
    mensuelle (méthode legacy) — ce sensor est complémentaire.
    """

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class  = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water-alert"
    _attr_name = "Fuite estimée 30 jours"
    _attr_suggested_display_precision = 3
    _attr_entity_registry_enabled_default = False  # désactivé par défaut

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_fuite_estimee"

    @property
    def available(self) -> bool:
        """Disponible uniquement si le compteur remonte des données de fuite."""
        return (
            super().available
            and self._contract.get("fuite_estime_30j_m3") is not None
        )

    @property
    def native_value(self) -> float | None:
        return self._contract.get("fuite_estime_30j_m3")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        daily = self._contract.get("consommations_journalieres", [])
        recent_30 = daily[-30:]
        all_fuite = [
            e for e in recent_30 if "volume_fuite_estime_m3" in e
        ]
        # Attributs limités aux 14 derniers jours pour limiter le volume en BDD
        detail = [
            {
                "date":                  e["date"],
                "volume_fuite_estime_m3": e.get("volume_fuite_estime_m3", 0),
            }
            for e in all_fuite[-14:]
        ]
        return {
            "nb_jours_avec_donnée":  len(all_fuite),
            "détail_journalier":     detail,
            "note": (
                "Volume de fuite nocturne estimé par le compteur Téléo. "
                "Non nul = possible fuite sur circuit intérieur."
            ),
            "source": "expérimental — volumeFuiteEstime dans /rest/produits/contrats/{id}/consommationsJournalieres",
        }


# ══════════════════════════════════════════════════════════════════════
# [INTELLIGENCE] Tendance & Prédiction
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonTrendSensor(_EauGrandLyonBase):
    """Sensor de tendance N-1 (%)."""

    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:trending-up"
    _attr_name = "Tendance vs N-1"
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
    _attr_state_class  = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:chart-bell-curve-cumulative"
    _attr_name = "Prédiction consommation mensuelle"
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
    _attr_state_class  = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "€"
    _attr_icon = "mdi:cash-clock"
    _attr_name = "Prédiction coût mensuel"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_prediction_cost"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("prediction_cout_mois")


# ══════════════════════════════════════════════════════════════════════
# Sensors Globaux (Agrégats)
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonGlobalConsoSensor(_EauGrandLyonGlobalBase):
    """Somme des consommations du mois courant pour tous les contrats."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class  = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water-group"
    _attr_name = "Consommation globale mensuelle"
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
    _attr_state_class  = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "€"
    _attr_icon = "mdi:cash-multiple"
    _attr_name = "Coût global mensuel"
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
    _attr_state_class  = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "€"
    _attr_icon = "mdi:cash-clock"
    _attr_name = "Prédiction coût global mensuel"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_global_prediction_cost"

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get("global", {}).get("total_prediction_cout_eur")


# ══════════════════════════════════════════════════════════════════════
# [NEXT-GEN] Eco-Score & Sécheresse
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonEcoScoreSensor(_EauGrandLyonBase):
    """Note de performance environnementale (A-G)."""

    _attr_icon = "mdi:leaf"
    _attr_name = "Eco-Score"

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


class EauGrandLyonDroughtSensor(_EauGrandLyonGlobalBase):
    """Statut des restrictions d'eau (Sécheresse) dans le Rhône."""

    _attr_icon = "mdi:water-off"
    _attr_name = "Restrictions Sécheresse (69)"

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


# ══════════════════════════════════════════════════════════════════════
# [COACHING] Entartrage & Conseils
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonLimescaleSensor(_EauGrandLyonBase):
    """Estimation de l'accumulation de calcaire (g)."""

    _attr_state_class  = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "g"
    _attr_icon = "mdi:shimmer"
    _attr_name = "Accumulation de calcaire"
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
    _attr_name = "Conseils Eco-Coach"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_coaching"

    @property
    def native_value(self) -> str:
        c = self._contract
        score = c.get("eco_score_grade", "Inconnu")
        conso = c.get("consommation_mois_courant", 0)
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


class EauGrandLyonCO2FootprintSensor(_EauGrandLyonBase):
    """Empreinte carbone de la consommation d'eau (kg CO2e)."""

    _attr_icon = "mdi:molecule-co2"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_name = "Empreinte carbone"
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


class EauGrandLyonSignalSensor(_EauGrandLyonBase):
    """Niveau de signal radio du module Téléo (%)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:signal-variant"
    _attr_name = "Signal module Téléo"
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
        if val is None:   return "mdi:signal-off"
        if val < 20:      return "mdi:signal-cellular-outline"
        if val < 50:      return "mdi:signal-cellular-1"
        if val < 80:      return "mdi:signal-cellular-2"
        return "mdi:signal-cellular-3"
