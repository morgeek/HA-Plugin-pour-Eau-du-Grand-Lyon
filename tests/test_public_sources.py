"""Tests des sources publiques PFAS et VigiEau, isolées et opt-in."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from custom_components.eau_grand_lyon import pfas as pfas_module
from custom_components.eau_grand_lyon.binary_sensor import EauGrandLyonPfasConformSensor
from custom_components.eau_grand_lyon.pfas import PfasClient, parse_pfas_html
from custom_components.eau_grand_lyon.sensors.global_sensors import (
    EauGrandLyonVigieauSensor,
)
from custom_components.eau_grand_lyon.sensors.quality import (
    EauGrandLyonPfasMaximumSensor,
    EauGrandLyonPfasMeanSensor,
)
from custom_components.eau_grand_lyon.vigieau import VigieauClient

PFAS_HTML = """
<div class="qualiteAnalyse__text"><b>0,014</b><p>Valeur moyenne des PFAS en µg/L</p></div>
<div class="qualiteAnalyse__text"><b>0,087</b><p>Valeur max des PFAS en µg/L</p></div>
<div class="qualiteAnalyse__text"><b>10</b><p>Nombre de prélèvements sur les 12 derniers mois</p></div>
"""


class _Response:
    def __init__(self, status: int, body: object) -> None:
        self.status = status
        self._body = body if isinstance(body, str) else json.dumps(body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self) -> str:
        return self._body


class _Session:
    def __init__(self, *responses: _Response) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, object]] = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("params")))
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _stub_client_timeout(monkeypatch):
    """Le faux module aiohttp partagé par les tests HA n'expose pas ce type."""
    monkeypatch.setattr(pfas_module.aiohttp, "ClientTimeout", lambda **kwargs: kwargs, raising=False)


def test_parse_confirmed_pfas_html():
    result = parse_pfas_html(PFAS_HTML, "Lyon 1")
    assert result["mean_ug_l"] == 0.014
    assert result["maximum_ug_l"] == 0.087
    assert result["samples_12_months"] == 10
    assert result["conform"] is True


def test_parse_malformed_pfas_html_is_unavailable():
    result = parse_pfas_html("<html>format changed</html>", "Lyon 1")
    assert result["mean_ug_l"] is None
    assert result["maximum_ug_l"] is None
    assert result["conform"] is None


def test_parse_pfas_html_tolerates_nested_markup_and_bad_number():
    html = """
    <div class="qualiteAnalyse__text"><div><b>invalide</b></div><p>Valeur moyenne des PFAS</p></div>
    <div class="qualiteAnalyse__text"><b>0,2</b><p>Valeur max des PFAS</p></div>
    """
    assert parse_pfas_html(html, "Lyon")["mean_ug_l"] is None


@pytest.mark.asyncio
async def test_pfas_client_resolves_commune_parses_page_and_caches():
    session = _Session(
        _Response(200, {"success": True, "data": [{"name": "Lyon 1", "code_postal": "69001"}]}),
        _Response(200, PFAS_HTML),
    )
    client = PfasClient(session)  # type: ignore[arg-type]
    first = await client.async_get("Lyon 1")
    second = await client.async_get("Lyon 1")
    assert first == second
    assert len(session.calls) == 2
    assert session.calls[1][1] == {"ville": "Lyon 1", "code_postal": "69001"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404, 500])
