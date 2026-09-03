"""Tests for EauGrandLyonCoordinator instance methods."""

from datetime import datetime, timedelta, timezone
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.eau_grand_lyon.api import (
    ApiError,
    AuthenticationError,
    EauGrandLyonApi,
    NetworkError,
    WafBlockedError,
)
from custom_components.eau_grand_lyon.coordinator import EauGrandLyonCoordinator
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed


def _make_coordinator(options=None):
    """Build a minimal coordinator with no real HA wiring."""
    entry = MagicMock()
    entry.options = options or {}
    hass = MagicMock()
    hass.data = {}
    coord = EauGrandLyonCoordinator.__new__(EauGrandLyonCoordinator)
    coord._entry = entry
    coord.data = None
    coord.hass = hass
    coord._last_good_data = None
    coord._last_request_mono = None
    coord._min_request_delay_s = 0.0
    coord._max_retries = 3
    coord._consecutive_failures = 0
    coord._cumulative_index_cache = {}
    coord._monthly_history = {}
    coord._save_persistent_data = AsyncMock()
    coord.logger = MagicMock()
    return coord


class TestCalculateDailyAggregates:
    def setup_method(self):
        self.coord = _make_coordinator()

    def test_empty_returns_none_none(self):
        assert self.coord._calculate_daily_aggregates([]) == (None, None)

    def test_fewer_than_7_uses_all(self):
        daily = [{"consommation_m3": 1.0} for _ in range(5)]
        c7, c30 = self.coord._calculate_daily_aggregates(daily)
        assert c7 == 5.0
        assert c30 == 5.0

    def test_7_days_correct(self, sample_daily):
        c7, c30 = self.coord._calculate_daily_aggregates(sample_daily)
        expected_7 = round(sum(e["consommation_m3"] for e in sample_daily[-7:]), 2)
        expected_30 = round(sum(e["consommation_m3"] for e in sample_daily[-30:]), 2)
        assert c7 == expected_7
        assert c30 == expected_30

    def test_30_days_same_as_7_when_only_7_entries(self):
        daily = [{"consommation_m3": 2.0} for _ in range(7)]
        c7, c30 = self.coord._calculate_daily_aggregates(daily)
        assert c7 == c30 == 14.0


class TestGetCumulativeIndex:
    def setup_method(self):
        self.coord = _make_coordinator()

    def test_no_data_returns_none(self):
        self.coord.data = None
        assert self.coord.get_cumulative_index("REF1") is None

    def test_real_index_used_when_present(self):
        self.coord.data = {"contracts": {"REF1": {"real_index": 1234.567, "consommations": []}}}
        assert self.coord.get_cumulative_index("REF1") == 1234.567

    def test_sum_used_when_no_real_index(self, sample_consos):
        self.coord.data = {"contracts": {"REF1": {"consommations": sample_consos}}}
        expected = round(sum(e["consommation_m3"] for e in sample_consos), 3)
        assert self.coord.get_cumulative_index("REF1") == expected

    def test_empty_consos_returns_none(self):
        self.coord.data = {"contracts": {"REF1": {"consommations": []}}}
        assert self.coord.get_cumulative_index("REF1") is None

    def test_cache_hit_avoids_recompute(self, sample_consos):
        self.coord.data = {"contracts": {"REF1": {"consommations": sample_consos}}}
        first = self.coord.get_cumulative_index("REF1")
        # Corrupt the underlying data — cache should still return first value
        self.coord.data["contracts"]["REF1"]["consommations"] = []
        assert self.coord.get_cumulative_index("REF1") == first

    def test_unknown_contract_returns_none(self):
        self.coord.data = {"contracts": {}}
        assert self.coord.get_cumulative_index("MISSING") is None


