"""Calculs tarifaires transparents pour Eau du Grand Lyon."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from typing import Any

# Grille générale TTC applicable au 01/01/2026.
# Source : https://www.eaudugrandlyon.com/wp-content/uploads/2026/04/Tarif-general-2026.pdf
OFFICIAL_2026_POTABLE_TIER_1_MAX_M3 = 12.0
OFFICIAL_2026_POTABLE_TIER_2_MAX_M3 = 180.0
OFFICIAL_2026_POTABLE_TIER_2_TTC_M3 = 1.3926
OFFICIAL_2026_POTABLE_TIER_3_TTC_M3 = 2.7852

# Assainissement et redevances, dus sur chaque m³ y compris les 12 m³ dont
# seule la part eau potable est gratuite.
OFFICIAL_2026_OTHER_VARIABLE_TTC_M3 = sum(
    (
        1.4495,  # assainissement collectif
        0.0095,  # VNF eau potable
        0.0471,  # VNF assainissement
        0.4115,  # redevance consommation
        0.0211,  # performance eau potable
        0.0559,  # prélèvement ressource
        0.0561,  # performance assainissement
    )
)
OFFICIAL_2026_TIER_2_TOTAL_TTC_M3 = OFFICIAL_2026_OTHER_VARIABLE_TTC_M3 + OFFICIAL_2026_POTABLE_TIER_2_TTC_M3

OFFICIAL_2026_SUBSCRIPTIONS_TTC: dict[int, float] = {
    15: 50.66,
    20: 242.87,
    30: 378.85,
    40: 783.53,
    50: 1265.70,
    60: 1498.18,
    80: 2324.76,
    100: 3843.85,
    150: 6157.54,
    200: 6734.43,
}


@dataclass(frozen=True, slots=True)
class BillingEstimate:
    """Résultat sérialisable d'une estimation de coût."""

    variable_eur: float
    fixed_eur: float
    total_eur: float
    volume_m3: float
    effective_rate_eur_m3: float | None
    source: str

    def as_dict(self) -> dict[str, Any]:
        """Convert to a coordinator-safe plain mapping."""
        return asdict(self)


def _safe_volume(volume_m3: float | int | None) -> float:
    """Return a finite non-negative volume."""
    try:
        value = float(volume_m3 or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return value if math.isfinite(value) and value >= 0 else 0.0


def effective_invoice_rate(invoice: dict[str, Any] | None) -> float | None:
    """Return the all-in TTC rate observed on one real invoice."""
    if not invoice:
        return None
    try:
        amount = float(invoice.get("montant_ttc") or 0.0)
        volume = float(invoice.get("volume_m3") or 0.0)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount) or not math.isfinite(volume) or amount <= 0 or volume <= 0:
        return None
    return amount / volume


def linear_estimate(
    volume_m3: float | int | None,
    rate_eur_m3: float,
    fixed_eur: float = 0.0,
    *,
    source: str,
) -> BillingEstimate:
    """Estimate a bill with a flat all-in or user-provided rate."""
    volume = _safe_volume(volume_m3)
    rate = float(rate_eur_m3)
    fixed_value = float(fixed_eur)
    rate = rate if math.isfinite(rate) and rate >= 0 else 0.0
    fixed_value = fixed_value if math.isfinite(fixed_value) and fixed_value >= 0 else 0.0
    variable = round(volume * rate, 2)
    fixed = round(fixed_value, 2)
    total = round(variable + fixed, 2)
    return BillingEstimate(
        variable_eur=variable,
        fixed_eur=fixed,
        total_eur=total,
        volume_m3=volume,
        effective_rate_eur_m3=round(total / volume, 6) if volume else None,
        source=source,
    )


def _official_2026_potable_total(volume_m3: float) -> float:
    """Return cumulative potable-water cost at one annual tier position."""
    volume = _safe_volume(volume_m3)
    tier_2_volume = min(
        max(volume - OFFICIAL_2026_POTABLE_TIER_1_MAX_M3, 0.0),
        OFFICIAL_2026_POTABLE_TIER_2_MAX_M3 - OFFICIAL_2026_POTABLE_TIER_1_MAX_M3,
    )
    tier_3_volume = max(volume - OFFICIAL_2026_POTABLE_TIER_2_MAX_M3, 0.0)
    return tier_2_volume * OFFICIAL_2026_POTABLE_TIER_2_TTC_M3 + tier_3_volume * OFFICIAL_2026_POTABLE_TIER_3_TTC_M3


def official_2026_estimate(
    volume_m3: float | int | None,
    *,
    fixed_eur: float = 0.0,
    starting_annual_volume_m3: float = 0.0,
) -> BillingEstimate:
    """Estimate an incremental 2026 bill using the official TTC tiers.

    ``starting_annual_volume_m3`` represents the volume already billed in the
    tariff year. It matters because only the potable-water part of the first
    12 m³ is free, and the third tier starts above 180 m³.
    """
    volume = _safe_volume(volume_m3)
    start = _safe_volume(starting_annual_volume_m3)
    potable = _official_2026_potable_total(start + volume) - _official_2026_potable_total(start)
    other = volume * OFFICIAL_2026_OTHER_VARIABLE_TTC_M3
    variable = round(potable + other, 2)
    fixed_value = float(fixed_eur)
    fixed = round(fixed_value, 2) if math.isfinite(fixed_value) and fixed_value >= 0 else 0.0
    total = round(variable + fixed, 2)
    return BillingEstimate(
        variable_eur=variable,
        fixed_eur=fixed,
        total_eur=total,
        volume_m3=volume,
        effective_rate_eur_m3=round(total / volume, 6) if volume else None,
        source="official_2026",
    )


def official_2026_subscription(calibre: object) -> tuple[float, str]:
    """Return annual TTC subscription for a meter calibre.

    The API commonly returns values such as ``15`` or ``DN15``. A standard
    domestic 15 mm meter is used as an explicit fallback when no calibre is
    available.
    """
    match = re.search(r"\d+", str(calibre or ""))
    diameter = int(match.group()) if match else 15
    if diameter in OFFICIAL_2026_SUBSCRIPTIONS_TTC:
        source = f"official_2026_dn{diameter}"
        if not match:
            source += "_assumed"
        return OFFICIAL_2026_SUBSCRIPTIONS_TTC[diameter], source
    return OFFICIAL_2026_SUBSCRIPTIONS_TTC[15], "official_2026_dn15_fallback"
