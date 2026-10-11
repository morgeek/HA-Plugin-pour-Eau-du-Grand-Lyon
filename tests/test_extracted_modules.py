"""Edge cases for the modules extracted from the coordinator."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.eau_grand_lyon import analytics
from custom_components.eau_grand_lyon import recorder_statistics as stats_module
from custom_components.eau_grand_lyon.api.cycle_cache import CycleCachedApi
from custom_components.eau_grand_lyon.history import sanitize_daily_history


class TestAnalyzeLoadCurve:
    def test_empty_curve_returns_no_values(self):
        assert analytics.analyze_load_curve([]) == (None, None, None)

    def test_peak_hour_and_non_zero_average(self):
        courbe = [
            {"date": "2026-08-02T08:00:00", "valeur": 0.1},
            {"date": "2026-08-02T09:00:00", "valeur": 0.3},
            {"date": "2026-08-02T10:00:00", "valeur": 0},
        ]
        assert analytics.analyze_load_curve(courbe) == (0.0, "09:00", 0.2)

    def test_invalid_peak_date_and_all_zero_curve(self):
        courbe = [{"date": "not-a-date", "valeur": 0}, {"valeur": None}]
        assert analytics.analyze_load_curve(courbe) == (0.0, None, None)


class TestLatestDailyIndex:
    def test_skips_days_without_index(self):
        daily = [
            {"date": "2026-08-01", "index_m3": "100.2"},
            {"date": "2026-08-02"},
        ]
        assert analytics.latest_daily_index(daily) == (100.2, "2026-08-01")

    def test_invalid_latest_index_is_not_replaced_by_an_older_one(self):
        daily = [
            {"date": "2026-08-01", "index_m3": 100.2},
            {"date": "2026-08-02", "index_m3": "bad"},
        ]
        assert analytics.latest_daily_index(daily) == (None, None)

    def test_no_daily_data(self):
        assert analytics.latest_daily_index([]) == (None, None)


def test_limescale_and_co2_use_rolling_twelve_months():
    consos = [{"consommation_m3": 100.0} for _ in range(13)]
    assert analytics.limescale(consos, 100.0) == (1200000.0, True)
    assert analytics.limescale(consos[:1], 30.0) == (30000.0, False)
    assert analytics.co2_footprint_kg(None) is None
    assert analytics.co2_footprint_kg(10) == 5.2


def test_sanitize_daily_history_rejects_non_mapping_cache():
    assert sanitize_daily_history(["not", "a", "dict"]) == {}


@pytest.mark.asyncio
async def test_cycle_cache_shares_calls_and_cancels_pending_tasks_on_close():
    started = asyncio.Event()

    async def never_finishes():
        started.set()
        await asyncio.Event().wait()

    api = MagicMock()
    api.get_contracts = AsyncMock(return_value=[{"id": "C1"}])
    api.get_alertes = MagicMock(side_effect=never_finishes)
    cycle = CycleCachedApi(api)

    assert await cycle.get_contracts() == await cycle.get_contracts()
    api.get_contracts.assert_awaited_once()

    pending = asyncio.ensure_future(cycle.get_alertes())
    await started.wait()
    await cycle.aclose()
    with pytest.raises(asyncio.CancelledError):
        await pending


@pytest.mark.asyncio
async def test_last_recorded_anchor_ignores_unexpected_start_type(monkeypatch):
    recorder = MagicMock()
    recorder.async_add_executor_job = AsyncMock(return_value={"stat": [{"start": object(), "sum": 1, "state": 1}]})
    monkeypatch.setattr(stats_module, "_HAS_LAST_STATS", True)
    monkeypatch.setattr(stats_module, "_get_recorder_instance", MagicMock(return_value=recorder), raising=False)
    monkeypatch.setattr(stats_module, "_get_last_statistics", MagicMock(), raising=False)

    assert await stats_module.async_last_recorded_anchor(MagicMock(), "stat") is None


@pytest.mark.asyncio
async def test_contract_statistics_legacy_mean_flag_and_no_cost_without_tariff(monkeypatch):
    monkeypatch.setattr(stats_module, "StatisticMeanType", None)
    monkeypatch.setattr(stats_module, "async_last_recorded_anchor", AsyncMock(return_value=None))
    add_stats = MagicMock(return_value=None)
    monkeypatch.setattr(stats_module, "async_add_external_statistics", add_stats)
    contracts = {
        "REF1": {
            "tarif_m3": 0,
            "consommations": [{"annee": 2026, "mois_index": 0, "consommation_m3": 3.0}],
        }
    }

    with patch.object(stats_module, "StatisticData", new=lambda **kwargs: kwargs):
        await stats_module.async_inject_contract_statistics(MagicMock(), contracts, {}, {})

    assert [call.args[1]["statistic_id"] for call in add_stats.call_args_list] == ["eau_grand_lyon:water_ref1"]
    metadata = add_stats.call_args.args[1]
    assert metadata["has_mean"] is False
    assert "mean_type" not in metadata
    series = add_stats.call_args.args[2]
    assert series == [{"start": datetime(2026, 1, 1, tzinfo=timezone.utc), "sum": 3.0, "state": 3.0}]
