"""Tests for new Phase 2–3 features: token revocation, parse_siamm_index,
sensor attribute capping, smart stats injection, service lifecycle, and
config entry migration.
"""
from __future__ import annotations

import json
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from custom_components.eau_grand_lyon.api import (
    EauGrandLyonApi,
    AuthenticationError,
    WafBlockedError,
    ApiError,
    NetworkError,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_response(status: int, body) -> MagicMock:
    """Crée un faux objet aiohttp.ClientResponse."""
    resp = MagicMock()
    resp.status = status
    if isinstance(body, (dict, list)):
        text = json.dumps(body)
    else:
        text = str(body)
    resp.text = AsyncMock(return_value=text)
    resp.url = MagicMock()
    resp.url.__str__ = lambda self: "https://agence.eaudugrandlyon.com/test"
    resp.raise_for_status = MagicMock()
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_session(responses: list) -> MagicMock:
    """Crée une session aiohttp simulée avec une file de réponses."""
    session = MagicMock()
    resp_iter = iter(responses)

    def _ctx(*args, **kwargs):
        resp = next(resp_iter)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    session.post = MagicMock(side_effect=_ctx)
    session.get  = MagicMock(side_effect=_ctx)
    return session


# ══════════════════════════════════════════════════════════════════════════════
# Item 1: Token Revocation
# ══════════════════════════════════════════════════════════════════════════════

class TestTokenRevocation:
    """Tests for EauGrandLyonApi.async_revoke_token."""

    @pytest.mark.asyncio
    async def test_revoke_calls_endpoint_and_clears_token(self):
        """Token is sent to revoke URL and cleared locally."""
        revoke_resp = _make_response(200, "OK")
        session = _make_session([revoke_resp])
        api = EauGrandLyonApi(session, "u@test.com", "pass")
        api._access_token = "MY_TOKEN"

        await api.async_revoke_token()

        # Token cleared
        assert api._access_token is None
        # Post was called with the token
        session.post.assert_called_once()
        call_kwargs = session.post.call_args
        assert "token" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_revoke_noop_when_no_token(self):
        """If there's no token, revoke does nothing (no network call)."""
        session = MagicMock()
        api = EauGrandLyonApi(session, "u@test.com", "pass")
        api._access_token = None

        await api.async_revoke_token()

        # No HTTP calls made
        session.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_best_effort_on_network_error(self):
        """Network errors during revocation are silently swallowed."""
        session = MagicMock()
        # Simulate network error
        err_ctx = MagicMock()
        err_ctx.__aenter__ = AsyncMock(side_effect=Exception("network down"))
        err_ctx.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=err_ctx)

        api = EauGrandLyonApi(session, "u@test.com", "pass")
        api._access_token = "TOKEN_TO_REVOKE"

        # Should NOT raise
        await api.async_revoke_token()
        # Token should still be cleared
        assert api._access_token is None


# ══════════════════════════════════════════════════════════════════════════════
# Item 4: parse_siamm_index
# ══════════════════════════════════════════════════════════════════════════════

class TestParseSiammIndex:
    """Tests for the static method parse_siamm_index."""

    def test_extracts_volume_from_grandeurs_physiques(self):
        data = {
            "grandeursPhysiques": [
                {
                    "modeleGrandeurPhysique": {"code": "DEBIT"},
                    "valeur": 0.5,
                },
                {
                    "modeleGrandeurPhysique": {"code": "VOLUME"},
                    "valeur": 1234.567,
                },
            ]
        }
        assert EauGrandLyonApi.parse_siamm_index(data) == 1234.567

    def test_returns_none_when_no_volume_code(self):
        data = {
            "grandeursPhysiques": [
                {"modeleGrandeurPhysique": {"code": "DEBIT"}, "valeur": 0.5},
            ]
        }
        assert EauGrandLyonApi.parse_siamm_index(data) is None

    def test_returns_none_on_empty_dict(self):
        assert EauGrandLyonApi.parse_siamm_index({}) is None

    def test_returns_none_on_none_input(self):
        assert EauGrandLyonApi.parse_siamm_index(None) is None

    def test_returns_none_on_non_dict_input(self):
        assert EauGrandLyonApi.parse_siamm_index("invalid") is None

    def test_returns_none_on_non_numeric_valeur(self):
        data = {
            "grandeursPhysiques": [
                {
                    "modeleGrandeurPhysique": {"code": "VOLUME"},
                    "valeur": "not_a_number",
                },
            ]
        }
        # Should return None (ValueError caught)
        assert EauGrandLyonApi.parse_siamm_index(data) is None

    def test_handles_missing_modele_key_gracefully(self):
        data = {
            "grandeursPhysiques": [
                {"valeur": 100},  # no modeleGrandeurPhysique
            ]
        }
        assert EauGrandLyonApi.parse_siamm_index(data) is None

    def test_handles_zero_valeur(self):
        data = {
            "grandeursPhysiques": [
                {
                    "modeleGrandeurPhysique": {"code": "VOLUME"},
                    "valeur": 0,
                },
            ]
        }
        assert EauGrandLyonApi.parse_siamm_index(data) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Item 6: Daily attribute capping (sensor.py)