class TestUpdateErrorPaths:
    def setup_method(self):
        self.coord = _make_coordinator()
        self.coord._fetch_all_data = AsyncMock()

    @pytest.mark.asyncio
    async def test_authentication_error_raises_config_entry_auth_failed(self):
        self.coord._fetch_all_data.side_effect = AuthenticationError("bad creds")
        with pytest.raises(ConfigEntryAuthFailed):
            await self.coord._async_update_data()

    @pytest.mark.asyncio
    async def test_unexpected_error_without_cache_raises_update_failed(self):
        # Une erreur vraiment inattendue (bug) sans cache → UpdateFailed, sans retry.
        self.coord._fetch_all_data.side_effect = RuntimeError("boom")
        with pytest.raises(UpdateFailed):
            await self.coord._async_update_data()

    @pytest.mark.asyncio
    async def test_unexpected_error_with_cache_falls_back_offline(self):
        # Une erreur inattendue ne doit pas faire tomber les entités si un cache existe.
        self.coord._last_good_data = {
            "contracts": {"REF1": {"reference": "REF1"}},
            "last_update_success_time": datetime(2026, 4, 20, tzinfo=timezone.utc),
        }
        self.coord.data = None
        self.coord._fetch_all_data.side_effect = RuntimeError("boom")
        with patch("custom_components.eau_grand_lyon.coordinator.check_long_outage_issue"):
            result = await self.coord._async_update_data()
        assert result["offline_mode"] is True
        assert result["last_error_type"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_api_error_retries_then_raises_update_failed(self):
        # HTTP 5xx / réponse malformée : retenté comme une erreur réseau puis UpdateFailed.
        self.coord._fetch_all_data.side_effect = ApiError("server exploded")
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()), patch.object(
            self.coord, "_compute_retry_delay", side_effect=[10.0, 20.0]
        ):
            with pytest.raises(UpdateFailed):
                await self.coord._async_update_data()
        assert self.coord._consecutive_failures == 3

    @pytest.mark.asyncio
    async def test_api_error_with_cache_enables_offline_mode(self):
        self.coord._last_good_data = {
            "contracts": {"REF1": {"reference": "REF1"}},
            "last_update_success_time": datetime(2026, 4, 20, tzinfo=timezone.utc),
        }
        self.coord.data = None
        self.coord._fetch_all_data.side_effect = ApiError("server exploded")
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()), patch.object(
            self.coord, "_compute_retry_delay", side_effect=[10.0, 20.0]
        ), patch("custom_components.eau_grand_lyon.coordinator.check_long_outage_issue"):
            result = await self.coord._async_update_data()
        assert result["offline_mode"] is True
        assert result["last_error_type"] == "ApiError"

    @pytest.mark.asyncio
    async def test_waf_failures_without_cache_raise_update_failed(self):
        self.coord._fetch_all_data.side_effect = WafBlockedError("blocked")
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()), patch.object(
            self.coord, "_compute_retry_delay", side_effect=[60.0, 120.0]
        ):
            with pytest.raises(UpdateFailed):
                await self.coord._async_update_data()
        assert self.coord._consecutive_failures == 3

    @pytest.mark.asyncio
    async def test_network_failures_without_cache_raise_update_failed(self):
        self.coord._fetch_all_data.side_effect = NetworkError("offline")
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()), patch.object(
            self.coord, "_compute_retry_delay", side_effect=[10.0, 20.0]
        ):
            with pytest.raises(UpdateFailed):
                await self.coord._async_update_data()
        assert self.coord._consecutive_failures == 3

    @pytest.mark.asyncio
    async def test_waf_failures_with_cache_enable_offline_mode(self):
        cached_time = datetime(2026, 4, 20, tzinfo=timezone.utc)
        self.coord._last_good_data = {
            "contracts": {"REF1": {"reference": "REF1"}},
            "last_update_success_time": cached_time,
        }
        self.coord.data = None
        self.coord._fetch_all_data.side_effect = WafBlockedError("blocked")
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()), patch.object(
            self.coord, "_compute_retry_delay", side_effect=[60.0, 120.0]
        ), patch("custom_components.eau_grand_lyon.coordinator.check_long_outage_issue") as outage:
            result = await self.coord._async_update_data()
        assert result["offline_mode"] is True
        assert result["last_error_type"] == "WafBlockedError"
        assert result["consecutive_failures"] == 3
        assert result["offline_since"] is not None
        outage.assert_called_once()

    @pytest.mark.asyncio
    async def test_network_failures_with_existing_offline_cache_preserve_offline_since(self):
        offline_since = datetime(2026, 4, 21, tzinfo=timezone.utc)
        self.coord._last_good_data = {
            "contracts": {"REF1": {"reference": "REF1"}},
            "last_update_success_time": datetime(2026, 4, 20, tzinfo=timezone.utc),
        }
        self.coord.data = {"offline_mode": True, "offline_since": offline_since}
        self.coord._fetch_all_data.side_effect = NetworkError("offline")
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()), patch.object(
            self.coord, "_compute_retry_delay", side_effect=[10.0, 20.0]
        ), patch("custom_components.eau_grand_lyon.coordinator.check_long_outage_issue"):
            result = await self.coord._async_update_data()
        assert result["offline_mode"] is True
        assert result["offline_since"] == offline_since
        assert result["last_error_type"] == "NetworkError"

    @pytest.mark.asyncio
    async def test_success_clears_offline_flags_and_failure_count(self):
        self.coord._consecutive_failures = 2
        self.coord._fetch_all_data.return_value = {"contracts": {"REF1": {}}}
        with patch("custom_components.eau_grand_lyon.coordinator.check_long_outage_issue") as outage:
            result = await self.coord._async_update_data()
        assert result["offline_mode"] is False
        assert result["last_error"] is None
        assert result["consecutive_failures"] == 0
        assert self.coord._consecutive_failures == 0
        self.coord._save_persistent_data.assert_awaited_once()
        outage.assert_called_once_with(self.coord.hass, 0)

    @pytest.mark.asyncio
    async def test_offline_transition_is_logged_once_and_recovery_once(self, caplog):
        self.coord._max_retries = 1
        self.coord._api_offline = False
        self.coord._last_good_data = {
            "contracts": {"REF1": {"reference": "REF1"}},
            "last_update_success_time": datetime(2026, 4, 20, tzinfo=timezone.utc),
        }
        self.coord._fetch_all_data.side_effect = [
            NetworkError("offline"),
            NetworkError("offline"),
            {"contracts": {"REF1": {"reference": "REF1"}}},
        ]

        with caplog.at_level(logging.DEBUG, logger="custom_components.eau_grand_lyon.coordinator"), patch(
            "custom_components.eau_grand_lyon.coordinator.check_long_outage_issue"
        ):
            first = await self.coord._async_update_data()
            self.coord.data = first
            second = await self.coord._async_update_data()
            self.coord.data = second
            third = await self.coord._async_update_data()
            self.coord.data = third

        transition_logs = [record for record in caplog.records if "offline mode active" in record.message]
        recovery_logs = [record for record in caplog.records if "available again" in record.message]
        assert len(transition_logs) == 1
        assert transition_logs[0].levelno == logging.WARNING
        assert len(recovery_logs) == 1
        assert recovery_logs[0].levelno == logging.INFO
        assert third["offline_mode"] is False
        assert third["consecutive_failures"] == 0

    @pytest.mark.asyncio
    async def test_rate_limiting_sleeps_when_request_too_soon(self):
        self.coord._last_request_mono = 100.0
        self.coord._min_request_delay_s = 30.0
        self.coord._fetch_all_data.return_value = {"contracts": {"REF1": {}}}
        with patch(
            "custom_components.eau_grand_lyon.coordinator.time.monotonic",
            side_effect=[110.0, 140.0],
        ), patch(
            "custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()
        ) as sleep_mock, patch("custom_components.eau_grand_lyon.coordinator.check_long_outage_issue"):
            await self.coord._async_update_data()
        sleep_mock.assert_awaited_once_with(20.0)

    def test_compute_retry_delay_applies_exponential_backoff_without_jitter(self):
        with patch("custom_components.eau_grand_lyon.coordinator.random.uniform", return_value=0.0):
            assert self.coord._compute_retry_delay(10.0, 0) == 10.0
            assert self.coord._compute_retry_delay(10.0, 1) == 20.0
            assert self.coord._compute_retry_delay(10.0, 2) == 40.0

    def test_compute_retry_delay_applies_jitter(self):
        with patch("custom_components.eau_grand_lyon.coordinator.random.uniform", return_value=3.0):
            assert self.coord._compute_retry_delay(10.0, 1) == 23.0

    def test_calculate_cache_age_days_returns_none_without_timestamp(self):
        assert self.coord._calculate_cache_age_days(None) is None

    def test_calculate_cache_age_days_returns_elapsed_days(self):
        now = datetime.now(timezone.utc)
        age = self.coord._calculate_cache_age_days(now - timedelta(days=3, hours=1))
        assert age == 3

    @pytest.mark.asyncio
    async def test_custom_max_retries_is_honored(self):
        self.coord._max_retries = 4
        self.coord._fetch_all_data.side_effect = NetworkError("offline")
        with patch(
            "custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()
        ) as sleep_mock, patch.object(self.coord, "_compute_retry_delay", side_effect=[10.0, 20.0, 40.0]):
            with pytest.raises(UpdateFailed):
                await self.coord._async_update_data()
        assert self.coord._consecutive_failures == 4
        assert sleep_mock.await_count == 3

    @pytest.mark.asyncio
    async def test_inject_statistics_cost_metadata_unit_class_is_none(self):
        """Cost stats must set unit_class=None (currency has no converter; omitting it is deprecated)."""
        self.coord.hass = MagicMock()
        self.coord._stats_month_counts = {}
        self.coord._monthly_history = {}

        contract_data = {
            "REF1": {
                "tarif_m3": 1.5,
                "consommations": [
                    {"mois_index": 0, "annee": 2025, "consommation_m3": 10.0},
                    {"mois_index": 1, "annee": 2025, "consommation_m3": 12.0},
                ],
            }
        }

        with patch(
            "custom_components.eau_grand_lyon.coordinator.async_add_external_statistics",
            new=MagicMock(return_value=None),
        ) as add_stats:
            await self.coord._inject_statistics(contract_data)

        cost_calls = [
            call for call in add_stats.call_args_list if call.args[1]["statistic_id"] == "eau_grand_lyon:cost_ref1"
        ]
        assert cost_calls, "expected cost statistics to be injected"
        cost_metadata = cost_calls[0].args[1]
        assert "unit_class" in cost_metadata
        assert cost_metadata["unit_class"] is None
        assert cost_metadata["unit_of_measurement"] == "EUR"

    @pytest.mark.asyncio
    async def test_injects_daily_statistics_without_monthly_data(self):
        self.coord.hass = MagicMock()
        self.coord._monthly_history = {}
        contract_data = {
            "REF1": {
                "consommations": [],
                "consommations_journalieres": [
                    {"date": "2026-08-16", "consommation_m3": 1.0},
                ],
            }
        }

        with patch(
            "custom_components.eau_grand_lyon.coordinator.async_add_external_statistics",
            new=MagicMock(return_value=None),
        ) as add_stats:
            await self.coord._inject_statistics(contract_data)

        assert [call.args[1]["statistic_id"] for call in add_stats.call_args_list] == [
            "eau_grand_lyon:water_daily_ref1",
        ]

    @pytest.mark.asyncio
    async def test_injects_daily_cost_statistics_separately(self):
        self.coord.hass = MagicMock()
        self.coord._monthly_history = {}
        self.coord._daily_history = {}
        contract_data = {
            "REF1": {
                "tarif_m3": 5.0,
                "consommations": [],
                "consommations_journalieres": [
                    {"date": "2026-08-16", "consommation_m3": 1.2},
                ],
            }
        }

        with patch(
            "custom_components.eau_grand_lyon.coordinator.async_add_external_statistics",
            new=MagicMock(return_value=None),
        ) as add_stats:
            await self.coord._inject_statistics(contract_data)

        calls = {call.args[1]["statistic_id"]: call for call in add_stats.call_args_list}
        assert set(calls) == {
            "eau_grand_lyon:water_daily_ref1",
            "eau_grand_lyon:cost_daily_ref1",
        }
        cost_metadata = calls["eau_grand_lyon:cost_daily_ref1"].args[1]
        cost_series = calls["eau_grand_lyon:cost_daily_ref1"].args[2]
        assert cost_metadata["unit_of_measurement"] == "EUR"
        assert cost_metadata["unit_class"] is None
        assert cost_series[0].sum == 6.0

    def test_build_stat_series_without_anchor_cumulates_from_zero(self):
        consos = [
            {"mois_index": 0, "annee": 2025, "consommation_m3": 10.0},
            {"mois_index": 1, "annee": 2025, "consommation_m3": 12.0},
            {"mois_index": 2, "annee": 2025, "consommation_m3": 8.0},
        ]
        with patch("custom_components.eau_grand_lyon.coordinator.StatisticData", new=lambda **kw: kw):
            series = EauGrandLyonCoordinator._build_stat_series(consos, lambda c: c, None, 3)
        assert [s["sum"] for s in series] == [10.0, 22.0, 30.0]
        assert [s["state"] for s in series] == [10.0, 12.0, 8.0]

    def test_build_stat_series_anchor_prevents_negative_delta(self):
        """Fenêtre glissante : le cumul repart de la base recorder, pas de 0 → jamais de delta négatif."""
        consos = [
            {"mois_index": 0, "annee": 2025, "consommation_m3": 10.0},  # Jan, déjà enregistré
            {"mois_index": 1, "annee": 2025, "consommation_m3": 12.0},  # Fév = dernier enregistré
            {"mois_index": 2, "annee": 2025, "consommation_m3": 8.0},  # Mars = nouveau
        ]
        # Recorder : dernier point = Fév 2025, somme cumulée 122 (base avant Fév = 110).
        anchor = ((2025, 2), 110.0)
        with patch("custom_components.eau_grand_lyon.coordinator.StatisticData", new=lambda **kw: kw):
            series = EauGrandLyonCoordinator._build_stat_series(consos, lambda c: c, anchor, 3)
        # Janvier (antérieur au dernier point) est préservé, pas ré-injecté.
        assert len(series) == 2
        # Fév repart de 110 (+12=122), Mars continue (+8=130) : suite strictement croissante.
        assert [s["sum"] for s in series] == [122.0, 130.0]
        assert all(series[i]["sum"] < series[i + 1]["sum"] for i in range(len(series) - 1))

    def test_build_stat_series_applies_value_fn_and_rounding(self):
        consos = [{"mois_index": 0, "annee": 2025, "consommation_m3": 10.0}]
        with patch("custom_components.eau_grand_lyon.coordinator.StatisticData", new=lambda **kw: kw):
            series = EauGrandLyonCoordinator._build_stat_series(consos, lambda c: round(c * 1.5, 2), None, 2)
        assert series[0]["state"] == 15.0
        assert series[0]["sum"] == 15.0

    def test_build_daily_stat_series_sorts_and_rebuilds_cumulative_values(self):
        daily = [
            {"date": "2026-08-18", "consommation_m3": 2.0},
            {"date": "2026-08-16", "consommation_m3": 1.0},
            {"date": "2026-08-17", "consommation_m3": 3.0},
        ]
        with patch("custom_components.eau_grand_lyon.coordinator.StatisticData", new=lambda **kw: kw):
            series = EauGrandLyonCoordinator._build_daily_stat_series(daily)
        assert [point["start"].date().isoformat() for point in series] == [
            "2026-08-16",
            "2026-08-17",
            "2026-08-18",
        ]
        assert [point["sum"] for point in series] == [1.0, 4.0, 6.0]

    def test_build_daily_stat_series_deduplicates_dates(self):
        daily = [
            {"date": "2026-08-16", "consommation_m3": 1.0},
            {"date": "2026-08-16", "consommation_m3": 2.5},
            {"date": "2026-08-17", "consommation_m3": 3.0},
        ]
        with patch("custom_components.eau_grand_lyon.coordinator.StatisticData", new=lambda **kw: kw):
            series = EauGrandLyonCoordinator._build_daily_stat_series(daily)
        assert len(series) == 2
        assert [point["state"] for point in series] == [2.5, 3.0]
        assert [point["sum"] for point in series] == [2.5, 5.5]

    def test_merge_daily_history_fresh_value_replaces_late_correction(self):
        merged = EauGrandLyonCoordinator._merge_daily_history(
            [{"date": "2026-08-16", "consommation_m3": 1.0}],
            [
                {"date": "2026-08-16", "consommation_m3": 2.5},
                {"date": "2026-08-17", "consommation_m3": 3.0},
            ],
        )
        assert merged == [
            {"date": "2026-08-16", "consommation_m3": 2.5},
            {"date": "2026-08-17", "consommation_m3": 3.0},
        ]

    def test_sanitize_daily_history_discards_corrupt_entries(self):
        stored = {
            "REF1": [
                {"date": "2026-08-16", "consommation_m3": 1.2},
                {"date": "not-a-date", "consommation_m3": 2.0},
                {"date": "2026-08-17", "consommation_m3": "nan"},
                None,
            ],
            "BROKEN": "not-a-list",
        }
        assert EauGrandLyonCoordinator._sanitize_daily_history(stored) == {
            "REF1": [{"date": "2026-08-16", "consommation_m3": 1.2}]
        }

    def test_statistic_ref_sanitizes_invalid_characters(self):
        """Recorder statistic ids only allow lowercase [a-z0-9_], no edge/double underscores.

        Regression: refs with uppercase letters or dashes produced an invalid
        statistic_id and statistics injection silently failed for those users.
        """
        assert EauGrandLyonCoordinator._statistic_ref("0123456789") == "0123456789"
        assert EauGrandLyonCoordinator._statistic_ref("REF1") == "ref1"
        assert EauGrandLyonCoordinator._statistic_ref("AB-12 34/X") == "ab_12_34_x"
        assert EauGrandLyonCoordinator._statistic_ref("--") == "contract"

    def test_statistic_id_preserves_public_prefixes_and_sanitizes_ref(self):
        assert EauGrandLyonCoordinator._statistic_id("water", "AB-12") == "eau_grand_lyon:water_ab_12"
        assert EauGrandLyonCoordinator._statistic_id("cost_daily", "REF1") == "eau_grand_lyon:cost_daily_ref1"

    @pytest.mark.asyncio
    async def test_offline_cache_persists_failure_context(self):
        now = datetime.now(timezone.utc)
        self.coord._last_good_data = {
            "contracts": {"REF1": {"reference": "REF1"}},
            "last_update_success_time": now - timedelta(days=7),
        }
        self.coord._fetch_all_data.side_effect = NetworkError("offline")
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()), patch.object(
            self.coord, "_compute_retry_delay", side_effect=[10.0, 20.0]
        ), patch("custom_components.eau_grand_lyon.coordinator.check_long_outage_issue"):
            result = await self.coord._async_update_data()
        assert isinstance(result["last_failure_time"], datetime)
        assert result["last_failure_reason"] == "offline"
        assert result["cache_age_days"] == 7

    def test_alert_notifications_use_sync_persistent_notification(self):
        """Regression: pn_create/pn_dismiss are sync; must not be wrapped in async_create_task."""
        from homeassistant.components.persistent_notification import async_create, async_dismiss

        async_create.reset_mock()
        async_dismiss.reset_mock()
        self.coord.hass = MagicMock()

        self.coord._prev_nb_alertes = 0
        self.coord._handle_alert_notifications(3)
        assert async_create.called
        # If wrapped in async_create_task(pn_create(...)), None would be passed to it.
        self.coord.hass.async_create_task.assert_not_called()

        self.coord._prev_nb_alertes = 3
        self.coord._handle_alert_notifications(0)
        assert async_dismiss.called
        self.coord.hass.async_create_task.assert_not_called()


