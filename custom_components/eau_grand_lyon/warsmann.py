"""Calcul indicatif du seuil de consommation anormale dit « Warsmann »."""

from __future__ import annotations

from datetime import date
from typing import Literal, TypedDict

from .models import DailyConsumption, MonthlyConsumption


class WarsmannAssessment(TypedDict):
    """Résultat explicable d'une comparaison sur trois périodes homologues."""

    average_m3: float
    basis: Literal["daily", "monthly"]
    eligible: bool
    historical_periods: list[str]
    historical_values_m3: list[float]
    observed_m3: float
    period: str
    threshold_m3: float


def _safe_volume(value: object) -> float | None:
    try:
        volume = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return volume if volume >= 0 else None


def assess_monthly(history: list[MonthlyConsumption]) -> WarsmannAssessment | None:
    """Compare le dernier mois aux mêmes mois des trois années précédentes."""
    by_period: dict[tuple[int, int], float] = {}
    for entry in history:
        year = entry.get("annee")
        month = entry.get("mois_index")
        volume = _safe_volume(entry.get("consommation_m3"))
        if isinstance(year, int) and isinstance(month, int) and 0 <= month <= 11 and volume is not None:
            by_period[(year, month)] = volume
    if not by_period:
        return None

    target = max(by_period)
    previous = [(target[0] - offset, target[1]) for offset in (1, 2, 3)]
    if any(period not in by_period for period in previous):
        return None
    values = [by_period[period] for period in previous]
    return _assessment(
        basis="monthly",
        period=f"{target[0]:04d}-{target[1] + 1:02d}",
        observed=by_period[target],
        historical_periods=[f"{year:04d}-{month + 1:02d}" for year, month in previous],
        historical_values=values,
    )


def assess_daily(history: list[DailyConsumption]) -> WarsmannAssessment | None:
    """Compare le dernier jour aux mêmes dates des trois années précédentes."""
    by_period: dict[date, float] = {}
    for entry in history:
        raw_date = entry.get("date")
        volume = _safe_volume(entry.get("consommation_m3"))
        if not raw_date or volume is None:
            continue
        try:
            parsed = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        by_period[parsed] = volume
    if not by_period:
        return None

    target = max(by_period)
    try:
        previous = [target.replace(year=target.year - offset) for offset in (1, 2, 3)]
    except ValueError:
        # Un 29 février n'a pas trois dates homologues exactes consécutives.
        return None
    if any(period not in by_period for period in previous):
        return None
    values = [by_period[period] for period in previous]
    return _assessment(
        basis="daily",
        period=target.isoformat(),
        observed=by_period[target],
        historical_periods=[period.isoformat() for period in previous],
        historical_values=values,
    )


def assess_warsmann(
    monthly: list[MonthlyConsumption],
    daily: list[DailyConsumption],
    *,
    teleo: bool,
) -> WarsmannAssessment | None:
    """Utilise les périodes journalières pour Téléo, mensuelles sinon."""
    return assess_daily(daily) if teleo else assess_monthly(monthly)


def _assessment(
    *,
    basis: Literal["daily", "monthly"],
    period: str,
    observed: float,
    historical_periods: list[str],
    historical_values: list[float],
) -> WarsmannAssessment:
    average = sum(historical_values) / 3
    threshold = average * 2
    return {
        "average_m3": round(average, 3),
        "basis": basis,
        # Évite qu'une représentation binaire telle que 0,2 × 2 rende 0,4
        # artificiellement supérieur au seuil.
        "eligible": observed > threshold + 1e-9,
        "historical_periods": historical_periods,
        "historical_values_m3": [round(value, 3) for value in historical_values],
        "observed_m3": round(observed, 3),
        "period": period,
        "threshold_m3": round(threshold, 3),
    }