# ══════════════════════════════════════════════════════════════════════════════

class TestAttributeCapping:
    """Tests verifying that sensor attributes are capped to avoid DB bloat."""

    def test_conso_30j_attributes_capped_to_14_days(self):
        """The 30J sensor should only expose 14 days in attributes, not 30."""
        from custom_components.eau_grand_lyon.sensor import EauGrandLyonConso30JSensor

        # Create a minimal mock
        coordinator = MagicMock()
        daily_data = [
            {"date": f"2024-01-{i:02d}", "consommation_m3": 0.5}
            for i in range(1, 31)  # 30 entries
        ]
        coordinator.data = {
            "contracts": {
                "REF001": {
                    "consommation_30j": 15.0,
                    "consommations_journalieres": daily_data,
                }
            }
        }

        sensor = EauGrandLyonConso30JSensor.__new__(EauGrandLyonConso30JSensor)
        sensor.coordinator = coordinator
        sensor._contract_ref = "REF001"
        sensor._attr_unique_id = "test_entry_REF001_conso_30j"

        attrs = sensor.extra_state_attributes
        # nb_jours_inclus should reflect the 30-day window for the value
        assert attrs["nb_jours_inclus"] == 30
        # But actual detail should be capped to 14
        assert len(attrs["derniers_jours"]) == 14

    def test_fuite_attributes_capped_to_14_days(self):
        """The Fuite sensor should only expose 14 days of detail."""
        from custom_components.eau_grand_lyon.sensor import EauGrandLyonFuiteEstimeeSensor

        coordinator = MagicMock()
        daily_data = [
            {
                "date": f"2024-01-{i:02d}",
                "consommation_m3": 0.5,
                "volume_fuite_estime_m3": 0.01,
            }
            for i in range(1, 31)  # 30 entries
        ]
        coordinator.data = {
            "contracts": {
                "REF001": {
                    "fuite_estimee_30j_m3": 0.3,
                    "consommations_journalieres": daily_data,
                }
            }
        }

        sensor = EauGrandLyonFuiteEstimeeSensor.__new__(EauGrandLyonFuiteEstimeeSensor)
        sensor.coordinator = coordinator
        sensor._contract_ref = "REF001"

        attrs = sensor.extra_state_attributes
        # Total available should count all 30
        assert attrs["nb_jours_avec_donnée"] == 30
        # But detail capped to 14
        assert len(attrs["détail_journalier"]) == 14


# ══════════════════════════════════════════════════════════════════════════════
# Item 3: Service lifecycle (register/unregister)
# ══════════════════════════════════════════════════════════════════════════════

class TestServiceLifecycle:
    """Tests verifying services are registered on setup and cleaned on unload."""

    @pytest.mark.asyncio
    async def test_services_removed_when_last_entry_unloaded(self):
        """When the last config entry is unloaded, services must be removed."""
        from custom_components.eau_grand_lyon import async_unload_entry
        from custom_components.eau_grand_lyon.const import DOMAIN

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "entry_1"

        # Simulate one coordinator in data
        mock_coordinator = MagicMock()
        mock_coordinator.async_close = AsyncMock()
        hass.data = {DOMAIN: {"entry_1": mock_coordinator}}

        # After popping, the dict is empty
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        hass.services.has_service = MagicMock(return_value=True)
        hass.services.async_remove = MagicMock()

        result = await async_unload_entry(hass, entry)

        assert result is True
        # Services should be removed
        assert hass.services.async_remove.call_count == 3  # clear_cache + update_now + export_data


# ══════════════════════════════════════════════════════════════════════════════
# Item 9: Config entry migration
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigMigration:
    """Tests for async_migrate_entry scaffold."""

    @pytest.mark.asyncio
    async def test_migration_v1_to_v2_succeeds(self):
        """Existing v1 entries are migrated to v2 without data changes."""
        from custom_components.eau_grand_lyon.config_flow import EauGrandLyonConfigFlow

        hass = MagicMock()
        entry = MagicMock()
        entry.version = 1
        entry.entry_id = "test_entry"
        entry.data = {"email": "u@test.com", "password": "pass", "tarif_m3": 3.5}

        result = await EauGrandLyonConfigFlow.async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 2

    @pytest.mark.asyncio
    async def test_migration_already_v2_succeeds(self):
        """Already-v2 entries pass through without issue."""
        from custom_components.eau_grand_lyon.config_flow import EauGrandLyonConfigFlow

        hass = MagicMock()
        entry = MagicMock()
        entry.version = 2
        entry.entry_id = "test_entry"

        result = await EauGrandLyonConfigFlow.async_migrate_entry(hass, entry)

        assert result is True
        assert entry.version == 2
