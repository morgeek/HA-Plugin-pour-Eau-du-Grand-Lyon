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
from homeassistant.util import dt as dt_util

from .const import CONF_LEAK_MULTIPLIER, DEFAULT_LEAK_MULTIPLIER
from .coordinator import EauGrandLyonCoordinator
from .device import account_device_info, contract_device_info

if TYPE_CHECKING:
    from . import EauGrandLyonConfigEntry

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EauGrandLyonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create binary sensors and follow contracts discovered after setup."""
    coordinator = entry.runtime_data
    added_unique_ids: set[str] = set()

    def _add_new_entities() -> None:
        candidates: list[BinarySensorEntity] = []
        for ref, contract in (coordinator.data or {}).get("contracts", {}).items():
            candidates.extend(_contract_binary_sensor_candidates(coordinator, entry, ref, contract))

        # [FEAT 3] Coupure/Travaux planifiés — capteur global
        candidates.append(EauGrandLyonOutageSensor(coordinator, entry))

        new_entities = []
        for entity in candidates:
            unique_id = entity._attr_unique_id
            if unique_id not in added_unique_ids:
                added_unique_ids.add(unique_id)
                new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities, update_before_add=False)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


def _contract_binary_sensor_candidates(
    coordinator,
    entry,
    ref: str,
    contract: dict,
) -> list[BinarySensorEntity]:
    """Build the currently applicable binary sensors for one contract."""
    entities: list[BinarySensorEntity] = []

    entities.append(EauGrandLyonLeakAlertSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonRealTimeLeakSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonLocalLeakSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonBatterySensor(coordinator, entry, ref))
    entities.append(EauGrandLyonLimescaleAlertSensor(coordinator, entry, ref))
    # ── Alertes serveur (seuils configurés dans l'espace Eau du Grand Lyon) ──
    if contract.get("abonne_alerte_fuite") is not None:
        entities.append(EauGrandLyonLeakSubscriptionSensor(coordinator, entry, ref))
    if contract.get("seuil_surconso_jour_m3") is not None:
        entities.append(EauGrandLyonSurconsoJourSensor(coordinator, entry, ref))
    if contract.get("seuil_surconso_mois_m3") is not None:
        entities.append(EauGrandLyonSurconsoMoisSensor(coordinator, entry, ref))
    return entities


class _EauGrandLyonBinaryBase(CoordinatorEntity[EauGrandLyonCoordinator], BinarySensorEntity):
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
        return contract_device_info(self.coordinator, self._entry, self._contract_ref)


class EauGrandLyonLeakAlertSensor(_EauGrandLyonBinaryBase):
    """Anomalie de consommation mensuelle calculée localement."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "leak_alert"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_leak_alert"

    @property
    def available(self) -> bool:
        c = self._contract
        return bool(
            super().available
            and c.get("consommation_mois_courant") is not None
            and c.get("consommation_mois_precedent") is not None
        )

    @property
    def is_on(self) -> bool:
        c = self._contract
        conso_courant = c.get("consommation_mois_courant")
        conso_precedent = c.get("consommation_mois_precedent")
        if conso_courant is not None and conso_precedent is not None and conso_precedent > 0:
            multiplier = float(
                (self.coordinator.config_entry.options or {}).get(CONF_LEAK_MULTIPLIER, DEFAULT_LEAK_MULTIPLIER)
            )
            return conso_courant > multiplier * conso_precedent
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        multiplier = float(
            (self.coordinator.config_entry.options or {}).get(CONF_LEAK_MULTIPLIER, DEFAULT_LEAK_MULTIPLIER)
        )
        return {
            "consommation_courant_m3": c.get("consommation_mois_courant"),
            "consommation_precedent_m3": c.get("consommation_mois_precedent"),
            "seuil_alerte": f"Consommation actuelle > {multiplier}x precedente (configurable)",
            "source": "Calcul local sur deux consommations mensuelles",
        }


