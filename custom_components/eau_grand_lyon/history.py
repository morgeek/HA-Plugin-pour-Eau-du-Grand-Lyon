"""Historique persistant (mensuel/journalier) pour Eau du Grand Lyon."""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import cast

from homeassistant.helpers.storage import Store

from .models import DailyConsumption, MonthlyConsumption

_LOGGER = logging.getLogger(__name__)

# 37 mois couvrent le mois courant et les trois périodes homologues nécessaires
# au calcul Warsmann (l'API ne retourne que 12 mois).
MONTHLY_HISTORY_MAX_MONTHS = 37
DAILY_HISTORY_MAX_DAYS = 1097


class RebuildableStore(Store[dict[str, object]]):
    """Store pour caches reconstructibles (historique mensuel, cache offline).

    Le Store par défaut lève NotImplementedError au chargement quand le fichier
    `.storage` porte une version antérieure à celle du code sans fonction de
    migration — ce qui plante le setup de l'intégration après une montée de
    version du schéma (ex. v1 -> v2 de l'historique mensuel).

    Ici les données sont entièrement reconstruites depuis l'API aux cycles
    suivants : une migration se résume donc à repartir d'un cache vide, ce qui
    est sûr et évite tout crash au démarrage.
    """

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, object],
    ) -> dict[str, object]:
        _LOGGER.debug(
            "Cache %s en version %s.%s — reconstruction depuis l'API (reset)",
            self.key,
            old_major_version,
            old_minor_version,
        )
        return {}


def merge_monthly_history(
    stored: list[MonthlyConsumption],
    fresh: list[MonthlyConsumption],
    max_months: int = MONTHLY_HISTORY_MAX_MONTHS,
) -> list[MonthlyConsumption]:
    """Fusionne l'historique stocké avec les données fraîches de l'API.

    Les données fraîches priment sur les données stockées pour le même mois.
    Retourne la liste triée chronologiquement, plafonnée à max_months.
    """
    by_key: dict[tuple[object, object], MonthlyConsumption] = {}
    for entry in stored:
        key = (entry.get("annee"), entry.get("mois_index"))
        if None not in key:
            by_key[key] = entry
    for entry in fresh:
        key = (entry.get("annee"), entry.get("mois_index"))
        if None not in key:
            by_key[key] = entry  # API prime sur le stocké
    merged = sorted(
        by_key.values(),
        key=lambda e: (e.get("annee", 0), e.get("mois_index", 0)),
    )
    return merged[-max_months:]


def merge_daily_history(
    stored: list[DailyConsumption],
    fresh: list[DailyConsumption],
    max_days: int = DAILY_HISTORY_MAX_DAYS,
) -> list[DailyConsumption]:
    """Fusionne les journées, les données fraîches remplaçant les anciennes."""
    by_date: dict[str, DailyConsumption] = {}
    entries = stored if isinstance(stored, list) else []
    fresh_entries = fresh if isinstance(fresh, list) else []
    for entry in (*entries, *fresh_entries):
        date = entry.get("date")
        if date:
            by_date[str(date)] = entry
    return sorted(by_date.values(), key=lambda entry: str(entry.get("date", "")))[-max_days:]


def sanitize_daily_history(stored: object) -> dict[str, list[DailyConsumption]]:
    """Conserve uniquement les contrats et journées valides du cache."""
    if not isinstance(stored, dict):
        return {}
    sanitized: dict[str, list[DailyConsumption]] = {}
    for ref, entries in stored.items():
        if not isinstance(ref, str) or not isinstance(entries, list):
            continue
        valid_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                datetime.fromisoformat(str(entry["date"]))
                value = float(entry["consommation_m3"])
                if not math.isfinite(value):
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            valid_entries.append(cast(DailyConsumption, entry))
        if valid_entries:
            sanitized[ref] = valid_entries
    return sanitized
