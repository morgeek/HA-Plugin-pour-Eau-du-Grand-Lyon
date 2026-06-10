"""Repairs platform for Eau du Grand Lyon."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

# NOTE: ir.async_create_issue / ir.async_delete_issue are synchronous @callback
# functions in Home Assistant (they return None). Do NOT `await` them — doing so
# raises "'NoneType' object can't be awaited". This wrapper stays `async def`
# only so the coordinator can `await` it uniformly.


async def check_long_outage_issue(hass: HomeAssistant, days: int) -> None:
    """Enregistre ou supprime une issue si la panne dure trop longtemps."""
    issue_id = "long_outage"
    if days >= 7:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="long_outage",
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
