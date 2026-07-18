"""Smoke tests against a REAL Home Assistant install (not the stub-based CI suite).

Run from the repo root with a venv that has pytest-homeassistant-custom-component:

    python -m pytest smoke_tests/test_real_ha.py -v

Only the HTTP layer (EauGrandLyonApi network methods) is mocked — config entry
setup, coordinator refresh, entity creation, statistics injection (real recorder),
services, options flow and unload all run through genuine Home Assistant code.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

DOMAIN = "eau_grand_lyon"

RAW_CONTRACT = {
    "id": "123",
    "reference": "REF1",
    "statutExtrait": {"libelle": "Actif"},
    "dateEffet": "2020-01-01",
    "dateEcheance": "2026-12-31",
    "conditionPaiement": {
        "compteClient": {"solde": {"value": 12.5}},
        "mensualise": True,
        "modePaiement": {"libelle": "Prélèvement"},
    },
    "servicesSouscrits": [
        {
            "calibreCompteur": {"libelle": "15"},
            "usage": {"libelle": "Domestique"},
            "nombreHabitants": {"libelle": "2 personnes"},
        }
    ],
    "espaceDeLivraison": {"reference": "PDS1"},
}

MONTHLY = [{"mois": m, "annee": 2025, "consommation": 10.0} for m in range(1, 13)]

EMPTY_QUALITY = {
    "durete_fh": 28.0,
    "nitrates_mgl": 20.0,
    "chlore_mgl": 0.2,
    "turbidite_ntu": None,
    "commune": "LYON",
    "date_analyse": "2026-06-01",
    "source": "Open Data Metropole de Lyon",
}

NO_DAILY = {"entries": [], "source": "Aucune", "nb_entries": 0, "last_date": None}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Allow loading the integration from custom_components/.

    recorder_mock is requested FIRST: the recorder harness asserts that the hass
    fixture has not been created yet, and enable_custom_integrations depends on hass.
    """
    yield


def _patch_api():
    """Patch only the network methods of the real EauGrandLyonApi class."""
    from custom_components.eau_grand_lyon.api import EauGrandLyonApi

    patches = {
        "authenticate": AsyncMock(return_value="token"),
        "async_revoke_token": AsyncMock(),
        "get_contracts": AsyncMock(return_value=[RAW_CONTRACT]),
        "get_alertes": AsyncMock(return_value=[]),
        "get_water_quality": AsyncMock(return_value=EMPTY_QUALITY),
        "get_interventions": AsyncMock(return_value=[]),
        "get_monthly_consumptions": AsyncMock(return_value=MONTHLY),
        "get_daily_consumptions": AsyncMock(return_value=NO_DAILY),
        "get_date_prochaine_facture": AsyncMock(return_value="2026-09-01"),
        "get_point_de_service_etendu": AsyncMock(return_value={}),
        "get_alerte_surconsommation": AsyncMock(
            return_value={
                "seuil_surconso_jour_m3": 4.6,
                "seuil_surconso_mois_m3": 138.0,
                "abonne_alerte_fuite": True,
            }
        ),
    }
    return [patch.object(EauGrandLyonApi, name, mock) for name, mock in patches.items()]


async def _setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={"email": "user@example.com", "password": "secret", "tarif_m3": 5.2},
        options={},
    )
    entry.add_to_hass(hass)
    patchers = _patch_api()
    for p in patchers:
        p.start()
    try:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    finally:
        for p in patchers:
            p.stop()
    return entry


