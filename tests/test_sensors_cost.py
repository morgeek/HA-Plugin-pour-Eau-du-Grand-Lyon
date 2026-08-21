"""Tests for sensors/cost.py — native_value calculations."""
from unittest.mock import MagicMock

import pytest

from custom_components.eau_grand_lyon.sensors.cost import (
    EauGrandLyonCoutCumuleSensor,
    EauGrandLyonEconomieSensor,
    EauGrandLyonCoutReelMoisSensor,
    EauGrandLyonCoutReelAnnuelSensor,
)


def _make_sensor(cls, contract_data):
    coordinator = MagicMock()
    coordinator.data = {"contracts": {"REF1": contract_data}}
    entry = MagicMock()
    entry.entry_id = "test_entry"
    sensor = cls.__new__(cls)
    sensor.coordinator = coordinator
    sensor._entry = entry
    sensor._contract_ref = "REF1"
    sensor._attr_unique_id = f"test_entry_REF1_{cls.__name__}"
    return sensor


# ── EauGrandLyonCoutCumuleSensor ──────────────────────────────────────────────

class TestCoutCumuleSensor:
    def test_normal(self):
        s = _make_sensor(EauGrandLyonCoutCumuleSensor, {
            "consommation_cumulee_annee": 20.0,
            "tarif_m3": 5.20,
        })
        assert s.native_value == round(20.0 * 5.20, 2)

    def test_zero_conso_returns_zero(self):
        s = _make_sensor(EauGrandLyonCoutCumuleSensor, {
            "consommation_cumulee_annee": 0,
            "tarif_m3": 5.20,
        })
        assert s.native_value == 0.0

    def test_missing_tarif_returns_none(self):
        s = _make_sensor(EauGrandLyonCoutCumuleSensor, {
            "consommation_cumulee_annee": 20.0,
        })
        assert s.native_value is None

    def test_missing_conso_returns_zero(self):
        s = _make_sensor(EauGrandLyonCoutCumuleSensor, {"tarif_m3": 5.20})
        assert s.native_value == 0.0

    def test_rounding(self):
        s = _make_sensor(EauGrandLyonCoutCumuleSensor, {
            "consommation_cumulee_annee": 3.333,
            "tarif_m3": 3.0,
        })
        assert s.native_value == round(3.333 * 3.0, 2)


# ── EauGrandLyonEconomieSensor ────────────────────────────────────────────────

class TestEconomieSensor:
    def test_economy_positive(self):
        s = _make_sensor(EauGrandLyonEconomieSensor, {
            "consommation_annuelle_n1": 120.0,
            "consommation_annuelle": 100.0,
            "tarif_m3": 5.0,
        })
        assert s.native_value == round((120.0 - 100.0) * 5.0, 2)

    def test_economy_negative(self):
        s = _make_sensor(EauGrandLyonEconomieSensor, {
            "consommation_annuelle_n1": 80.0,
            "consommation_annuelle": 100.0,
            "tarif_m3": 5.0,
        })
        assert s.native_value == round((80.0 - 100.0) * 5.0, 2)

    def test_economy_zero(self):
        s = _make_sensor(EauGrandLyonEconomieSensor, {
            "consommation_annuelle_n1": 100.0,
            "consommation_annuelle": 100.0,
            "tarif_m3": 5.0,
        })
        assert s.native_value == 0.0

    def test_missing_n1_returns_none(self):
        s = _make_sensor(EauGrandLyonEconomieSensor, {
            "consommation_annuelle": 100.0,
            "tarif_m3": 5.0,
        })
        assert s.native_value is None

    def test_missing_tarif_returns_none(self):
        s = _make_sensor(EauGrandLyonEconomieSensor, {
            "consommation_annuelle_n1": 120.0,
            "consommation_annuelle": 100.0,
        })
        assert s.native_value is None

    def test_zero_tarif_returns_none(self):
        s = _make_sensor(EauGrandLyonEconomieSensor, {
            "consommation_annuelle_n1": 120.0,
            "consommation_annuelle": 100.0,
            "tarif_m3": 0,
        })
        assert s.native_value is None


# ── EauGrandLyonCoutReelMoisSensor ────────────────────────────────────────────

class TestCoutReelMoisSensor:
    def test_returns_coordinator_value(self):
        s = _make_sensor(EauGrandLyonCoutReelMoisSensor, {"cout_reel_mois": 45.50})
        assert s.native_value == 45.50

    def test_missing_returns_none(self):
        s = _make_sensor(EauGrandLyonCoutReelMoisSensor, {})
        assert s.native_value is None

    def test_extra_attributes_subscription(self):
        s = _make_sensor(EauGrandLyonCoutReelMoisSensor, {
            "cout_reel_mois": 45.50,
            "cout_mois_courant_eur": 30.0,
            "subscription_annual": 180.0,
            "tarif_m3": 5.20,
        })
        attrs = s.extra_state_attributes
        assert attrs["part_fixe_eur"] == round(180.0 / 12, 2)
        assert attrs["part_variable_eur"] == 30.0
        assert attrs["abonnement_annuel"] == 180.0
        assert attrs["inclut_abonnement"] is True


# ── EauGrandLyonCoutReelAnnuelSensor ─────────────────────────────────────────

class TestCoutReelAnnuelSensor:
    def test_returns_coordinator_value(self):
        s = _make_sensor(EauGrandLyonCoutReelAnnuelSensor, {"cout_reel_annuel": 540.0})
        assert s.native_value == 540.0

    def test_missing_returns_none(self):
        s = _make_sensor(EauGrandLyonCoutReelAnnuelSensor, {})
        assert s.native_value is None


def test_monetary_sensors_never_use_total_increasing():
    """HA forbids state_class TOTAL_INCREASING with device_class MONETARY (None or TOTAL only)."""
    import inspect as _inspect
    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
    import custom_components.eau_grand_lyon.sensors.cost as cost_mod

    monetary = [
        (name, cls)
        for name, cls in _inspect.getmembers(cost_mod, _inspect.isclass)
        if getattr(cls, "_attr_device_class", None) is SensorDeviceClass.MONETARY
    ]
    assert monetary, "expected at least one monetary sensor"
    for name, cls in monetary:
        state_class = getattr(cls, "_attr_state_class", None)
        assert state_class is not SensorStateClass.TOTAL_INCREASING, (
            f"{name} uses TOTAL_INCREASING with MONETARY device_class"
        )
