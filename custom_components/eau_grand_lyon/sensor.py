"""Sensors pour Eau du Grand Lyon — point d'entrée de la plateforme sensor."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .sensors.alerts import (
    EauGrandLyonSeuilSurconsoJourSensor,
    EauGrandLyonSeuilSurconsoMoisSensor,
)
from .sensors.consumption import (
    EauGrandLyonCompatibilitySensor,
    EauGrandLyonConso7JSensor,
    EauGrandLyonConso30JSensor,
    EauGrandLyonConsoAnnuelleRefSensor,
    EauGrandLyonConsommationAnnuelleSensor,
    EauGrandLyonConsommationSensor,
    EauGrandLyonConsoMoyenne7JSensor,
    EauGrandLyonIndexJournalierSensor,
    EauGrandLyonIndexSensor,
    EauGrandLyonYesterdaySensor,
)
from .sensors.contract import (
    EauGrandLyonDateEcheanceSensor,
    EauGrandLyonProchaineFactureSensor,
    EauGrandLyonProchaineReleveSensor,
    EauGrandLyonStatutSensor,
)
from .sensors.cost import (
    EauGrandLyonCoutAnnuelSensor,
    EauGrandLyonCoutCumuleSensor,
    EauGrandLyonCoutMoisSensor,
    EauGrandLyonCoutReelAnnuelSensor,
    EauGrandLyonCoutReelMoisSensor,
    EauGrandLyonEconomieSensor,
    EauGrandLyonEnergyCostSensor,
    EauGrandLyonEnergyWaterSensor,
    EauGrandLyonSoldeSensor,
)
from .sensors.experimental import (
    EauGrandLyonAvgFlowSensor,
    EauGrandLyonDerniereFactureSensor,
    EauGrandLyonFuiteEstimeeSensor,
    EauGrandLyonHourlyConsoSensor,
    EauGrandLyonPeakHourSensor,
)
from .sensors.global_sensors import (
    EauGrandLyonAlertesSensor,
    EauGrandLyonDroughtSensor,
    EauGrandLyonGlobalConsoSensor,
    EauGrandLyonGlobalCostSensor,
    EauGrandLyonGlobalPredictionCostSensor,
    EauGrandLyonHealthSensor,
    EauGrandLyonLastUpdateSensor,
    EauGrandLyonNextOutageSensor,
)
from .sensors.intelligence import (
    EauGrandLyonCO2FootprintSensor,
    EauGrandLyonCoachingSensor,
    EauGrandLyonEcoScoreSensor,
    EauGrandLyonLimescaleSensor,
    EauGrandLyonPredictionConsoSensor,
    EauGrandLyonPredictionCostSensor,
    EauGrandLyonSignalSensor,
    EauGrandLyonTrendSensor,
)
from .sensors.quality import (
    EauGrandLyonChloreSensor,
    EauGrandLyonNitratesSensor,
    EauGrandLyonWaterHardnessSensor,
)

PARALLEL_UPDATES = 0

if TYPE_CHECKING:
    from . import EauGrandLyonConfigEntry

_LOGGER = logging.getLogger(__name__)


def _is_teleo_meter(contract: dict) -> bool:
    """Infer whether a contract uses a communicant Teleo meter."""
    teleo = contract.get("teleo_compatible")
    if teleo is not None:
        return bool(teleo)
    # Fallback for API responses that don't include teleo_compatible.
    # pds_communicabilite_amm and pds_mode_releve may be dicts {code, libelle}
    # or legacy plain values (bool / string).
    amm = contract.get("pds_communicabilite_amm")
    if amm is True or (isinstance(amm, dict) and amm.get("code") == "ACTIVE"):
        return True
    mode = contract.get("pds_mode_releve")
    if isinstance(mode, dict):
        return mode.get("code") == "AMM"
    return mode == "AMM"


def _supports_daily_sensors(contract: dict) -> bool:
    """Daily sensors only make sense on Teleo/TIC-compatible meters."""
    return _is_teleo_meter(contract)


def _supports_hourly_sensors(contract: dict) -> bool:
    """Hourly sensors are only exposed for Teleo communicant meters."""
    return _is_teleo_meter(contract)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EauGrandLyonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensors and add entities for contracts discovered after setup."""
    coordinator = entry.runtime_data
    added_unique_ids: set[str] = set()

    def _add_new_entities() -> None:
        data = coordinator.data or {}
        candidates: list[SensorEntity] = []
        for ref, contract in data.get("contracts", {}).items():
            candidates.extend(
                _contract_sensor_candidates(
                    coordinator,
                    entry,
                    ref,
                    contract,
                    experimental=bool(data.get("experimental_mode", False)),
                )
            )
        candidates.extend(_global_sensor_candidates(coordinator, entry))

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