async def test_pfas_client_http_failures_are_empty_and_cached(status):
    session = _Session(_Response(status, "failure"))
    client = PfasClient(session)  # type: ignore[arg-type]
    assert (await client.async_get("Lyon 1"))["mean_ug_l"] is None
    assert (await client.async_get("Lyon 1"))["mean_ug_l"] is None
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_vigieau_client_parses_confirmed_live_shape_and_caches():
    session = _Session(
        _Response(200, [{"nom": "Villeurbanne", "code": "69266"}]),
        _Response(
            200,
            [
                {
                    "nom": "ZONE 8",
                    "niveauGravite": "alerte_renforcee",
                    "arrete": {
                        "dateDebutValidite": "2026-08-24T00:00:00.000Z",
                        "dateFinValidite": "2026-10-31T00:00:00.000Z",
                        "cheminFichier": "https://example.test/arrete.pdf",
                    },
                }
            ],
        ),
    )
    client = VigieauClient(session)  # type: ignore[arg-type]
    first = await client.async_get("Villeurbanne")
    second = await client.async_get("Villeurbanne")
    assert first == second
    assert first["level"] == "alerte_renforcee"
    assert first["commune_code"] == "69266"
    assert first["decree_start_date"] == "2026-08-24"
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_vigieau_uses_most_restrictive_valid_aep_zone():
    session = _Session(
        _Response(200, [{"nom": "Lyon", "code": "69123"}]),
        _Response(
            200,
            [
                {"nom": "Zone normale", "niveauGravite": "normal"},
                {"nom": "Zone inconnue", "niveauGravite": "autre"},
                {"nom": "Zone crise", "niveauGravite": "crise"},
            ],
        ),
    )
    result = await VigieauClient(session).async_get("Lyon")  # type: ignore[arg-type]
    assert result["level"] == "crise"
    assert result["zone_name"] == "Zone crise"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("responses", "expected_calls"),
    [
        ((_Response(200, {}),), 1),
        ((_Response(200, []),), 1),
        ((_Response(200, [{"nom": "Lyon", "code": "69123"}]), _Response(500, "failure")), 2),
        ((_Response(200, [{"nom": "Lyon", "code": "69123"}]), _Response(200, {})), 2),
        ((_Response(200, "not-json"),), 1),
    ],
)
async def test_vigieau_malformed_stages_are_non_blocking(responses, expected_calls):
    session = _Session(*responses)
    assert (await VigieauClient(session).async_get("Lyon"))["level"] is None  # type: ignore[arg-type]
    assert len(session.calls) == expected_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404, 500])
async def test_vigieau_client_http_failures_are_empty_and_cached(status):
    session = _Session(_Response(status, "failure"))
    client = VigieauClient(session)  # type: ignore[arg-type]
    assert (await client.async_get("Villeurbanne"))["level"] is None
    assert (await client.async_get("Villeurbanne"))["level"] is None
    assert len(session.calls) == 1


def _global_entity(cls, data):
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock(entry_id="entry-1")
    entity = cls.__new__(cls)
    entity.coordinator = coordinator
    entity._entry = entry
    return entity


def test_public_entities_are_disabled_by_default_and_expose_values():
    pfas = {
        "pfas_enabled": True,
        "pfas": {
            "commune": "Lyon 1",
            "conform": True,
            "maximum_ug_l": 0.087,
            "mean_ug_l": 0.014,
            "samples_12_months": 10,
            "threshold_ug_l": 0.1,
        },
    }
    mean = _global_entity(EauGrandLyonPfasMeanSensor, pfas)
    maximum = _global_entity(EauGrandLyonPfasMaximumSensor, pfas)
    conform = _global_entity(EauGrandLyonPfasConformSensor, pfas)
    assert mean.native_value == 0.014
    assert maximum.native_value == 0.087
    assert conform.is_on is True
    assert EauGrandLyonPfasMeanSensor._attr_entity_registry_enabled_default is False
    assert EauGrandLyonPfasMaximumSensor._attr_entity_registry_enabled_default is False
    assert EauGrandLyonPfasConformSensor._attr_entity_registry_enabled_default is False

    assert mean.available is True
    assert maximum.available is True
    assert conform.available is True
    assert mean.extra_state_attributes["nombre_prelevements_12_mois"] == 10
    assert maximum.extra_state_attributes["commune"] == "Lyon 1"
    assert conform.extra_state_attributes["valeur_maximale_ug_l"] == 0.087

    vigieau = _global_entity(
        EauGrandLyonVigieauSensor,
        {
            "vigieau_enabled": True,
            "vigieau": {"level": "crise", "commune": "Villeurbanne"},
        },
    )
    assert vigieau.native_value == "crise"
    assert vigieau.available is True
    assert vigieau.extra_state_attributes["commune"] == "Villeurbanne"
    assert EauGrandLyonVigieauSensor._attr_entity_registry_enabled_default is False


def test_public_entity_constructors_keep_new_unique_ids_and_unavailable_state():
    coordinator = MagicMock()
    coordinator.data = {"pfas_enabled": False, "vigieau_enabled": False}
    entry = MagicMock(entry_id="entry-1")

    mean = EauGrandLyonPfasMeanSensor(coordinator, entry)
    maximum = EauGrandLyonPfasMaximumSensor(coordinator, entry)
    conform = EauGrandLyonPfasConformSensor(coordinator, entry)
    vigieau = EauGrandLyonVigieauSensor(coordinator, entry)

    assert mean._attr_unique_id == "entry-1_pfas_mean"
    assert maximum._attr_unique_id == "entry-1_pfas_maximum"
    assert conform._attr_unique_id == "entry-1_pfas_conform"
    assert vigieau._attr_unique_id == "entry-1_vigieau_aep"
    assert mean.available is False
    assert conform.available is False
    assert vigieau.available is False
    assert conform.is_on is False
    assert conform.device_info is not None
