"""Tests for transparent invoice and official-tariff calculations."""

import pytest

from custom_components.eau_grand_lyon.billing import (
    OFFICIAL_2026_OTHER_VARIABLE_TTC_M3,
    OFFICIAL_2026_TIER_2_TOTAL_TTC_M3,
    effective_invoice_rate,
    linear_estimate,
    official_2026_estimate,
    official_2026_subscription,
)


def test_anonymized_real_invoice_reference_totals_328_42():
    """88 m³ all in tier 2 plus the prorated fixed part totals €328.42."""
    estimate = official_2026_estimate(
        88,
        fixed_eur=25.41,
        starting_annual_volume_m3=12,
    )

    assert estimate.variable_eur == 303.01
    assert estimate.fixed_eur == 25.41
    assert estimate.total_eur == 328.42
    assert estimate.effective_rate_eur_m3 == pytest.approx(3.732045, abs=0.000001)


def test_first_twelve_cubic_metres_only_exempt_potable_component():
    estimate = official_2026_estimate(12)
    assert estimate.variable_eur == round(12 * OFFICIAL_2026_OTHER_VARIABLE_TTC_M3, 2)


def test_tier_two_rate_applies_after_vital_allowance():
    estimate = official_2026_estimate(10, starting_annual_volume_m3=12)
    assert estimate.variable_eur == round(10 * OFFICIAL_2026_TIER_2_TOTAL_TTC_M3, 2)


def test_official_120_m3_reference_rounds_to_published_average():
    estimate = official_2026_estimate(120, fixed_eur=50.66)
    assert estimate.total_eur == 447.14
    assert round(estimate.total_eur / 120, 2) == 3.73


def test_invoice_rate_uses_real_ttc_and_volume():
    assert effective_invoice_rate({"montant_ttc": 328.42, "volume_m3": 88}) == pytest.approx(3.73204545)
    assert effective_invoice_rate({"montant_ttc": 328.42, "volume_m3": 0}) is None
    assert effective_invoice_rate({"montant_ttc": float("nan"), "volume_m3": 88}) is None
    assert effective_invoice_rate({"montant_ttc": "invalid", "volume_m3": 88}) is None
    assert effective_invoice_rate(None) is None


def test_linear_estimate_keeps_variable_and_fixed_parts_separate():
    estimate = linear_estimate(88, 3.4433, 25.41, source="invoice_fixture")
    assert estimate.variable_eur == 303.01
    assert estimate.total_eur == 328.42
    assert estimate.as_dict()["source"] == "invoice_fixture"


def test_non_finite_inputs_are_safely_zeroed():
    estimate = linear_estimate(float("nan"), float("inf"), float("nan"), source="test")
    assert estimate.total_eur == 0
    assert estimate.effective_rate_eur_m3 is None


def test_invalid_volume_type_is_safely_zeroed():
    estimate = linear_estimate("not-a-number", 3.5, source="invalid_fixture")
    assert estimate.volume_m3 == 0
    assert estimate.total_eur == 0


@pytest.mark.parametrize(
    ("calibre", "amount", "source"),
    [
        ("DN15", 50.66, "official_2026_dn15"),
        (20, 242.87, "official_2026_dn20"),
        (None, 50.66, "official_2026_dn15_assumed"),
        ("DN17", 50.66, "official_2026_dn15_fallback"),
    ],
)
def test_subscription_uses_meter_diameter_with_explicit_fallback(calibre, amount, source):
    assert official_2026_subscription(calibre) == (amount, source)
