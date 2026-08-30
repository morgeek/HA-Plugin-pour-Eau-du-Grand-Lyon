"""Smoke-test ConfigFlow against an installed, real Home Assistant package."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from homeassistant import config_entries

from custom_components.eau_grand_lyon import _async_update_options
from custom_components.eau_grand_lyon.config_flow import EauGrandLyonConfigFlow
from custom_components.eau_grand_lyon.const import CONF_EMAIL, CONF_PASSWORD, CONF_TARIF_M3, DOMAIN


class _FlowManager:
    def async_progress_by_handler(self, *args, **kwargs):
        return []

    def async_abort(self, flow_id):
        raise AssertionError(f"Unexpected flow abort request: {flow_id}")


class _ConfigEntries:
    def __init__(self, entry):
        self.entry = entry
        self.flow = _FlowManager()
        self.update_calls = 0
        self.reload_calls = 0

    def async_get_entry(self, entry_id):
        return self.entry if entry_id == self.entry.entry_id else None

    def async_get_known_entry(self, entry_id):
        entry = self.async_get_entry(entry_id)
        if entry is None:
            raise AssertionError(f"Unknown smoke-test entry: {entry_id}")
        return entry

    def async_entry_for_domain_unique_id(self, domain, unique_id):
        if domain == DOMAIN and unique_id == self.entry.unique_id:
            return self.entry
        return None

    def async_update_entry(self, entry, *, data, **kwargs):
        self.update_calls += 1
        entry.data = dict(data)
        return True

    async def async_reload(self, entry_id):
        assert entry_id == self.entry.entry_id
        self.reload_calls += 1


class _Hass:
    """Small hashable HA stand-in; ConfigFlow 2024.11 keys notifications by hass."""

    def __init__(self, config_entries_manager):
        self.config_entries = config_entries_manager
        self.data = {}


async def _exercise_step(step_name: str, source: str, reason: str, expect_modern: bool) -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        unique_id="old@example.com",
        data={
            CONF_EMAIL: "old@example.com",
            CONF_PASSWORD: "old-password",
            "account_setting": "kept",
        },
        options={CONF_TARIF_M3: 4.8, "option_setting": "kept"},
    )
    manager = _ConfigEntries(entry)
    hass = _Hass(manager)
    flow = EauGrandLyonConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.flow_id = "smoke-flow"
    flow.context = {"source": source, "entry_id": entry.entry_id}

    with patch(
        "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
        new=AsyncMock(return_value={}),
    ):
        result = await getattr(flow, step_name)(
            {
                CONF_EMAIL: " OLD@example.com ",
                CONF_PASSWORD: "new-password",
            }
        )

    assert result["reason"] == reason
    assert manager.update_calls == 1
    assert manager.reload_calls == 0
    assert entry.data == {
        CONF_EMAIL: "OLD@example.com",
        CONF_PASSWORD: "new-password",
        "account_setting": "kept",
    }
    assert entry.options == {CONF_TARIF_M3: 4.8, "option_setting": "kept"}

    await _async_update_options(hass, entry)
    assert manager.reload_calls == 1
    assert hasattr(config_entries.ConfigFlow, "async_update_and_abort") is expect_modern


async def _main(expect_modern: bool) -> None:
    await _exercise_step(
        "async_step_reauth_confirm",
        "reauth",
        "reauth_successful",
        expect_modern,
    )
    await _exercise_step(
        "async_step_reconfigure",
        "reconfigure",
        "reconfigure_successful",
        expect_modern,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-modern", choices=("yes", "no"), required=True)
    args = parser.parse_args()
    asyncio.run(_main(args.expect_modern == "yes"))
