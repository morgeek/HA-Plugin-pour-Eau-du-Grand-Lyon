"""Behavior coverage for API endpoint variants and malformed provider payloads."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.eau_grand_lyon.api import HttpError, NetworkError
from custom_components.eau_grand_lyon.api.client import (
    EauGrandLyonApi,
    _infer_unit_from_magnitude,
)


def _api() -> EauGrandLyonApi:
    return EauGrandLyonApi(MagicMock(), "user@example.com", "secret", experimental=True)


@pytest.mark.asyncio
async def test_client_accessors_authentication_revoke_and_request_proxies():
    api = _api()
    api._auth.authenticate = AsyncMock(return_value="token")
    api._auth.revoke_token = AsyncMock()

    assert api.experimental is True
    assert api.access_token is None
    assert await api.authenticate() == "token"
    await api.async_revoke_token()
    api._auth.revoke_token.assert_awaited_once()

    api._request = AsyncMock(side_effect=[{"get": True}, {"post": True}])
    assert await api._get("/path", {"x": 1}) == {"get": True}
    assert await api._post("/path", {"x": 1}) == {"post": True}

    api._do_get = AsyncMock(return_value={"interfaces": True})
    assert await api._get_interfaces("/daily", {"days": 1}) == {"interfaces": True}


def test_unit_inference_ignores_invalid_entries_and_handles_empty_and_magnitudes():
    assert _infer_unit_from_magnitude([None, {}, {"consommation": "bad"}, {"consommation": 0}]) == ""
    assert _infer_unit_from_magnitude([{"consommation": 1}, {"consommation": 2}]) == "M3"
    assert _infer_unit_from_magnitude([{"consommation": 100}, {"consommation": 200}]) == "L"


@pytest.mark.asyncio
async def test_contract_and_monthly_endpoint_payload_variants():
    api = _api()
    api._post = AsyncMock(side_effect=[{"content": [{"id": "C1"}]}, [{"id": "C2"}], "invalid"])
    assert await api.get_contracts() == [{"id": "C1"}]
    assert await api.get_contracts() == [{"id": "C2"}]
    assert await api.get_contracts() == []

    api._get = AsyncMock(
        side_effect=[
            {
                "postes": [
                    {"data": [{"annee": "2026", "mois": "8", "consommation": 2}]},
                    {"data": [{"annee": "2025", "mois": "9", "consommation": 1}]},
                ]
            },
            [],
        ]
    )
    monthly = await api.get_monthly_consumptions("C1", nb_jours=0)
    assert [(item["annee"], item["mois"]) for item in monthly] == [
        ("2025", "9"),
        ("2026", "8"),
    ]
    assert await api.get_monthly_consumptions("C1") == []


@pytest.mark.asyncio
async def test_daily_retry_alert_thresholds_and_error_policies():
    api = _api()
    api._fetch_daily_raw = AsyncMock(
        side_effect=[
            {"entries": [], "source": "Aucune", "nb_entries": 0, "last_date": None},
            {
                "entries": [{"date": "2026-08-01", "consommation_m3": 1}],
                "source": "Legacy",
                "nb_entries": 1,
                "last_date": "2026-08-01",
            },
        ]
    )
    result = await api.get_daily_consumptions("C1", 365)
    assert result["nb_entries"] == 1
    assert api._fetch_daily_raw.await_args_list[-1].args == ("C1", 30)

    api._get_produits = AsyncMock(
        side_effect=[
            {"seuilAlerteSurconsommationJournaliere": "1.2345"},
            "invalid-number",
            {"actif": True},
        ]
    )
    alerts = await api.get_alerte_surconsommation("C1")
    assert alerts == {
        "seuil_surconso_jour_m3": 1.234,
        "seuil_surconso_mois_m3": None,
        "abonne_alerte_fuite": True,
    }

    api._get_produits = AsyncMock(side_effect=HttpError(500, "GET", "threshold", "down"))
    assert await api.get_alerte_surconsommation("C1") == {
        "seuil_surconso_jour_m3": None,
        "seuil_surconso_mois_m3": None,
        "abonne_alerte_fuite": None,
    }


@pytest.mark.asyncio
async def test_optional_endpoint_non_mapping_and_non_404_errors_propagate():
    api = _api()
    api._do_get = AsyncMock(return_value=[])
    assert await api.get_point_de_service_etendu("C1") == {}

    for method in (api.get_point_de_service_etendu, api.get_interventions):
        api._do_get = AsyncMock(side_effect=HttpError(500, "GET", "optional", "down"))
        with pytest.raises(HttpError):
            (await method("C1") if method == api.get_point_de_service_etendu else await method())

    api._get_produits = AsyncMock(side_effect=[[], {"content": [{"id": "I1"}]}, "bad"])
    assert await api.get_factures() == []
    assert await api.get_factures() == [{"id": "I1"}]
    assert await api.get_factures() == []
    api._get_produits = AsyncMock(side_effect=HttpError(500, "GET", "invoices", "down"))
    with pytest.raises(HttpError):
        await api.get_factures()

    api._get_interfaces = AsyncMock(side_effect=HttpError(500, "GET", "curve", "down"))
    with pytest.raises(HttpError):
        await api.get_courbe_de_charge("C1")

    api._get_produits = AsyncMock(side_effect=HttpError(418, "GET", "siamm", "teapot"))
    with pytest.raises(HttpError):
        await api.get_derniere_releve_siamm("C1")


def test_static_formatters_handle_malformed_and_all_realistic_payload_shapes():
    assert EauGrandLyonApi.format_consumptions(
        [
            {"mois": 12, "annee": 2026, "consommation": 1},
            {"mois": "bad", "annee": 2026},
            {"mois": 0, "annee": 2026, "consommation": 1.5},
        ]
    ) == [
        {
            "mois_index": 0,
            "mois": "Janvier",
            "annee": 2026,
            "label": "Janvier 2026",
            "consommation_m3": 1.5,
        }
    ]

    assert EauGrandLyonApi._extract_index({"index": "bad", "indexCompteur": 123456}) == 123.456
    assert EauGrandLyonApi._extract_conso({"consommation": "bad", "volume": 1.2}) == 1.2
    assert EauGrandLyonApi.format_daily_consumptions([], "C1") == []
    daily = EauGrandLyonApi.format_daily_consumptions(
        [
            {
                "date": "2026-08-01",
                "volumeFuiteEstime": "bad",
                "debitMin": "bad",
                "index": "bad",
            },
            {"date": "2026-08-02", "volumeFuiteEstime": 0.1},
        ],
        "C1",
    )
    assert daily == [{"date": "2026-08-02", "consommation_m3": 0.0, "volume_fuite_estime_m3": 0.1}]

    assert EauGrandLyonApi.format_factures([None, {"montantTTC": "bad"}]) == []


def test_postes_daily_parser_converts_units_and_tolerates_bad_fields():
    parsed = EauGrandLyonApi._parse_daily_response(
        {
            "unites": {
                "consommation": "L",
                "volumeEstimeFuite": "L",
                "debitMin": "L/h",
                "index": "L",
            },
            "postes": [
                None,
                {
                    "data": [
                        {
                            "annee": 2026,
                            "mois": 0,
                            "jour": 2,
                            "consommation": 1200,
                            "volumeEstimeFuite": 100,
                            "debitMin": 50,
                            "index": 20990,
                        },
                        {
                            "annee": "bad",
                            "mois": "bad",
                            "consommation": "bad",
                            "volumeFuiteEstime": "bad",
                            "debitMin": "bad",
                            "index": "bad",
                        },
                        "invalid",
                    ]
                },
            ],
        }
    )
    assert parsed[0]["date"] == "2026-01-02"
    assert parsed[0]["consommation"] == 1.2
    assert parsed[0]["volumeFuiteEstime"] == 0.1
    assert parsed[0]["debitMin"] == 0.05
    assert parsed[0]["index"] == 20.99


def test_contract_and_siamm_parsers_cover_invalid_and_complete_provider_values():
    contract = EauGrandLyonApi.parse_contract_details(
        {
            "id": "C1",
            "reference": "REF1",
            "conditionPaiement": {
                "mensualise": True,
                "compteClient": {"solde": {"value": "bad"}},
                "modePaiement": {"libelle": "Prélèvement"},
            },
            "servicesSouscrits": [
                {
                    "calibreCompteur": {"libelle": "DN15"},
                    "usage": {"libelle": "Domestique"},
                    "nombreHabitants": {"libelle": "2"},
                }
            ],
            "pointDeReleve": {"moduleRadio": {"niveauSignal": "bad", "etatPile": "OK"}},
        }
    )
    assert contract["solde_eur"] == 0
    assert contract["calibre_compteur"] == "DN15"
    assert contract["signal_pct"] is None
    assert contract["battery_ok"] is True

    assert EauGrandLyonApi.parse_siamm_index([]) is None
    assert (
        EauGrandLyonApi.parse_siamm_index(
            {"grandeursPhysiques": [{"modeleGrandeurPhysique": {"code": "VOLUME"}, "valeur": "bad"}]}
        )
        is None
    )
