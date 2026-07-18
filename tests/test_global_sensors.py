"""Tests for global diagnostic sensor offline/cache attributes."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from custom_components.eau_grand_lyon.sensors.global_sensors import (
    EauGrandLyonHealthSensor,
    EauGrandLyonLastUpdateSensor,
)


def _make_global_sensor(sensor_cls, data: dict):
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.entry_id = "entry-1"
    sensor = sensor_cls.__new__(sensor_cls)
    sensor.coordinator = coordinator
    sensor._entry = entry
    return sensor


class TestLastUpdateSensor:
    def test_exposes_failure_context_and_cache_age(self):
        sensor = _make_global_sensor(
            EauGrandLyonLastUpdateSensor,
            {
                "last_error": "offline",
                "last_error_type": "NetworkError",
                "last_failure_time": datetime(2026, 4, 27, tzinfo=timezone.utc),
                "last_failure_reason": "offline",
                "cache_age_days": 7,
            },
        )
        attrs = sensor.extra_state_attributes
        assert attrs["dernière_erreur"] == "offline"
        assert attrs["type_erreur"] == "NetworkError"
        assert attrs["heure_dernier_echec"] is not None
        assert attrs["raison_dernier_echec"] == "offline"
        assert attrs["age_cache_jours"] == 7


class TestHealthSensor:
    def test_offline_attributes_include_cache_age(self):
        sensor = _make_global_sensor(
            EauGrandLyonHealthSensor,
            {
                "offline_mode": True,
                "offline_since": datetime(2026, 4, 25, tzinfo=timezone.utc),
                "cache_age_days": 5,
                "last_error": "blocked",
                "last_error_type": "WafBlockedError",
                "last_failure_time": datetime(2026, 4, 27, tzinfo=timezone.utc),
                "last_failure_reason": "blocked",
                "consecutive_failures": 3,
            },
        )
        assert sensor.native_value == "HORS-LIGNE"
        attrs = sensor.extra_state_attributes
        assert attrs["offline_mode"] is True
        assert attrs["cached_data_age_days"] == 5
        assert attrs["last_failure_reason"] == "blocked"
