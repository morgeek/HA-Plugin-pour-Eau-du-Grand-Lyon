"""Tests for sensors/contract.py — date parsing, state and availability logic."""

from datetime import date
from unittest.mock import MagicMock

from custom_components.eau_grand_lyon.const import CONF_HOUSEHOLD_SIZE
from custom_components.eau_grand_lyon.sensors.contract import (
    EauGrandLyonStatutSensor,
    EauGrandLyonDateEcheanceSensor,
    EauGrandLyonProchaineFactureSensor,
    EauGrandLyonProchaineReleveSensor,
)


def _make(cls, contract_data, contract_ref="REF1", options=None):
    coordinator = MagicMock()
    coordinator.data = {"contracts": {contract_ref: contract_data}}
    entry = MagicMock()
    entry.entry_id = "test_entry"
    # Un vrai dict (pas un MagicMock) : entry.options.get(...) doit renvoyer
    # None quand la clé est absente, comme la vraie ConfigEntry de HA.
    entry.options = options if options is not None else {}
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
        s = _make(
            EauGrandLyonStatutSensor,
            {
                "statut": "ACTIF",
                "reference": "REF-123",
                "usage": "Habitation",
            },
        )
        attrs = s.extra_state_attributes
        assert "référence" in attrs
        assert "usage" in attrs

    def test_nombre_habitants_falls_back_to_household_size_option(self):
        """Retour utilisateur : servicesSouscrits[0].nombreHabitants est vide pour
        certains types de contrat. On retombe sur l'option household_size déjà
        collectée pour l'Éco-Score, en indiquant sa provenance."""
        s = _make(
            EauGrandLyonStatutSensor,
            {"statut": "ACTIF"},
            options={CONF_HOUSEHOLD_SIZE: 4},
        )
        assert s.extra_state_attributes["nombre_habitants"] == "4 (valeur configurée)"

    def test_nombre_habitants_empty_when_no_api_value_and_no_option(self):
        s = _make(EauGrandLyonStatutSensor, {"statut": "ACTIF"}, options={})
        assert s.extra_state_attributes["nombre_habitants"] == ""

    def test_nombre_habitants_prefers_api_value_over_option(self):
        s = _make(
            EauGrandLyonStatutSensor,
            {"statut": "ACTIF", "nombre_habitants": "3"},
            options={CONF_HOUSEHOLD_SIZE: 4},
        )
        assert s.extra_state_attributes["nombre_habitants"] == "3"


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
        s = _make(
            EauGrandLyonProchaineReleveSensor,
            {
                "pds_mode_releve": "RADIO",
                "pds_communicabilite_amm": True,
            },
        )
        attrs = s.extra_state_attributes
        assert attrs["mode_releve"] == "RADIO"
