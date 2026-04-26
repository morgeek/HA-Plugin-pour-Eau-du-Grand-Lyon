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
    translation_key = "billing_events"

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
        """Retourne les événements du calendrier dans la plage demandée."""
        events = []
        data = self.coordinator.data or {}

        for ref, contract in data.get("contracts", {}).items():
            # Date de paiement / Échéance
            pay_date = contract.get("next_payment_date")
            if pay_date:
                try:
                    dt = datetime.strptime(pay_date, "%Y-%m-%d")
                    # On s'assure que l'événement est dans la plage demandée (optimisation HA)
                    events.append(CalendarEvent(
                        summary=f"Paiement Eau ({ref})",
                        start=dt.date(),
                        end=dt.date() + timedelta(days=1),
                        description=f"Échéance de paiement pour le contrat {ref}",
                        location="Eau du Grand Lyon",
                    ))
                except (ValueError, TypeError):
                    pass

            # Prochaine facture (réelle ou estimée)
            bill_date = contract.get("next_bill_date")
            if bill_date:
                try:
                    dt = datetime.strptime(bill_date, "%Y-%m-%d")
                    # Si la date vient de l'API, on le précise dans le titre
                    label = "Prochaine facture" if contract.get("next_bill_date") else "Facture estimée"
                    events.append(CalendarEvent(
                        summary=f"🧾 {label} ({ref})",
                        start=dt.date(),
                        end=dt.date() + timedelta(days=1),
                        description=f"Prochaine facture eau pour le contrat {ref}",
                        location="Eau du Grand Lyon",
                    ))
                except (ValueError, TypeError):
                    pass

            # Prochain relevé compteur (depuis /pointDeService)
            releve_date = contract.get("date_prochaine_releve")
            if releve_date:
                try:
                    dt = datetime.strptime(releve_date, "%Y-%m-%d")
                    mode = contract.get("pds_mode_releve", "")
                    label = "Relevé AMM automatique" if "AMM" in (mode or "") else "Relevé compteur"
                    events.append(CalendarEvent(
                        summary=f"📊 {label} ({ref})",
                        start=dt.date(),
                        end=dt.date() + timedelta(days=1),
                        description=f"Prochain relevé du compteur pour le contrat {ref}",
                        location="Eau du Grand Lyon",
                    ))
                except (ValueError, TypeError):
                    pass

        # Interventions terrain planifiées (releveur, technicien…)
        for inter in data.get("interventions_planifiees", []):
            try:
                debut_str = inter.get("date_debut")
                fin_str   = inter.get("date_fin") or debut_str
                if not debut_str:
                    continue
                debut_dt = datetime.strptime(debut_str, "%Y-%m-%d")
                fin_dt   = datetime.strptime(fin_str,   "%Y-%m-%d")
                type_label = inter.get("type") or "Intervention"
                contrat_ref = inter.get("contrat_ref", "")
                presence = " 🏠" if inter.get("presence_requise") else ""
                events.append(CalendarEvent(
                    summary=f"🔧 {type_label}{presence} ({contrat_ref})",
                    start=debut_dt.date(),
                    end=(fin_dt + timedelta(days=1)).date() if fin_dt.date() == debut_dt.date() else fin_dt.date(),
                    description=(
                        f"Intervention planifiée sur le compteur"
                        + (" — votre présence est requise" if inter.get("presence_requise") else "")
                        + f"\nRéférence : {inter.get('reference', '')}"
                    ),
                    location="Eau du Grand Lyon",
                ))
            except (ValueError, TypeError, KeyError):
                continue

        # Interruptions de service / travaux réseau (alertes API)
        for inter in data.get("interruptions", []):
            try:
                debut_str = inter.get("date_debut")
                fin_str   = inter.get("date_fin") or debut_str
                if not debut_str:
                    continue
                
                # Support formats YYYY-MM-DD ou ISO
                try:
                    debut_dt = datetime.fromisoformat(debut_str.replace('Z', '+00:00'))
                    fin_dt   = datetime.fromisoformat(fin_str.replace('Z', '+00:00'))
                except ValueError:
                    debut_dt = datetime.strptime(debut_str[:10], "%Y-%m-%d")
                    fin_dt   = datetime.strptime(fin_str[:10],   "%Y-%m-%d")

                type_label = inter.get("type", "TRAVAUX")
                emoji = "🚧" if "TRAVAUX" in type_label else "🔴"
                
                events.append(CalendarEvent(
                    summary=f"{emoji} {inter.get('titre', 'Interruption eau')}",
                    start=debut_dt,
                    end=fin_dt + timedelta(days=1) if fin_dt == debut_dt else fin_dt,
                    description=inter.get("description") or f"Interruption type : {type_label}",
                    location="Eau du Grand Lyon",
                ))
            except (ValueError, TypeError, KeyError):
                continue

        # Mise à jour de l'événement courant (le prochain à venir)
        now = datetime.now()
        future_events = [e for e in events if (isinstance(e.start, datetime) and e.start >= now) or (not isinstance(e.start, datetime) and e.start >= now.date())]
        if future_events:
            self._event = min(future_events, key=lambda e: e.start if isinstance(e.start, datetime) else datetime.combine(e.start, datetime.min.time()))
        else:
            self._event = None

        return events

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Eau du Grand Lyon",
        )
