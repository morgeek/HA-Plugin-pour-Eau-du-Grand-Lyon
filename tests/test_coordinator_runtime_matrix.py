"""Runtime behavior matrix for coordinator persistence, calculations, and recorder fallbacks."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.eau_grand_lyon import coordinator as coordinator_module
from custom_components.eau_grand_lyon.coordinator import EauGrandLyonCoordinator, _CycleCachedApi, _parse_outage_alertes
from homeassistant.exceptions import HomeAssistantError


def _coordinator() -> EauGrandLyonCoordinator:
    coord = EauGrandLyonCoordinator.__new__(EauGrandLyonCoordinator)
    coord._entry = MagicMock()
    coord._entry.entry_id = "entry-1"
    coord._entry.data = {"tarif_m3": 4.0}
    coord._entry.options = {}
    coord.hass = MagicMock()
    coord.data = None
    coord._last_good_data = None
    coord._monthly_history = {}
    coord._daily_history = {}
    coord._cumulative_index_cache = {}
    coord._stats_month_counts = {}
    coord._prev_nb_alertes = 0
    coord.vacation_mode = False
    coord._persistent_data_loaded = False
    coord._persistent_data_lock = asyncio.Lock()
    coord._store = MagicMock()
    coord._monthly_history_store = MagicMock()
    coord._daily_history_store = MagicMock()
    return coord


@pytest.mark.asyncio
async def test_initialize_and_load_all_persistent_stores_with_timestamp_normalization():
    coord = _coordinator()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    coord._monthly_history_store.async_load = AsyncMock(return_value={"REF1": [{"annee": 2026}]})
    coord._daily_history_store.async_load = AsyncMock(
        return_value={"REF1": [{"date": "2026-08-01"}], 12: [], "BROKEN": "not-list"}
    )
    coord._store.async_load = AsyncMock(
        return_value={
            "contracts": {"REF1": {}},
            "last_update_success_time": now.isoformat(),
            "offline_since": "invalid",
            "last_failure_time": now.isoformat(),
            "cache_saved_at": now.isoformat(),
        }
    )

    await coord.async_initialize()
    await coord.async_initialize()

    assert coord._persistent_data_loaded is True
    assert coord._monthly_history == {"REF1": [{"annee": 2026}]}
    assert coord._daily_history == {"REF1": [{"date": "2026-08-01"}]}
    assert coord.data["offline_mode"] is False
    assert coord.data["offline_since"] is None
    assert isinstance(coord.data["last_update_success_time"], datetime)
    coord._store.async_load.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_and_corrupt_persistent_stores_are_safely_ignored():
    expired = _coordinator()
    expired._monthly_history_store.async_load = AsyncMock(return_value={})
    expired._daily_history_store.async_load = AsyncMock(return_value={})
    expired._store.async_load = AsyncMock(
        return_value={
            "contracts": {"REF1": {}},
            "cache_saved_at": (datetime.now(timezone.utc) - timedelta(days=400)).isoformat(),
        }
    )
    expired._store.async_remove = AsyncMock()
    await expired._load_persistent_data()
    expired._store.async_remove.assert_awaited_once()
    assert expired._last_good_data is None

    corrupt = _coordinator()
    corrupt._monthly_history_store.async_load = AsyncMock(side_effect=json.JSONDecodeError("bad", "x", 0))
    corrupt._daily_history_store.async_load = AsyncMock(side_effect=OSError("daily broken"))
    corrupt._store.async_load = AsyncMock(side_effect=KeyError("cache broken"))
    await corrupt._load_persistent_data()
    assert corrupt._monthly_history == {}
    assert corrupt._daily_history == {}
    assert corrupt._last_good_data is None


@pytest.mark.asyncio
async def test_save_clear_and_close_persistence_paths_are_best_effort():
    coord = _coordinator()
    now = datetime.now(timezone.utc)
    coord._last_good_data = {
        "contracts": {"REF1": {}},
        "last_update_success_time": now,
        "last_failure_time": now,
    }
    coord._store.async_save = AsyncMock()
    coord._monthly_history_store.async_save = AsyncMock()
    coord._daily_history_store.async_save = AsyncMock()

    await coord._save_persistent_data()
    saved = coord._store.async_save.await_args.args[0]
    assert isinstance(saved["last_update_success_time"], str)
    assert saved["offline_mode"] is False
    await coord._save_monthly_history()
    await coord._save_daily_history()

    coord._store.async_save = AsyncMock(side_effect=TypeError("serialize"))
    coord._monthly_history_store.async_save = AsyncMock(side_effect=OSError("monthly"))
    coord._daily_history_store.async_save = AsyncMock(side_effect=OSError("daily"))
    await coord._save_persistent_data()
    await coord._save_monthly_history()
    await coord._save_daily_history()

    coord._store.async_remove = AsyncMock()
    coord._monthly_history_store.async_remove = AsyncMock()
    coord._daily_history_store.async_remove = AsyncMock()
    coord.data = {"contracts": {"REF1": {}}}
    await coord.async_clear_cache()
    assert coord.data == {}
    assert coord._last_good_data is None

    coord.api = MagicMock()
    coord.api.async_revoke_token = AsyncMock()
    coord._own_session = MagicMock(closed=False)
    coord._own_session.close = AsyncMock()
    await coord.async_close()
    coord._own_session.close.assert_awaited_once()
    coord._own_session.closed = True
    await coord.async_close()


def test_tariff_intelligence_eco_score_and_date_calculation_edge_cases():
    coord = _coordinator()
    coord._entry.options = {"price_entity": "sensor.price"}
    coord.hass.states.get.return_value = MagicMock(state="4.25")
    assert coord._calculate_tarif_m3() == 4.25
    coord.hass.states.get.return_value = MagicMock(state="bad")
    assert coord._calculate_tarif_m3() == 4.0
    coord._entry.options = {"tarif_m3": "bad"}
    assert coord._calculate_tarif_m3() > 0

    assert coord._get_consumption_n1([]) == (None, None)
    assert coord._get_consumption_n1(
        [
            {"mois_index": 7, "annee": 2025, "consommation_m3": 8.0, "label": "Août 2025"},
            {"mois_index": 7, "annee": 2026, "consommation_m3": 9.0, "label": "Août 2026"},
        ]
    ) == (8.0, "Août 2025")
    assert coord._calculate_intelligence(None, None, [], 4.0) == (None, None, None)
    assert coord._calculate_intelligence(10, 5, [{"date": "bad"}], 4.0)[2] == 100.0
    assert coord._calculate_intelligence(10, 5, [{"date": "2020-01-01"}], 4.0) == (None, None, 100.0)

    coord._entry.options = {"household_size": 1}
    assert coord._calculate_eco_score({}, None)[1] == "Inconnu"
    for volume, grade in ((2, "A"), (3, "B"), (5, "C"), (7, "D"), (9, "E"), (12, "F"), (15, "G")):
        assert coord._calculate_eco_score({}, volume)[1] == grade

    assert coord._estimate_next_bill_date(None) is None
    assert coord._estimate_next_bill_date("invalid") is None
    assert coord._calculate_experimental_leak(False, []) is None
    assert coord._calculate_experimental_leak(True, [{"volume_fuite_estime_m3": 0.1}]) == 0.1


@pytest.mark.asyncio
async def test_real_index_cost_vacation_and_statistic_error_branches(monkeypatch):
    coord = _coordinator()
    cycle = MagicMock()
    cycle.get_derniere_releve_siamm = AsyncMock(
        side_effect=[
            {"grandeursPhysiques": [{"modeleGrandeurPhysique": {"code": "VOLUME"}, "valeur": 321}]},
            None,
            None,
        ]
    )
    assert await coord._get_real_index(cycle, True, "C1", []) == 321
    assert await coord._get_real_index(cycle, True, "C1", [{"index_m3": 12.3}]) == 12.3
    assert await coord._get_real_index(cycle, True, "C1", []) is None

    coord._entry.options = {"subscription_annual": 0}
    assert coord._get_real_monthly_cost(None, 4) is None
    coord._entry.options = {"subscription_annual": 120}
    assert coord._get_real_monthly_cost(2, 4) == 18
    assert coord._get_real_annual_cost(10, 4) == 160

    coord.vacation_mode = True
    assert coord._check_vacation_alert({"REF1": {"consommations_journalieres": []}}) is False
    assert coord._check_vacation_alert({"REF1": {"consommations_journalieres": [{"consommation_m3": 0.1}]}}) is True

    with patch.object(coordinator_module, "StatisticData", new=lambda **kwargs: kwargs):
        series = coord._build_stat_series(
            [
                {"annee": 2026, "mois_index": 99, "consommation_m3": 1},
                {"annee": 2026, "mois_index": 0, "consommation_m3": 1},
            ],
            lambda value: value,
            None,
            2,
        )
        assert len(series) == 1
        daily = coord._build_daily_stat_series(
            [
                {"date": "bad", "consommation_m3": 1},
                {"date": "2026-01-01", "consommation_m3": "bad"},
            ]
        )
        assert daily == []

    await coord._inject_series({}, [], "empty")
    monkeypatch.setattr(coordinator_module, "async_add_external_statistics", AsyncMock())
    await coord._inject_series({}, [MagicMock()], "async")
    monkeypatch.setattr(
        coordinator_module,
        "async_add_external_statistics",
        MagicMock(side_effect=HomeAssistantError("recorder rejected")),
    )
    await coord._inject_series({}, [MagicMock()], "failure")


@pytest.mark.asyncio
async def test_last_recorder_anchor_datetime_timestamp_empty_and_failure(monkeypatch):
    coord = _coordinator()
    recorder = MagicMock()
    recorder.async_add_executor_job = AsyncMock(
        side_effect=[
            {},
            {"stat": [{"start": datetime(2026, 8, 1, tzinfo=timezone.utc), "sum": 20, "state": 5}]},
            {"stat": [{"start": datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp(), "sum": 10, "state": 2}]},
            RuntimeError("recorder down"),
        ]
    )
    monkeypatch.setattr(coordinator_module, "_HAS_LAST_STATS", True)
    monkeypatch.setattr(coordinator_module, "_get_recorder_instance", MagicMock(return_value=recorder), raising=False)
    monkeypatch.setattr(coordinator_module, "_get_last_statistics", MagicMock(), raising=False)

    assert await coord._last_recorded_anchor("stat") is None
    assert await coord._last_recorded_anchor("stat") == ((2026, 8), 15.0)
    assert await coord._last_recorded_anchor("stat") == ((2026, 7), 8.0)
    assert await coord._last_recorded_anchor("stat") is None

    monkeypatch.setattr(coordinator_module, "_HAS_LAST_STATS", False)
    assert await coord._last_recorded_anchor("stat") is None


@pytest.mark.asyncio
async def test_recorder_absence_daily_index_and_cycle_cache_wrappers(monkeypatch):
    coord = _coordinator()
    monkeypatch.setattr(coordinator_module, "_HAS_RECORDER", False)
    await coord._inject_statistics({"REF1": {"consommations": []}})

    coord.data = {"contracts": {"REF1": {"index_journalier_dernier": 123.4567}}}
    assert coord.get_cumulative_index("REF1") == 123.457

    api = MagicMock()
    method_names = (
        "get_contracts",
        "get_alertes",
        "get_interventions",
        "get_factures",
        "get_monthly_consumptions",
        "get_daily_consumptions",
        "get_alerte_surconsommation",
        "get_date_prochaine_facture",
        "get_point_de_service_etendu",
        "get_courbe_de_charge",
        "get_derniere_releve_siamm",
    )
    for name in method_names:
        setattr(api, name, AsyncMock(return_value=name))
    cycle = _CycleCachedApi(api)

    assert await cycle.get_contracts() == "get_contracts"
    assert await cycle.get_alertes() == "get_alertes"
    assert await cycle.get_interventions() == "get_interventions"
    assert await cycle.get_factures() == "get_factures"
    assert await cycle.get_monthly_consumptions("C1") == "get_monthly_consumptions"
    assert await cycle.get_daily_consumptions("C1", 30) == "get_daily_consumptions"
    assert await cycle.get_alerte_surconsommation("C1") == "get_alerte_surconsommation"
    assert await cycle.get_date_prochaine_facture("C1") == "get_date_prochaine_facture"
    assert await cycle.get_point_de_service_etendu("C1") == "get_point_de_service_etendu"
    assert await cycle.get_courbe_de_charge("C1", 3) == "get_courbe_de_charge"
    assert await cycle.get_derniere_releve_siamm("C1") == "get_derniere_releve_siamm"
    await cycle.aclose()


def test_outage_parser_ignores_malformed_alert_and_normalizes_fallback_fields():
    alerts = [
        None,
        {"id": 1, "typeCode": "maintenance", "dateDebut": "2026-09-02T10:00:00", "description": "x"},
    ]
    assert _parse_outage_alertes(alerts) == [
        {
            "titre": "Interruption service eau",
            "date_debut": "2026-09-02",
            "date_fin": None,
            "type": "MAINTENANCE",
            "description": "x",
            "reference": "1",
        }
    ]
