"""Tests for EauGrandLyonCoordinator instance methods."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.eau_grand_lyon.api import ApiError, AuthenticationError, NetworkError, WafBlockedError
from custom_components.eau_grand_lyon.coordinator import EauGrandLyonCoordinator
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
        self.coord.data = {
            "contracts": {"REF1": {"real_index": 1234.567, "consommations": []}}
        }
        assert self.coord.get_cumulative_index("REF1") == 1234.6

    def test_sum_used_when_no_real_index(self, sample_consos):
        self.coord.data = {
            "contracts": {"REF1": {"consommations": sample_consos}}
        }
        expected = round(sum(e["consommation_m3"] for e in sample_consos), 1)
        assert self.coord.get_cumulative_index("REF1") == expected

    def test_empty_consos_returns_none(self):
        self.coord.data = {"contracts": {"REF1": {"consommations": []}}}
        assert self.coord.get_cumulative_index("REF1") is None

    def test_cache_hit_avoids_recompute(self, sample_consos):
        self.coord.data = {
            "contracts": {"REF1": {"consommations": sample_consos}}
        }
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
    async def test_authentication_error_starts_reauth_and_raises_update_failed(self):
        self.coord._fetch_all_data.side_effect = AuthenticationError("bad creds")
        with pytest.raises(UpdateFailed):
            await self.coord._async_update_data()
        self.coord._entry.async_start_reauth.assert_called_once_with(self.coord.hass)

    @pytest.mark.asyncio
    async def test_unexpected_error_raises_update_failed(self):
        self.coord._fetch_all_data.side_effect = ApiError("server exploded")
        with pytest.raises(UpdateFailed):
            await self.coord._async_update_data()

    @pytest.mark.asyncio
    async def test_waf_failures_without_cache_raise_update_failed(self):
        self.coord._fetch_all_data.side_effect = WafBlockedError("blocked")
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()), \
             patch.object(self.coord, "_compute_retry_delay", side_effect=[60.0, 120.0]):
            with pytest.raises(UpdateFailed):
                await self.coord._async_update_data()
        assert self.coord._consecutive_failures == 3

    @pytest.mark.asyncio
    async def test_network_failures_without_cache_raise_update_failed(self):
        self.coord._fetch_all_data.side_effect = NetworkError("offline")
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()), \
             patch.object(self.coord, "_compute_retry_delay", side_effect=[10.0, 20.0]):
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
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()), \
             patch.object(self.coord, "_compute_retry_delay", side_effect=[60.0, 120.0]), \
             patch("custom_components.eau_grand_lyon.coordinator.check_long_outage_issue") as outage:
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
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()), \
             patch.object(self.coord, "_compute_retry_delay", side_effect=[10.0, 20.0]), \
             patch("custom_components.eau_grand_lyon.coordinator.check_long_outage_issue"):
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
    async def test_rate_limiting_sleeps_when_request_too_soon(self):
        self.coord._last_request_mono = 100.0
        self.coord._min_request_delay_s = 30.0
        self.coord._fetch_all_data.return_value = {"contracts": {"REF1": {}}}
        with patch(
            "custom_components.eau_grand_lyon.coordinator.time.monotonic",
            side_effect=[110.0, 140.0],
        ), patch(
            "custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()
        ) as sleep_mock, patch(
            "custom_components.eau_grand_lyon.coordinator.check_long_outage_issue"
        ):
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
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()) as sleep_mock, \
             patch.object(self.coord, "_compute_retry_delay", side_effect=[10.0, 20.0, 40.0]):
            with pytest.raises(UpdateFailed):
                await self.coord._async_update_data()
        assert self.coord._consecutive_failures == 4
        assert sleep_mock.await_count == 3

    @pytest.mark.asyncio
    async def test_offline_cache_persists_failure_context(self):
        now = datetime.now(timezone.utc)
        self.coord._last_good_data = {
            "contracts": {"REF1": {"reference": "REF1"}},
            "last_update_success_time": now - timedelta(days=7),
        }
        self.coord._fetch_all_data.side_effect = NetworkError("offline")
        with patch("custom_components.eau_grand_lyon.coordinator.asyncio.sleep", new=AsyncMock()), \
             patch.object(self.coord, "_compute_retry_delay", side_effect=[10.0, 20.0]), \
             patch("custom_components.eau_grand_lyon.coordinator.check_long_outage_issue"):
            result = await self.coord._async_update_data()
        assert isinstance(result["last_failure_time"], datetime)
        assert result["last_failure_reason"] == "offline"
        assert result["cache_age_days"] == 7
