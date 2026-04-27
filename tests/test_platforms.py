"""Tests for button, switch, and calendar platforms."""
from datetime import date, timedelta
from unittest.mock import MagicMock, AsyncMock

from custom_components.eau_grand_lyon import sensor as sensor_platform
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


class TestSensorAutoDiscovery:
    def _patch_sensor_factories(self, monkeypatch):
        created = []

        def _factory(name):
            def _make(coordinator, entry, ref, *args):
                entity = MagicMock()
                suffix = name
                if name == "conso":
                    suffix = f"conso_{args[0]}"
                entity._attr_unique_id = f"{entry.entry_id}_{ref}_{suffix}"
                created.append(entity._attr_unique_id)
                return entity
            return _make

        def _global_factory(name):
            def _make(coordinator, entry, *args):
                entity = MagicMock()
                entity._attr_unique_id = f"{entry.entry_id}_{name}"
                created.append(entity._attr_unique_id)
                return entity
            return _make

        patches = {
            "EauGrandLyonIndexSensor": _factory("index_cumulatif"),
            "EauGrandLyonEnergyWaterSensor": _factory("energy_water"),
            "EauGrandLyonEnergyCostSensor": _factory("energy_cost"),
            "EauGrandLyonConsommationSensor": _factory("conso"),
            "EauGrandLyonConsommationAnnuelleSensor": _factory("conso_annuelle"),
            "EauGrandLyonYesterdaySensor": _factory("conso_hier"),
            "EauGrandLyonIndexJournalierSensor": _factory("index_journalier"),
            "EauGrandLyonConso7JSensor": _factory("conso_7j"),
            "EauGrandLyonConsoMoyenne7JSensor": _factory("conso_moyenne_7j"),
            "EauGrandLyonConso30JSensor": _factory("conso_30j"),
            "EauGrandLyonCoutMoisSensor": _factory("cout_mois"),
            "EauGrandLyonCoutAnnuelSensor": _factory("cout_annuel"),
            "EauGrandLyonCoutCumuleSensor": _factory("cout_cumule"),
            "EauGrandLyonEconomieSensor": _factory("economie"),
            "EauGrandLyonCoutReelMoisSensor": _factory("cout_reel_mois"),
            "EauGrandLyonCoutReelAnnuelSensor": _factory("cout_reel_annuel"),
            "EauGrandLyonSoldeSensor": _factory("solde"),
            "EauGrandLyonStatutSensor": _factory("statut"),
            "EauGrandLyonDateEcheanceSensor": _factory("date_echeance"),
            "EauGrandLyonProchaineFactureSensor": _factory("prochaine_facture"),
            "EauGrandLyonProchaineReleveSensor": _factory("prochaine_releve"),
            "EauGrandLyonConsoAnnuelleRefSensor": _factory("conso_annuelle_ref"),
            "EauGrandLyonCompatibilitySensor": _factory("compatibility"),
            "EauGrandLyonTrendSensor": _factory("trend"),
            "EauGrandLyonPredictionConsoSensor": _factory("prediction_conso"),
            "EauGrandLyonPredictionCostSensor": _factory("prediction_cost"),
            "EauGrandLyonEcoScoreSensor": _factory("eco_score"),
            "EauGrandLyonCO2FootprintSensor": _factory("co2"),
            "EauGrandLyonSignalSensor": _factory("signal"),
            "EauGrandLyonDerniereFactureSensor": _factory("derniere_facture"),
            "EauGrandLyonFuiteEstimeeSensor": _factory("fuite_estimee"),
            "EauGrandLyonHourlyConsoSensor": _factory("hourly_conso"),
            "EauGrandLyonPeakHourSensor": _factory("peak_hour"),
            "EauGrandLyonAvgFlowSensor": _factory("avg_flow"),
            "EauGrandLyonAlertesSensor": _global_factory("alertes"),
            "EauGrandLyonLastUpdateSensor": _global_factory("last_update"),
            "EauGrandLyonHealthSensor": _global_factory("health"),
            "EauGrandLyonDroughtSensor": _global_factory("drought"),
            "EauGrandLyonNextOutageSensor": _global_factory("next_outage"),
            "EauGrandLyonWaterHardnessSensor": _global_factory("water_hardness"),
            "EauGrandLyonNitratesSensor": _global_factory("nitrates"),
            "EauGrandLyonChloreSensor": _global_factory("chlore"),
            "EauGrandLyonGlobalConsoSensor": _global_factory("global_conso"),
            "EauGrandLyonGlobalCostSensor": _global_factory("global_cost"),
            "EauGrandLyonGlobalPredictionCostSensor": _global_factory("global_prediction"),
            "EauGrandLyonLimescaleSensor": _factory("limescale"),
            "EauGrandLyonCoachingSensor": _factory("coaching"),
        }
        for attr, factory in patches.items():
            monkeypatch.setattr(sensor_platform, attr, factory)
        return created

    async def test_standard_meter_skips_daily_and_hourly_sensors(self, monkeypatch):
        created = self._patch_sensor_factories(monkeypatch)
        coordinator = MagicMock()
        coordinator.data = {
            "contracts": {
                "REF1": {
                    "teleo_compatible": False,
                    "pds_communicabilite_amm": False,
                    "pds_mode_releve": "RELEVE_TERRAIN",
                }
            },
            "experimental_mode": True,
            "global": {},
        }
        entry = MagicMock()
        entry.runtime_data = coordinator
        entry.entry_id = "test_entry"

        captured = []

        def _add_entities(entities, update_before_add=False):
            captured.extend(entities)

        await sensor_platform.async_setup_entry(MagicMock(), entry, _add_entities)

        unique_ids = set(created)
        assert f"{entry.entry_id}_REF1_conso_hier" not in unique_ids
        assert f"{entry.entry_id}_REF1_index_journalier" not in unique_ids
        assert f"{entry.entry_id}_REF1_hourly_conso" not in unique_ids
        assert f"{entry.entry_id}_REF1_peak_hour" not in unique_ids
        assert f"{entry.entry_id}_REF1_avg_flow" not in unique_ids
        assert f"{entry.entry_id}_REF1_compatibility" in unique_ids

    async def test_teleo_meter_keeps_daily_and_hourly_sensors(self, monkeypatch):
        created = self._patch_sensor_factories(monkeypatch)
        coordinator = MagicMock()
        coordinator.data = {
            "contracts": {
                "REF1": {
                    "teleo_compatible": True,
                    "pds_communicabilite_amm": True,
                    "pds_mode_releve": "AMM",
                }
            },
            "experimental_mode": True,
            "global": {},
        }
        entry = MagicMock()
        entry.runtime_data = coordinator
        entry.entry_id = "test_entry"

        captured = []

        def _add_entities(entities, update_before_add=False):
            captured.extend(entities)

        await sensor_platform.async_setup_entry(MagicMock(), entry, _add_entities)

        unique_ids = set(created)
        assert f"{entry.entry_id}_REF1_conso_hier" in unique_ids
        assert f"{entry.entry_id}_REF1_index_journalier" in unique_ids
        assert f"{entry.entry_id}_REF1_hourly_conso" in unique_ids
        assert f"{entry.entry_id}_REF1_peak_hour" in unique_ids
        assert f"{entry.entry_id}_REF1_avg_flow" in unique_ids
