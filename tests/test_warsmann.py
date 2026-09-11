"""Tests du calcul indicatif du seuil de consommation anormale."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.eau_grand_lyon.binary_sensor import EauGrandLyonWarsmannSensor
from custom_components.eau_grand_lyon.warsmann import (
    assess_daily,
    assess_monthly,
    assess_warsmann,
)


def test_monthly_assessment_uses_three_matching_years():
    history = [
        {"annee": 2023, "mois_index": 7, "consommation_m3": 10.0},
        {"annee": 2024, "mois_index": 7, "consommation_m3": 12.0},
        {"annee": 2025, "mois_index": 7, "consommation_m3": 8.0},
        {"annee": 2026, "mois_index": 7, "consommation_m3": 21.0},
    ]

    result = assess_monthly(history)

    assert result is not None
    assert result["average_m3"] == 10.0
    assert result["threshold_m3"] == 20.0
    assert result["eligible"] is True
    assert result["period"] == "2026-08"


def test_monthly_assessment_requires_all_three_matching_periods():
    history = [
        {"annee": 2024, "mois_index": 7, "consommation_m3": 12.0},
        {"annee": 2025, "mois_index": 7, "consommation_m3": 8.0},
        {"annee": 2026, "mois_index": 7, "consommation_m3": 30.0},
    ]
    assert assess_monthly(history) is None


def test_monthly_assessment_rejects_empty_and_invalid_history():
    assert assess_monthly([]) is None
    assert assess_monthly([{"annee": 2026, "mois_index": 12, "consommation_m3": -1}]) is None


def test_daily_assessment_uses_same_calendar_day():
    history = [
        {"date": "2023-08-31", "consommation_m3": 0.1},
        {"date": "2024-08-31", "consommation_m3": 0.2},
        {"date": "2025-08-31", "consommation_m3": 0.3},
        {"date": "2026-08-31", "consommation_m3": 0.4},
    ]
    result = assess_daily(history)
    assert result is not None
    assert result["basis"] == "daily"
    assert result["threshold_m3"] == 0.4
    assert result["eligible"] is False


def test_daily_assessment_rejects_bad_dates_values_and_leap_day():
    assert assess_daily([{"date": "bad", "consommation_m3": 2.0}]) is None
    assert assess_daily([{"date": "2026-01-01", "consommation_m3": "bad"}]) is None
    assert assess_daily([{"date": "2024-02-29", "consommation_m3": 2.0}]) is None


def test_assess_warsmann_selects_meter_granularity():
    monthly = [
        {"annee": year, "mois_index": 0, "consommation_m3": value}
        for year, value in ((2023, 1.0), (2024, 1.0), (2025, 1.0), (2026, 3.0))
    ]
    assert assess_warsmann(monthly, [], teleo=False) is not None
    assert assess_warsmann(monthly, [], teleo=True) is None


def _entity(assessment):
    coordinator = MagicMock()
    coordinator.data = {"contracts": {"REF1": {"warsmann_assessment": assessment}}}
    entry = MagicMock(entry_id="entry-1")
    sensor = EauGrandLyonWarsmannSensor.__new__(EauGrandLyonWarsmannSensor)
    sensor.coordinator = coordinator
    sensor._entry = entry
    sensor._contract_ref = "REF1"
    return sensor


def test_warsmann_entity_is_disabled_and_unavailable_without_history():
    sensor = _entity(None)
    assert EauGrandLyonWarsmannSensor._attr_entity_registry_enabled_default is False
    assert sensor.available is False
    assert sensor.is_on is False
    assert "Trois périodes" in sensor.extra_state_attributes["historique_requis"]


def test_warsmann_entity_exposes_explainable_result():
    assessment = {
        "average_m3": 10.0,
        "basis": "monthly",
        "eligible": True,
        "historical_periods": ["2025-08", "2024-08", "2023-08"],
        "historical_values_m3": [8.0, 12.0, 10.0],
        "observed_m3": 21.0,
        "period": "2026-08",
        "threshold_m3": 20.0,
    }
    sensor = _entity(assessment)
    assert sensor.available is True
    assert sensor.is_on is True
    assert sensor.extra_state_attributes["seuil_double_m3"] == 20.0
