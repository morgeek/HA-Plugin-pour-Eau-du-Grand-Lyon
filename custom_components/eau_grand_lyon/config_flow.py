"""Config flow et Options flow pour l'intégration Eau du Grand Lyon."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry

from .api import (
    AuthenticationError,
    ApiError,
    EauGrandLyonApi,
    NetworkError,
    WafBlockedError,
)
from .const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_TARIF_M3,
    CONF_UPDATE_INTERVAL_HOURS,
    DEFAULT_TARIF_M3,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
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

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> EauGrandLyonOptionsFlowHandler:
        """Retourne le gestionnaire du flux d'options."""
        return EauGrandLyonOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Étape principale : saisie des identifiants."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]

            jar = aiohttp.CookieJar(unsafe=True)
            async with aiohttp.ClientSession(cookie_jar=jar) as session:
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
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "site_url": "https://agence.eaudugrandlyon.com",
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
            # Convertir en float pour le tarif (vol.Coerce peut retourner un int)
            user_input[CONF_TARIF_M3] = float(user_input[CONF_TARIF_M3])
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options or {}
        current_interval = int(opts.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS))
        current_tarif = float(opts.get(CONF_TARIF_M3, DEFAULT_TARIF_M3))

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
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            description_placeholders={
                "tarif_default": str(DEFAULT_TARIF_M3),
            },
        )