class TestMergeMonthlyHistory:
    """Tests for _merge_monthly_history static method."""

    def _make_month(self, annee, mois_index, conso):
        return {"annee": annee, "mois_index": mois_index, "label": f"M{mois_index}/{annee}", "consommation_m3": conso}

    def test_empty_stored_returns_fresh(self):
        fresh = [self._make_month(2025, 1, 10.0), self._make_month(2025, 2, 12.0)]
        result = EauGrandLyonCoordinator._merge_monthly_history([], fresh)
        assert len(result) == 2
        assert result[0]["consommation_m3"] == 10.0

    def test_fresh_overrides_stored_for_same_month(self):
        stored = [self._make_month(2025, 1, 10.0)]
        fresh = [self._make_month(2025, 1, 15.0)]  # API has updated value
        result = EauGrandLyonCoordinator._merge_monthly_history(stored, fresh)
        assert len(result) == 1
        assert result[0]["consommation_m3"] == 15.0

    def test_accumulates_old_and_new_months(self):
        # Simulates API returning months 13-24 (old) stored, now returning months 1-12 (new)
        stored = [self._make_month(2024, m, 10.0) for m in range(1, 13)]  # 12 months 2024
        fresh = [self._make_month(2025, m, 12.0) for m in range(1, 13)]  # 12 months 2025
        result = EauGrandLyonCoordinator._merge_monthly_history(stored, fresh)
        assert len(result) == 24
        assert result[0]["annee"] == 2024
        assert result[-1]["annee"] == 2025

    def test_sorted_chronologically(self):
        stored = [self._make_month(2024, 6, 8.0), self._make_month(2024, 3, 9.0)]
        fresh = [self._make_month(2024, 1, 10.0)]
        result = EauGrandLyonCoordinator._merge_monthly_history(stored, fresh)
        years_months = [(e["annee"], e["mois_index"]) for e in result]
        assert years_months == sorted(years_months)

    def test_capped_at_max_months(self):
        stored = [self._make_month(2023, m, 10.0) for m in range(1, 13)]  # 12 months 2023
        fresh = [self._make_month(2024, m, 11.0) for m in range(1, 13)]  # 12 months 2024
        result = EauGrandLyonCoordinator._merge_monthly_history(stored, fresh, max_months=15)
        assert len(result) == 15
        # Most recent months kept
        assert result[-1]["annee"] == 2024

    def test_24_months_enables_n1_calculation(self):
        """After 1 year of accumulation, N-1 annual calculation becomes possible."""
        stored = [self._make_month(2024, m, 10.0) for m in range(1, 13)]
        fresh = [self._make_month(2025, m, 12.0) for m in range(1, 13)]
        merged = EauGrandLyonCoordinator._merge_monthly_history(stored, fresh)
        assert len(merged) >= 24
        last_24 = merged[-24:-12]
        conso_n1 = sum(e["consommation_m3"] for e in last_24)
        assert conso_n1 == pytest.approx(120.0)  # 12 × 10.0 from 2024


