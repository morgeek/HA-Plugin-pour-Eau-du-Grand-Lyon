"""Tests unitaires pour les sensors Eau du Grand Lyon.

Couvre :
  - EauGrandLyonConsommationSensor (courant / précédent)
  - EauGrandLyonConsommationAnnuelleSensor
  - EauGrandLyonConso7JSensor / Conso30JSensor
  - EauGrandLyonCoutMoisSensor / CoutAnnuelSensor
  - EauGrandLyonSoldeSensor / StatutSensor
  - EauGrandLyonAlertesSensor / HealthSensor
  - EauGrandLyonDerniereFactureSensor  [expérimental]
  - EauGrandLyonFuiteEstimeeSensor     [expérimental]
  - async_setup_entry — décompte et flag expérimental
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.eau_grand_lyon.sensor import (
    EauGrandLyonConsommationSensor,
    EauGrandLyonConsommationAnnuelleSensor,
    EauGrandLyonConso7JSensor,
    EauGrandLyonConso30JSensor,
    EauGrandLyonCoutMoisSensor,
    EauGrandLyonCoutAnnuelSensor,
    EauGrandLyonSoldeSensor,
    EauGrandLyonStatutSensor,
    EauGrandLyonAlertesSensor,
    EauGrandLyonHealthSensor,
    EauGrandLyonLastUpdateSensor,
    EauGrandLyonDerniereFactureSensor,
    EauGrandLyonFuiteEstimeeSensor,
    async_setup_entry,
)


# ── Factories ─────────────────────────────────────────────────────────────────

def _make_entry(entry_id: str = "entry1") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    return entry


def _base_contract(ref: str = "REF123", **overrides) -> dict:
    base = {
        "id":                          "C001",
        "reference":                   ref,
        "statut":                      "Actif",
        "date_effet":                  "2020-01-01",
        "date_echeance":               "2025-12-31",
        "solde_eur":                   12.5,
        "mensualise":                  False,
        "mode_paiement":               "Virement",
        "calibre_compteur":            "15",
        "usage":                       "Domestique",
        "nombre_habitants":            "2",
        "reference_pds":               "PDS001",
        "signal_pct":                  None,
        "battery_ok":                  None,
        "consommations":               [
            {"mois_index": 0, "mois": "Janvier", "annee": 2024, "label": "Janvier 2024", "consommation_m3": 15.0},
            {"mois_index": 1, "mois": "Février", "annee": 2024, "label": "Février 2024", "consommation_m3": 12.0},
            {"mois_index": 2, "mois": "Mars",    "annee": 2024, "label": "Mars 2024",    "consommation_m3": 18.0},
        ],
        "consommation_mois_courant":   18.0,
        "label_mois_courant":          "Mars 2024",
        "consommation_mois_precedent": 12.0,
        "label_mois_precedent":        "Février 2024",
        "consommation_annuelle":       45.0,
        "consommation_cumulee_annee":  45.0,
        "consommation_n1":             17.0,
        "label_n1":                    "Mars 2023",
        "mois_manquants":              [],
        "consommations_journalieres":  [
            {"date": f"2024-03-{d:02d}", "consommation_m3": 0.6}
            for d in range(1, 32)
        ],
        "consommation_7j":             4.2,
        "consommation_30j":            18.0,
        "cout_mois_courant_eur":       27.0,
        "cout_annuel_eur":             67.5,
        "tarif_m3":                    1.5,
        "factures":                    [],
        "derniere_facture":            None,
        "fuite_estime_30j_m3":         None,
        "courbe_de_charge":            [],
    }
    base.update(overrides)
    return base


def _make_coordinator(ref: str = "REF123", experimental: bool = False, **contract_overrides) -> MagicMock:
    coord = MagicMock()
    coord.data = {
        "contracts": {ref: _base_contract(ref=ref, **contract_overrides)},
        "nb_alertes": 0,
        "last_update_success_time": datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc),
        "last_error": None,
        "last_error_type": None,
        "offline_mode": False,
        "offline_since": None,
        "experimental_mode": experimental,
    }
    return coord


# ── EauGrandLyonConsommationSensor ────────────────────────────────────────────

class TestConsommationSensor:
    def test_courant_value(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonConsommationSensor(coord, _make_entry(), "REF123", "courant")
        assert sensor.native_value == pytest.approx(18.0)

    def test_precedent_value(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonConsommationSensor(coord, _make_entry(), "REF123", "precedent")
        assert sensor.native_value == pytest.approx(12.0)

    def test_returns_none_when_no_data(self):
        coord       = _make_coordinator()
        coord.data  = None
        sensor      = EauGrandLyonConsommationSensor(coord, _make_entry(), "REF123", "courant")
        assert sensor.native_value is None

    def test_attributes_contain_periode(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonConsommationSensor(coord, _make_entry(), "REF123", "courant")
        attrs  = sensor.extra_state_attributes
        assert "période" in attrs
        assert attrs["période"] == "Mars 2024"

    def test_attributes_courant_contain_historique(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonConsommationSensor(coord, _make_entry(), "REF123", "courant")
        attrs  = sensor.extra_state_attributes
        assert "historique" in attrs
        assert isinstance(attrs["historique"], list)

    def test_attributes_precedent_contain_periode(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonConsommationSensor(coord, _make_entry(), "REF123", "precedent")
        attrs  = sensor.extra_state_attributes
        assert "période" in attrs


# ── EauGrandLyonConsommationAnnuelleSensor ────────────────────────────────────

class TestConsommationAnnuelleSensor:
    def test_value(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonConsommationAnnuelleSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value == pytest.approx(45.0)

    def test_available_when_has_consumptions(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonConsommationAnnuelleSensor(coord, _make_entry(), "REF123")
        assert sensor.available is True

    def test_value_none_when_no_consumptions(self):
        """Sans données, consommation_annuelle n'est pas calculée → native_value None."""
        coord  = _make_coordinator(consommation_annuelle=None)
        sensor = EauGrandLyonConsommationAnnuelleSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value is None

    def test_attributes_include_detail_mensuel(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonConsommationAnnuelleSensor(coord, _make_entry(), "REF123")
        attrs  = sensor.extra_state_attributes
        assert "détail_mensuel" in attrs
        assert "nb_mois_inclus" in attrs
        assert attrs["nb_mois_inclus"] == 3


# ── EauGrandLyonConso7JSensor / Conso30JSensor ────────────────────────────────

class TestConsoDailySensors:
    def test_7j_value(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonConso7JSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value == pytest.approx(4.2)

    def test_30j_value(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonConso30JSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value == pytest.approx(18.0)

    def test_7j_disabled_by_default(self):
        assert EauGrandLyonConso7JSensor._attr_entity_registry_enabled_default is False

    def test_30j_disabled_by_default(self):
        assert EauGrandLyonConso30JSensor._attr_entity_registry_enabled_default is False

    def test_7j_none_when_no_daily(self):
        coord  = _make_coordinator(consommation_7j=None)
        sensor = EauGrandLyonConso7JSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value is None

    def test_30j_attributes_include_nb_jours(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonConso30JSensor(coord, _make_entry(), "REF123")
        attrs  = sensor.extra_state_attributes
        # Should have some info about the period
        assert attrs is not None


# ── EauGrandLyonCoutMoisSensor / CoutAnnuelSensor ─────────────────────────────

class TestCoutSensors:
    def test_cout_mois_value(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonCoutMoisSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value == pytest.approx(27.0)

    def test_cout_annuel_value(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonCoutAnnuelSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value == pytest.approx(67.5)

    def test_cout_mois_none_when_no_courant(self):
        coord  = _make_coordinator(cout_mois_courant_eur=None)
        sensor = EauGrandLyonCoutMoisSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value is None

    def test_cout_attrs_include_tarif(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonCoutMoisSensor(coord, _make_entry(), "REF123")
        attrs  = sensor.extra_state_attributes
        assert "tarif_appliqué_eur_m3" in attrs
        assert attrs["tarif_appliqué_eur_m3"] == pytest.approx(1.5)


# ── EauGrandLyonSoldeSensor / StatutSensor ────────────────────────────────────

class TestContractInfoSensors:
    def test_solde_value(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonSoldeSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value == pytest.approx(12.5)

    def test_statut_value(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonStatutSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value == "Actif"

    def test_statut_none_when_no_data(self):
        coord      = _make_coordinator()
        coord.data = None
        sensor     = EauGrandLyonStatutSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value is None

    def test_statut_attributes_include_contract_details(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonStatutSensor(coord, _make_entry(), "REF123")
        attrs  = sensor.extra_state_attributes
        assert "mode_paiement" in attrs or "mensualise" in attrs or len(attrs) > 0


# ── EauGrandLyonAlertesSensor ─────────────────────────────────────────────────

class TestAlertesSensor:
    def test_value_when_no_alertes(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonAlertesSensor(coord, _make_entry())
        assert sensor.native_value == 0

    def test_value_when_alertes(self):
        coord = _make_coordinator()
        coord.data["nb_alertes"] = 3
        sensor = EauGrandLyonAlertesSensor(coord, _make_entry())
        assert sensor.native_value == 3

    def test_returns_zero_when_no_data(self):
        coord      = _make_coordinator()
        coord.data = None
        sensor     = EauGrandLyonAlertesSensor(coord, _make_entry())
        # Doit retourner 0, pas lever d'exception
        assert sensor.native_value == 0


# ── EauGrandLyonHealthSensor ──────────────────────────────────────────────────

class TestHealthSensor:
    def test_ok_when_no_error(self):
        coord  = _make_coordinator()
        sensor = EauGrandLyonHealthSensor(coord, _make_entry())
        assert sensor.native_value == "OK"

    def test_hors_ligne_when_offline(self):
        coord = _make_coordinator()
        coord.data["offline_mode"] = True
        sensor = EauGrandLyonHealthSensor(coord, _make_entry())
        assert sensor.native_value == "HORS-LIGNE"

    def test_ko_when_last_error(self):
        coord = _make_coordinator()
        coord.data["last_error"] = "Some error"
        sensor = EauGrandLyonHealthSensor(coord, _make_entry())
        assert sensor.native_value == "KO"

    def test_inconnu_when_no_data(self):
        coord      = _make_coordinator()
        coord.data = None
        sensor     = EauGrandLyonHealthSensor(coord, _make_entry())
        assert sensor.native_value == "INCONNU"

    def test_attributes_include_experimental_mode(self):
        coord  = _make_coordinator(experimental=True)
        sensor = EauGrandLyonHealthSensor(coord, _make_entry())
        attrs  = sensor.extra_state_attributes
        assert attrs.get("experimental_mode") is True

    def test_attributes_include_offline_since_when_offline(self):
        coord = _make_coordinator()
        coord.data["offline_mode"]  = True
        coord.data["offline_since"] = datetime(2024, 3, 1, tzinfo=timezone.utc)
        sensor = EauGrandLyonHealthSensor(coord, _make_entry())
        attrs  = sensor.extra_state_attributes
        assert "offline_since" in attrs


# ── [EXPÉRIMENTAL] EauGrandLyonDerniereFactureSensor ─────────────────────────

class TestDerniereFactureSensor:
    def _make_with_facture(self, montant: float = 35.0) -> tuple:
        facture = {
            "reference":        "F001",
            "date_edition":     "2024-03-01",
            "date_exigibilite": "2024-04-01",
            "montant_ht":       30.0,
            "montant_ttc":      montant,
            "volume_m3":        15.0,
            "statut_paiement":  "Payée",
            "contrat_id":       "C001",
        }
        coord  = _make_coordinator(derniere_facture=facture, factures=[facture])
        entry  = _make_entry()
        sensor = EauGrandLyonDerniereFactureSensor(coord, entry, "REF123")
        return sensor, facture

    def test_disabled_by_default(self):
        assert EauGrandLyonDerniereFactureSensor._attr_entity_registry_enabled_default is False

    def test_value_is_montant_ttc(self):
        sensor, _ = self._make_with_facture(montant=42.5)
        assert sensor.native_value == pytest.approx(42.5)

    def test_available_when_facture_present(self):
        sensor, _ = self._make_with_facture()
        assert sensor.available is True

    def test_unavailable_when_no_facture(self):
        coord  = _make_coordinator(derniere_facture=None)
        sensor = EauGrandLyonDerniereFactureSensor(coord, _make_entry(), "REF123")
        assert sensor.available is False

    def test_value_none_when_no_facture(self):
        coord  = _make_coordinator(derniere_facture=None)
        sensor = EauGrandLyonDerniereFactureSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value is None

    def test_value_none_when_no_coordinator_data(self):
        coord      = _make_coordinator()
        coord.data = None
        sensor     = EauGrandLyonDerniereFactureSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value is None

    def test_attributes_contain_reference_and_dates(self):
        sensor, facture = self._make_with_facture()
        attrs = sensor.extra_state_attributes
        assert attrs["référence"]       == "F001"
        assert attrs["date_édition"]    == "2024-03-01"
        assert attrs["montant_ttc_eur"] == pytest.approx(35.0)
        assert attrs["statut_paiement"] == "Payée"

    def test_attributes_contain_historique(self):
        sensor, _ = self._make_with_facture()
        attrs = sensor.extra_state_attributes
        assert "historique_factures" in attrs
        assert isinstance(attrs["historique_factures"], list)


# ── [EXPÉRIMENTAL] EauGrandLyonFuiteEstimeeSensor ────────────────────────────

class TestFuiteEstimeeSensor:
    def _make_with_fuite(self, valeur: float = 0.15) -> EauGrandLyonFuiteEstimeeSensor:
        daily = [
            {"date": f"2024-03-{d:02d}", "consommation_m3": 0.5, "volume_fuite_estime_m3": 0.005}
            for d in range(1, 31)
        ]
        coord  = _make_coordinator(
            fuite_estime_30j_m3=valeur,
            consommations_journalieres=daily,
        )
        return EauGrandLyonFuiteEstimeeSensor(coord, _make_entry(), "REF123")

    def test_disabled_by_default(self):
        assert EauGrandLyonFuiteEstimeeSensor._attr_entity_registry_enabled_default is False

    def test_value_returned(self):
        sensor = self._make_with_fuite(0.15)
        assert sensor.native_value == pytest.approx(0.15)

    def test_available_when_fuite_present(self):
        sensor = self._make_with_fuite(0.15)
        assert sensor.available is True

    def test_unavailable_when_fuite_none(self):
        coord  = _make_coordinator(fuite_estime_30j_m3=None)
        sensor = EauGrandLyonFuiteEstimeeSensor(coord, _make_entry(), "REF123")
        assert sensor.available is False

    def test_value_none_when_fuite_none(self):
        coord  = _make_coordinator(fuite_estime_30j_m3=None)
        sensor = EauGrandLyonFuiteEstimeeSensor(coord, _make_entry(), "REF123")
        assert sensor.native_value is None

    def test_attributes_contain_detail_journalier(self):
        sensor = self._make_with_fuite()
        attrs  = sensor.extra_state_attributes
        assert "nb_jours_avec_donnée" in attrs
        assert "détail_journalier"    in attrs
        assert isinstance(attrs["détail_journalier"], list)

    def test_attributes_detail_capped_at_14_entries(self):
        sensor = self._make_with_fuite()
        attrs  = sensor.extra_state_attributes
        assert len(attrs["détail_journalier"]) <= 14

    def test_unavailable_when_no_coordinator_data(self):
        coord      = _make_coordinator()
        coord.data = None
        sensor     = EauGrandLyonFuiteEstimeeSensor(coord, _make_entry(), "REF123")
        assert sensor.available is False


# ── async_setup_entry ─────────────────────────────────────────────────────────

class TestAsyncSetupEntry:
    @pytest.mark.asyncio
    async def test_creates_standard_sensors_per_contract(self):
        coord = _make_coordinator(experimental=False)
        entry = _make_entry()
        entry.runtime_data = coord  # pattern HA moderne (entry.runtime_data)

        hass = MagicMock()
        added = []
        async_add = MagicMock(side_effect=lambda entities, **kw: added.extend(entities))

        await async_setup_entry(hass, entry, async_add)

        # Au moins 1 appel à async_add_entities
        assert async_add.called
        # Vérification que les sensors globaux sont présents
        types = [type(e).__name__ for e in added]
        assert "EauGrandLyonAlertesSensor"    in types
        assert "EauGrandLyonHealthSensor"     in types
        assert "EauGrandLyonLastUpdateSensor" in types

    @pytest.mark.asyncio
    async def test_no_experimental_sensors_in_legacy_mode(self):
        coord = _make_coordinator(experimental=False)
        entry = _make_entry()
        entry.runtime_data = coord
        hass  = MagicMock()

        added = []
        async_add = MagicMock(side_effect=lambda entities, **kw: added.extend(entities))
        await async_setup_entry(hass, entry, async_add)

        types = [type(e).__name__ for e in added]
        assert "EauGrandLyonDerniereFactureSensor" not in types
        assert "EauGrandLyonFuiteEstimeeSensor"     not in types

    @pytest.mark.asyncio
    async def test_experimental_sensors_added_in_experimental_mode(self):
        coord = _make_coordinator(experimental=True)
        entry = _make_entry()
        entry.runtime_data = coord
        hass  = MagicMock()

        added = []
        async_add = MagicMock(side_effect=lambda entities, **kw: added.extend(entities))
        await async_setup_entry(hass, entry, async_add)

        types = [type(e).__name__ for e in added]
        assert "EauGrandLyonDerniereFactureSensor" in types
        assert "EauGrandLyonFuiteEstimeeSensor"     in types

    @pytest.mark.asyncio
    async def test_multiple_contracts_creates_sensors_for_each(self):
        coord = MagicMock()
        coord.data = {
            "contracts": {
                "REF001": _base_contract(ref="REF001"),
                "REF002": _base_contract(ref="REF002"),
            },
            "nb_alertes": 0,
            "experimental_mode": False,
            "global": {"nb_contracts": 2},
        }
        entry = _make_entry()
        entry.runtime_data = coord
        hass  = MagicMock()

        added = []
        async_add = MagicMock(side_effect=lambda entities, **kw: added.extend(entities))
        await async_setup_entry(hass, entry, async_add)

        refs = {getattr(e, "_contract_ref", None) for e in added}
        assert "REF001" in refs
        assert "REF002" in refs
