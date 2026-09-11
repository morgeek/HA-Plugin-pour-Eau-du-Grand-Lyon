"""Tests for the isolated Hub'Eau drinking-water quality client."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.eau_grand_lyon import hubeau as hubeau_module
from custom_components.eau_grand_lyon.hubeau import (
    FAILURE_CACHE_SECONDS,
    HUBEAU_COMMUNES_UDI_URL,
    HUBEAU_PARAM_CHLORINE,
    HUBEAU_PARAM_HARDNESS,
    HUBEAU_PARAM_NITRATES,
    HUBEAU_PARAM_TURBIDITY,
    HUBEAU_RESULTATS_DIS_URL,
    SUCCESS_CACHE_SECONDS,
    HubeauWaterQualityClient,
    _latest_measurement,
)


class _ClientError(Exception):
    pass


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
    def __init__(self, *responses: _Response | BaseException) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.fixture(autouse=True)
def _aiohttp_types(monkeypatch):
    monkeypatch.setattr(
        hubeau_module.aiohttp,
        "ClientTimeout",
        lambda **kwargs: SimpleNamespace(**kwargs),
        raising=False,
    )
    monkeypatch.setattr(hubeau_module.aiohttp, "ClientError", _ClientError, raising=False)


def _commune_row(
    *,
    code: str = "69123",
    name: str = "LYON",
    network: str = "069000069",
    network_name: str = "CENTRE (METROPOLE LYON)",
    year: str = "2026",
) -> dict[str, object]:
    return {
        "code_commune": code,
        "nom_commune": name,
        "code_reseau": network,
        "nom_reseau": network_name,
        "annee": year,
    }


_UNITS = {
    HUBEAU_PARAM_HARDNESS: ("28", "°f"),
    HUBEAU_PARAM_NITRATES: ("162", "mg/L"),
    HUBEAU_PARAM_CHLORINE: ("165", "mg(Cl2)/L"),
    HUBEAU_PARAM_TURBIDITY: ("232", "NFU"),
}


def _result_row(
    parameter: str,
    value: object,
    *,
    sampled_at: object = "2026-08-20T12:00:00Z",
    commune_code: str = "69123",
    network: str = "069000069",
    unit_code: str | None = None,
    unit_label: str | None = None,
    sample: str = "SAMPLE-1",
) -> dict[str, object]:
    expected_code, expected_label = _UNITS[parameter]
    return {
        "code_commune": commune_code,
        "code_prelevement": sample,
        "date_prelevement": sampled_at,
        "code_parametre": parameter,
        "resultat_numerique": value,
        "code_unite": expected_code if unit_code is None else unit_code,
        "libelle_unite": expected_label if unit_label is None else unit_label,
        "code_installation_amont": network,
        "nom_installation_amont": "CENTRE (METROPOLE LYON)",
        "reseaux": [{"code": network, "nom": "CENTRE (METROPOLE LYON)"}],
    }


def _successful_session(*, commune_status: int = 200, result_status: int = 200) -> _Session:
    return _Session(
        _Response(commune_status, {"data": [_commune_row()]}),
        _Response(result_status, {"data": [_result_row(HUBEAU_PARAM_HARDNESS, 18.7)]}),
        _Response(result_status, {"data": [_result_row(HUBEAU_PARAM_NITRATES, 4.6)]}),
        _Response(result_status, {"data": [_result_row(HUBEAU_PARAM_CHLORINE, 0.15)]}),
        _Response(result_status, {"data": [_result_row(HUBEAU_PARAM_TURBIDITY, 0.11)]}),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 206])
async def test_exact_commune_and_confirmed_parameter_mappings(status):
    session = _successful_session(commune_status=status, result_status=status)
    result = await HubeauWaterQualityClient(session).async_get_water_quality("lyon")  # type: ignore[arg-type]

    assert result == {
        "durete_fh": 18.7,
        "nitrates_mgl": 4.6,
        "chlore_mgl": 0.15,
        "turbidite_ntu": 0.11,
        "commune": "LYON",
        "date_analyse": "2026-08-20",
        "source": "Hub'Eau / Ministère chargé de la Santé",
        "unite_turbidite": "NFU",
        "code_commune": "69123",
        "code_reseau": "069000069",
        "nom_reseau": "CENTRE (METROPOLE LYON)",
    }
    assert session.calls[0][0] == HUBEAU_COMMUNES_UDI_URL
    assert all(url == HUBEAU_RESULTATS_DIS_URL for url, _ in session.calls[1:])
    params = [call[1]["params"] for call in session.calls[1:]]
    assert {item["code_parametre"] for item in params} == set(_UNITS)
    assert all(item["sort"] == "desc" and item["size"] == "20" for item in params)
    assert not any(
        private_key in str(session.calls)
        for private_key in ("email", "password", "token", "cookie", "contract", "meter")
    )


@pytest.mark.asyncio
async def test_empty_commune_is_unavailable_without_http_call():
    session = _Session()
    result = await HubeauWaterQualityClient(session).async_get_water_quality("  ")  # type: ignore[arg-type]
    assert result["commune"] is None
    assert result["durete_fh"] is None
    assert session.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"data": []},
        {"data": [_commune_row(code="75056", name="PARIS")]},
        {"data": [_commune_row(code="69123"), _commune_row(code="69001")]},
    ],
)
async def test_unknown_foreign_or_ambiguous_commune_never_falls_back(payload):
    session = _Session(_Response(200, payload))
    result = await HubeauWaterQualityClient(session).async_get_water_quality("Lyon")  # type: ignore[arg-type]
    assert result["commune"] is None
    assert result["durete_fh"] is None
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_commune_without_current_udi_is_unavailable():
    row = _commune_row()
    row["code_reseau"] = None
    session = _Session(_Response(200, {"data": [row]}))
    result = await HubeauWaterQualityClient(session).async_get_water_quality("Lyon")  # type: ignore[arg-type]
    assert result["commune"] is None


@pytest.mark.asyncio
async def test_resolved_commune_with_no_valid_measurements_keeps_diagnostics():
    session = _Session(
        _Response(200, {"data": [_commune_row()]}),
        *(_Response(200, {"data": []}) for _ in range(4)),
    )
    result = await HubeauWaterQualityClient(session).async_get_water_quality("Lyon")  # type: ignore[arg-type]
    assert result["commune"] == "LYON"
    assert result["code_commune"] == "69123"
    assert result["date_analyse"] is None


@pytest.mark.asyncio
async def test_multiple_udis_use_latest_year_and_latest_valid_measurement():
    commune_rows = [
        _commune_row(network="OLD", year="2025"),
        _commune_row(network="UDI-A", network_name="NETWORK A"),
        _commune_row(network="UDI-B", network_name="NETWORK B"),
    ]
    latest = _result_row(
        HUBEAU_PARAM_HARDNESS,
        22.0,
        sampled_at="2026-08-21T09:00:00Z",
        network="UDI-B",
        sample="B",
    )
    older = _result_row(
        HUBEAU_PARAM_HARDNESS,
        19.0,
        sampled_at="2026-08-19T09:00:00Z",
        network="UDI-A",
        sample="A",
    )
    session = _Session(
        _Response(200, {"data": commune_rows}),
        _Response(200, {"data": [older, latest]}),
        _Response(200, {"data": []}),
        _Response(200, {"data": []}),
        _Response(200, {"data": []}),
    )
    result = await HubeauWaterQualityClient(session).async_get_water_quality("LYON")  # type: ignore[arg-type]

    assert result["durete_fh"] == 22.0
    assert result["code_reseau"] == "UDI-B"
    assert result["nom_reseau"] == "NETWORK B"
    assert session.calls[1][1]["params"]["code_reseau"] == "UDI-A,UDI-B"


@pytest.mark.asyncio
async def test_hyphenated_commune_uses_bounded_search_terms_without_relaxing_exact_match():
    session = _Session(_Response(200, {"data": [_commune_row(name="SAINT-PRIEST", code="69290")]}))
    client = HubeauWaterQualityClient(session)  # type: ignore[arg-type]
    client._fetch_measurements = AsyncMock(return_value={})
    await client.async_get_water_quality("Saint-Priest")
    assert session.calls[0][1]["params"]["nom_commune"] == "Saint Priest"


def test_defensive_measurement_validation_and_ordering():
    valid_old = _result_row(HUBEAU_PARAM_TURBIDITY, 0.3, sampled_at="2026-08-19", sample="A")
    valid_zero = _result_row(HUBEAU_PARAM_TURBIDITY, 0, sampled_at="2026-08-20", sample="B")
    invalid_rows = [
        _result_row(HUBEAU_PARAM_TURBIDITY, None, sampled_at="2026-08-25"),
        _result_row(HUBEAU_PARAM_TURBIDITY, "not-a-number", sampled_at="2026-08-25"),
        _result_row(HUBEAU_PARAM_TURBIDITY, float("nan"), sampled_at="2026-08-25"),
        _result_row(HUBEAU_PARAM_TURBIDITY, 1.0, sampled_at=None),
        _result_row(HUBEAU_PARAM_TURBIDITY, 1.0, sampled_at="invalid"),
        _result_row(HUBEAU_PARAM_TURBIDITY, 1.0, commune_code="69266"),
        {**_result_row(HUBEAU_PARAM_TURBIDITY, 1.0), "code_parametre": HUBEAU_PARAM_HARDNESS},
        _result_row(HUBEAU_PARAM_TURBIDITY, 1.0, unit_code="999", unit_label="NTU"),
    ]
    measurement = _latest_measurement(
        [valid_zero, *invalid_rows, valid_old],
        commune_code="69123",
        parameter_code=HUBEAU_PARAM_TURBIDITY,
    )
    assert measurement is not None
    assert measurement.value == 0.0
    assert measurement.sampled_at.isoformat() == "2026-08-20T00:00:00+00:00"


def test_unit_label_is_used_only_when_unit_code_is_absent():
    row = _result_row(HUBEAU_PARAM_NITRATES, 3.2)
    row.pop("code_unite")
    measurement = _latest_measurement(
        [row],
        commune_code="69123",
        parameter_code=HUBEAU_PARAM_NITRATES,
    )
    assert measurement is not None
    assert measurement.value == 3.2


def test_network_metadata_is_exposed_only_when_unambiguous():
    networks = [
        {"code": "UDI-A", "name": "Network A"},
        {"code": "UDI-B", "name": "Network B"},
    ]
    resolve = HubeauWaterQualityClient._network_for_row
    assert resolve({"code_installation_amont": "UDI-B"}, networks) == networks[1]
    assert resolve({}, networks) is None
    assert resolve({"reseaux": "invalid"}, networks) is None
    assert resolve({"reseaux": [None, {"code": "UDI-A"}]}, networks) == networks[0]
    assert resolve({"reseaux": [{"code": "UDI-A"}, {"code": "UDI-B"}]}, networks) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404, 429, 500])
async def test_http_errors_are_non_blocking_and_cached(status):
    session = _Session(_Response(status, {"error": "failure"}))
    client = HubeauWaterQualityClient(session)  # type: ignore[arg-type]
    assert (await client.async_get_water_quality("Lyon"))["durete_fh"] is None
    assert (await client.async_get_water_quality("Lyon"))["durete_fh"] is None
    assert len(session.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        _Response(200, "not-json"),
        _Response(200, "<html>maintenance</html>"),
        _Response(200, {}),
        _Response(200, {"data": {}}),
        _Response(200, {"data": [None, "bad"]}),
    ],
)
async def test_invalid_communes_payload_is_unavailable(response):
    session = _Session(response)
    result = await HubeauWaterQualityClient(session).async_get_water_quality("Lyon")  # type: ignore[arg-type]
    assert result["commune"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_result", ["not-json", "<html>maintenance</html>", {}, {"data": {}}])
async def test_invalid_results_payload_invalidates_only_hubeau(bad_result):
    session = _Session(
        _Response(200, {"data": [_commune_row()]}),
        _Response(200, bad_result),
        _Response(200, {"data": []}),
        _Response(200, {"data": []}),
        _Response(200, {"data": []}),
    )
    result = await HubeauWaterQualityClient(session).async_get_water_quality("Lyon")  # type: ignore[arg-type]
    assert result["durete_fh"] is None
    assert result["commune"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError(), _ClientError("network")])
async def test_timeout_and_client_error_are_non_blocking(error):
    session = _Session(error)
    result = await HubeauWaterQualityClient(session).async_get_water_quality("Lyon")  # type: ignore[arg-type]
    assert result["durete_fh"] is None


@pytest.mark.asyncio
async def test_success_cache_lasts_24_hours(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(hubeau_module.time, "monotonic", lambda: clock[0])
    session = _Session(_Response(200, {"data": []}), _Response(200, {"data": []}))
    client = HubeauWaterQualityClient(session)  # type: ignore[arg-type]

    await client.async_get_water_quality("Unknown")
    clock[0] += SUCCESS_CACHE_SECONDS - 1
    await client.async_get_water_quality("unknown")
    assert len(session.calls) == 1

    clock[0] += 2
    await client.async_get_water_quality("Unknown")
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_failure_cache_retries_after_15_minutes(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(hubeau_module.time, "monotonic", lambda: clock[0])
    session = _Session(_Response(500, {}), _Response(500, {}))
    client = HubeauWaterQualityClient(session)  # type: ignore[arg-type]

    await client.async_get_water_quality("Lyon")
    clock[0] += FAILURE_CACHE_SECONDS - 1
    await client.async_get_water_quality("lyon")
    assert len(session.calls) == 1

    clock[0] += 2
    await client.async_get_water_quality("Lyon")
    assert len(session.calls) == 2


def test_old_grand_lyon_water_quality_endpoint_cannot_return():
    root = Path(__file__).parents[1] / "custom_components" / "eau_grand_lyon"
    runtime = "\n".join((root / path).read_text() for path in ("api/client.py", "coordinator.py", "hubeau.py"))
    assert "data.grandlyon.com" not in runtime
    assert not hasattr(hubeau_module, "PfasClient")
    assert not hasattr(hubeau_module, "VigieauClient")


def test_quality_sensor_unique_ids_remain_unchanged():
    from custom_components.eau_grand_lyon.sensors.quality import (
        EauGrandLyonChloreSensor,
        EauGrandLyonNitratesSensor,
        EauGrandLyonWaterHardnessSensor,
    )

    coordinator = MagicMock()
    coordinator.data = {}
    entry = MagicMock(entry_id="entry-1")
    assert EauGrandLyonWaterHardnessSensor(coordinator, entry)._attr_unique_id == "entry-1_water_hardness_live"
    assert EauGrandLyonNitratesSensor(coordinator, entry)._attr_unique_id == "entry-1_nitrates"
    assert EauGrandLyonChloreSensor(coordinator, entry)._attr_unique_id == "entry-1_chlore"