class TestCoordinatorFetchOrchestration:
    @pytest.mark.asyncio
    async def test_fetch_all_data_without_contracts_keeps_optional_global_data(self):
        coord = _make_coordinator()
        coord._entry.options = {}
        coord._monthly_history = {"OLD": [{"annee": 2025}]}
        coord._daily_history = {"OLD": [{"date": "2025-01-01"}]}
        coord.api = MagicMock()
        coord.api.experimental = False
        coord.api.get_contracts = AsyncMock(return_value=[])
        coord.api.get_alertes = AsyncMock(return_value=[])
        coord.api.get_factures = AsyncMock(return_value=[])
        coord._hubeau_client = MagicMock()
        coord._hubeau_client.async_get_water_quality = AsyncMock(return_value={"commune": "Lyon"})
        coord.api.get_interventions = AsyncMock(return_value=[])
        coord._calculate_tarif_m3 = MagicMock(return_value=4.0)
        coord._get_drought_level = MagicMock(return_value="normal")
        coord._check_vacation_alert = MagicMock(return_value=False)
        coord._inject_statistics = AsyncMock()
        coord._handle_alert_notifications = MagicMock()
        coord._save_monthly_history = AsyncMock()
        coord._save_daily_history = AsyncMock()

        result = await coord._fetch_all_data()

        assert result["contracts"] == {}
        assert result["global"]["nb_contracts"] == 0
        assert result["water_quality"] == {"commune": "Lyon"}
        assert result["api_mode"] == "Legacy"
        coord._inject_statistics.assert_awaited_once_with({})
        coord._handle_alert_notifications.assert_called_once_with(0)

    @pytest.mark.asyncio
    async def test_hubeau_failure_does_not_put_private_api_offline(self):
        coord = _make_coordinator()
        coord._entry.options = {}
        coord.api = MagicMock(experimental=False)
        coord.api.get_contracts = AsyncMock(return_value=[])
        coord.api.get_alertes = AsyncMock(return_value=[])
        coord.api.get_factures = AsyncMock(return_value=[])
        coord.api.get_interventions = AsyncMock(return_value=[])
        coord._hubeau_client = MagicMock()
        coord._hubeau_client.async_get_water_quality = AsyncMock(side_effect=RuntimeError("Hub'Eau down"))
        coord._calculate_tarif_m3 = MagicMock(return_value=4.0)
        coord._get_drought_level = MagicMock(return_value="normal")
        coord._check_vacation_alert = MagicMock(return_value=False)
        coord._inject_statistics = AsyncMock()
        coord._handle_alert_notifications = MagicMock()
        coord._save_monthly_history = AsyncMock()
        coord._save_daily_history = AsyncMock()

        result = await coord._fetch_all_data()

        assert result["contracts"] == {}
        assert result["last_error"] is None
        assert result["water_quality"]["durete_fh"] is None
        assert result["water_quality"]["source"].startswith("Hub'Eau")

    @pytest.mark.asyncio
    async def test_process_contract_combines_consumption_billing_and_alerts(self):
        coord = _make_coordinator()
        coord._entry.options = {"water_hardness": 30, "subscription_annual": 180}
        coord._daily_history = {}
        coord._monthly_history = {}
        cycle_api = MagicMock()
        cycle_api.get_monthly_consumptions = AsyncMock(
            return_value=[
                {"mois": 6, "annee": 2026, "consommation": 8.0},
                {"mois": 7, "annee": 2026, "consommation": 10.0},
            ]
        )
        daily = [
            {"date": "2026-08-01", "consommation_m3": 0.2, "index_m3": "100.2"},
            {"date": "2026-08-02", "consommation_m3": 0.3, "index_m3": "100.5"},
        ]
        cycle_api.get_daily_consumptions = AsyncMock(
            return_value={"entries": daily, "source": "Produits", "nb_entries": 2, "last_date": "2026-08-02"}
        )
        cycle_api.get_date_prochaine_facture = AsyncMock(return_value="2026-09-15")
        cycle_api.get_point_de_service_etendu = AsyncMock(
            return_value={
                "date_prochaine_releve": "2026-10-01",
                "conso_annuelle_ref_m3": 100.0,
                "mode_releve": "AMM",
                "communicabilite_amm": True,
            }
        )
        cycle_api.get_alerte_surconsommation = AsyncMock(
            return_value={
                "seuil_surconso_jour_m3": 0.25,
                "seuil_surconso_mois_m3": 9.0,
                "abonne_alerte_fuite": True,
            }
        )
        cycle_api.get_courbe_de_charge = AsyncMock(
            return_value=[
                {"date": "2026-08-02T08:00:00", "consommation": "bad"},
                {"date": "2026-08-02T09:00:00", "consommation": 0.4},
            ]
        )
        coord._calculate_intelligence = MagicMock(return_value=(12.0, 48.0, 25.0))
        coord._calculate_eco_score = MagicMock(return_value=(5.0, "A", 2))
        coord._calculate_experimental_leak = MagicMock(return_value=0.1)
        coord._detect_local_leak = MagicMock(return_value=True)
        coord._get_real_index = AsyncMock(return_value=100.5)

        result = await coord._process_contract(
            cycle_api,
            {"id": "C1", "reference": "REF1", "date_echeance": "2026-09-01", "teleo_compatible": True},
            4.0,
            [{"contrat_id": "C1", "reference": "INV-1"}],
            True,
        )

        assert result["consommation_mois_courant"] == 10.0
        assert result["cout_mois_courant_eur"] == 40.0
        assert result["next_bill_date"] == "2026-09-15"
        assert result["index_journalier_dernier"] == 100.5
        assert result["consommation_derniere_heure_m3"] == 0.4
        assert result["heure_pic"] == "09:00"
        assert result["surconso_jour_depassee"] is True
        assert result["surconso_mois_depassee"] is True
        assert result["derniere_facture"]["reference"] == "INV-1"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("optional_body", ["", "<!DOCTYPE html><html>maintenance</html>", "not-json"])
    async def test_invalid_optional_invoice_date_keeps_contract_online_without_global_retry(
        self, optional_body, caplog
    ):
        coord = _make_coordinator()
        coord._entry.data = {"tarif_m3": 4.0}
        coord._entry.options = {"water_hardness": 30}
        coord._daily_history = {}
        coord._monthly_history = {}
        coord._daily_history_store = MagicMock()
        coord._monthly_history_store = MagicMock()
        coord._store = MagicMock()
        coord._save_monthly_history = AsyncMock()
        coord._save_daily_history = AsyncMock()
        coord._inject_statistics = AsyncMock()
        coord._handle_alert_notifications = MagicMock()
        coord.vacation_mode = False

        api = EauGrandLyonApi(MagicMock(), "user@example.com", "secret")
        api.get_contracts = AsyncMock(
            return_value=[
                {
                    "id": "C1",
                    "reference": "REF1",
                    "dateEcheance": "2026-09-01",
                    "pointDeReleve": {"moduleRadio": {"etatPile": "OK"}},
                }
            ]
        )
        api.get_alertes = AsyncMock(return_value=[])
        api.get_factures = AsyncMock(return_value=[])
        coord._hubeau_client = MagicMock()
        coord._hubeau_client.async_get_water_quality = AsyncMock(return_value={"commune": "Lyon"})
        api.get_interventions = AsyncMock(return_value=[])
        api.get_monthly_consumptions = AsyncMock(return_value=[{"mois": 7, "annee": 2026, "consommation": 10.0}])
        api.get_daily_consumptions = AsyncMock(
            return_value={
                "entries": [{"date": "2026-08-01", "consommation_m3": 0.2, "index_m3": 100.2}],
                "source": "Produits",
                "nb_entries": 1,
                "last_date": "2026-08-01",
            }
        )
        api.get_point_de_service_etendu = AsyncMock(return_value={})
        api.get_alerte_surconsommation = AsyncMock(return_value={})
        api._request_text = AsyncMock(return_value=(200, "text/html", optional_body))
        coord.api = api

        with caplog.at_level(logging.DEBUG, logger="custom_components.eau_grand_lyon.coordinator"), patch(
            "custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()
        ) as sleep_mock, patch("custom_components.eau_grand_lyon.coordinator.check_long_outage_issue"):
            result = await coord._async_update_data()

        contract = result["contracts"]["REF1"]
        assert contract["next_bill_date"] is None
        assert contract["consommation_mois_courant"] == 10.0
        assert contract["index_journalier_dernier"] == 100.2
        assert result["offline_mode"] is False
        sleep_mock.assert_not_awaited()
        assert "skipped for this cycle" not in caplog.text


