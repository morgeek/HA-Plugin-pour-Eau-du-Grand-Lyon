"""Config flow et Options flow pour l'intégration Eau du Grand Lyon."""
from __future__ import annotations

import logging
import re
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import (
    AuthenticationError,
    ApiError,
    EauGrandLyonApi,
    NetworkError,
    WafBlockedError,
)
from .const import (
    CONF_EMAIL,
    CONF_EXPERIMENTAL,
    CONF_PASSWORD,
    CONF_PRICE_ENTITY,
    CONF_TARIF_M3,
    CONF_UPDATE_INTERVAL_HOURS,
    CONF_HOUSEHOLD_SIZE,
    CONF_WATER_HARDNESS,
    CONF_SUBSCRIPTION_ANNUAL,
    DEFAULT_EXPERIMENTAL,
    DEFAULT_HOUSEHOLD_SIZE,
    DEFAULT_TARIF_M3,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DEFAULT_WATER_HARDNESS,
    DEFAULT_SUBSCRIPTION_ANNUAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _validate_email(value: str) -> str:
    value = value.strip()
    if not _EMAIL_REGEX.match(value):
        raise vol.Invalid("invalid_email")
    return value


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): vol.All(str, _validate_email),
        vol.Required(CONF_PASSWORD): vol.All(str, vol.Length(min=4)),
        vol.Optional(CONF_TARIF_M3, default=DEFAULT_TARIF_M3): vol.All(
            vol.Coerce(float), vol.Range(min=0.5, max=30.0)
        ),
    }
)

_INTERVAL_OPTIONS = {
    6: "Toutes les 6 heures",
    12: "Toutes les 12 heures",
    24: "Une fois par jour (recommandé)",
    48: "Tous les 2 jours",
}


class EauGrandLyonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Flux de configuration de l'intégration Eau du Grand Lyon."""

    VERSION = 2

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> EauGrandLyonOptionsFlowHandler:
        """Retourne le gestionnaire du flux d'options."""
        return EauGrandLyonOptionsFlowHandler(config_entry)

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Flux de réauthentification après une erreur d'authentification."""
        config_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        if not config_entry:
            return self.async_abort(reason="reauth_failed")

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Confirmation de réauthentification : saisie des identifiants."""
        config_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        if not config_entry:
            return self.async_abort(reason="reauth_failed")

        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
                api = EauGrandLyonApi(session, email, password)
                try:
                    await api.authenticate()
                except AuthenticationError as err:
                    _LOGGER.warning("Réauth échouée: %s", err)
                    errors["base"] = "invalid_auth"
                except WafBlockedError as err:
                    _LOGGER.warning("Blocage WAF: %s", err)
                    errors["base"] = "waf_blocked"
                except NetworkError as err:
                    _LOGGER.warning("Erreur réseau: %s", err)
                    errors["base"] = "cannot_connect"
                except ApiError as err:
                    _LOGGER.warning("Erreur API: %s", err)
                    errors["base"] = "api_error"
                except Exception as err:  # noqa: BLE001
                    _LOGGER.exception("Erreur inattendue: %s", err)
                    errors["base"] = "unknown"
                else:
                    self.hass.config_entries.async_update_entry(
                        config_entry,
                        data={
                            **config_entry.data,
                            CONF_EMAIL: email,
                            CONF_PASSWORD: password,
                        },
                    )
                    await self.hass.config_entries.async_reload(config_entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        # Pré-remplir avec l'email courant
        current_email = config_entry.data.get(CONF_EMAIL, "")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=current_email): vol.All(
                        str, _validate_email
                    ),
                    vol.Required(CONF_PASSWORD): vol.All(str, vol.Length(min=4)),
                }
            ),
            errors=errors,
            description_placeholders={
                "site_url": "https://agence.eaudugrandlyon.com",
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Étape principale : saisie des identifiants."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]  # already stripped and validated by schema
            password = user_input[CONF_PASSWORD]

            async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
                api = EauGrandLyonApi(session, email, password)
                try:
                    await api.authenticate()
                except AuthenticationError as err:
                    _LOGGER.warning("Auth échouée: %s", err)
                    errors["base"] = "invalid_auth"
                except WafBlockedError as err:
                    _LOGGER.warning("Blocage WAF: %s", err)
                    errors["base"] = "waf_blocked"
                except NetworkError as err:
                    _LOGGER.warning("Erreur réseau: %s", err)
                    errors["base"] = "cannot_connect"
                except ApiError as err:
                    _LOGGER.warning("Erreur API: %s", err)
                    errors["base"] = "api_error"
                except Exception as err:  # noqa: BLE001
                    _LOGGER.exception("Erreur inattendue: %s", err)
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(email.lower())
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Eau du Grand Lyon ({email})",
                        data={
                            CONF_EMAIL: email,
                            CONF_PASSWORD: password,
                            CONF_TARIF_M3: user_input[CONF_TARIF_M3],
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "site_url": "https://agence.eaudugrandlyon.com",
                "recommended_interval": str(DEFAULT_UPDATE_INTERVAL_HOURS),
            },
        )


class EauGrandLyonOptionsFlowHandler(config_entries.OptionsFlow):
    """Options : intervalle de mise à jour + tarif au m³."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        super().__init__()
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Étape unique : modification des options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options or {}
        current_interval = int(opts.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS))
        current_tarif = float(
            opts[CONF_TARIF_M3]
            if CONF_TARIF_M3 in opts
            else self._config_entry.data.get(CONF_TARIF_M3, DEFAULT_TARIF_M3)
        )
        current_experimental = bool(opts.get(CONF_EXPERIMENTAL, DEFAULT_EXPERIMENTAL))
        current_price_entity = opts.get(CONF_PRICE_ENTITY, "")
        current_household = int(opts.get(CONF_HOUSEHOLD_SIZE, DEFAULT_HOUSEHOLD_SIZE))
        current_hardness = float(opts.get(CONF_WATER_HARDNESS, DEFAULT_WATER_HARDNESS))
        current_subscription = float(opts.get(CONF_SUBSCRIPTION_ANNUAL, DEFAULT_SUBSCRIPTION_ANNUAL))

        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL_HOURS,
                    default=current_interval,
                ): vol.In(_INTERVAL_OPTIONS),
                vol.Optional(
                    CONF_TARIF_M3,
                    default=current_tarif,
                ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=30.0)),
                vol.Optional(
                    CONF_PRICE_ENTITY,
                    default=current_price_entity,
                ): str,
                vol.Optional(
                    CONF_EXPERIMENTAL,
                    default=current_experimental,
                ): bool,
                vol.Optional(
                    CONF_HOUSEHOLD_SIZE,
                    default=current_household,
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
                vol.Optional(
                    CONF_WATER_HARDNESS,
                    default=current_hardness,
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0)),
                vol.Optional(
                    CONF_SUBSCRIPTION_ANNUAL,
                    default=current_subscription,
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2000.0)),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            description_placeholders={
                "hardness_lyon_avg": str(DEFAULT_WATER_HARDNESS),
                "subscription_example": "180",
            },
        )
