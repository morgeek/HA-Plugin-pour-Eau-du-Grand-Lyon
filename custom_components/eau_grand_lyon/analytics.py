"""Calculs locaux dérivés des consommations Eau du Grand Lyon.

Fonctions pures (sans I/O ni état) : tendances, prédictions, Eco-Score,
heuristiques de fuite, analyse de la courbe horaire, calcaire. Ce sont des
indicateurs déterministes, pas des données fournisseur.
"""

from __future__ import annotations

import calendar
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .api import MONTHS_FR
from .models import DailyConsumption, MonthlyConsumption

_LOGGER = logging.getLogger(__name__)

# Facteur d'émission fixe (kg CO₂e par m³ d'eau distribuée et traitée).
CO2_KG_PER_M3 = 0.52
# Au-delà de 100 kg de calcaire par an, l'alerte entartrage est levée.
LIMESCALE_ALERT_G = 100000
# Plancher de l'heuristique de pic journalier (500 L/j) contre les faux positifs.
LEAK_MIN_DAILY_M3 = 0.5


def parse_nb_habitants(val: str) -> int:
    """Extrait le nombre d'habitants depuis une chaîne (ex: '4 personnes')."""
    if not val:
        return 1
    match = re.search(r"(\d+)", val)
    return int(match.group(1)) if match else 1


def find_missing_months(consos: list[MonthlyConsumption]) -> list[str]:
    """Détecte les mois manquants entre le premier et le dernier relevé disponible."""
    if len(consos) < 2:
        return []

    present = {(e["annee"], e["mois_index"]) for e in consos}
    first = consos[0]
    last = consos[-1]
    missing: list[str] = []
    year = first["annee"]
    month_idx = first["mois_index"]
    end_year = last["annee"]
    end_m_idx = last["mois_index"]

    while (year, month_idx) <= (end_year, end_m_idx):
        if (year, month_idx) not in present:
            missing.append(f"{MONTHS_FR[month_idx]} {year}")
        month_idx += 1
        if month_idx > 11:
            month_idx = 0
            year += 1

    return missing


def consumption_n1(consos: list[MonthlyConsumption]) -> tuple[float | None, str | None]:
    """Récupère la consommation à N-1 pour le même mois."""
    if not consos:
        return None, None
    target_mois = consos[-1]["mois_index"]
    target_annee = consos[-1]["annee"] - 1
    for e in consos:
        if e["mois_index"] == target_mois and e["annee"] == target_annee:
            return e["consommation_m3"], e["label"]
    return None, None


def daily_aggregates(daily: list[DailyConsumption]) -> tuple[float | None, float | None]:
    """Calcule les agrégats sur 7 et 30 jours."""
    if not daily:
        return None, None
    conso_7j = round(sum(e["consommation_m3"] for e in daily[-7:]), 2)
    conso_30j = round(sum(e["consommation_m3"] for e in daily[-30:]), 2)
    return conso_7j, conso_30j


def trend_and_prediction(
    current: float | None,
    n1: float | None,
    daily: list[DailyConsumption],
    tarif: float,
) -> tuple[float | None, float | None, float | None]:
    """Retourne (prédiction m³ fin de mois, prédiction coût, tendance N-1 en %).

    La prédiction est une extrapolation linéaire au dernier jour publié,
    uniquement quand ce jour appartient au mois courant.
    """
    if current is None:
        return None, None, None

    tendance = round(((current - n1) / n1) * 100, 1) if n1 and n1 > 0 else None

    now = datetime.now(timezone.utc)
    last_data_date = now
    if daily:
        try:
            last_data_date = datetime.strptime(daily[-1]["date"], "%Y-%m-%d")
        except (ValueError, KeyError, TypeError):
            pass

    if last_data_date.month == now.month and last_data_date.year == now.year:
        jours_ecoules = last_data_date.day
        _, jours_total = calendar.monthrange(now.year, now.month)
        if jours_ecoules > 0:
            pred_conso = round((current / jours_ecoules) * jours_total, 1)
            return pred_conso, round(pred_conso * tarif, 2), tendance

    return None, None, tendance


def household_size(details: dict[str, Any], configured: int | float | str | None, default: int) -> int:
    """Taille du foyer : option explicite, sinon valeur du contrat, sinon défaut."""
    if configured is not None:
        return int(configured)
    api_hab = parse_nb_habitants(details.get("nombre_habitants", ""))
    return api_hab if api_hab > 0 else default


def eco_score(current: float | None, nb_hab: int) -> tuple[float | None, str]:
    """Retourne (m³ par habitant, grade A–G) selon des seuils internes."""
    if current is None or nb_hab <= 0:
        return None, "Inconnu"

    m3_per_hab = current / nb_hab
    grade = "G"
    if m3_per_hab < 2.5:
        grade = "A"
    elif m3_per_hab < 4.0:
        grade = "B"
    elif m3_per_hab < 6.0:
        grade = "C"
    elif m3_per_hab < 8.0:
        grade = "D"
    elif m3_per_hab < 10.0:
        grade = "E"
    elif m3_per_hab < 13.0:
        grade = "F"

    return round(m3_per_hab, 2), grade