class EauGrandLyonRealTimeLeakSensor(_EauGrandLyonBinaryBase):
    """Indicateur fournisseur fondé sur son volume de fuite estimé sur 30 jours."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "real_time_leak"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_real_time_leak"

    @property
    def available(self) -> bool:
        """Disponible uniquement si le mode expérimental est actif et données présentes."""
        return bool(
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
    """Anomalie locale basée sur une courbe horaire ou un pic journalier.

    Désactivé par défaut : l'algorithme nécessite au moins 7 jours d'historique
    journalier et peut produire des faux positifs sur les compteurs sans courbe
    intra-journalière (un seul relevé par 24h).
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "local_leak"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_local_leak_pattern"

    @property
    def available(self) -> bool:
        courbe = self._contract.get("courbe_de_charge") or []
        daily = self._contract.get("consommations_journalieres") or []
        return bool(super().available and (len(courbe) >= 24 or len(daily) >= 7))

    @property
    def is_on(self) -> bool:
        return self._contract.get("local_leak_pattern", False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        courbe = self._contract.get("courbe_de_charge") or []
        method = "Flux horaire non nul pendant 24 points" if len(courbe) >= 24 else "Pic journalier vs moyenne 7 jours"
        return {
            "méthode": method,
            "note": "Heuristique locale indicative, distincte d'une alerte du fournisseur.",
        }


class EauGrandLyonBatterySensor(_EauGrandLyonBinaryBase):
    """État de la pile du module Téléo."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_translation_key = "battery"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_battery_low"

    @property
    def available(self) -> bool:
        # Sans cette garde, un battery_ok absent de l'API (etatPile non fourni
        # pour ce type de contrat) donnait `None is False` -> False, soit un
        # état "pile OK" faussement rassurant sans aucune donnée réelle
        # derrière (retour utilisateur : capteur "qui marche" mais qui ne
        # fait en réalité que masquer l'absence de donnée).
        return super().available and self._contract.get("battery_ok") is not None

    @property
    def is_on(self) -> bool:
        """True si la batterie est faible."""
        return self._contract.get("battery_ok") is False


class EauGrandLyonLimescaleAlertSensor(_EauGrandLyonBinaryBase):
    """Alerte accumulation excessive de calcaire."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "limescale_alert"
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


class EauGrandLyonLeakSubscriptionSensor(_EauGrandLyonBinaryBase):
    """Statut d'abonnement à l'alerte fuite (endpoint /abonneAlerteFuite)."""

    _attr_translation_key = "leak_subscription"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_leak_subscription"

    @property
    def available(self) -> bool:
        return super().available and self._contract.get("abonne_alerte_fuite") is not None

    @property
    def is_on(self) -> bool:
        """True si l'abonné est inscrit à l'alerte fuite d'Eau du Grand Lyon."""
        return self._contract.get("abonne_alerte_fuite") is True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "note": "Abonnement à l'alerte fuite configuré sur l'espace Eau du Grand Lyon.",
        }


class EauGrandLyonSurconsoJourSensor(_EauGrandLyonBinaryBase):
    """Dépassement du seuil de surconsommation journalier configuré côté serveur."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "surconso_jour"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_surconso_jour"

    @property
    def available(self) -> bool:
        return super().available and self._contract.get("seuil_surconso_jour_m3") is not None

    @property
    def is_on(self) -> bool:
        return bool(self._contract.get("surconso_jour_depassee"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "seuil_m3": c.get("seuil_surconso_jour_m3"),
            "consommation_jour_m3": c.get("derniere_conso_jour_m3"),
            "note": "Compare la dernière consommation journalière au seuil configuré côté serveur.",
        }


class EauGrandLyonSurconsoMoisSensor(_EauGrandLyonBinaryBase):
    """Dépassement du seuil de surconsommation mensuel configuré côté serveur."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "surconso_mois"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_surconso_mois"

    @property
    def available(self) -> bool:
        return super().available and self._contract.get("seuil_surconso_mois_m3") is not None

    @property
    def is_on(self) -> bool:
        return bool(self._contract.get("surconso_mois_depassee"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "seuil_m3": c.get("seuil_surconso_mois_m3"),
            "consommation_mois_m3": c.get("consommation_mois_courant"),
            "note": "Compare la consommation du mois en cours au seuil configuré côté serveur.",
        }


# ══════════════════════════════════════════════════════════════════════
# Feat 3 — Capteur global : Interruption / Travaux planifiés
# ══════════════════════════════════════════════════════════════════════


class EauGrandLyonOutageSensor(CoordinatorEntity[EauGrandLyonCoordinator], BinarySensorEntity):
    """True si une interruption de service est active ou prévue dans les 48h."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "outage_alert"
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
        today = dt_util.now().date()
        horizon = today + timedelta(days=2)
        for inter in interruptions:
            debut_str = inter.get("date_debut")
            fin_str = inter.get("date_fin")
            try:
                debut = date.fromisoformat(debut_str) if debut_str else None
                fin = date.fromisoformat(fin_str) if fin_str else debut
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
            "nb_interruptions": len(interruptions),
            "prochaine_date": prochaine.get("date_debut"),
            "prochaine_fin": prochaine.get("date_fin"),
            "prochaine_titre": prochaine.get("titre"),
            "prochaine_type": prochaine.get("type"),
            "toutes": [
                {
                    "titre": i.get("titre"),
                    "date_debut": i.get("date_debut"),
                    "date_fin": i.get("date_fin"),
                    "type": i.get("type"),
                }
                for i in interruptions[:10]
            ],
        }

    @property
    def device_info(self) -> DeviceInfo:
        return account_device_info(self.coordinator, self._entry)
