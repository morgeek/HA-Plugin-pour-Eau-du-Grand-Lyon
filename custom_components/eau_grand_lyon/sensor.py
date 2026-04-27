"""Sensors pour Eau du Grand Lyon — point d'entrée de la plateforme sensor."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .sensors.consumption import (
    EauGrandLyonConso30JSensor,
    EauGrandLyonConso7JSensor,
    EauGrandLyonCompatibilitySensor,
    EauGrandLyonConsoAnnuelleRefSensor,
    EauGrandLyonConsommationAnnuelleSensor,
    EauGrandLyonConsommationSensor,
    EauGrandLyonConsoMoyenne7JSensor,
    EauGrandLyonIndexJournalierSensor,
    EauGrandLyonIndexSensor,
    EauGrandLyonYesterdaySensor,
)

PARALLEL_UPDATES = 0
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
from .sensors.contract import (
    EauGrandLyonDateEcheanceSensor,
    EauGrandLyonProchaineFactureSensor,
    EauGrandLyonProchaineReleveSensor,
    EauGrandLyonStatutSensor,
)
from .sensors.intelligence import (
    EauGrandLyonCoachingSensor,
    EauGrandLyonCO2FootprintSensor,
    EauGrandLyonEcoScoreSensor,
    EauGrandLyonLimescaleSensor,
    EauGrandLyonPredictionConsoSensor,
    EauGrandLyonPredictionCostSensor,
    EauGrandLyonSignalSensor,
    EauGrandLyonTrendSensor,
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
from .sensors.quality import (
    EauGrandLyonChloreSensor,
    EauGrandLyonNitratesSensor,
    EauGrandLyonWaterHardnessSensor,
)
from .sensors.experimental import (
    EauGrandLyonAvgFlowSensor,
    EauGrandLyonDerniereFactureSensor,
    EauGrandLyonFuiteEstimeeSensor,
    EauGrandLyonHourlyConsoSensor,
    EauGrandLyonPeakHourSensor,
)

if TYPE_CHECKING:
    from . import EauGrandLyonConfigEntry

_LOGGER = logging.getLogger(__name__)


def _is_teleo_meter(contract: dict) -> bool:
    """Infer whether a contract uses a communicant Teleo meter."""
    if contract.get("teleo_compatible"):
        return True
    if contract.get("pds_communicabilite_amm") is True:
        return True
    return contract.get("pds_mode_releve") == "AMM"


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
    """Crée toutes les entités sensor après chargement de la config entry."""
    coordinator = entry.runtime_data
    contracts = (coordinator.data or {}).get("contracts", {})
    experimental = bool((coordinator.data or {}).get("experimental_mode", False))

    entities: list[SensorEntity] = []

    for ref, contract in contracts.items():
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
        # ── Coût réel avec abonnement ─────────────────────────────────
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
        # ── Expérimental ──────────────────────────────────────────────
        if experimental:
            entities.append(EauGrandLyonDerniereFactureSensor(coordinator, entry, ref))
            entities.append(EauGrandLyonFuiteEstimeeSensor(coordinator, entry, ref))
            if supports_hourly:
                entities.append(EauGrandLyonHourlyConsoSensor(coordinator, entry, ref))
                entities.append(EauGrandLyonPeakHourSensor(coordinator, entry, ref))
                entities.append(EauGrandLyonAvgFlowSensor(coordinator, entry, ref))

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

    # ── Coaching (per-contract) ───────────────────────────────────────
    for ref in contracts:
        entities.append(EauGrandLyonLimescaleSensor(coordinator, entry, ref))
        entities.append(EauGrandLyonCoachingSensor(coordinator, entry, ref))

    async_add_entities(entities, update_before_add=False)
