"""Tests for sensors/quality.py — water quality sensors."""
from unittest.mock import MagicMock

from custom_components.eau_grand_lyon.sensors.quality import (
    EauGrandLyonWaterHardnessSensor,
    EauGrandLyonNitratesSensor,
    EauGrandLyonChloreSensor,
)


def _make_quality_sensor(cls, water_quality_data):
    coordinator = MagicMock()
    coordinator.data = {"water_quality": water_quality_data}
    entry = MagicMock()
    entry.entry_id = "test_entry"
    sensor = cls.__new__(cls)
    sensor.coordinator = coordinator
    sensor._entry = entry
    sensor._attr_unique_id = f"test_entry_{cls.__name__}"
    return sensor


# ── EauGrandLyonWaterHardnessSensor ───────────────────────────────────────────

class TestWaterHardnessSensor:
    def test_normal(self):
        s = _make_quality_sensor(EauGrandLyonWaterHardnessSensor,
                                 {"durete_fh": 28.5})
        assert s.native_value == 28.5

    def test_missing_returns_none(self):
        s = _make_quality_sensor(EauGrandLyonWaterHardnessSensor, {})
        assert s.native_value is None

    def test_no_water_quality_data_returns_none(self):
        s = _make_quality_sensor(EauGrandLyonWaterHardnessSensor, {})
        s.coordinator.data = {}
        assert s.native_value is None

    def test_enabled_by_default(self):
        from custom_components.eau_grand_lyon.sensors.base import _EauGrandLyonWaterQualityBase
        assert _EauGrandLyonWaterQualityBase._attr_entity_registry_enabled_default is True

    def test_extra_attributes_contains_turbidity(self):
        s = _make_quality_sensor(EauGrandLyonWaterHardnessSensor,
                                 {"durete_fh": 28.5, "turbidite_ntu": 0.3})
        attrs = s.extra_state_attributes
        assert attrs["turbidite_ntu"] == 0.3


# ── EauGrandLyonNitratesSensor ────────────────────────────────────────────────

class TestNitratesSensor:
    def test_normal(self):
        s = _make_quality_sensor(EauGrandLyonNitratesSensor,
                                 {"nitrates_mgl": 12.4})
        assert s.native_value == 12.4

    def test_missing_returns_none(self):
        s = _make_quality_sensor(EauGrandLyonNitratesSensor, {})
        assert s.native_value is None

    def test_icon_safe_level(self):
        s = _make_quality_sensor(EauGrandLyonNitratesSensor, {"nitrates_mgl": 5.0})
        assert s.icon == "mdi:flask"

    def test_icon_moderate_level(self):
        s = _make_quality_sensor(EauGrandLyonNitratesSensor, {"nitrates_mgl": 15.0})
        assert s.icon == "mdi:flask-empty-outline"

    def test_icon_high_level(self):
        s = _make_quality_sensor(EauGrandLyonNitratesSensor, {"nitrates_mgl": 30.0})
        assert s.icon == "mdi:alert-circle-outline"

    def test_icon_critical_level(self):
        s = _make_quality_sensor(EauGrandLyonNitratesSensor, {"nitrates_mgl": 55.0})
        assert s.icon == "mdi:alert-circle"

    def test_icon_missing_data(self):
        s = _make_quality_sensor(EauGrandLyonNitratesSensor, {})
        assert s.icon == "mdi:flask-outline"

    def test_extra_attributes_has_threshold(self):
        s = _make_quality_sensor(EauGrandLyonNitratesSensor, {"nitrates_mgl": 12.0})
        attrs = s.extra_state_attributes
        assert attrs["seuil_oms_mgl"] == 50


# ── EauGrandLyonChloreSensor ──────────────────────────────────────────────────

class TestChloreSensor:
    def test_normal(self):
        s = _make_quality_sensor(EauGrandLyonChloreSensor,
                                 {"chlore_mgl": 0.15})
        assert s.native_value == 0.15

    def test_zero(self):
        s = _make_quality_sensor(EauGrandLyonChloreSensor, {"chlore_mgl": 0.0})
        assert s.native_value == 0.0

    def test_missing_returns_none(self):
        s = _make_quality_sensor(EauGrandLyonChloreSensor, {})
        assert s.native_value is None
