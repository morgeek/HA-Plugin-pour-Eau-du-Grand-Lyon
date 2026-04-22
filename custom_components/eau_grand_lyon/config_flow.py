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
    DEFAULT_EXPERIMENTAL,
    DEFAULT_TARIF_M3,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def validate_email(email: str) -> str:
    """Valide le format de l'email."""
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        raise vol.Invalid("Format d'email invalide")
    return email


def validate_password(password: str) -> str:
    """Valide la complexité du mot de passe."""
    if len(password) < 4:
        raise vol.Invalid("Le mot de passe doit contenir au moins 4 caractères")
    return password


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,  # no validator here
        vol.Required(CONF_PASSWORD): vol.All(str, vol.Length(min=4)),  # Length is fine
        vol.Optional(CONF_TARIF_M3, default=DEFAULT_TARIF_M3): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=30.0)),
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
    async def async_migrate_entry(
        hass: HomeAssistant, config_entry: ConfigEntry  # noqa: ARG004
    ) -> bool:
        """Migre les anciennes config entries vers le schéma courant.

        VERSION 1 → 2 :
        - Aucune modification de données nécessaire pour l'instant.
        - Ce scaffold existe pour permettre des migrations futures sans
          casser les installations existantes.
        """
        _LOGGER.debug(
            "Migration config entry %s de v%s vers v%s",
            config_entry.entry_id,
            config_entry.version,
            EauGrandLyonConfigFlow.VERSION,
        )
        # Ajouter des migrations ici quand nécessaire :
        # if config_entry.version == 1:
        #     new_data = {**config_entry.data, "new_field": "default"}
        #     hass.config_entries.async_update_entry(config_entry, data=new_data)
        config_entry.version = EauGrandLyonConfigFlow.VERSION
        return True

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
            if not _EMAIL_REGEX.match(email):
                errors[CONF_EMAIL] = "invalid_email"
            else:
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
                                CONF_TARIF_M3: user_input[CONF_TARIF_M3],
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
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
        )
