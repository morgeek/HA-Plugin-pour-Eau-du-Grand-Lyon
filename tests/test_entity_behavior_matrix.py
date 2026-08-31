"""Behavior matrices for entity values, availability, attributes, and icons."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from custom_components.eau_grand_lyon import binary_sensor as binary_platform
from custom_components.eau_grand_lyon import sensor as sensor_platform
from custom_components.eau_grand_lyon.sensors.consumption import EauGrandLyonConsommationSensor
from custom_components.eau_grand_lyon.sensors.global_sensors import (
    EauGrandLyonDroughtSensor,
    EauGrandLyonHealthSensor,
    EauGrandLyonNextOutageSensor,
)


def _entry() -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.options = {"leak_multiplier": 2.0}
    return entry


def _rich_contract() -> dict:
    monthly = [{"label": f"M{i}", "consommation_m3": float(i + 1), "annee": 2026, "mois_index": i} for i in range(12)]
    daily = [{"date": f"2026-08-{i:02d}", "consommation_m3": i / 10} for i in range(1, 15)]
    return {
        "reference": "REF1",
        "statut": "Actif",
        "date_effet": "2025-01-01",
        "date_echeance": "2026-12-31",
        "solde_eur": -12.5,
        "mensualise": True,
        "mode_paiement": "Prélèvement",
        "calibre_compteur": "DN15",
        "usage": "Domestique",
        "nombre_habitants": "2",
        "reference_pds": "PDS-1",
        "consommations": monthly,
        "mois_manquants": ["Mars 2025"],
        "consommation_mois_courant": 20.0,
        "consommation_mois_precedent": 8.0,
        "label_mois_courant": "Août 2026",
        "label_mois_precedent": "Juillet 2026",
        "consommation_annuelle": 78.0,
        "consommation_cumulee_annee": 50.0,
        "consommation_annuelle_n1": 90.0,
        "consommation_n1": 10.0,
        "label_n1": "Août 2025",
        "consommations_journalieres": daily,
        "daily_source": "Produits",
        "daily_nb_entries": len(daily),
        "daily_last_date": daily[-1]["date"],
        "index_journalier_dernier": 321.5,
        "index_journalier_dernier_date": daily[-1]["date"],
        "consommation_7j": 7.0,
        "conso_moyenne_7j_litres": 1000.0,
        "consommation_30j": 14.0,
        "cout_mois_courant_eur": 70.0,
        "cout_annuel_eur": 300.0,
        "cout_reel_mois": 75.0,
        "cout_reel_annuel": 328.42,
        "subscription_annual": 50.66,
        "tarif_m3": 3.75,
        "billing_mode": "latest_invoice",
        "tariff_source": "latest_invoice_ttc_per_m3",
        "cost_breakdown_monthly": {"volume_m3": 20, "variable_eur": 70, "fixed_eur": 5},
        "cost_breakdown_annual": {"volume_m3": 78, "variable_eur": 277.76, "fixed_eur": 50.66},
        "latest_invoice_ttc": 328.42,
        "latest_invoice_volume_m3": 88.0,
        "latest_invoice_effective_rate_eur_m3": 3.732,
        "tendance_n1_pct": 25.0,
        "prediction_conso_mois": 25.0,
        "prediction_cout_mois": 93.75,
        "eco_score_grade": "C",
        "eco_score_m3_pers": 10.0,
        "nb_habitants": 2,
        "co2_footprint_kg": 10.4,
        "limescale_g": 5000.0,
        "hardness_fh": 30.0,
        "signal_pct": 65.0,
        "battery_ok": False,
        "teleo_compatible": True,
        "next_payment_date": "2026-09-01",
        "next_bill_date": "2026-09-15",
        "estimated_next_bill_date": "2027-02-28",
        "date_prochaine_releve": "2026-10-01",
        "conso_annuelle_ref_m3": 100.0,
        "pds_mode_releve": "AMM",
        "pds_communicabilite_amm": True,
        "factures": [{"id": "INV-1", "montant_ttc": 328.42}],
        "derniere_facture": {"reference": "INV-1", "montant_ttc": 328.42},
        "fuite_estime_30j_m3": 0.25,
        "courbe_de_charge": [{"date": "2026-08-01T10:00:00", "consommation": 0.1}] * 24,
        "consommation_derniere_heure_m3": 0.1,
        "heure_pic": "10:00",
        "debit_moyen_m3h": 0.05,
        "local_leak_pattern": True,
        "limescale_alert": True,
        "seuil_surconso_jour_m3": 0.5,
        "seuil_surconso_mois_m3": 15.0,
        "abonne_alerte_fuite": True,
        "derniere_conso_jour_m3": 1.4,
        "surconso_jour_depassee": True,
        "surconso_mois_depassee": True,
    }


def _exercise_properties(entity) -> None:
    for property_name in (
        "available",
        "native_value",
        "extra_state_attributes",
        "icon",
        "device_info",
        "is_on",
    ):
        descriptor = getattr(type(entity), property_name, None)
        if isinstance(descriptor, property):
            getattr(entity, property_name)


def test_all_contract_sensor_behaviors_accept_rich_and_missing_provider_data():
    coordinator = MagicMock()
    coordinator.get_cumulative_index.return_value = 432.1
    coordinator.config_entry = _entry()
    entry = _entry()

    for contract in (_rich_contract(), {}):
        coordinator.data = {"contracts": {"REF1": contract}, "experimental_mode": True}
        entities = sensor_platform._contract_sensor_candidates(coordinator, entry, "REF1", contract, experimental=True)
        assert len({entity._attr_unique_id for entity in entities}) == len(entities)
        for entity in entities:
            _exercise_properties(entity)


@pytest.mark.parametrize(
    ("value", "expected_icon"),
    [
        (None, "mdi:water-outline"),
        (0, "mdi:water-outline"),
        (3, "mdi:water-minus"),
        (10, "mdi:water"),
        (20, "mdi:water-percent"),
    ],
)
def test_monthly_consumption_icon_thresholds(value, expected_icon):
    coordinator = MagicMock()
    coordinator.data = {"contracts": {"REF1": {"consommation_mois_courant": value}}}
    sensor = EauGrandLyonConsommationSensor(coordinator, _entry(), "REF1", "courant")
    assert sensor.icon == expected_icon


def test_global_sensor_behavior_states_and_outage_payloads():
    entry = _entry()
    coordinator = MagicMock()
    coordinator.data = {
        "contracts": {
            "REF1": {"teleo_compatible": True},
            "REF2": {"teleo_compatible": False, "daily_nb_entries": 0},
        },
        "global": {
            "nb_contracts": 2,
            "total_conso_courant": 12.0,
            "total_cout_courant_eur": 45.0,
            "total_prediction_cout_eur": 55.0,
        },
        "nb_alertes": 2,
        "last_update_success_time": datetime(2026, 8, 30, tzinfo=timezone.utc),
        "drought_level": "vigilance",
        "water_quality": {"durete_fh": 30.0, "nitrates_mgl": 4.0, "chlore_mgl": 0.1},
        "prochaine_coupure": {
            "titre": "Travaux",
            "type": "TRAVAUX",
            "date_debut": "2026-09-01",
            "date_fin": "2026-09-02",
        },
        "interruptions": [{"titre": "Travaux", "date_debut": "2026-09-01", "type": "TRAVAUX"}],
    }

    for entity in sensor_platform._global_sensor_candidates(coordinator, entry):
        _exercise_properties(entity)

    health = EauGrandLyonHealthSensor(coordinator, entry)
    assert health.native_value == "ok"
    assert "teleo_note" in health.extra_state_attributes
    coordinator.data["offline_mode"] = True
    assert health.native_value == "offline"
    assert "offline_since" in health.extra_state_attributes
    coordinator.data["offline_mode"] = False
    coordinator.data["last_error"] = "boom"
    assert health.native_value == "error"
    coordinator.data = {}
    assert health.native_value == "unknown"

    for level, icon in (("normal", "mdi:water-check"), ("crise", "mdi:water-alert"), ("vigilance", "mdi:water-remove")):
        coordinator.data = {"drought_level": level}
        assert EauGrandLyonDroughtSensor(coordinator, entry).icon == icon

    coordinator.data = {"prochaine_coupure": {"date_debut": "invalid"}, "interruptions": []}
    assert EauGrandLyonNextOutageSensor(coordinator, entry).native_value is None
    coordinator.data = {}
    assert EauGrandLyonNextOutageSensor(coordinator, entry).native_value is None


def test_all_binary_sensor_behaviors_accept_rich_and_missing_provider_data():
    coordinator = MagicMock()
    coordinator.config_entry = _entry()
    entry = _entry()

    for contract in (_rich_contract(), {}):
        coordinator.data = {"contracts": {"REF1": contract}, "experimental_mode": True}
        entities = binary_platform._contract_binary_sensor_candidates(coordinator, entry, "REF1", contract)
        assert len({entity._attr_unique_id for entity in entities}) == len(entities)
        for entity in entities:
            _exercise_properties(entity)
