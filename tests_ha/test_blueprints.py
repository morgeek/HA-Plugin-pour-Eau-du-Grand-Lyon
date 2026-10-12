"""Les blueprints fournis se chargent et se comportent comme documenté dans un vrai Home Assistant."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

REPO_ROOT = Path(__file__).resolve().parent.parent
BLUEPRINT_DIR = REPO_ROOT / "blueprints" / "automation" / "eau_grand_lyon"
VIGIEAU_SENSOR = "sensor.eau_du_grand_lyon_niveau_officiel_vigieau"
VIGIEAU_ATTRIBUTES = {"arrete_url": "https://example.invalid/arrete.pdf", "arrete_fin": "2026-10-31"}

# Entrées obligatoires (sans valeur par défaut) de chaque blueprint.
REQUIRED_INPUTS = {
    "alerte_budget.yaml": {"sensor_cout": "sensor.eau_du_grand_lyon_cout_estime_du_mois_courant"},
    "alerte_coupure.yaml": {
        "binary_sensor_coupure": "binary_sensor.eau_du_grand_lyon_interruption_de_service_travaux_coupure"
    },
    "alerte_fuite.yaml": {
        "sensor_fuite": "binary_sensor.eau_du_grand_lyon_alerte_surconsommation_mensuelle_heuristique"
    },
    "alerte_secheresse.yaml": {"sensor_secheresse": "sensor.eau_du_grand_lyon_niveau_de_secheresse"},
    "alerte_vigieau.yaml": {"sensor_vigieau": VIGIEAU_SENSOR},
}


@pytest.fixture
def blueprints_in_config(hass: HomeAssistant, tmp_path: Path) -> None:
    """Expose les blueprints du dépôt comme s'ils étaient importés dans /config/blueprints."""
    hass.config.config_dir = str(tmp_path)
    shutil.copytree(BLUEPRINT_DIR, tmp_path / "blueprints" / "automation" / "eau_grand_lyon")


def _automation(name: str, inputs: dict[str, object]) -> dict[str, object]:
    return {
        "id": name.removesuffix(".yaml"),
        "alias": name.removesuffix(".yaml"),
        "use_blueprint": {
            "path": f"eau_grand_lyon/{name}",
            "input": {**inputs, "service_notification": "notify.test"},
        },
    }


def test_every_shipped_blueprint_is_covered() -> None:
    assert sorted(path.name for path in BLUEPRINT_DIR.glob("*.yaml")) == sorted(REQUIRED_INPUTS)


async def test_every_blueprint_loads_as_a_valid_automation(hass: HomeAssistant, blueprints_in_config: None) -> None:
    async_mock_service(hass, "notify", "test")
    config = [_automation(name, inputs) for name, inputs in REQUIRED_INPUTS.items()]

    assert await async_setup_component(hass, "automation", {"automation": config})
    await hass.async_block_till_done()

    for name in REQUIRED_INPUTS:
        state = hass.states.get(f"automation.{name.removesuffix('.yaml')}")
        assert state is not None, name
        assert state.state == STATE_ON, f"{name} invalide : {state.attributes}"


async def test_vigieau_blueprint_notifies_only_on_real_level_changes(
    hass: HomeAssistant, blueprints_in_config: None
) -> None:
    calls: list[ServiceCall] = async_mock_service(hass, "notify", "test")
    hass.states.async_set(VIGIEAU_SENSOR, "vigilance", VIGIEAU_ATTRIBUTES)
    assert await async_setup_component(
        hass, "automation", {"automation": [_automation("alerte_vigieau.yaml", REQUIRED_INPUTS["alerte_vigieau.yaml"])]}
    )
    await hass.async_block_till_done()

    async def set_level(level: str) -> None:
        hass.states.async_set(VIGIEAU_SENSOR, level, VIGIEAU_ATTRIBUTES)
        await hass.async_block_till_done()

    await set_level("crise")
    assert len(calls) == 1
    assert calls[0].data["title"] == "🚱 Restriction d'eau — Crise"
    assert "2026-10-31" in calls[0].data["message"]
    assert calls[0].data["data"]["actions"][0]["uri"] == "https://example.invalid/arrete.pdf"

    # Retour d'une indisponibilité (redémarrage, source en panne) : pas de notification.
    await set_level(STATE_UNAVAILABLE)
    await set_level("crise")
    # Niveau non sélectionné par défaut : pas de notification.
    await set_level("vigilance")
    assert len(calls) == 1

    await set_level("alerte_renforcee")
    assert len(calls) == 2
    assert calls[1].data["title"] == "🚱 Restriction d'eau — Alerte renforcée"


async def test_drought_blueprint_ignores_restarts_and_labels_official_levels(
    hass: HomeAssistant, blueprints_in_config: None
) -> None:
    sensor = "sensor.eau_du_grand_lyon_niveau_de_secheresse"
    calls: list[ServiceCall] = async_mock_service(hass, "notify", "test")
    hass.states.async_set(sensor, "normal")
    assert await async_setup_component(
        hass,
        "automation",
        {"automation": [_automation("alerte_secheresse.yaml", REQUIRED_INPUTS["alerte_secheresse.yaml"])]},
    )
    await hass.async_block_till_done()

    async def set_level(level: str) -> None:
        hass.states.async_set(sensor, level)
        await hass.async_block_till_done()

    await set_level("alerte_renforcee")
    assert len(calls) == 1
    assert calls[0].data["title"] == "🌵 Alerte Sécheresse — Alerte renforcée"

    # Redémarrage : le capteur repasse par « unavailable » sans nouvelle notification.
    await set_level(STATE_UNAVAILABLE)
    await set_level("alerte_renforcee")
    assert len(calls) == 1
