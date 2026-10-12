"""Statistiques long terme injectées dans un vrai Recorder (base SQLite en mémoire)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.statistics import list_statistic_ids
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from .conftest import NOW


@pytest.fixture
def mock_recorder_before_hass(async_test_recorder: Any) -> None:
    """Prépare la base du Recorder avant la création de l'instance hass."""


async def test_external_statistics_are_injected_into_the_recorder(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_api: dict[str, AsyncMock],
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    freezer.move_to(NOW)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)

    statistic_ids = {
        item["statistic_id"]
        for item in await recorder_mock.async_add_executor_job(list_statistic_ids, hass)
        if item["statistic_id"].startswith("eau_grand_lyon:")
    }
    assert statistic_ids == {
        "eau_grand_lyon:water_ab1234567890",
        "eau_grand_lyon:water_daily_ab1234567890",
        "eau_grand_lyon:cost_ab1234567890",
        "eau_grand_lyon:cost_daily_ab1234567890",
    }
