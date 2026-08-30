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
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers import selector

from .api import (
    ApiError,
    AuthenticationError,
    EauGrandLyonApi,
    NetworkError,
    WafBlockedError,
)
from .const import (
    CONF_EMAIL,
    CONF_EXPERIMENTAL,
    CONF_HOUSEHOLD_SIZE,
    CONF_LEAK_MULTIPLIER,
    CONF_MAX_RETRIES,
    CONF_PASSWORD,
    CONF_PRICE_ENTITY,
    CONF_SUBSCRIPTION_ANNUAL,
    CONF_TARIF_M3,
    CONF_TARIFF_MODE,
    CONF_UPDATE_INTERVAL_HOURS,
    CONF_WATER_HARDNESS,
    CONF_WATER_QUALITY_COMMUNE,
    DEFAULT_EXPERIMENTAL,
    DEFAULT_HOUSEHOLD_SIZE,
    DEFAULT_LEAK_MULTIPLIER,
    DEFAULT_MAX_RETRIES,
    DEFAULT_SUBSCRIPTION_ANNUAL,
    DEFAULT_TARIF_M3,
    DEFAULT_TARIFF_MODE,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DEFAULT_WATER_HARDNESS,
    DEFAULT_WATER_QUALITY_COMMUNE,
    DOMAIN,
    TARIFF_MODES,
)

_LOGGER = logging.getLogger(__name__)

_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _is_valid_email(value: str) -> bool:
    return bool(_EMAIL_REGEX.match((value or "").strip()))


async def _authenticate_and_handle_errors(
    hass: HomeAssistant, email: str, password: str, context: str = ""
) -> dict[str, str]:
    """Authenticate user and return error dict if authentication fails, or empty dict on success."""
    errors: dict[str, str] = {}
    async with async_create_clientsession(
        hass,
        cookie_jar=aiohttp.CookieJar(),
        timeout=aiohttp.ClientTimeout(total=30),
    ) as session:
        api = EauGrandLyonApi(session, email, password)
        try:
            await api.authenticate()
        except AuthenticationError as err:
            _LOGGER.warning("Authentication failed%s: %s", context, err)
            errors["base"] = "invalid_auth"
        except WafBlockedError as err:
            _LOGGER.warning("WAF blocked%s: %s", context, err)
            errors["base"] = "waf_blocked"
        except NetworkError as err:
            _LOGGER.warning("Network error%s: %s", context, err)
            errors["base"] = "cannot_connect"
        except ApiError as err:
            _LOGGER.warning("API error%s: %s", context, err)
            errors["base"] = "api_error"
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Unexpected error%s: %s", context, err)
            errors["base"] = "unknown"
    return errors


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): vol.All(str, vol.Length(min=4)),
        vol.Optional(CONF_TARIF_M3, default=DEFAULT_TARIF_M3): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=30.0)),
    }
)

# Valeurs (en heures) proposées pour l'intervalle. Les libellés sont traduits
# côté frontend via la section `selector.update_interval` de strings.json.
_INTERVAL_VALUES = ["6", "12", "24", "48"]


class EauGrandLyonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Flux de configuration de l'intégration Eau du Grand Lyon."""

    VERSION = 4

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> EauGrandLyonOptionsFlowHandler:
        """Retourne le gestionnaire du flux d'options."""
        return EauGrandLyonOptionsFlowHandler()

    def _async_update_and_abort_compat(
        self,
        config_entry: ConfigEntry,
        *,
        data_updates: dict[str, Any],
        reason: str,
    ) -> config_entries.FlowResult:
        """Update credentials with the best ConfigFlow API available.

        ``async_update_and_abort`` is the primary path on recent Home Assistant
        releases. Home Assistant 2024.11 does not expose it, so that version
        receives the equivalent update without a direct reload; the config-entry
        update listener remains the sole owner of the reload.
        """
        modern_update = getattr(self, "async_update_and_abort", None)
        if callable(modern_update):
            return modern_update(
                config_entry,
                data_updates=data_updates,
                reason=reason,
            )

        data = dict(config_entry.data)
        data.update(data_updates)
        self.hass.config_entries.async_update_entry(config_entry, data=data)
        return self.async_abort(reason=reason)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        """Flux de réauthentification après une erreur d'authentification."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        """Confirmation de réauthentification : saisie des identifiants."""
        config_entry = self._get_reauth_entry()

        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]
            if not _is_valid_email(email):
                errors[CONF_EMAIL] = "invalid_email"
            else:
                errors = await _authenticate_and_handle_errors(self.hass, email, password, " (reauth)")
            if not errors:
                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_mismatch()
                return self._async_update_and_abort_compat(
                    config_entry,
                    data_updates={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                    },
                    reason="reauth_successful",
                )

        # Pré-remplir avec l'email courant
        current_email = config_entry.data.get(CONF_EMAIL, "")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=current_email): str,
                    vol.Required(CONF_PASSWORD): vol.All(str, vol.Length(min=4)),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        """Flux de reconfiguration : permet de changer les identifiants."""
        config_entry = self._get_reconfigure_entry()

        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]
            if not _is_valid_email(email):
                errors[CONF_EMAIL] = "invalid_email"
            else:
                errors = await _authenticate_and_handle_errors(self.hass, email, password, " (reconfigure)")
            if not errors:
                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_mismatch()
                return self._async_update_and_abort_compat(
                    config_entry,
                    data_updates={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                    },
                    reason="reconfigure_successful",
                )

        # Le tarif est une option et ne doit jamais être dupliqué dans data.
        current_email = config_entry.data.get(CONF_EMAIL, "")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=current_email): str,
                    vol.Required(CONF_PASSWORD): vol.All(str, vol.Length(min=4)),
                }
            ),
            errors=errors,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        """Étape principale : saisie des identifiants."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]
            if not _is_valid_email(email):
                errors[CONF_EMAIL] = "invalid_email"
            else:
                errors = await _authenticate_and_handle_errors(self.hass, email, password)
            if not errors:
                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Eau du Grand Lyon ({email})",
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                    },
                    options={
                        CONF_TARIF_M3: user_input[CONF_TARIF_M3],
                        CONF_TARIFF_MODE: DEFAULT_TARIFF_MODE,
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

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        """Étape unique : modification des options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options or {}
        current_interval = int(opts.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS))
        current_tarif = float(
            opts[CONF_TARIF_M3]
            if CONF_TARIF_M3 in opts
            else self.config_entry.data.get(CONF_TARIF_M3, DEFAULT_TARIF_M3)
        )
        current_tariff_mode = opts.get(CONF_TARIFF_MODE, DEFAULT_TARIFF_MODE)
        if current_tariff_mode not in TARIFF_MODES:
            current_tariff_mode = DEFAULT_TARIFF_MODE
        current_experimental = bool(opts.get(CONF_EXPERIMENTAL, DEFAULT_EXPERIMENTAL))
        current_max_retries = int(opts.get(CONF_MAX_RETRIES, DEFAULT_MAX_RETRIES))
        current_price_entity = opts.get(CONF_PRICE_ENTITY, "")
        current_household = int(opts.get(CONF_HOUSEHOLD_SIZE, DEFAULT_HOUSEHOLD_SIZE))
        current_hardness = float(opts.get(CONF_WATER_HARDNESS, DEFAULT_WATER_HARDNESS))
        current_commune = opts.get(CONF_WATER_QUALITY_COMMUNE, DEFAULT_WATER_QUALITY_COMMUNE)
        current_subscription = float(opts.get(CONF_SUBSCRIPTION_ANNUAL, DEFAULT_SUBSCRIPTION_ANNUAL))
        current_leak_multiplier = float(opts.get(CONF_LEAK_MULTIPLIER, DEFAULT_LEAK_MULTIPLIER))

        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL_HOURS,
                    default=str(current_interval),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_INTERVAL_VALUES,
                        translation_key="update_interval",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_TARIFF_MODE,
                    default=current_tariff_mode,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=TARIFF_MODES,
                        translation_key="tariff_mode",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_TARIF_M3,
                    default=current_tarif,
                ): vol.All(vol.Coerce(float), vol.Range(min=0.5, max=30.0)),
                # Pas de `default=` : un EntitySelector valide sa valeur par défaut
                # même quand la clé est absente de l'input, et une chaîne vide
                # (aucune entité de prix configurée — le cas le plus courant)
                # provoque alors un crash "Entity is neither a valid entity ID
                # nor a valid UUID." à chaque sauvegarde des options. `suggested_value`
                # pré-remplit le champ sans déclencher de validation sur le vide.
                vol.Optional(
                    CONF_PRICE_ENTITY,
                    description={"suggested_value": current_price_entity or None},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "input_number"])),
                vol.Optional(
                    CONF_EXPERIMENTAL,
                    default=current_experimental,
                ): bool,
                vol.Optional(
                    CONF_MAX_RETRIES,
                    default=current_max_retries,
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=6)),
                vol.Optional(
                    CONF_HOUSEHOLD_SIZE,
                    default=current_household,
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
                vol.Optional(
                    CONF_WATER_HARDNESS,
                    default=current_hardness,
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0)),
                vol.Optional(
                    CONF_WATER_QUALITY_COMMUNE,
                    default=current_commune,
                ): str,
                vol.Optional(
                    CONF_SUBSCRIPTION_ANNUAL,
                    default=current_subscription,
                ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=2000.0)),
                vol.Optional(
                    CONF_LEAK_MULTIPLIER,
                    default=current_leak_multiplier,
                ): vol.All(vol.Coerce(float), vol.Range(min=1.5, max=10.0)),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            description_placeholders={
                "hardness_lyon_avg": "30",
                "subscription_example": "50.66",
            },
        )
