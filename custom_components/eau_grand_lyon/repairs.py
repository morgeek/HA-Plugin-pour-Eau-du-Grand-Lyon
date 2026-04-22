"""Repairs platform for Eau du Grand Lyon."""
from __future__ import annotations

from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str] | None,
) -> ConfirmRepairFlow | None:
    """Crée un flux de correction pour une issue."""
    if issue_id == "drought_alert":
        return ConfirmRepairFlow()
    return None

def async_check_drought_issue(hass: HomeAssistant, level: str) -> None:
    """Enregistre ou supprime une issue de sécheresse selon le niveau."""
    issue_id = "drought_alert"
    if level in ["Alerte", "Alerte Renforcée", "Crise"]:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING if level != "Crise" else ir.IssueSeverity.ERROR,
            translation_key="drought_alert",
            translation_placeholders={"level": level},
            learn_more_url="https://www.rhone.gouv.fr/Politiques-publiques/Environnement/Eau/Secheresse",
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
