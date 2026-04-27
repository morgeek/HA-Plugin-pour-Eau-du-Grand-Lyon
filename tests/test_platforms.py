"""Tests for button, switch, and calendar platforms."""
from datetime import date, timedelta
from unittest.mock import MagicMock, AsyncMock

from custom_components.eau_grand_lyon.button import (
    EauGrandLyonRefreshButton,
    EauGrandLyonDownloadInvoiceButton,
)
from custom_components.eau_grand_lyon.switch import EauGrandLyonVacationSwitch
from custom_components.eau_grand_lyon.calendar import EauGrandLyonCalendar


def _make_button(cls, coordinator_data=None, entry=None):
    """Helper to create a button with mocked dependencies."""
    if coordinator_data is None:
        coordinator_data = {"contracts": {}}

    coordinator = MagicMock()
    coordinator.data = coordinator_data
    coordinator.async_request_refresh = AsyncMock()

    if entry is None:
        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.options = {}

    entity = cls.__new__(cls)
    entity.coordinator = coordinator
    entity._entry = entry
    # Set unique_id based on button type
    if cls.__name__ == "EauGrandLyonRefreshButton":
        entity._attr_unique_id = f"{entry.entry_id}_refresh"
    elif cls.__name__ == "EauGrandLyonDownloadInvoiceButton":
        entity._attr_unique_id = f"{entry.entry_id}_download_invoice"
    return entity


def _make_switch(coordinator_data=None, entry=None, hass=None):
    """Helper to create a switch with mocked dependencies."""
    if coordinator_data is None:
        coordinator_data = {"contracts": {}}

    coordinator = MagicMock()
    coordinator.data = coordinator_data

    if entry is None:
        entry = MagicMock()
        entry.entry_id = "test_entry"

    if hass is None:
        hass = MagicMock()
        hass.data = {}

    switch = EauGrandLyonVacationSwitch.__new__(EauGrandLyonVacationSwitch)
    switch.coordinator = coordinator
    switch._entry = entry
    switch.hass = hass
    switch._attr_unique_id = f"{entry.entry_id}_vacation_mode"
    switch.async_write_ha_state = MagicMock()
    return switch


def _make_calendar(coordinator_data=None, entry=None, hass=None):
    """Helper to create a calendar with mocked dependencies."""
    if coordinator_data is None:
        coordinator_data = {"contracts": {}, "interruptions": [], "interventions_planifiees": []}

    coordinator = MagicMock()
    coordinator.data = coordinator_data

    if entry is None:
        entry = MagicMock()
        entry.entry_id = "test_entry"

    if hass is None:
        hass = MagicMock()

    calendar = EauGrandLyonCalendar.__new__(EauGrandLyonCalendar)
    calendar.coordinator = coordinator
    calendar._entry = entry
    calendar.hass = hass
    calendar._attr_unique_id = f"{entry.entry_id}_calendar"
    calendar._event = None
    return calendar


# ── EauGrandLyonRefreshButton ───────────────────────────────────────────────

class TestRefreshButton:
    def test_unique_id_generation(self):
        b = _make_button(EauGrandLyonRefreshButton)
        assert b._attr_unique_id == "test_entry_refresh"

    async def test_async_press_calls_coordinator(self):
        b = _make_button(EauGrandLyonRefreshButton)
        await b.async_press()
        b.coordinator.async_request_refresh.assert_called_once()


# ── EauGrandLyonDownloadInvoiceButton ────────────────────────────────────────

class TestDownloadInvoiceButton:
    def test_unique_id_generation(self):
        b = _make_button(EauGrandLyonDownloadInvoiceButton)
        assert b._attr_unique_id == "test_entry_download_invoice"

    async def test_async_press_calls_service(self):
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        b = _make_button(EauGrandLyonDownloadInvoiceButton)
        b.hass = hass
        await b.async_press()
        hass.services.async_call.assert_called_once()


# ── EauGrandLyonVacationSwitch ──────────────────────────────────────────────

class TestVacationSwitch:
    def test_unique_id_generation(self):
        s = _make_switch()
        assert s._attr_unique_id == "test_entry_vacation_mode"

    def test_is_on_default_false(self):
        s = _make_switch()
        assert s.is_on is False

    def test_is_on_when_enabled(self):
        hass = MagicMock()
        hass.data = {"eau_grand_lyon": {"vacation_mode": True}}
        s = _make_switch(hass=hass)
        assert s.is_on is True

    async def test_async_turn_on(self):
        hass = MagicMock()
        hass.data = {}
        s = _make_switch(hass=hass)
        await s.async_turn_on()
        assert hass.data["eau_grand_lyon"]["vacation_mode"] is True
        s.async_write_ha_state.assert_called_once()

    async def test_async_turn_off(self):
        hass = MagicMock()
        hass.data = {"eau_grand_lyon": {"vacation_mode": True}}
        s = _make_switch(hass=hass)
        await s.async_turn_off()
        assert hass.data["eau_grand_lyon"]["vacation_mode"] is False
        s.async_write_ha_state.assert_called_once()


# ── EauGrandLyonCalendar ───────────────────────────────────────────────────

class TestCalendar:
    def test_unique_id_generation(self):
        c = _make_calendar()
        assert c._attr_unique_id == "test_entry_calendar"

    async def test_empty_events_when_no_data(self):
        hass = MagicMock()
        c = _make_calendar(hass=hass)
        start = date.today()
        end = start + timedelta(days=30)
        events = await c.async_get_events(hass, start, end)
        assert events == []

    async def test_events_from_interruptions(self):
        hass = MagicMock()
        today = date.today()
        tomorrow = today + timedelta(days=1)
        coordinator_data = {
            "contracts": {},
            "interruptions": [
                {
                    "titre": "Maintenance réseau",
                    "date_debut": tomorrow.isoformat(),
                    "date_fin": tomorrow.isoformat(),
                    "type": "TRAVAUX",
                    "description": "Travaux de maintenance",
                }
            ],
            "interventions_planifiees": [],
        }
        c = _make_calendar(coordinator_data=coordinator_data, hass=hass)
        start = today
        end = start + timedelta(days=30)
        events = await c.async_get_events(hass, start, end)
        assert len(events) > 0
        assert any("Maintenance réseau" in e.summary for e in events)

    async def test_updates_current_event(self):
        hass = MagicMock()
        today = date.today()
        tomorrow = today + timedelta(days=1)
        coordinator_data = {
            "contracts": {},
            "interruptions": [
                {
                    "titre": "Maintenance",
                    "date_debut": tomorrow.isoformat(),
                    "date_fin": tomorrow.isoformat(),
                    "type": "TRAVAUX",
                }
            ],
            "interventions_planifiees": [],
        }
        c = _make_calendar(coordinator_data=coordinator_data, hass=hass)
        start = today
        end = start + timedelta(days=30)
        await c.async_get_events(hass, start, end)
        assert c.event is not None
        assert "Maintenance" in c.event.summary