class TestBillingModes:
    def test_latest_invoice_reproduces_anonymized_real_total(self):
        coord = _make_coordinator(options={"tariff_mode": "latest_invoice", "subscription_annual": 999})

        result = coord._calculate_billing(
            {"calibre_compteur": "DN15"},
            {"montant_ttc": 328.42, "volume_m3": 88},
            8,
            88,
            88,
            5.20,
        )

        assert result["billing_mode"] == "latest_invoice"
        assert result["tariff_source"] == "latest_invoice_ttc_per_m3"
        assert result["cout_reel_annuel"] == 328.42
        assert result["subscription_annual"] == 0
        assert result["latest_invoice_effective_rate_eur_m3"] == pytest.approx(3.732045, abs=1e-6)

    def test_latest_invoice_without_volume_falls_back_to_official_grid(self):
        coord = _make_coordinator(options={"tariff_mode": "latest_invoice"})

        result = coord._calculate_billing(
            {"calibre_compteur": "15"},
            {"montant_ttc": 328.42, "volume_m3": 0},
            8,
            88,
            88,
            5.20,
        )

        assert result["billing_mode"] == "official_2026"
        assert result["subscription_annual"] == 50.66
        assert result["tariff_source"] == "official_2026_dn15"

    def test_manual_mode_preserves_legacy_flat_calculation(self):
        coord = _make_coordinator(options={"tariff_mode": "manual", "subscription_annual": 180})

        result = coord._calculate_billing({}, None, 10, 18, 18, 4.0)

        assert result["cout_mois_courant_eur"] == 40
        assert result["cout_reel_mois"] == 55
        assert result["cout_reel_annuel"] == 252
