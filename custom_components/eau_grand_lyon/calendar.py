"""Calendar platform for Eau du Grand Lyon."""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les calendriers depuis une config entry."""
    from .coordinator import EauGrandLyonCoordinator
    
    coordinator = entry.runtime_data
    async_add_entities([EauGrandLyonCalendar(coordinator, entry)])

class EauGrandLyonCalendar(CalendarEntity):
    """Calendrier des échéances Eau du Grand Lyon."""

    _attr_has_entity_name = True
    _attr_name = "Échéances & Facturation"

    def __init__(self, coordinator: Any, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._event: CalendarEvent | None = None

    @property
    def event(self) -> CalendarEvent | None:
        return self._event

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        events = []
        data = self.coordinator.data or {}

        for ref, contract in data.get("contracts", {}).items():
            # Date de paiement
            pay_date = contract.get("next_payment_date")
            if pay_date:
                dt = datetime.strptime(pay_date, "%Y-%m-%d")
                events.append(CalendarEvent(
                    summary=f"Paiement Eau ({ref})",
                    start=dt,
                    end=dt + timedelta(days=1),
                    description=f"Échéance de paiement pour le contrat {ref}",
                    location="Eau du Grand Lyon",
                ))
            # Prochaine facture estimée
            bill_date = contract.get("next_bill_date")
            if bill_date:
                dt = datetime.strptime(bill_date, "%Y-%m-%d")
                events.append(CalendarEvent(
                    summary=f"Facture estimée ({ref})",
                    start=dt,
                    end=dt + timedelta(days=1),
                    description="Date estimée de la prochaine facture",
                ))

        # [FEAT 3] Interruptions de service / travaux
        for inter in data.get("interruptions", []):
            try:
                debut_str = inter.get("date_debut")
                fin_str   = inter.get("date_fin") or debut_str
                if not debut_str:
                    continue
                debut = datetime.strptime(debut_str, "%Y-%m-%d")
                fin   = datetime.strptime(fin_str,   "%Y-%m-%d") + timedelta(days=1)
                type_label = inter.get("type", "TRAVAUX")
                emoji = "🚧" if "TRAVAUX" in type_label else "🔴"
                events.append(CalendarEvent(
                    summary=f"{emoji} {inter.get('titre', 'Interruption eau')}",
                    start=debut,
                    end=fin,
                    description=inter.get("description") or f"Interruption type : {type_label}",
                    location="Eau du Grand Lyon",
                ))
            except (ValueError, TypeError):
                continue

        return events

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Eau du Grand Lyon",
        )
