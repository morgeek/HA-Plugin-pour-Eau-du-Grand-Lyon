"""Tests for sensors/contract.py — date parsing, state and availability logic."""
from datetime import date
from unittest.mock import MagicMock

from custom_components.eau_grand_lyon.sensors.contract import (
    EauGrandLyonStatutSensor,
    EauGrandLyonDateEcheanceSensor,
    EauGrandLyonProchaineFactureSensor,
    EauGrandLyonProchaineReleveSensor,
)


def _make(cls, contract_data, contract_ref="REF1"):
    coordinator = MagicMock()
    coordinator.data = {"contracts": {contract_ref: contract_data}}
    entry = MagicMock()
    entry.entry_id = "test_entry"
    sensor = cls.__new__(cls)
    sensor.coordinator = coordinator
    sensor._entry = entry
    sensor._contract_ref = contract_ref
    sensor._attr_unique_id = f"test_{cls.__name__}"
    return sensor


# ── EauGrandLyonStatutSensor ──────────────────────────────────────────────────

class TestStatutSensor:
    def test_returns_statut(self):
        s = _make(EauGrandLyonStatutSensor, {"statut": "ACTIF"})
        assert s.native_value == "ACTIF"

    def test_none_when_missing(self):
        s = _make(EauGrandLyonStatutSensor, {})
        assert s.native_value is None

    def test_extra_attrs_present(self):
        s = _make(EauGrandLyonStatutSensor, {
            "statut": "ACTIF",
            "reference": "REF-123",
            "usage": "Habitation",
        })
        attrs = s.extra_state_attributes
        assert "référence" in attrs
        assert "usage" in attrs


# ── EauGrandLyonDateEcheanceSensor ────────────────────────────────────────────

class TestDateEcheanceSensor:
    def test_valid_iso_date(self):
        s = _make(EauGrandLyonDateEcheanceSensor, {"date_echeance": "2027-12-31"})
        assert s.native_value == date(2027, 12, 31)

    def test_invalid_date_returns_none(self):
        s = _make(EauGrandLyonDateEcheanceSensor, {"date_echeance": "not-a-date"})
        assert s.native_value is None

    def test_missing_returns_none(self):
        s = _make(EauGrandLyonDateEcheanceSensor, {})
        assert s.native_value is None

    def test_empty_string_returns_none(self):
        s = _make(EauGrandLyonDateEcheanceSensor, {"date_echeance": ""})
        assert s.native_value is None


# ── EauGrandLyonProchaineFactureSensor ────────────────────────────────────────

class TestProchaineFactureSensor:
    def test_valid_date(self):
        s = _make(EauGrandLyonProchaineFactureSensor, {"next_bill_date": "2026-09-15"})
        assert s.native_value == date(2026, 9, 15)

    def test_invalid_date_returns_none(self):
        s = _make(EauGrandLyonProchaineFactureSensor, {"next_bill_date": "???"})
        assert s.native_value is None

    def test_missing_returns_none(self):
        s = _make(EauGrandLyonProchaineFactureSensor, {})
        assert s.native_value is None


# ── EauGrandLyonProchaineReleveSensor ─────────────────────────────────────────

class TestProchaineReleveSensor:
    def test_valid_date(self):
        s = _make(EauGrandLyonProchaineReleveSensor, {"date_prochaine_releve": "2026-10-01"})
        assert s.native_value == date(2026, 10, 1)

    def test_invalid_date_returns_none(self):
        s = _make(EauGrandLyonProchaineReleveSensor, {"date_prochaine_releve": "invalid"})
        assert s.native_value is None

    def test_missing_returns_none(self):
        s = _make(EauGrandLyonProchaineReleveSensor, {})
        assert s.native_value is None

    def test_extra_attrs(self):
        s = _make(EauGrandLyonProchaineReleveSensor, {
            "pds_mode_releve": "RADIO",
            "pds_communicabilite_amm": True,
        })
        attrs = s.extra_state_attributes
        assert attrs["mode_releve"] == "RADIO"
