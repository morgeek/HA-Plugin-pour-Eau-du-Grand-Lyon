"""Tests for config flow error paths and recovery steps."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.eau_grand_lyon.api import (
    ApiError,
    AuthenticationError,
    NetworkError,
    WafBlockedError,
)
from custom_components.eau_grand_lyon.config_flow import (
    EauGrandLyonConfigFlow,
    EauGrandLyonOptionsFlowHandler,
    _authenticate_and_handle_errors,
)
from custom_components.eau_grand_lyon import _async_update_options
from custom_components.eau_grand_lyon.const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PRICE_ENTITY,
    CONF_TARIF_M3,
    CONF_TARIFF_MODE,
    DEFAULT_TARIFF_MODE,
)


class _FakeClientSession:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def patch_config_flow_runtime(monkeypatch):
    monkeypatch.setattr(
        "custom_components.eau_grand_lyon.config_flow.async_create_clientsession",
        _FakeClientSession,
        raising=False,
    )
    monkeypatch.setattr(
        "custom_components.eau_grand_lyon.config_flow.aiohttp.CookieJar",
        lambda: MagicMock(),
        raising=False,
    )
    monkeypatch.setattr(
        "custom_components.eau_grand_lyon.config_flow.aiohttp.ClientTimeout",
        lambda total=None: MagicMock(),
        raising=False,
    )
    monkeypatch.setattr(
        "custom_components.eau_grand_lyon.config_flow.vol.Required",
        lambda key, default=None, **kwargs: key,
    )
    monkeypatch.setattr(
        "custom_components.eau_grand_lyon.config_flow.vol.Optional",
        lambda key, default=None, **kwargs: key,
    )


class TestAuthenticateAndHandleErrors:
    @pytest.mark.asyncio
    async def test_authentication_uses_safe_cookie_jar(self, monkeypatch):
        cookie_jar = MagicMock(return_value=MagicMock())
        monkeypatch.setattr("custom_components.eau_grand_lyon.config_flow.aiohttp.CookieJar", cookie_jar)
        with patch(
            "custom_components.eau_grand_lyon.config_flow.EauGrandLyonApi.authenticate",
            new=AsyncMock(return_value="token"),
        ):
            assert await _authenticate_and_handle_errors(MagicMock(), "user@example.com", "secret") == {}
        cookie_jar.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_authentication_error_maps_to_invalid_auth(self):
        with patch(
            "custom_components.eau_grand_lyon.config_flow.EauGrandLyonApi.authenticate",
            new=AsyncMock(side_effect=AuthenticationError("bad creds")),
        ):
            errors = await _authenticate_and_handle_errors(MagicMock(), "user@example.com", "secret")
        assert errors == {"base": "invalid_auth"}

    @pytest.mark.asyncio
    async def test_waf_error_maps_to_waf_blocked(self):
        with patch(
            "custom_components.eau_grand_lyon.config_flow.EauGrandLyonApi.authenticate",
            new=AsyncMock(side_effect=WafBlockedError("blocked")),
        ):
            errors = await _authenticate_and_handle_errors(MagicMock(), "user@example.com", "secret")
        assert errors == {"base": "waf_blocked"}

    @pytest.mark.asyncio
    async def test_network_error_maps_to_cannot_connect(self):
        with patch(
            "custom_components.eau_grand_lyon.config_flow.EauGrandLyonApi.authenticate",
            new=AsyncMock(side_effect=NetworkError("offline")),
        ):
            errors = await _authenticate_and_handle_errors(MagicMock(), "user@example.com", "secret")
        assert errors == {"base": "cannot_connect"}

    @pytest.mark.asyncio
    async def test_api_error_maps_to_api_error(self):
        with patch(
            "custom_components.eau_grand_lyon.config_flow.EauGrandLyonApi.authenticate",
            new=AsyncMock(side_effect=ApiError("bad api")),
        ):
            errors = await _authenticate_and_handle_errors(MagicMock(), "user@example.com", "secret")
        assert errors == {"base": "api_error"}

    @pytest.mark.asyncio
    async def test_unexpected_error_maps_to_unknown(self):
        with patch(
            "custom_components.eau_grand_lyon.config_flow.EauGrandLyonApi.authenticate",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            errors = await _authenticate_and_handle_errors(MagicMock(), "user@example.com", "secret")
        assert errors == {"base": "unknown"}


def _make_flow(entry: MagicMock | None = None) -> tuple[EauGrandLyonConfigFlow, MagicMock]:
    flow = EauGrandLyonConfigFlow()
    flow.context = {"entry_id": "entry-1"}
    flow.hass = MagicMock()
    config_entry = entry or MagicMock()
    config_entry.entry_id = "entry-1"
    config_entry.unique_id = "old@example.com"
    config_entry.data = {CONF_EMAIL: "old@example.com", CONF_PASSWORD: "oldpw", "account_setting": "kept"}
    config_entry.options = {CONF_TARIF_M3: 4.8, "option_setting": "kept"}
    flow.hass.config_entries.async_get_entry.return_value = config_entry
    flow.hass.config_entries.async_reload = AsyncMock()
    flow.async_abort = MagicMock(side_effect=lambda **kw: {"type": "abort", **kw})
    flow.async_show_form = MagicMock(side_effect=lambda **kw: {"type": "form", **kw})
    flow.async_create_entry = MagicMock(side_effect=lambda **kw: {"type": "create_entry", **kw})
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    flow._abort_if_unique_id_mismatch = MagicMock()
    flow._get_reauth_entry = MagicMock(return_value=config_entry)
    flow._get_reconfigure_entry = MagicMock(return_value=config_entry)

    return flow, config_entry


class TestUserFlow:
    def test_options_flow_factory_returns_handler(self):
        assert isinstance(EauGrandLyonConfigFlow.async_get_options_flow(MagicMock()), EauGrandLyonOptionsFlowHandler)

    @pytest.mark.asyncio
    async def test_user_success_creates_entry_and_sets_unique_id(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={}),
        ):
            result = await flow.async_step_user(
                {CONF_EMAIL: "New@Example.com", CONF_PASSWORD: "secret", CONF_TARIF_M3: 5.2}
            )
        assert result["type"] == "create_entry"
        assert result["data"] == {CONF_EMAIL: "New@Example.com", CONF_PASSWORD: "secret"}
        assert result["options"] == {
            CONF_TARIF_M3: 5.2,
            CONF_TARIFF_MODE: DEFAULT_TARIFF_MODE,
        }
        # unique_id doit être l'email en minuscules (détection de doublon).
        flow.async_set_unique_id.assert_awaited_once_with("new@example.com")
        flow._abort_if_unique_id_configured.assert_called_once()

    @pytest.mark.asyncio
    async def test_user_invalid_email_shows_error(self):
        flow, _ = _make_flow()
        result = await flow.async_step_user({CONF_EMAIL: "not-an-email", CONF_PASSWORD: "secret", CONF_TARIF_M3: 5.2})
        assert result["errors"][CONF_EMAIL] == "invalid_email"


class TestReauthFlow:
    @pytest.mark.asyncio
    async def test_reauth_step_delegates_to_confirmation(self):
        flow, _ = _make_flow()
        flow.async_step_reauth_confirm = AsyncMock(return_value={"type": "form"})
        assert await flow.async_step_reauth() == {"type": "form"}
        flow.async_step_reauth_confirm.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_reauth_uses_modern_entry_helper(self):
        flow, _ = _make_flow()
        await flow.async_step_reauth_confirm()
        flow._get_reauth_entry.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_reauth_form_prefills_current_email(self):
        flow, _ = _make_flow()
        result = await flow.async_step_reauth_confirm()
        assert result["step_id"] == "reauth_confirm"
        assert result["errors"] == {}

    @pytest.mark.asyncio
    async def test_reauth_invalid_email_skips_authentication(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(),
        ) as authenticate:
            result = await flow.async_step_reauth_confirm({CONF_EMAIL: "invalid", CONF_PASSWORD: "secret"})
        assert result["errors"] == {CONF_EMAIL: "invalid_email"}
        authenticate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reauth_invalid_auth_shows_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "invalid_auth"}),
        ):
            result = await flow.async_step_reauth_confirm({CONF_EMAIL: "new@example.com", CONF_PASSWORD: "secret"})
        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_auth"}

    @pytest.mark.asyncio
    async def test_reauth_waf_error_shows_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "waf_blocked"}),
        ):
            result = await flow.async_step_reauth_confirm({CONF_EMAIL: "new@example.com", CONF_PASSWORD: "secret"})
        assert result["errors"] == {"base": "waf_blocked"}

    @pytest.mark.asyncio
    async def test_reauth_network_error_shows_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "cannot_connect"}),
        ):
            result = await flow.async_step_reauth_confirm({CONF_EMAIL: "new@example.com", CONF_PASSWORD: "secret"})
        assert result["errors"] == {"base": "cannot_connect"}

    @pytest.mark.asyncio
    async def test_reauth_success_updates_only_credentials_without_direct_reload(self):
        flow, entry = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={}),
        ):
            result = await flow.async_step_reauth_confirm({CONF_EMAIL: " Old@Example.com ", CONF_PASSWORD: "secret"})
        assert result == {"type": "abort", "reason": "reauth_successful"}
        flow.async_set_unique_id.assert_awaited_once_with("old@example.com")
        flow._abort_if_unique_id_mismatch.assert_called_once_with()
        assert flow._modern_update_calls == [
            (
                entry,
                {CONF_EMAIL: "Old@Example.com", CONF_PASSWORD: "secret"},
                "reauth_successful",
            )
        ]
        flow.hass.config_entries.async_update_entry.assert_called_once_with(
            entry,
            data={
                CONF_EMAIL: "Old@Example.com",
                CONF_PASSWORD: "secret",
                "account_setting": "kept",
            },
        )
        assert entry.options == {CONF_TARIF_M3: 4.8, "option_setting": "kept"}
        flow.hass.config_entries.async_reload.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reauth_different_email_is_rejected_before_update(self):
        flow, _ = _make_flow()
        flow._abort_if_unique_id_mismatch.side_effect = RuntimeError("unique_id_mismatch")
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={}),
        ), pytest.raises(RuntimeError, match="unique_id_mismatch"):
            await flow.async_step_reauth_confirm({CONF_EMAIL: "other@example.com", CONF_PASSWORD: "secret"})
        flow.hass.config_entries.async_update_entry.assert_not_called()
        flow.hass.config_entries.async_reload.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reauth_existing_account_conflict_does_not_replace_entry(self):
        flow, _ = _make_flow()
        flow._abort_if_unique_id_mismatch.side_effect = RuntimeError("existing account")
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={}),
        ), pytest.raises(RuntimeError, match="existing account"):
            await flow.async_step_reauth_confirm({CONF_EMAIL: "configured@example.com", CONF_PASSWORD: "secret"})
        assert flow._modern_update_calls == []


class TestReconfigureFlow:
    @pytest.mark.asyncio
    async def test_reconfigure_uses_modern_entry_helper(self):
        flow, _ = _make_flow()
        await flow.async_step_reconfigure()
        flow._get_reconfigure_entry.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_reconfigure_form_renders_without_errors(self):
        flow, _ = _make_flow()
        result = await flow.async_step_reconfigure()
        assert result["step_id"] == "reconfigure"
        assert result["errors"] == {}
        schema = getattr(result["data_schema"], "schema", result["data_schema"]._schema)
        assert set(schema) == {CONF_EMAIL, CONF_PASSWORD}
        assert CONF_TARIF_M3 not in schema

    @pytest.mark.asyncio
    async def test_reconfigure_invalid_auth_shows_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "invalid_auth"}),
        ):
            result = await flow.async_step_reconfigure(
                {
                    CONF_EMAIL: "new@example.com",
                    CONF_PASSWORD: "secret",
                }
            )
        assert result["errors"] == {"base": "invalid_auth"}

    @pytest.mark.asyncio
    async def test_reconfigure_invalid_email_skips_authentication(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(),
        ) as authenticate:
            result = await flow.async_step_reconfigure({CONF_EMAIL: "invalid", CONF_PASSWORD: "secret"})
        assert result["errors"] == {CONF_EMAIL: "invalid_email"}
        authenticate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reconfigure_api_error_shows_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "api_error"}),
        ):
            result = await flow.async_step_reconfigure(
                {
                    CONF_EMAIL: "new@example.com",
                    CONF_PASSWORD: "secret",
                }
            )
        assert result["errors"] == {"base": "api_error"}

    @pytest.mark.asyncio
    async def test_reconfigure_success_preserves_tariff_and_has_no_double_reload(self):
        flow, entry = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={}),
        ):
            result = await flow.async_step_reconfigure(
                {
                    CONF_EMAIL: "OLD@example.com",
                    CONF_PASSWORD: "secret",
                }
            )
        assert result == {"type": "abort", "reason": "reconfigure_successful"}
        assert flow._modern_update_calls == [
            (
                entry,
                {CONF_EMAIL: "OLD@example.com", CONF_PASSWORD: "secret"},
                "reconfigure_successful",
            )
        ]
        flow.hass.config_entries.async_update_entry.assert_called_once_with(
            entry,
            data={
                CONF_EMAIL: "OLD@example.com",
                CONF_PASSWORD: "secret",
                "account_setting": "kept",
            },
        )
        assert entry.options[CONF_TARIF_M3] == 4.8
        flow.hass.config_entries.async_reload.assert_not_awaited()

        await _async_update_options(flow.hass, entry)
        flow.hass.config_entries.async_reload.assert_awaited_once_with("entry-1")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("step_name", "reason"),
        [
            ("async_step_reauth_confirm", "reauth_successful"),
            ("async_step_reconfigure", "reconfigure_successful"),
        ],
    )
    async def test_ha_2024_11_fallback_updates_and_aborts_without_direct_reload(self, step_name, reason):
        flow, entry = _make_flow()
        # Mask only the missing HA capability. Our compatibility helper and the
        # complete reauth/reconfigure flow remain real and exercised.
        flow.async_update_and_abort = None
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={}),
        ):
            result = await getattr(flow, step_name)({CONF_EMAIL: " OLD@example.com ", CONF_PASSWORD: "new-secret"})

        assert result == {"type": "abort", "reason": reason}
        flow.hass.config_entries.async_update_entry.assert_called_once_with(
            entry,
            data={
                CONF_EMAIL: "OLD@example.com",
                CONF_PASSWORD: "new-secret",
                "account_setting": "kept",
            },
        )
        assert entry.options == {CONF_TARIF_M3: 4.8, "option_setting": "kept"}
        flow.hass.config_entries.async_reload.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reconfigure_different_account_is_rejected(self):
        flow, _ = _make_flow()
        flow._abort_if_unique_id_mismatch.side_effect = RuntimeError("unique_id_mismatch")
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={}),
        ), pytest.raises(RuntimeError, match="unique_id_mismatch"):
            await flow.async_step_reconfigure({CONF_EMAIL: "other@example.com", CONF_PASSWORD: "secret"})
        flow.hass.config_entries.async_update_entry.assert_not_called()


class TestUserFlowErrors:
    @pytest.mark.asyncio
    async def test_user_flow_invalid_auth_returns_form_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "invalid_auth"}),
        ):
            result = await flow.async_step_user(
                {
                    CONF_EMAIL: "new@example.com",
                    CONF_PASSWORD: "secret",
                    CONF_TARIF_M3: 5.2,
                }
            )
        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_auth"}

    @pytest.mark.asyncio
    async def test_user_flow_api_error_returns_form_error(self):
        flow, _ = _make_flow()
        with patch(
            "custom_components.eau_grand_lyon.config_flow._authenticate_and_handle_errors",
            new=AsyncMock(return_value={"base": "api_error"}),
        ):
            result = await flow.async_step_user(
                {
                    CONF_EMAIL: "new@example.com",
                    CONF_PASSWORD: "secret",
                    CONF_TARIF_M3: 5.2,
                }
            )
        assert result["errors"] == {"base": "api_error"}


class TestOptionsFlow:
    @pytest.mark.asyncio
    async def test_submit_creates_options_entry(self):
        flow = EauGrandLyonOptionsFlowHandler()
        flow.async_create_entry = MagicMock(side_effect=lambda **kw: {"type": "create_entry", **kw})
        options = {CONF_TARIF_M3: 5.4}
        result = await flow.async_step_init(options)
        assert result == {"type": "create_entry", "title": "", "data": options}

    @pytest.mark.asyncio
    async def test_init_form_provides_description_placeholders(self):
        """Regression: options form must supply every {placeholder} its translations use."""
        flow = EauGrandLyonOptionsFlowHandler()
        flow.config_entry = MagicMock()
        flow.config_entry.options = {}
        flow.config_entry.data = {}
        flow.async_show_form = MagicMock(side_effect=lambda **kw: {"type": "form", **kw})

        result = await flow.async_step_init()

        placeholders = result["description_placeholders"]
        # These keys are referenced by water_hardness / subscription_annual
        # data_description strings; missing them raises formatjs MISSING_VALUE.
        assert placeholders["hardness_lyon_avg"] == "30"
        assert placeholders["subscription_example"] == "50.66"

    @pytest.mark.asyncio
    async def test_invalid_legacy_tariff_mode_falls_back_to_supported_default(self, monkeypatch):
        optional_defaults = {}

        def spy_optional(key, default=None, **kwargs):
            optional_defaults[key] = default
            return key

        monkeypatch.setattr("custom_components.eau_grand_lyon.config_flow.vol.Optional", spy_optional)
        flow = EauGrandLyonOptionsFlowHandler()
        flow.config_entry = MagicMock()
        flow.config_entry.options = {CONF_TARIFF_MODE: "removed-provider-mode"}
        flow.config_entry.data = {}
        flow.async_show_form = MagicMock(side_effect=lambda **kw: {"type": "form", **kw})

        await flow.async_step_init()

        assert optional_defaults[CONF_TARIFF_MODE] == DEFAULT_TARIFF_MODE

    @pytest.mark.asyncio
    async def test_price_entity_field_has_no_invalid_default(self, monkeypatch):
        """Régression (retour utilisateur) : un EntitySelector avec `default=""`
        crashe ("Entity is neither a valid entity ID nor a valid UUID.") dès
        qu'aucune entité de prix n'est configurée — le cas le plus courant —
        car vol.Optional(key, default=X) valide X même quand la clé est absente
        de l'input. Le champ doit donc être construit SANS `default` invalide ;
        `description={"suggested_value": ...}` est utilisé pour le pré-remplissage
        à la place (reproduit et vérifié manuellement avec la vraie voluptuous :
        vol.Optional(key, default="") lève sur un schema({}) vide)."""
        calls: dict[str, dict] = {}

        def spy_optional(key, default=None, **kwargs):
            calls[key] = {"default": default, "kwargs": kwargs}
            return key

        monkeypatch.setattr(
            "custom_components.eau_grand_lyon.config_flow.vol.Optional",
            spy_optional,
        )
        flow = EauGrandLyonOptionsFlowHandler()
        flow.config_entry = MagicMock()
        flow.config_entry.options = {}
        flow.config_entry.data = {}
        flow.async_show_form = MagicMock(side_effect=lambda **kw: {"type": "form", **kw})

        await flow.async_step_init()

        price_entity_call = calls[CONF_PRICE_ENTITY]
        assert price_entity_call["default"] is None
        assert price_entity_call["kwargs"].get("description") == {"suggested_value": None}