def _contract_sensor_candidates(
    coordinator,
    entry,
    ref: str,
    contract: dict,
    *,
    experimental: bool,
) -> list[SensorEntity]:
    """Build the currently applicable sensors for one contract."""
    entities: list[SensorEntity] = []
    supports_daily = _supports_daily_sensors(contract)
    supports_hourly = _supports_hourly_sensors(contract)
    # ── Tableau de bord Énergie HA ────────────────────────────────
    entities.append(EauGrandLyonIndexSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonEnergyWaterSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonEnergyCostSensor(coordinator, entry, ref))
    # ── Consommations mensuelles ──────────────────────────────────
    entities.append(EauGrandLyonConsommationSensor(coordinator, entry, ref, "courant"))
    entities.append(EauGrandLyonConsommationSensor(coordinator, entry, ref, "precedent"))
    entities.append(EauGrandLyonConsommationAnnuelleSensor(coordinator, entry, ref))
    # ── Consommations journalières (si compteur compatible) ───────
    if supports_daily:
        entities.append(EauGrandLyonYesterdaySensor(coordinator, entry, ref))
        entities.append(EauGrandLyonIndexJournalierSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonConso7JSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonConsoMoyenne7JSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonConso30JSensor(coordinator, entry, ref))
        # ── Coûts estimés ─────────────────────────────────────────────
    entities.append(EauGrandLyonCoutMoisSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonCoutAnnuelSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonCoutCumuleSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonEconomieSensor(coordinator, entry, ref))
    # ── Estimations avec part fixe ────────────────────────────────
    entities.append(EauGrandLyonCoutReelMoisSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonCoutReelAnnuelSensor(coordinator, entry, ref))
    # ── Compte & contrat ──────────────────────────────────────────
    entities.append(EauGrandLyonSoldeSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonStatutSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonDateEcheanceSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonProchaineFactureSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonProchaineReleveSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonConsoAnnuelleRefSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonCompatibilitySensor(coordinator, entry, ref))
    # ── Intelligence ──────────────────────────────────────────────
    entities.append(EauGrandLyonTrendSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonPredictionConsoSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonPredictionCostSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonEcoScoreSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonCO2FootprintSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonSignalSensor(coordinator, entry, ref))
    # ── Seuils d'alerte surconsommation (configurés côté serveur) ─
    if contract.get("seuil_surconso_jour_m3") is not None:
        entities.append(EauGrandLyonSeuilSurconsoJourSensor(coordinator, entry, ref))
    if contract.get("seuil_surconso_mois_m3") is not None:
        entities.append(EauGrandLyonSeuilSurconsoMoisSensor(coordinator, entry, ref))
        # ── Facture réelle ────────────────────────────────────────────
    if contract.get("derniere_facture") is not None:
        entities.append(EauGrandLyonDerniereFactureSensor(coordinator, entry, ref))
        # ── Expérimental ──────────────────────────────────────────────
    if experimental:
        entities.append(EauGrandLyonFuiteEstimeeSensor(coordinator, entry, ref))
        if supports_hourly:
            entities.append(EauGrandLyonHourlyConsoSensor(coordinator, entry, ref))
            entities.append(EauGrandLyonPeakHourSensor(coordinator, entry, ref))
            entities.append(EauGrandLyonAvgFlowSensor(coordinator, entry, ref))

    entities.append(EauGrandLyonLimescaleSensor(coordinator, entry, ref))
    entities.append(EauGrandLyonCoachingSensor(coordinator, entry, ref))
    return entities


def _global_sensor_candidates(coordinator, entry) -> list[SensorEntity]:
    """Build account-level sensors, including multi-contract aggregates."""
    entities: list[SensorEntity] = []

    # ── Sensors globaux ───────────────────────────────────────────────
    entities.append(EauGrandLyonAlertesSensor(coordinator, entry))
    entities.append(EauGrandLyonLastUpdateSensor(coordinator, entry))
    entities.append(EauGrandLyonHealthSensor(coordinator, entry))
    entities.append(EauGrandLyonDroughtSensor(coordinator, entry))
    entities.append(EauGrandLyonNextOutageSensor(coordinator, entry))

    # ── Qualité de l'eau (Open Data) ──────────────────────────────────
    entities.append(EauGrandLyonWaterHardnessSensor(coordinator, entry))
    entities.append(EauGrandLyonNitratesSensor(coordinator, entry))
    entities.append(EauGrandLyonChloreSensor(coordinator, entry))

    # ── Agrégats si plusieurs contrats ────────────────────────────────
    if (coordinator.data or {}).get("global", {}).get("nb_contracts", 0) > 1:
        entities.append(EauGrandLyonGlobalConsoSensor(coordinator, entry))
        entities.append(EauGrandLyonGlobalCostSensor(coordinator, entry))
        entities.append(EauGrandLyonGlobalPredictionCostSensor(coordinator, entry))

    return entities
