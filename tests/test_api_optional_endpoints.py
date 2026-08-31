"""Functional tests for optional API endpoint parsing and failure policy."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.eau_grand_lyon.api import (
    AuthenticationError,
    HttpError,
    NetworkError,
    WafBlockedError,
)
from custom_components.eau_grand_lyon.api.client import EauGrandLyonApi
from custom_components.eau_grand_lyon.api import client as client_module


def _api() -> EauGrandLyonApi:
    return EauGrandLyonApi(MagicMock(), "user@example.com", "secret")


class TestOptionalEndpointParsing:
    @pytest.mark.asyncio
    async def test_alerts_preserve_provider_list(self):
        api = _api()
        api._get = AsyncMock(return_value=[{"id": "A1"}])
        assert await api.get_alertes() == [{"id": "A1"}]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "body", "expected"),
        [
            (200, '"2026-09-15"', "2026-09-15"),
            (200, '{"date": "2026-09-16T00:00:00Z"}', "2026-09-16"),
            (200, '{"dateProchaineFacture": "2026-10-02T00:00:00Z"}', "2026-10-02"),
            (200, '{"valeur": "2026-10-03"}', "2026-10-03"),
            (200, "2026-09-17", "2026-09-17"),
            (200, "2026-09-18T00:00:00Z", "2026-09-18"),
            (200, "", None),
            (204, "", None),
            (404, "missing", None),
            (200, "<!DOCTYPE html><html>maintenance</html>", None),
            (200, '{"value": null}', None),
            (200, "2026-02-30", None),
        ],
    )
    async def test_next_invoice_date_formats_supported_payloads(self, status, body, expected):
        api = _api()
        api._request_text = AsyncMock(return_value=(status, "text/plain", body))
        assert await api.get_date_prochaine_facture("C1") == expected

    @pytest.mark.asyncio
    async def test_extended_service_point_parses_profile(self):
        api = _api()
        api._do_get = AsyncMock(
            return_value={
                "communicabiliteAMM": True,
                "modeReleve": "AMM",
                "dateProchaineReleveReelle": "2026-09-10T00:00:00Z",
                "reference": "PDS-1",
                "periodesActiviteProfil": [
                    {"consommationAnnuelleReference": "120.5"},
                    {"consommationAnnuelleReference": "invalid"},
                ],
            }
        )

        result = await api.get_point_de_service_etendu("C1")

        assert result["communicabilite_amm"] is True
        assert result["date_prochaine_releve"] == "2026-09-10"
        assert result["conso_annuelle_ref_m3"] == 120.5
        assert result["reference_pds"] == "PDS-1"

    @pytest.mark.asyncio
    async def test_interventions_parses_valid_items_and_skips_malformed(self):
        api = _api()
        api._do_get = AsyncMock(
            return_value={
                "content": [
                    {
                        "reference": "I1",
                        "sousType": {"libelle": "Remplacement compteur"},
                        "statut": 4,
                        "dateDebutPrevue": "2026-09-12T08:00:00Z",
                        "presenceDuClientNecessaire": True,
                        "serviceSouscrit": {"contrat": {"reference": "C1"}},
                    },
                    None,
                ]
            }
        )

        result = await api.get_interventions()

        assert result == [
            {
                "reference": "I1",
                "type": "Remplacement compteur",
                "statut": "4",
                "date_debut": "2026-09-12",
                "date_fin": "2026-09-12",
                "presence_requise": True,
                "contrat_ref": "C1",
            }
        ]

    @pytest.mark.asyncio
    async def test_invoices_accept_embedded_content(self):
        api = _api()
        api._get_produits = AsyncMock(return_value={"content": [{"reference": "INV-1"}]})
        assert await api.get_factures() == [{"reference": "INV-1"}]

    def test_invoice_formatter_preserves_download_identifier_and_flag(self):
        result = EauGrandLyonApi.format_factures(
            [
                {
                    "id": "API-ID-1",
                    "reference": "INV-1",
                    "telechargeable": False,
                    "montantTTC": 328.42,
                    "volume": 88,
                    "contrat": {"id": "C1"},
                }
            ]
        )

        assert result[0]["id"] == "API-ID-1"
        assert result[0]["telechargeable"] is False

    def test_invoice_formatter_uses_confirmed_api_fields_and_converts_litres(self):
        result = EauGrandLyonApi.format_factures(
            [
                {
                    "id": "API-ID-2",
                    "reference": "INV-2",
                    "montantHT": 120.5,
                    "montantTTC": 132.55,
                    "statutReglement": {"code": "REGLE", "libelle": "Réglée"},
                    "consommationTotale": {"value": 42500, "unit": "L"},
                    "contrat": {"id": "C2"},
                }
            ]
        )

        assert result[0]["statut_paiement"] == "Réglée"
        assert result[0]["volume_m3"] == 42.5
        assert result[0]["montant_ht"] == 120.5
        assert result[0]["montant_ttc"] == 132.55

    @pytest.mark.asyncio
    async def test_load_curve_sorts_daily_points(self):
        api = _api()
        api._get_interfaces = AsyncMock(
            return_value={
                "data": [
                    {"date": "2026-08-02", "consommation": 0.2},
                    {"date": "2026-08-01", "consommation": 0.1},
                ]
            }
        )
        result = await api.get_courbe_de_charge("C1", nb_jours=7)
        assert [item["date"] for item in result] == ["2026-08-01", "2026-08-02"]

    @pytest.mark.asyncio
    async def test_load_curve_accepts_confirmed_empty_valeurs_envelope(self):
        api = _api()
        api._get_interfaces = AsyncMock(return_value={"valeurs": [], "unite": None})

        assert await api.get_courbe_de_charge("C1", nb_jours=7) == []

    @pytest.mark.asyncio
    async def test_load_curve_defensively_maps_hypothetical_populated_valeurs(self, caplog):
        # La forme de valeurs[i] est synthétique : seules l'enveloppe valeurs/unite
        # et la réponse vide ont été confirmées en production. Ce mapping devra être
        # révisé si les clés réelles observées sur un compte peuplé diffèrent.
        api = _api()
        api._get_interfaces = AsyncMock(
            return_value={
                "valeurs": [
                    {"date": "2026-08-02", "consommation": 250},
                    {"date": "2026-08-01", "consommation": 100},
                ],
                "unite": "l",
            }
        )

        with caplog.at_level("DEBUG"):
            result = await api.get_courbe_de_charge("C1", nb_jours=7)

        assert result == [
            {"date": "2026-08-01", "consommation": 0.1},
            {"date": "2026-08-02", "consommation": 0.25},
        ]
        assert "cles de la premiere entree valeurs=['consommation', 'date']" in caplog.text

    @pytest.mark.asyncio
    async def test_load_curve_rejects_unknown_populated_valeurs_shape(self):
        api = _api()
        api._get_interfaces = AsyncMock(return_value={"valeurs": [{"date": "2026-08-01", "inconnue": 1}]})

        assert await api.get_courbe_de_charge("C1", nb_jours=7) == []

    @pytest.mark.asyncio
    async def test_siamm_returns_mapping_only(self):
        api = _api()
        api._get_produits = AsyncMock(return_value={"grandeursPhysiques": []})
        assert await api.get_derniere_releve_siamm("C1") == {"grandeursPhysiques": []}
        api._get_produits.return_value = []
        assert await api.get_derniere_releve_siamm("C1") is None


class TestOptionalEndpointFailurePolicy:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method_name", "dependency", "args", "empty"),
        [
            ("get_point_de_service_etendu", "_do_get", ("C1",), {}),
            ("get_interventions", "_do_get", (), []),
            ("get_factures", "_get_produits", (), []),
            ("get_courbe_de_charge", "_get_interfaces", ("C1",), []),
        ],
    )
    async def test_expected_404_returns_endpoint_empty_value(self, method_name, dependency, args, empty):
        api = _api()
        setattr(
            api,
            dependency,
            AsyncMock(side_effect=HttpError(404, "GET", "optional", "missing")),
        )
        assert await getattr(api, method_name)(*args) == empty

    @pytest.mark.asyncio
    async def test_next_invoice_date_404_is_optional(self):
        api = _api()
        api._request_text = AsyncMock(return_value=(404, "text/plain", "missing"))
        assert await api.get_date_prochaine_facture("C1") is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("method_name", "dependency", "args"),
        [
            ("get_alertes", "_get", ()),
            ("get_point_de_service_etendu", "_do_get", ("C1",)),
            ("get_interventions", "_do_get", ()),
            ("get_factures", "_get_produits", ()),
            ("get_courbe_de_charge", "_get_interfaces", ("C1",)),
            ("get_derniere_releve_siamm", "_get_produits", ("C1",)),
        ],
    )
    async def test_network_errors_are_never_converted_to_empty_data(self, method_name, dependency, args):
        api = _api()
        setattr(api, dependency, AsyncMock(side_effect=NetworkError("offline")))
        with pytest.raises(NetworkError):
            await getattr(api, method_name)(*args)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            NetworkError("offline"),
            AuthenticationError("bad auth"),
            WafBlockedError("blocked"),
        ],
    )
    async def test_next_invoice_date_significant_errors_are_propagated(self, error):
        api = _api()
        api._request_text = AsyncMock(side_effect=error)
        with pytest.raises(type(error)):
            await api.get_date_prochaine_facture("C1")


class _ResponseContext:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self) -> str:
        return json.dumps(self._payload)


class TestWaterQualityOptionalSource:
    @pytest.mark.asyncio
    async def test_water_quality_selects_requested_commune(self, monkeypatch):
        session = MagicMock()
        session.get.return_value = _ResponseContext(
            {
                "values": [
                    {"commune": "Lyon", "durete": "28"},
                    {
                        "commune": "Villeurbanne",
                        "durete": "31.5",
                        "nitrates": "4.2",
                        "chloreresiduel": "0.1",
                        "turbidite": "0.3",
                        "dateanalyse": "2026-08-20T12:00:00Z",
                    },
                ]
            }
        )
        monkeypatch.setattr(
            client_module.aiohttp,
            "ClientTimeout",
            lambda total: SimpleNamespace(total=total),
            raising=False,
        )
        api = EauGrandLyonApi(session, "user@example.com", "secret")

        result = await api.get_water_quality("villeurbanne")

        assert result["commune"] == "Villeurbanne"
        assert result["durete_fh"] == 31.5
        assert result["date_analyse"] == "2026-08-20"

    @pytest.mark.asyncio
    async def test_water_quality_http_failure_is_acceptable_empty_value(self, monkeypatch):
        session = MagicMock()
        session.get.return_value = _ResponseContext({}, status=503)
        monkeypatch.setattr(
            client_module.aiohttp,
            "ClientTimeout",
            lambda total: SimpleNamespace(total=total),
            raising=False,
        )
        api = EauGrandLyonApi(session, "user@example.com", "secret")

        result = await api.get_water_quality()

        assert result["commune"] is None
        assert result["source"] == "Open Data Metropole de Lyon"
