"""Tests for sensors/experimental.py — availability guards and state logic."""
from unittest.mock import MagicMock

from custom_components.eau_grand_lyon.sensors.experimental import (
    EauGrandLyonDerniereFactureSensor,
    EauGrandLyonFuiteEstimeeSensor,
    EauGrandLyonHourlyConsoSensor,
    EauGrandLyonPeakHourSensor,
    EauGrandLyonAvgFlowSensor,
)


def _make(cls, contract_data, contract_ref="REF1", available=True):
    coordinator = MagicMock()
    coordinator.data = {"contracts": {contract_ref: contract_data}}
    entry = MagicMock()
    entry.entry_id = "test_entry"
    sensor = cls.__new__(cls)
    sensor.coordinator = coordinator
    sensor._entry = entry
    sensor._contract_ref = contract_ref
    sensor._attr_unique_id = f"test_{cls.__name__}"
    sensor._attr_available = available
    return sensor


# ── EauGrandLyonDerniereFactureSensor ─────────────────────────────────────────

class TestDerniereFactureSensor:
    def test_available_when_facture_present(self):
        s = _make(EauGrandLyonDerniereFactureSensor, {
            "derniere_facture": {"montant_ttc": 42.5}
        })
        assert s.available is True

    def test_unavailable_when_no_facture(self):
        s = _make(EauGrandLyonDerniereFactureSensor, {})
        assert s.available is False

    def test_native_value(self):
        s = _make(EauGrandLyonDerniereFactureSensor, {
            "derniere_facture": {"montant_ttc": 67.80}
        })
        assert s.native_value == 67.80

    def test_none_when_facture_missing(self):
        s = _make(EauGrandLyonDerniereFactureSensor, {})
        assert s.native_value is None

    def test_disabled_by_default(self):
        assert EauGrandLyonDerniereFactureSensor._attr_entity_registry_enabled_default is False

    def test_extra_attrs_nb_factures(self):
        s = _make(EauGrandLyonDerniereFactureSensor, {
            "derniere_facture": {"montant_ttc": 42.5, "reference": "F001"},
            "factures": [{"reference": "F001"}, {"reference": "F002"}],
        })
        assert s.extra_state_attributes["nb_factures_total"] == 2

    def test_extra_attrs_historique_capped_12(self):
        factures = [{"reference": f"F{i:03d}", "montant_ttc": i} for i in range(20)]
        s = _make(EauGrandLyonDerniereFactureSensor, {
            "derniere_facture": {"montant_ttc": 10.0},
            "factures": factures,
        })
        assert len(s.extra_state_attributes["historique_factures"]) == 12


# ── EauGrandLyonFuiteEstimeeSensor ────────────────────────────────────────────

class TestFuiteEstimeeSensor:
    def test_available_when_data_present(self):
        s = _make(EauGrandLyonFuiteEstimeeSensor, {"fuite_estime_30j_m3": 0.5})
        assert s.available is True

    def test_unavailable_when_none(self):
        s = _make(EauGrandLyonFuiteEstimeeSensor, {"fuite_estime_30j_m3": None})
        assert s.available is False

    def test_unavailable_when_missing(self):
        s = _make(EauGrandLyonFuiteEstimeeSensor, {})
        assert s.available is False

    def test_native_value(self):
        s = _make(EauGrandLyonFuiteEstimeeSensor, {"fuite_estime_30j_m3": 1.234})
        assert s.native_value == 1.234

    def test_disabled_by_default(self):
        assert EauGrandLyonFuiteEstimeeSensor._attr_entity_registry_enabled_default is False

    def test_extra_attrs_capped_14_days(self):
        daily = [
            {"date": f"2026-01-{i+1:02d}", "volume_fuite_estime_m3": 0.1}
            for i in range(20)
        ]
        s = _make(EauGrandLyonFuiteEstimeeSensor, {
            "fuite_estime_30j_m3": 2.0,
            "consommations_journalieres": daily,
        })
        detail = s.extra_state_attributes["détail_journalier"]
        assert len(detail) <= 14


# ── EauGrandLyonHourlyConsoSensor ─────────────────────────────────────────────

class TestHourlyConsoSensor:
    def test_returns_last_hour(self):
        s = _make(EauGrandLyonHourlyConsoSensor, {"consommation_derniere_heure_m3": 0.012})
        assert s.native_value == 0.012

    def test_none_when_missing(self):
        s = _make(EauGrandLyonHourlyConsoSensor, {})
        assert s.native_value is None


# ── EauGrandLyonPeakHourSensor ───────────────────────────────────────────────

class TestPeakHourSensor:
    def test_returns_peak_hour(self):
        s = _make(EauGrandLyonPeakHourSensor, {"heure_pic": "07:30"})
        assert s.native_value == "07:30"

    def test_none_when_missing(self):
        s = _make(EauGrandLyonPeakHourSensor, {})
        assert s.native_value is None


# ── EauGrandLyonAvgFlowSensor ────────────────────────────────────────────────

class TestAvgFlowSensor:
    def test_returns_flow(self):
        s = _make(EauGrandLyonAvgFlowSensor, {"debit_moyen_m3h": 0.0034})
        assert s.native_value == 0.0034

    def test_none_when_missing(self):
        s = _make(EauGrandLyonAvgFlowSensor, {})
        assert s.native_value is None
