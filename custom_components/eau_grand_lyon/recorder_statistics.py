"""Injection des statistiques longue durée (dashboard Énergie) pour Eau du Grand Lyon."""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

try:
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
    )

    _HAS_RECORDER = True
except ImportError:
    _HAS_RECORDER = False

# Importé séparément : absent sur les versions HA plus anciennes, où l'on
# retombe sur has_mean sans désactiver toute l'injection de statistiques.
if TYPE_CHECKING:
    from homeassistant.components.recorder.models.statistics import StatisticMeanType
else:
    try:
        from homeassistant.components.recorder.statistics import StatisticMeanType
    except ImportError:
        StatisticMeanType = None

# Lecture de la dernière somme connue du recorder pour ancrer le cumul et éviter
# les deltas négatifs quand la fenêtre glissante perd son plus vieux
# mois. Optionnel : toute absence/erreur retombe sur un cumul à partir de 0.
try:
    if TYPE_CHECKING:
        from homeassistant.helpers.recorder import (
            get_instance as _get_recorder_instance,
        )
    else:
        from homeassistant.components.recorder import (
            get_instance as _get_recorder_instance,
        )
    from homeassistant.components.recorder.statistics import (
        get_last_statistics as _get_last_statistics,
    )

    _HAS_LAST_STATS = True
except ImportError:
    _HAS_LAST_STATS = False

from .const import (
    DOMAIN,
    STATISTIC_COST,
    STATISTIC_COST_DAILY,
    STATISTIC_WATER,
    STATISTIC_WATER_DAILY,
)
from .models import ContractData, DailyConsumption, MonthlyConsumption

_LOGGER = logging.getLogger(__name__)

StatAnchor = tuple[tuple[int, int], float]


def statistic_ref(ref: str) -> str:
    """Normalise une référence contrat en object_id de statistique valide.

    Le recorder n'accepte que [a-z0-9_] (minuscules, pas d'underscore en
    bordure ni doublé) — une référence avec majuscules ou tirets rendait
    le statistic_id invalide et l'injection échouait silencieusement.
    Pour les références purement numériques (cas courant), no-op.
    """
    sanitized = re.sub(r"[^a-z0-9]+", "_", str(ref).lower()).strip("_")
    return sanitized or "contract"


def statistic_id(prefix: str, ref: str) -> str:
    """Construit un statistic ID stable pour un contrat."""
    return f"{DOMAIN}:{prefix}_{statistic_ref(ref)}"


def build_monthly_series(
    consos: list[MonthlyConsumption],
    value_fn: Callable[[float], float],
    anchor: StatAnchor | None,
    ndigits: int,
) -> list["StatisticData"]:
    """Construit une série cumulative (state + sum) prête pour le recorder.

    `value_fn(conso_m3) -> valeur du mois` (m³ ou EUR). `anchor`, s'il est
    fourni, vaut ((année, mois) du dernier mois déjà enregistré, somme cumulée
    AVANT ce mois) : le cumul repart de cette base et les mois antérieurs sont
    laissés intacts. Sans ancrage, le cumul part de 0 sur toute la fenêtre.
    Ancrer sur le recorder évite les deltas négatifs quand la fenêtre
    glissante perd son plus ancien mois (le cumul repartait sinon de 0).
    """
    series: list["StatisticData"] = []
    cumulative = anchor[1] if anchor else 0.0
    last_ym = anchor[0] if anchor else None
    for entry in sorted(consos, key=lambda e: (e.get("annee", 0), e.get("mois_index", 0))):
        try:
            mois_num = entry["mois_index"] + 1
            annee = entry["annee"]
            value = value_fn(entry["consommation_m3"])
            dt = datetime(annee, mois_num, 1, 0, 0, 0, tzinfo=timezone.utc)
        except (KeyError, ValueError, TypeError) as err:
            _LOGGER.debug("Skipping statistic entry: %s — %s", entry, err)
            continue
        if last_ym is not None and (annee, mois_num) < last_ym:
            continue  # déjà enregistré : préserver la somme existante
        cumulative += value
        series.append(
            StatisticData(
                start=dt,
                sum=round(cumulative, ndigits),
                state=round(value, ndigits),
            )
        )
    return series


def build_daily_series(
    consos: list[DailyConsumption],
    value_fn: Callable[[float], float] = float,
    ndigits: int = 3,
) -> list["StatisticData"]:
    """Reconstruit un cumul journalier à la date réelle de chaque journée."""
    series: list["StatisticData"] = []
    cumulative = 0.0
    by_date: dict[str, DailyConsumption] = {}
    for entry in consos:
        if isinstance(entry, dict) and entry.get("date"):
            by_date[str(entry["date"])] = entry
    for entry in sorted(by_date.values(), key=lambda item: str(item.get("date", ""))):
        try:
            date = datetime.fromisoformat(str(entry["date"])).date()
            value = float(value_fn(float(entry["consommation_m3"])))
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.debug("Skipping daily statistic entry: %s — %s", entry, err)
            continue
        cumulative += value
        series.append(
            StatisticData(
                start=datetime.combine(date, datetime.min.time(), tzinfo=timezone.utc),
                sum=round(cumulative, ndigits),
                state=round(value, ndigits),
            )
        )
    return series


