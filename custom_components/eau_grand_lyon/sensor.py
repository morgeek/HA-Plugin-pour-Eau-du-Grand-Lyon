"""Sensors pour Eau du Grand Lyon — toutes les données disponibles."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

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

    for ref, contract in (coordinator.data or {}).get("contracts", {}).items():
        # ── Tableau de bord Énergie HA ────────────────────────────────
        entities.append(EauGrandLyonIndexSensor(coordinator, entry, ref))
        # ── Consommations ─────────────────────────────────────────────
        entities.append(
            EauGrandLyonConsommationSensor(coordinator, entry, ref, "courant")
        )
        entities.append(
            EauGrandLyonConsommationSensor(coordinator, entry, ref, "precedent")
        )
        entities.append(
            EauGrandLyonConsommationAnnuelleSensor(coordinator, entry, ref)
        )
        # ── Compte & contrat ──────────────────────────────────────────
        entities.append(EauGrandLyonSoldeSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonStatutSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonDateEcheanceSensor(coordinator, entry, ref))

    # ── Alertes (global, pas par contrat) ─────────────────────────────
    entities.append(EauGrandLyonAlertesSensor(coordinator, entry))

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
        # Numéro de compteur (référence PDS physique, ex. "71233HC1")
        numero_compteur = (
            self._contract.get("reference_pds")
            or self._contract.get("reference", self._contract_ref)
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_{self._contract_ref}")},
            name="Eau du Grand Lyon",
            manufacturer="Morgeek & Claude",
            model=", ".join(model_parts) or "Compteur eau",
            serial_number=numero_compteur,
            configuration_url="https://agence.eaudugrandlyon.com",
        )


# ══════════════════════════════════════════════════════════════════════
# Index cumulatif — Tableau de bord Énergie HA
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonIndexSensor(_EauGrandLyonBase):
    """Index cumulatif de consommation d'eau (somme de tous les mois disponibles).

    Ce sensor a state_class=TOTAL_INCREASING, ce qui permet de l'ajouter
    directement dans le tableau de bord Énergie de Home Assistant (section Eau).
    La valeur augmente chaque mois quand de nouvelles données sont publiées.
    L'écart mensuel est calculé automatiquement par HA pour les graphiques.
    """

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water-pump"
    _attr_name = "Index cumulatif"
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: ConfigEntry,
        contract_ref: str,
    ) -> None:
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
        return {
            "premier_relevé": consos[0]["label"] if consos else None,
            "dernier_relevé": consos[-1]["label"] if consos else None,
            "nb_mois_inclus": len(consos),
            "note": (
                "Somme cumulée des relevés disponibles via l'API. "
                "Utilisez ce sensor dans Énergie → Eau."
            ),
        }


# ══════════════════════════════════════════════════════════════════════
# Consommations mensuelles (mois courant et mois précédent)
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonConsommationSensor(_EauGrandLyonBase):
    """Consommation d'eau pour le mois courant ou précédent (m³)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water"
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: ConfigEntry,
        contract_ref: str,
        period: str,  # "courant" | "precedent"
    ) -> None:
        super().__init__(coordinator, entry, contract_ref)
        self._period = period
        if period == "courant":
            self._attr_name = "Consommation mois courant"
        else:
            self._attr_name = "Consommation mois précédent"
        self._attr_unique_id = (
            f"{entry.entry_id}_{contract_ref}_conso_{period}"
        )

    @property
    def native_value(self) -> float | None:
        c = self._contract
        if self._period == "courant":
            return c.get("consommation_mois_courant")
        return c.get("consommation_mois_precedent")

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
                attrs["variation_m3"] = round(curr - prev, 1)
                attrs["variation_pct"] = (
                    round((curr - prev) / prev * 100, 1) if prev != 0 else None
                )
        else:
            attrs["période"] = c.get("label_mois_precedent", "")

        # Historique complet (tous les mois disponibles)
        attrs["historique"] = [
            {"période": e["label"], "consommation_m3": e["consommation_m3"]}
            for e in consos
        ]
        attrs["nb_mois_disponibles"] = len(consos)
        return attrs


# ══════════════════════════════════════════════════════════════════════
# Consommation annuelle (somme glissante 12 mois)
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonConsommationAnnuelleSensor(_EauGrandLyonBase):
    """Consommation totale des 12 derniers mois disponibles (m³)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    _attr_icon = "mdi:water-outline"
    _attr_name = "Consommation annuelle (12 mois)"
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: ConfigEntry,
        contract_ref: str,
    ) -> None:
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_conso_annuelle"

    @property
    def native_value(self) -> float | None:
        c = self._contract
        return c.get("consommation_annuelle")

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
# Solde du compte client
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonSoldeSensor(_EauGrandLyonBase):
    """Solde du compte client en euros."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "EUR"
    _attr_icon = "mdi:currency-eur"
    _attr_name = "Solde compte"
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: ConfigEntry,
        contract_ref: str,
    ) -> None:
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
    """Statut actuel du contrat (actif, résilié, etc.)."""

    _attr_icon = "mdi:file-document-check"
    _attr_name = "Statut contrat"

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: ConfigEntry,
        contract_ref: str,
    ) -> None:
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

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: ConfigEntry,
        contract_ref: str,
    ) -> None:
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
        c = self._contract
        return {
            "date_début": c.get("date_effet"),
        }


# ══════════════════════════════════════════════════════════════════════
# Alertes actives (sensor global)
# ══════════════════════════════════════════════════════════════════════

class EauGrandLyonAlertesSensor(CoordinatorEntity[EauGrandLyonCoordinator], SensorEntity):
    """Nombre d'alertes actives sur l'ensemble des contrats."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:bell-alert"
    _attr_has_entity_name = True
    _attr_name = "Alertes actives"
    _attr_native_unit_of_measurement = "alertes"

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_alertes"

    @property
    def device_info(self) -> DeviceInfo:
        # Rattaché au premier contrat trouvé (ou device générique si aucun)
        contracts = (self.coordinator.data or {}).get("contracts", {})
        first_ref = next(iter(contracts), None)
        if first_ref:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry.entry_id}_{first_ref}")},
            )
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Eau du Grand Lyon",
            manufacturer="Morgeek & Claude",
        )

    @property
    def native_value(self) -> int:
        if not self.coordinator.data:
            return 0
        return self.coordinator.data.get("nb_alertes", 0)