async def test_all_modules_import_under_real_ha(hass: HomeAssistant) -> None:
    """Every module must import with the real homeassistant package."""
    import importlib

    for mod in (
        "custom_components.eau_grand_lyon",
        "custom_components.eau_grand_lyon.api",
        "custom_components.eau_grand_lyon.api.auth",
        "custom_components.eau_grand_lyon.api.client",
        "custom_components.eau_grand_lyon.api.endpoints",
        "custom_components.eau_grand_lyon.binary_sensor",
        "custom_components.eau_grand_lyon.button",
        "custom_components.eau_grand_lyon.calendar",
        "custom_components.eau_grand_lyon.config_flow",
        "custom_components.eau_grand_lyon.const",
        "custom_components.eau_grand_lyon.coordinator",
        "custom_components.eau_grand_lyon.device",
        "custom_components.eau_grand_lyon.diagnostics",
        "custom_components.eau_grand_lyon.repairs",
        "custom_components.eau_grand_lyon.sensor",
        "custom_components.eau_grand_lyon.switch",
        "custom_components.eau_grand_lyon.sensors.base",
        "custom_components.eau_grand_lyon.sensors.consumption",
        "custom_components.eau_grand_lyon.sensors.contract",
        "custom_components.eau_grand_lyon.sensors.cost",
        "custom_components.eau_grand_lyon.sensors.experimental",
        "custom_components.eau_grand_lyon.sensors.global_sensors",
        "custom_components.eau_grand_lyon.sensors.intelligence",
        "custom_components.eau_grand_lyon.sensors.quality",
    ):
        importlib.import_module(mod)

    # Recorder must be importable; StatisticMeanType may be absent on older HA,
    # in which case the has_mean fallback must be active (regression: the old code
    # disabled ALL statistics injection when StatisticMeanType was missing).
    from custom_components.eau_grand_lyon import coordinator as coord_mod

    assert coord_mod._HAS_RECORDER is True
    print(
        "statistics path:",
        "mean_type" if coord_mod.StatisticMeanType is not None else "has_mean fallback",
    )


async def test_setup_creates_entities_and_services(hass: HomeAssistant, caplog) -> None:
    """Full config-entry setup with real HA: entities, statistics, services, unload."""
    entry = await _setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED

    # Entities created with correct values (real entity platform + registry)
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert len(entities) > 20

    def state_of(unique_id):
        ent = next(e for e in entities if e.unique_id == unique_id)
        return hass.states.get(ent.entity_id)

    conso = state_of(f"{entry.entry_id}_REF1_conso_courant")
    assert conso is not None and float(conso.state) == 10.0

    cout = state_of(f"{entry.entry_id}_REF1_cout_mois")
    assert cout is not None and float(cout.state) == 52.0  # 10 m³ × 5.2 €
    assert cout.attributes["unit_of_measurement"] == "EUR"

    coaching = state_of(f"{entry.entry_id}_REF1_coaching")
    assert coaching is not None and coaching.state not in ("unknown", "unavailable")

    # Statistics injected through the REAL recorder without errors
    await async_wait_recording_done(hass)
    assert "Failed to inject statistics" not in caplog.text
    assert "Failed to inject cost statistics" not in caplog.text

    # Services registered
    for service in ("clear_cache", "update_now", "export_data", "download_latest_invoice"):
        assert hass.services.has_service(DOMAIN, service)

    # Unload cleanly (also closes the aiohttp session)
    with patch(
        "custom_components.eau_grand_lyon.api.client.EauGrandLyonApi.async_revoke_token",
        new=AsyncMock(),
    ):
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_options_flow_shows_form(hass: HomeAssistant) -> None:
    """Options flow must open (validates OptionsFlow.config_entry + new commune field)."""
    entry = await _setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert result["step_id"] == "init"
    schema_keys = {str(k) for k in result["data_schema"].schema}
    assert "water_quality_commune" in schema_keys

    with patch(
        "custom_components.eau_grand_lyon.api.client.EauGrandLyonApi.async_revoke_token",
        new=AsyncMock(),
    ):
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_export_service_rejects_disallowed_path(hass: HomeAssistant) -> None:
    """export_data must refuse paths outside allowlist_external_dirs."""
    from homeassistant.exceptions import ServiceValidationError

    entry = await _setup_entry(hass)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "export_data",
            {"path": "/definitely/not/allowed/out.csv"},
            blocking=True,
        )

    with patch(
        "custom_components.eau_grand_lyon.api.client.EauGrandLyonApi.async_revoke_token",
        new=AsyncMock(),
    ):
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
