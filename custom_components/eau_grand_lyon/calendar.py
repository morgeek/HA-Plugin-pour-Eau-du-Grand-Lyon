"""Calendar platform for Eau du Grand Lyon."""
from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EauGrandLyonCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les calendriers depuis une config entry."""
    coordinator = entry.runtime_data
    async_add_entities([EauGrandLyonCalendar(coordinator, entry)])


class EauGrandLyonCalendar(
    CoordinatorEntity[EauGrandLyonCoordinator], CalendarEntity
):
    """Calendrier des échéances Eau du Grand Lyon."""

    _attr_has_entity_name = True
    translation_key = "billing_events"

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._event: CalendarEvent | None = None

    @property
    def event(self) -> CalendarEvent | None:
        return self._event

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Retourne les événements du calendrier dans la plage demandée."""
        events: list[CalendarEvent] = []
        data = self.coordinator.data or {}

        for ref, contract in data.get("contracts", {}).items():
            # Date de paiement / Échéance
            pay_date = contract.get("next_payment_date")
            if pay_date:
                try:
                    dt = datetime.strptime(pay_date, "%Y-%m-%d").date()
                    events.append(CalendarEvent(
                        summary=f"Paiement Eau ({ref})",
                        start=dt,
                        end=dt + timedelta(days=1),
                        description=f"Échéance de paiement pour le contrat {ref}",
                        location="Eau du Grand Lyon",
                    ))
                except (ValueError, TypeError):
                    pass

            # Prochaine facture
            bill_date = contract.get("next_bill_date")
            if bill_date:
                try:
                    dt = datetime.strptime(bill_date, "%Y-%m-%d").date()
                    events.append(CalendarEvent(
                        summary=f"Prochaine facture ({ref})",
                        start=dt,
                        end=dt + timedelta(days=1),
                        description=f"Prochaine facture eau pour le contrat {ref}",
                        location="Eau du Grand Lyon",
                    ))
                except (ValueError, TypeError):
                    pass

            # Prochain relevé compteur
            releve_date = contract.get("date_prochaine_releve")
            if releve_date:
                try:
                    dt = datetime.strptime(releve_date, "%Y-%m-%d").date()
                    mode = contract.get("pds_mode_releve", "")
                    label = "Relevé AMM automatique" if "AMM" in (mode or "") else "Relevé compteur"
                    events.append(CalendarEvent(
                        summary=f"{label} ({ref})",
                        start=dt,
                        end=dt + timedelta(days=1),
                        description=f"Prochain relevé du compteur pour le contrat {ref}",
                        location="Eau du Grand Lyon",
                    ))
                except (ValueError, TypeError):
                    pass

        # Interventions terrain planifiées
        for inter in data.get("interventions_planifiees", []):
            try:
                debut_str = inter.get("date_debut")
                fin_str = inter.get("date_fin") or debut_str
                if not debut_str:
                    continue
                debut_d = datetime.strptime(debut_str[:10], "%Y-%m-%d").date()
                fin_d = datetime.strptime(fin_str[:10], "%Y-%m-%d").date()
                type_label = inter.get("type") or "Intervention"
                contrat_ref = inter.get("contrat_ref", "")
                presence = " (présence requise)" if inter.get("presence_requise") else ""
                end_d = fin_d + timedelta(days=1) if fin_d == debut_d else fin_d
                events.append(CalendarEvent(
                    summary=f"{type_label}{presence} ({contrat_ref})",
                    start=debut_d,
                    end=end_d,
                    description=(
                        "Intervention planifiée sur le compteur"
                        + (" — votre présence est requise" if inter.get("presence_requise") else "")
                        + f"\nRéférence : {inter.get('reference', '')}"
                    ),
                    location="Eau du Grand Lyon",
                ))
            except (ValueError, TypeError, KeyError):
                continue

        # Interruptions de service / travaux réseau — always all-day (date, not datetime)
        for inter in data.get("interruptions", []):
            try:
                debut_str = inter.get("date_debut")
                fin_str = inter.get("date_fin") or debut_str
                if not debut_str:
                    continue
                debut_d = date.fromisoformat(debut_str[:10])
                fin_d = date.fromisoformat(fin_str[:10])
                end_d = fin_d + timedelta(days=1) if fin_d == debut_d else fin_d
                type_label = inter.get("type", "TRAVAUX")
                emoji = "🚧" if "TRAVAUX" in type_label else "🔴"
                events.append(CalendarEvent(
                    summary=f"{emoji} {inter.get('titre', 'Interruption eau')}",
                    start=debut_d,
                    end=end_d,
                    description=inter.get("description") or f"Interruption type : {type_label}",
                    location="Eau du Grand Lyon",
                ))
            except (ValueError, TypeError, KeyError):
                continue

        # Mise à jour de l'événement courant (le prochain à venir)
        today = date.today()
        future_events = [e for e in events if e.start >= today]
        self._event = min(future_events, key=lambda e: e.start) if future_events else None

        return events

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Eau du Grand Lyon",
        )
