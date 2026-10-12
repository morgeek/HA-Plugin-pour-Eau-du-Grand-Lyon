"""Cycle de vie complet de l'intégration dans un vrai Home Assistant."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eau_grand_lyon.api import HttpError

from .conftest import NOW

REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCUMENTED_ID = re.compile(r"\b(?:sensor|binary_sensor|button|switch|calendar)\.eau_du_grand_lyon_[a-z0-9_]+")


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, freezer: FrozenDateTimeFactory) -> None:
    freezer.move_to(NOW)
    # Les entity_id sont générés depuis les noms traduits dans la langue du système.
    hass.config.language = "fr"
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _enable(hass: HomeAssistant, entry: MockConfigEntry, *entity_ids: str) -> None:
    registry = er.async_get(hass)
    for entity_id in entity_ids:
        registry.async_update_entity(entity_id, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_documented_entity_ids_exist(
    hass: HomeAssistant, mock_api: dict[str, AsyncMock], config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """Chaque entity_id cité dans le README et dans lovelace/ est réellement créé."""
    await _setup(hass, config_entry, freezer)
    assert config_entry.state is ConfigEntryState.LOADED

    created = {
        entry.entity_id for entry in er.async_entries_for_config_entry(er.async_get(hass), config_entry.entry_id)
    }
    documents = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "lovelace").glob("*"))]
    documented = {
        (match, path.name) for path in documents for match in _DOCUMENTED_ID.findall(path.read_text(encoding="utf-8"))
    }
    missing = sorted(f"{entity_id} ({source})" for entity_id, source in documented if entity_id not in created)
    assert documented
    assert not missing, (
        "entity_id documentés mais inexistants :\n"
        + "\n".join(missing)
        + "\nCRÉÉS(switch/button/calendar): "
        + ", ".join(sorted(e for e in created if not e.startswith(("sensor.", "binary_sensor."))))
    )


async def test_states_reflect_provider_data(
    hass: HomeAssistant, mock_api: dict[str, AsyncMock], config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    await _setup(hass, config_entry, freezer)

    assert hass.states.get("sensor.eau_du_grand_lyon_consommation_mois_courant").state == "6.0"
    # Le 12 octobre n'a pas d'index publié (`null`) : l'index reste celui du 11, jamais 0.
    assert hass.states.get("sensor.eau_du_grand_lyon_index_compteur").state == "1002.2"
    assert hass.states.get("sensor.eau_du_grand_lyon_index_journalier_teleo").state == "1002.2"
    assert hass.states.get("sensor.eau_du_grand_lyon_consommation_7_derniers_jours").state == "1.25"
    assert hass.states.get("sensor.eau_du_grand_lyon_niveau_de_secheresse").state == "normal"

    await _enable(
        hass,
        config_entry,
        "sensor.eau_du_grand_lyon_prediction_consommation_mois",
        "sensor.eau_du_grand_lyon_niveau_officiel_vigieau",
        "sensor.eau_du_grand_lyon_sante_de_l_integration",
    )
    # 2,25 m³ sur les 12 premiers jours d'octobre, extrapolés sur 31 jours.
    assert hass.states.get("sensor.eau_du_grand_lyon_prediction_consommation_mois").state == "5.8"
    assert hass.states.get("sensor.eau_du_grand_lyon_niveau_officiel_vigieau").state == "crise"
    assert hass.states.get("sensor.eau_du_grand_lyon_sante_de_l_integration").state == "ok"


async def test_optional_interventions_error_keeps_integration_loaded(
    hass: HomeAssistant, mock_api: dict[str, AsyncMock], config_entry: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    """Une erreur 500 sur l'endpoint secondaire des interventions ne fait pas échouer le cycle."""
    mock_api["get_interventions"].side_effect = HttpError(500, "GET", "/interventions", "boom")

    await _setup(hass, config_entry, freezer)

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.eau_du_grand_lyon_consommation_mois_courant").state == "6.0"


async def test_unload_then_remove_deletes_persistent_caches(
    hass: HomeAssistant,
    hass_storage: dict[str, object],
    mock_api: dict[str, AsyncMock],
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _setup(hass, config_entry, freezer)
    keys = [
        f"eau_grand_lyon_{config_entry.entry_id}_{name}" for name in ("history", "monthly_history", "daily_history")
    ]
    assert all(key in hass_storage for key in keys)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    mock_api["async_revoke_token"].assert_awaited()

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert not any(key in hass_storage for key in keys)
    # Régression : fermer soi-même la session HA déclenchait un avertissement
    # « closes the Home Assistant aiohttp session … create a bug report ».
    assert "closes the Home Assistant aiohttp session" not in caplog.text
