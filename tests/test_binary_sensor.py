"""Tests for binary_sensor.py — entity availability and state logic."""
from unittest.mock import MagicMock

from custom_components.eau_grand_lyon.binary_sensor import (
    EauGrandLyonLeakAlertSensor,
    EauGrandLyonRealTimeLeakSensor,
    EauGrandLyonLocalLeakSensor,
    EauGrandLyonBatterySensor,
    EauGrandLyonLimescaleAlertSensor,
    EauGrandLyonOutageSensor,
)


def _make_binary_sensor(cls, coordinator_data, contract_ref="REF1"):
    """Helper to create a binary sensor with mocked coordinator."""
    coordinator = MagicMock()
    coordinator.data = coordinator_data
    entry = MagicMock()
    entry.entry_id = "test_entry"

    if issubclass(cls, EauGrandLyonOutageSensor):
        sensor = cls.__new__(cls)
        sensor.coordinator = coordinator
        sensor._entry = entry
    else:
        sensor = cls.__new__(cls)
        sensor.coordinator = coordinator
        sensor._entry = entry
        sensor._contract_ref = contract_ref
        # Mock parent class's available property
        sensor._attr_available = True

    return sensor


# ── EauGrandLyonLeakAlertSensor ──────────────────────────────────────────────

class TestLeakAlertSensor:
    def test_alert_when_current_exceeds_double_previous(self):
        s = _make_binary_sensor(EauGrandLyonLeakAlertSensor, {
            "contracts": {
                "REF1": {
                    "consommation_mois_courant": 20.0,
                    "consommation_mois_precedent": 8.0,
                }
            }
        })
        assert s.is_on is True

    def test_no_alert_when_within_threshold(self):
        s = _make_binary_sensor(EauGrandLyonLeakAlertSensor, {
            "contracts": {
                "REF1": {
                    "consommation_mois_courant": 15.0,
                    "consommation_mois_precedent": 10.0,
                }
            }
        })
        assert s.is_on is False

    def test_no_alert_when_missing_data(self):
        s = _make_binary_sensor(EauGrandLyonLeakAlertSensor, {"contracts": {"REF1": {}}})
        assert s.is_on is False


# ── EauGrandLyonRealTimeLeakSensor ──────────────────────────────────────────

class TestRealTimeLeakSensor:
    def test_alert_when_leak_detected(self):
        s = _make_binary_sensor(EauGrandLyonRealTimeLeakSensor, {
            "contracts": {"REF1": {"fuite_estime_30j_m3": 5.0}},
            "experimental_mode": True,
        })
        assert s.is_on is True

    def test_no_alert_when_no_leak(self):
        s = _make_binary_sensor(EauGrandLyonRealTimeLeakSensor, {
            "contracts": {"REF1": {"fuite_estime_30j_m3": 0.0}},
            "experimental_mode": True,
        })
        assert s.is_on is False

    def test_no_leak_when_value_is_none(self):
        s = _make_binary_sensor(EauGrandLyonRealTimeLeakSensor, {
            "contracts": {"REF1": {"fuite_estime_30j_m3": None}},
            "experimental_mode": True,
        })
        assert s.is_on is False


# ── EauGrandLyonLocalLeakSensor ──────────────────────────────────────────────

class TestLocalLeakSensor:
    def test_alert_when_pattern_detected(self):
        s = _make_binary_sensor(EauGrandLyonLocalLeakSensor, {
            "contracts": {"REF1": {"local_leak_pattern": True}}
        })
        assert s.is_on is True

    def test_no_alert_when_pattern_not_detected(self):
        s = _make_binary_sensor(EauGrandLyonLocalLeakSensor, {
            "contracts": {"REF1": {"local_leak_pattern": False}}
        })
        assert s.is_on is False


# ── EauGrandLyonBatterySensor ───────────────────────────────────────────────

class TestBatterySensor:
    def test_alert_when_battery_low(self):
        s = _make_binary_sensor(EauGrandLyonBatterySensor, {
            "contracts": {"REF1": {"battery_ok": False}}
        })
        assert s.is_on is True

    def test_no_alert_when_battery_ok(self):
        s = _make_binary_sensor(EauGrandLyonBatterySensor, {
            "contracts": {"REF1": {"battery_ok": True}}
        })
        assert s.is_on is False


# ── EauGrandLyonLimescaleAlertSensor ────────────────────────────────────────

class TestLimescaleAlertSensor:
    def test_alert_when_threshold_exceeded(self):
        s = _make_binary_sensor(EauGrandLyonLimescaleAlertSensor, {
            "contracts": {"REF1": {"limescale_alert": True}}
        })
        assert s.is_on is True

    def test_no_alert_when_below_threshold(self):
        s = _make_binary_sensor(EauGrandLyonLimescaleAlertSensor, {
            "contracts": {"REF1": {"limescale_alert": False}}
        })
        assert s.is_on is False


# ── EauGrandLyonOutageSensor ────────────────────────────────────────────────

class TestOutageSensor:
    def test_alert_when_interruption_upcoming_in_48h(self):
        from datetime import date, timedelta
        today = date.today()
        tomorrow = today + timedelta(days=1)

        s = _make_binary_sensor(EauGrandLyonOutageSensor, {
            "interruptions": [
                {
                    "date_debut": tomorrow.isoformat(),
                    "date_fin": (tomorrow + timedelta(hours=4)).isoformat(),
                }
            ]
        })
        assert s.is_on is True

    def test_no_alert_when_interruption_beyond_48h(self):
        from datetime import date, timedelta
        today = date.today()
        future = today + timedelta(days=3)

        s = _make_binary_sensor(EauGrandLyonOutageSensor, {
            "interruptions": [
                {
                    "date_debut": future.isoformat(),
                    "date_fin": (future + timedelta(hours=4)).isoformat(),
                }
            ]
        })
        assert s.is_on is False

    def test_no_alert_when_no_interruptions(self):
        s = _make_binary_sensor(EauGrandLyonOutageSensor, {"interruptions": []})
        assert s.is_on is False