def co2_footprint_kg(conso_m3: float | None) -> float | None:
    """Empreinte CO₂e indicative de la consommation."""
    return round(conso_m3 * CO2_KG_PER_M3, 2) if conso_m3 is not None else None


def estimate_next_bill_date(next_payment: str | None) -> str | None:
    """Estime la prochaine date de facture (échéance + 180 jours)."""
    if not next_payment:
        return None
    try:
        dt_pay = datetime.strptime(next_payment, "%Y-%m-%d")
        return (dt_pay + timedelta(days=180)).strftime("%Y-%m-%d")
    except ValueError:
        return None


def experimental_leak_30d(experimental: bool, daily: list[DailyConsumption]) -> float | None:
    """Somme des volumes de fuite estimés par le fournisseur sur 30 jours."""
    if not (experimental and daily):
        return None
    valeurs = [e["volume_fuite_estime_m3"] for e in daily[-30:] if "volume_fuite_estime_m3" in e]
    return round(sum(valeurs), 3) if valeurs else None


def detect_local_leak(
    courbe: list[dict[str, Any]],
    daily: list[DailyConsumption],
    ref: str,
    multiplier: float,
) -> bool:
    """Détecte une fuite locale par analyse de pattern.

    L'API Téléo ne pousse qu'un index par 24h, donc la règle "jamais à 0 sur
    24h" est toujours vraie dans un logement habité. On utilise à la place un
    seuil statistique : alerte si la conso du dernier jour dépasse
    `multiplier`× la moyenne glissante des 7 derniers jours (minimum
    500 L/j pour éviter les faux positifs sur de très faibles consos). Le
    multiplicateur est celui configuré dans les options, unifié avec la
    détection mensuelle du binary_sensor.
    """
    if courbe:
        vals = [e.get("valeur", 0) for e in courbe if "valeur" in e]
        # Courbe intra-journalière : flux non-nul en permanence sur 24h+ = fuite probable.
        if len(vals) >= 24 and all(v > 0 for v in vals):
            _LOGGER.warning("Suspected leak (flat 24h+ pattern): %s", ref)
            return True
    elif daily and len(daily) >= 7:
        recent = [e["consommation_m3"] for e in daily[-7:]]
        moyenne_7j = sum(recent) / len(recent)
        last = recent[-1]
        seuil = max(moyenne_7j * multiplier, LEAK_MIN_DAILY_M3)
        if moyenne_7j > 0 and last > seuil:
            _LOGGER.warning(
                "Suspected leak (daily spike): %s — last=%.3f m³, avg7j=%.3f m³",
                ref,
                last,
                moyenne_7j,
            )
            return True
    return False


def analyze_load_curve(
    courbe: list[dict[str, Any]],
) -> tuple[float | None, str | None, float | None]:
    """Retourne (conso dernière heure m³, heure du pic HH:MM, débit moyen non nul m³/h)."""
    raw_vals: list[float] = []
    for curve_entry in courbe:
        v = curve_entry.get("valeur") or curve_entry.get("consommation") or 0
        try:
            raw_vals.append(float(v) if isinstance(v, (str, int, float)) else 0.0)
        except (ValueError, TypeError):
            raw_vals.append(0.0)
    if not raw_vals:
        return None, None, None

    heure_pic: str | None
    max_idx = raw_vals.index(max(raw_vals))
    try:
        heure_pic = datetime.fromisoformat(courbe[max_idx].get("date", "")).strftime("%H:%M")
    except (ValueError, TypeError, AttributeError):
        heure_pic = None
    non_zero = [v for v in raw_vals if v > 0]
    debit_moyen = round(sum(non_zero) / len(non_zero), 4) if non_zero else None
    return raw_vals[-1], heure_pic, debit_moyen


def latest_daily_index(daily: list[DailyConsumption]) -> tuple[float | None, str | None]:
    """Dernier index compteur publié dans les données journalières (Téléo)."""
    for e in reversed(daily):
        idx = e.get("index_m3")
        if idx is not None:
            try:
                return float(idx), e.get("date")
            except (ValueError, TypeError):
                return None, None
    return None, None


def limescale(consos: list[MonthlyConsumption], hardness_fh: float) -> tuple[float, bool]:
    """Entartrage estimé (g) sur 12 mois glissants et alerte associée.

    Basé sur la conso des 12 derniers mois (fenêtre bornée), et NON sur
    l'index absolu du compteur (cumul depuis la pose) qui faisait dépasser
    le seuil en permanence — l'alerte était donc toujours active.
    """
    annual_volume = sum(e["consommation_m3"] for e in consos[-12:])
    limescale_g = round(annual_volume * hardness_fh * 10, 0)
    return limescale_g, limescale_g > LIMESCALE_ALERT_G


def drought_level() -> str:
    """Niveau de sécheresse (heuristique calendaire). Valeurs = clés ENUM traduites."""
    current_month = datetime.now(timezone.utc).month
    return "vigilance" if 6 <= current_month <= 9 else "normal"
