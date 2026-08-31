"""Tests des seuils d'alerte surconsommation configurés côté serveur.

Couvre la méthode API `get_alerte_surconsommation`, les capteurs de seuil et
les binary_sensors de dépassement / abonnement fuite.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.eau_grand_lyon.api import HttpError
from custom_components.eau_grand_lyon.api.client import EauGrandLyonApi
from custom_components.eau_grand_lyon.binary_sensor import (
    EauGrandLyonLeakSubscriptionSensor,
    EauGrandLyonSurconsoJourSensor,
    EauGrandLyonSurconsoMoisSensor,
)
from custom_components.eau_grand_lyon.sensors.alerts import (
    EauGrandLyonSeuilSurconsoJourSensor,
    EauGrandLyonSeuilSurconsoMoisSensor,
)


def _make_api() -> EauGrandLyonApi:
    return EauGrandLyonApi(MagicMock(), "user@example.com", "secret")


# ── API : get_alerte_surconsommation ─────────────────────────────────────────


async def test_get_alerte_surconsommation_parses_values():
    api = _make_api()

    async def fake(sub_path, params=None, *, log_response_errors=True):
        if sub_path.endswith("journaliere"):
            return {"seuilAlerteSurconsommationJournaliere": 4.6000000000000005}
        if sub_path.endswith("mensuelle"):
            return {"seuilAlerteSurconsommationMensuelle": 138.00000000000003}
        if sub_path.endswith("abonneAlerteFuite"):
            return True
        return None

    api._get_produits = fake  # type: ignore[assignment]
    res = await api.get_alerte_surconsommation("CID")
    assert res["seuil_surconso_jour_m3"] == 4.6
    assert res["seuil_surconso_mois_m3"] == 138.0
    assert res["abonne_alerte_fuite"] is True


async def test_get_alerte_surconsommation_handles_missing_endpoints():
    api = _make_api()

    async def boom(sub_path, params=None, *, log_response_errors=True):
        raise HttpError(404, "GET", "https://example.test/optional", "missing")

    api._get_produits = boom  # type: ignore[assignment]
    res = await api.get_alerte_surconsommation("CID")
    assert res == {
        "seuil_surconso_jour_m3": None,
        "seuil_surconso_mois_m3": None,
        "abonne_alerte_fuite": None,
    }


# ── Capteurs / binary_sensors ────────────────────────────────────────────────


def _sensor(cls, contract_data, ref="REF1"):
    coordinator = MagicMock()
    coordinator.data = {"contracts": {ref: contract_data}}
    entry = MagicMock()
    entry.entry_id = "test_entry"
    s = cls.__new__(cls)
    s.coordinator = coordinator
    s._entry = entry
    s._contract_ref = ref
    return s


def test_seuil_sensors_native_value():
    data = {"seuil_surconso_jour_m3": 4.6, "seuil_surconso_mois_m3": 138.0}
    assert _sensor(EauGrandLyonSeuilSurconsoJourSensor, data).native_value == 4.6
    assert _sensor(EauGrandLyonSeuilSurconsoMoisSensor, data).native_value == 138.0


def test_surconso_jour_binary_on_and_off():
    on = _sensor(
        EauGrandLyonSurconsoJourSensor,
        {
            "seuil_surconso_jour_m3": 4.6,
            "derniere_conso_jour_m3": 5.0,
            "surconso_jour_depassee": True,
        },
    )
    off = _sensor(
        EauGrandLyonSurconsoJourSensor,
        {
            "seuil_surconso_jour_m3": 4.6,
            "derniere_conso_jour_m3": 0.4,
            "surconso_jour_depassee": False,
        },
    )
    assert on.is_on is True
    assert off.is_on is False


def test_surconso_mois_binary():
    on = _sensor(
        EauGrandLyonSurconsoMoisSensor,
        {
            "seuil_surconso_mois_m3": 138.0,
            "surconso_mois_depassee": True,
        },
    )
    assert on.is_on is True


def test_leak_subscription_binary():
    yes = _sensor(EauGrandLyonLeakSubscriptionSensor, {"abonne_alerte_fuite": True})
    no = _sensor(EauGrandLyonLeakSubscriptionSensor, {"abonne_alerte_fuite": False})
    assert yes.is_on is True
    assert no.is_on is False
