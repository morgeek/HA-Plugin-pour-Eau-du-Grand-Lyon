"""Tests for sensors/consumption.py — native_value and availability logic."""
from unittest.mock import MagicMock

from custom_components.eau_grand_lyon.sensors.consumption import (
    EauGrandLyonConsommationSensor,
    EauGrandLyonConsommationAnnuelleSensor,
    EauGrandLyonYesterdaySensor,
    EauGrandLyonConso7JSensor,
    EauGrandLyonConso30JSensor,
    EauGrandLyonConsoMoyenne7JSensor,
    EauGrandLyonCompatibilitySensor,
    EauGrandLyonConsoAnnuelleRefSensor,
)


def _make_sensor(cls, contract_data, *args):
    coordinator = MagicMock()
    coordinator.data = {"contracts": {"REF1": contract_data}}
    entry = MagicMock()
    entry.entry_id = "test_entry"
    sensor = cls.__new__(cls)
    sensor.coordinator = coordinator
    sensor._entry = entry
    sensor._contract_ref = "REF1"
    sensor._attr_unique_id = f"test_entry_REF1_{cls.__name__}"
    for k, v in (args[0] if args else {}).items():
        setattr(sensor, k, v)
    return sensor


# ── EauGrandLyonConsommationSensor ────────────────────────────────────────────

class TestConsommationSensor:
    def test_courant(self):
        s = _make_sensor(EauGrandLyonConsommationSensor,
                         {"consommation_mois_courant": 8.5})
        s._period = "courant"
        assert s.native_value == 8.5

    def test_precedent(self):
        s = _make_sensor(EauGrandLyonConsommationSensor,
                         {"consommation_mois_precedent": 7.2})
        s._period = "precedent"
        assert s.native_value == 7.2

    def test_courant_missing_returns_none(self):
        s = _make_sensor(EauGrandLyonConsommationSensor, {})
        s._period = "courant"
        assert s.native_value is None

    def test_precedent_missing_returns_none(self):
        s = _make_sensor(EauGrandLyonConsommationSensor, {})
        s._period = "precedent"
        assert s.native_value is None


# ── EauGrandLyonConsommationAnnuelleSensor ────────────────────────────────────

class TestConsommationAnnuelleSensor:
    def test_normal(self):
        s = _make_sensor(EauGrandLyonConsommationAnnuelleSensor,
                         {"consommation_annuelle": 95.0})
        assert s.native_value == 95.0

    def test_missing_returns_none(self):
        s = _make_sensor(EauGrandLyonConsommationAnnuelleSensor, {})
        assert s.native_value is None


# ── EauGrandLyonYesterdaySensor ───────────────────────────────────────────────

class TestYesterdaySensor:
    def test_converts_m3_to_litres(self):
        s = _make_sensor(EauGrandLyonYesterdaySensor, {
            "consommations_journalieres": [
                {"date": "2026-04-26", "consommation_m3": 0.150},
            ]
        })
        assert s.native_value == 150.0

    def test_rounds_to_zero_decimal(self):
        s = _make_sensor(EauGrandLyonYesterdaySensor, {
            "consommations_journalieres": [
                {"date": "2026-04-26", "consommation_m3": 0.1234},
            ]
        })
        assert s.native_value == round(0.1234 * 1000, 0)

    def test_empty_daily_returns_none(self):
        s = _make_sensor(EauGrandLyonYesterdaySensor,
                         {"consommations_journalieres": []})
        assert s.native_value is None

    def test_missing_daily_returns_none(self):
        s = _make_sensor(EauGrandLyonYesterdaySensor, {})
        assert s.native_value is None

    def test_missing_consommation_m3_returns_none(self):
        s = _make_sensor(EauGrandLyonYesterdaySensor, {
            "consommations_journalieres": [{"date": "2026-04-26"}]
        })
        assert s.native_value is None

    def test_uses_last_entry(self):
        s = _make_sensor(EauGrandLyonYesterdaySensor, {
            "consommations_journalieres": [
                {"date": "2026-04-25", "consommation_m3": 0.100},
                {"date": "2026-04-26", "consommation_m3": 0.200},
            ]
        })
        assert s.native_value == 200.0


# ── EauGrandLyonConso7JSensor ─────────────────────────────────────────────────

class TestConso7JSensor:
    def test_normal(self):
        s = _make_sensor(EauGrandLyonConso7JSensor, {"consommation_7j": 1.05})
        assert s.native_value == 1.05

    def test_missing_returns_none(self):
        s = _make_sensor(EauGrandLyonConso7JSensor, {})
        assert s.native_value is None

    def test_enabled_by_default(self):
        assert EauGrandLyonConso7JSensor._attr_entity_registry_enabled_default is True


# ── EauGrandLyonConso30JSensor ────────────────────────────────────────────────

class TestConso30JSensor:
    def test_normal(self):
        s = _make_sensor(EauGrandLyonConso30JSensor, {"consommation_30j": 4.5})
        assert s.native_value == 4.5

    def test_missing_returns_none(self):
        s = _make_sensor(EauGrandLyonConso30JSensor, {})
        assert s.native_value is None

    def test_enabled_by_default(self):
        assert EauGrandLyonConso30JSensor._attr_entity_registry_enabled_default is True


# ── EauGrandLyonConsoMoyenne7JSensor ──────────────────────────────────────────

class TestConsoMoyenne7JSensor:
    def test_normal(self):
        s = _make_sensor(EauGrandLyonConsoMoyenne7JSensor,
                         {"conso_moyenne_7j_litres": 142.0})
        assert s.native_value == 142.0

    def test_missing_returns_none(self):
        s = _make_sensor(EauGrandLyonConsoMoyenne7JSensor, {})
        assert s.native_value is None


# ── EauGrandLyonCompatibilitySensor ──────────────────────────────────────────

class TestCompatibilitySensor:
    def test_teleo(self):
        s = _make_sensor(EauGrandLyonCompatibilitySensor,
                         {"teleo_compatible": True})
        assert "Téléo" in s.native_value

    def test_standard(self):
        s = _make_sensor(EauGrandLyonCompatibilitySensor,
                         {"teleo_compatible": False})
        assert "Standard" in s.native_value

    def test_missing_defaults_to_standard(self):
        s = _make_sensor(EauGrandLyonCompatibilitySensor, {})
        assert "Standard" in s.native_value

    def test_disabled_by_default(self):
        assert EauGrandLyonCompatibilitySensor._attr_entity_registry_enabled_default is False


# ── EauGrandLyonConsoAnnuelleRefSensor ────────────────────────────────────────

class TestConsoAnnuelleRefSensor:
    def test_normal(self):
        s = _make_sensor(EauGrandLyonConsoAnnuelleRefSensor,
                         {"conso_annuelle_ref_m3": 110.0})
        assert s.native_value == 110.0

    def test_missing_returns_none(self):
        s = _make_sensor(EauGrandLyonConsoAnnuelleRefSensor, {})
        assert s.native_value is None

    def test_disabled_by_default(self):
        assert EauGrandLyonConsoAnnuelleRefSensor._attr_entity_registry_enabled_default is False
