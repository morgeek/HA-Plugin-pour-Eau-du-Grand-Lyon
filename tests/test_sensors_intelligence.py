"""Tests for sensors/intelligence.py — eco_score, CO2, trend, coaching, limescale."""

from unittest.mock import MagicMock

from custom_components.eau_grand_lyon.sensors.intelligence import (
    EauGrandLyonTrendSensor,
    EauGrandLyonEcoScoreSensor,
    EauGrandLyonCO2FootprintSensor,
    EauGrandLyonLimescaleSensor,
    EauGrandLyonCoachingSensor,
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


# ── EauGrandLyonTrendSensor ───────────────────────────────────────────────────


class TestTrendSensor:
    def test_positive_trend(self):
        s = _make_sensor(EauGrandLyonTrendSensor, {"tendance_n1_pct": 12.5})
        assert s.native_value == 12.5

    def test_negative_trend(self):
        s = _make_sensor(EauGrandLyonTrendSensor, {"tendance_n1_pct": -8.3})
        assert s.native_value == -8.3

    def test_missing_returns_none(self):
        s = _make_sensor(EauGrandLyonTrendSensor, {})
        assert s.native_value is None

    def test_extra_attributes(self):
        s = _make_sensor(
            EauGrandLyonTrendSensor,
            {
                "tendance_n1_pct": 10.0,
                "consommation_mois_courant": 8.0,
                "consommation_n1": 7.2,
                "label_n1": "avril 2025",
            },
        )
        attrs = s.extra_state_attributes
        assert attrs["conso_actuelle"] == 8.0
        assert attrs["conso_n1"] == 7.2
        assert attrs["mois_n1"] == "avril 2025"


# ── EauGrandLyonEcoScoreSensor ────────────────────────────────────────────────


class TestEcoScoreSensor:
    def test_grade_a(self):
        s = _make_sensor(EauGrandLyonEcoScoreSensor, {"eco_score_grade": "A"})
        assert s.native_value == "a"

    def test_grade_g(self):
        s = _make_sensor(EauGrandLyonEcoScoreSensor, {"eco_score_grade": "G"})
        assert s.native_value == "g"

    def test_missing_returns_default(self):
        s = _make_sensor(EauGrandLyonEcoScoreSensor, {})
        assert s.native_value == "unknown"

    def test_extra_attributes_m3_per_person(self):
        s = _make_sensor(
            EauGrandLyonEcoScoreSensor,
            {
                "eco_score_grade": "B",
                "eco_score_m3_pers": 2.5,
            },
        )
        attrs = s.extra_state_attributes
        assert attrs["m3_par_personne"] == 2.5


# ── EauGrandLyonCO2FootprintSensor ───────────────────────────────────────────


class TestCO2FootprintSensor:
    def test_normal(self):
        s = _make_sensor(EauGrandLyonCO2FootprintSensor, {"co2_footprint_kg": 3.14})
        assert s.native_value == 3.14

    def test_zero(self):
        s = _make_sensor(EauGrandLyonCO2FootprintSensor, {"co2_footprint_kg": 0.0})
        assert s.native_value == 0.0

    def test_missing_returns_none(self):
        s = _make_sensor(EauGrandLyonCO2FootprintSensor, {})
        assert s.native_value is None


# ── EauGrandLyonLimescaleSensor ───────────────────────────────────────────────


class TestLimescaleSensor:
    def test_normal(self):
        s = _make_sensor(EauGrandLyonLimescaleSensor, {"limescale_g": 85.5})
        assert s.native_value == 85.5

    def test_missing_returns_none(self):
        s = _make_sensor(EauGrandLyonLimescaleSensor, {})
        assert s.native_value is None


# ── EauGrandLyonCoachingSensor ────────────────────────────────────────────────


class TestCoachingSensor:
    def test_grade_a_returns_excellent(self):
        s = _make_sensor(EauGrandLyonCoachingSensor, {"eco_score_grade": "A"})
        assert "Excellent" in s.native_value

    def test_grade_b_returns_bonne(self):
        s = _make_sensor(EauGrandLyonCoachingSensor, {"eco_score_grade": "B"})
        assert "Bonne" in s.native_value

    def test_high_trend_returns_warning(self):
        s = _make_sensor(
            EauGrandLyonCoachingSensor,
            {
                "eco_score_grade": "C",
                "tendance_n1_pct": 25.0,
            },
        )
        assert "bondi" in s.native_value

    def test_leak_pattern_returns_alert(self):
        s = _make_sensor(
            EauGrandLyonCoachingSensor,
            {
                "eco_score_grade": "C",
                "tendance_n1_pct": 5.0,
                "local_leak_pattern": True,
            },
        )
        assert "Alerte" in s.native_value

    def test_grade_fg_returns_high_consumption(self):
        s = _make_sensor(EauGrandLyonCoachingSensor, {"eco_score_grade": "F"})
        assert "élevée" in s.native_value

    def test_default_returns_stable_message(self):
        s = _make_sensor(
            EauGrandLyonCoachingSensor,
            {
                "eco_score_grade": "C",
                "tendance_n1_pct": 5.0,
            },
        )
        assert isinstance(s.native_value, str)
        assert len(s.native_value) > 0

    def test_none_trend_does_not_crash(self):
        """Regression: the coordinator always sets tendance_n1_pct, often to None.

        `c.get("tendance_n1_pct", 0)` therefore returned None and `None > 20`
        raised TypeError on every state write for grades C-G without N-1 data.
        """
        s = _make_sensor(
            EauGrandLyonCoachingSensor,
            {
                "eco_score_grade": "C",
                "tendance_n1_pct": None,
            },
        )
        assert isinstance(s.native_value, str)
        assert len(s.native_value) > 0