async def async_last_recorded_anchor(hass: HomeAssistant, stat_id: str) -> StatAnchor | None:
    """Retourne ((année, mois), somme cumulée avant ce mois) du dernier point enregistré.

    Best-effort : toute absence de recorder ou erreur renvoie None, et
    l'injection retombe alors sur un cumul depuis 0 (comportement historique).
    """
    if not _HAS_LAST_STATS:
        return None
    try:
        recorder = _get_recorder_instance(hass)
        rows = await recorder.async_add_executor_job(_get_last_statistics, hass, 1, stat_id, True, {"sum", "state"})
        points = rows.get(stat_id) if rows else None
        if not points:
            return None
        last = points[0]
        raw_start: object = last["start"]
        if isinstance(raw_start, datetime):
            start = raw_start
        elif isinstance(raw_start, (str, int, float)):
            start = datetime.fromtimestamp(float(raw_start), tz=timezone.utc)
        else:
            return None
        last_sum = float(last.get("sum") or 0.0)
        last_state = float(last.get("state") or 0.0)
        # baseline = cumul jusqu'au mois PRÉCÉDENT ce dernier point.
        return ((start.year, start.month), last_sum - last_state)
    except Exception as err:  # noqa: BLE001 - lecture optionnelle, jamais bloquante
        _LOGGER.debug("Lecture last_statistics indisponible pour %s : %s", stat_id, err)
        return None


async def async_inject_series(
    hass: HomeAssistant,
    metadata: "StatisticMetaData",
    series: list["StatisticData"],
    label: str,
) -> None:
    """Envoie une série au recorder ; un rejet est journalisé sans interrompre le cycle."""
    if not series:
        return
    try:
        result: object = async_add_external_statistics(hass, metadata, series)
        if inspect.isawaitable(result):
            await result
        _LOGGER.debug("Injected %s statistics: %d months", label, len(series))
    except (HomeAssistantError, ValueError) as err:
        _LOGGER.warning("Failed to inject %s statistics: %s", label, err)


def _metadata(
    mean_kwargs: dict[str, Any],
    name: str,
    stat_id: str,
    unit: str,
    unit_class: str | None,
) -> "StatisticMetaData":
    return cast(
        StatisticMetaData,
        {
            **mean_kwargs,
            "has_sum": True,
            "name": name,
            "source": DOMAIN,
            "statistic_id": stat_id,
            "unit_of_measurement": unit,
            # Currency has no unit converter -> unit_class must be None (not
            # "monetary"). Omitting it entirely is deprecated (removed in HA
            # 2025.11); "monetary" is rejected as an unsupported converter.
            "unit_class": unit_class,
        },
    )


async def async_inject_contract_statistics(
    hass: HomeAssistant,
    contracts_data: dict[str, ContractData],
    monthly_history: dict[str, list[MonthlyConsumption]],
    daily_history: dict[str, list[DailyConsumption]],
) -> None:
    """Injecte l'historique mensuel et journalier dans les statistiques longue durée HA."""
    if not _HAS_RECORDER:
        return

    # StatisticMeanType sur les HA récents, has_mean en fallback sur les anciens
    if StatisticMeanType is not None:
        mean_kwargs: dict[str, Any] = {"mean_type": StatisticMeanType.NONE}
    else:
        mean_kwargs = {"has_mean": False}

    for ref, contract in contracts_data.items():
        tarif = contract.get("tarif_m3", 0)

        daily_consos = daily_history.get(ref) or contract.get("consommations_journalieres", [])
        if daily_consos:
            daily_metadata = _metadata(
                mean_kwargs,
                f"Eau Grand Lyon - Journalier {ref}",
                statistic_id(STATISTIC_WATER_DAILY, ref),
                "m³",
                "volume",
            )
            await async_inject_series(
                hass, daily_metadata, build_daily_series(daily_consos), f"journalier contrat {ref}"
            )

            if tarif > 0:
                daily_cost_metadata = _metadata(
                    mean_kwargs,
                    f"Eau Grand Lyon - Coût journalier {ref}",
                    statistic_id(STATISTIC_COST_DAILY, ref),
                    "EUR",
                    None,
                )
                daily_cost_series = build_daily_series(daily_consos, lambda conso: round(conso * tarif, 2), 2)
                await async_inject_series(hass, daily_cost_metadata, daily_cost_series, f"coût journalier {ref}")

        # Historique fusionné pour que le passé soit toujours
        # injecté, pas seulement les ~12 mois renvoyés par l'API à chaque appel.
        consos = monthly_history.get(ref) or contract.get("consommations", [])
        if not consos:
            continue

        water_id = statistic_id(STATISTIC_WATER, ref)
        metadata = _metadata(mean_kwargs, f"Eau Grand Lyon - Compteur {ref}", water_id, "m³", "volume")
        anchor = await async_last_recorded_anchor(hass, water_id)
        water_series = build_monthly_series(consos, lambda conso: conso, anchor, 3)
        await async_inject_series(hass, metadata, water_series, f"contrat {ref}")

        # Statistiques de coût (EUR/mois) si un tarif est configuré.
        if tarif <= 0:
            continue
        cost_id = statistic_id(STATISTIC_COST, ref)
        cost_metadata = _metadata(mean_kwargs, f"Eau Grand Lyon - Coût {ref}", cost_id, "EUR", None)
        cost_anchor = await async_last_recorded_anchor(hass, cost_id)
        cost_series = build_monthly_series(consos, lambda conso: round(conso * tarif, 2), cost_anchor, 2)
        await async_inject_series(hass, cost_metadata, cost_series, f"coût {ref}")
