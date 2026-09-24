"""Coordinateur de mise à jour pour Eau du Grand Lyon."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, cast

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession, async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

if TYPE_CHECKING:
    from . import EauGrandLyonConfigEntry

from . import analytics
from .api import (
    ApiError,
    AuthenticationError,
    EauGrandLyonApi,
    NetworkError,
    WafBlockedError,
)
from .api.cycle_cache import CycleCachedApi
from .billing import build_billing_data
from .history import RebuildableStore, merge_daily_history, merge_monthly_history
from .hubeau import HubeauWaterQualityClient, empty_water_quality
from .models import (
    BillingData,
    ContractData,
    DailyConsumption,
    EauGrandLyonData,
    GlobalData,
    InvoiceData,
    MonthlyConsumption,
)
from .outages import parse_outage_alertes
from .recorder_statistics import async_inject_contract_statistics
from .warsmann import assess_warsmann
from .pfas import PfasClient, empty_pfas_data
from .vigieau import VigieauClient, empty_vigieau_data
from .const import (
    CACHE_MAX_AGE_DAYS,
    CONF_EMAIL,
    CONF_EXPERIMENTAL,
    CONF_HOUSEHOLD_SIZE,
    CONF_LEAK_MULTIPLIER,
    CONF_MAX_RETRIES,
    CONF_PASSWORD,
    CONF_PFAS_ENABLED,
    CONF_PRICE_ENTITY,
    CONF_SUBSCRIPTION_ANNUAL,
    CONF_TARIF_M3,
    CONF_TARIFF_MODE,
    CONF_UPDATE_INTERVAL_HOURS,
    CONF_VIGIEAU_ENABLED,
    CONF_WATER_HARDNESS,
    CONF_WATER_QUALITY_COMMUNE,
    DEFAULT_EXPERIMENTAL,
    DEFAULT_HOUSEHOLD_SIZE,
    DEFAULT_LEAK_MULTIPLIER,
    DEFAULT_MAX_RETRIES,
    DEFAULT_PFAS_ENABLED,
    DEFAULT_SUBSCRIPTION_ANNUAL,
    DEFAULT_TARIF_M3,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DEFAULT_VIGIEAU_ENABLED,
    DEFAULT_WATER_HARDNESS,
    DOMAIN,
    NETWORK_RETRY_BASE_DELAY_S,
    RATE_LIMIT_DELAY_S,
    RETRY_BACKOFF_MULTIPLIER,
    RETRY_JITTER_RATIO,
    TARIFF_MODE_DYNAMIC,
    TARIFF_MODE_MANUAL,
    TARIFF_MODES,
    WAF_RETRY_BASE_DELAY_S,
)
from .repairs import check_long_outage_issue

_LOGGER = logging.getLogger(__name__)


class EauGrandLyonCoordinator(DataUpdateCoordinator[EauGrandLyonData]):
    """Manages periodic data updates for Eau du Grand Lyon.

    Data schema is defined in ContractData and CoordinatorData TypedDicts.
    """

    def __init__(self, hass: HomeAssistant, entry: EauGrandLyonConfigEntry) -> None:
        options: dict[str, Any] = dict(entry.options)
        try:
            interval_hours = int(options.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS))
        except (ValueError, TypeError):
            interval_hours = DEFAULT_UPDATE_INTERVAL_HOURS

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=interval_hours),
        )
        self._entry = entry
        self._prev_nb_alertes = 0
        try:
            # max(1, ...) : une option à 0 donnerait range(0) → aucune tentative.
            self._max_retries = max(1, int(options.get(CONF_MAX_RETRIES, DEFAULT_MAX_RETRIES)))
        except (ValueError, TypeError):
            self._max_retries = DEFAULT_MAX_RETRIES
        self.vacation_mode = False

        # Mode expérimental — lu depuis les options

        experimental = bool(options.get(CONF_EXPERIMENTAL, DEFAULT_EXPERIMENTAL))

        # Session dédiée : le fournisseur utilise un hostname HTTPS classique,
        # donc le CookieJar sécurisé par défaut conserve les cookies OAuth requis.
        # Timeout explicite : sans lui, une requête qui pend bloque le refresh
        # pendant les 5 minutes du timeout aiohttp par défaut.
        self._own_session = async_create_clientsession(
            hass,
            cookie_jar=aiohttp.CookieJar(),
            timeout=aiohttp.ClientTimeout(total=30),
        )
        self.api = EauGrandLyonApi(
            self._own_session,
            entry.data[CONF_EMAIL],
            entry.data[CONF_PASSWORD],
            experimental=experimental,
        )
        # Hub'Eau is anonymous public data and must never receive the private
        # OAuth session, its cookies, or Eau du Grand Lyon account identifiers.
        self._hubeau_client = HubeauWaterQualityClient(async_get_clientsession(hass))
        self._pfas_client = PfasClient(self._own_session)
        self._vigieau_client = VigieauClient(self._own_session)
        self._last_request_mono: float | None = None
        self._min_request_delay_s: float = RATE_LIMIT_DELAY_S

        # Suivi de la santé des mises à jour
        self._consecutive_failures: int = 0
        self._api_offline: bool = False

        # Cache du résultat de get_cumulative_index — invalidé à chaque mise à jour réussie
        self._cumulative_index_cache: dict[str, float | None] = {}

        # Dernières données valides connues (utilisées en mode hors-ligne)
        self._last_good_data: EauGrandLyonData | None = None
        self._persistent_data_loaded = False
        self._persistent_data_lock = asyncio.Lock()

        # Cache persistant pour l'historique offline
        self._store = RebuildableStore(hass, 1, f"{DOMAIN}_{entry.entry_id}_history")

        # Historique mensuel cumulatif — 37 mois couvrent le mois courant et
        # les trois périodes homologues nécessaires au calcul Warsmann.
        # (l'API ne retourne que 12 mois ; ce store persiste les mois précédents entre mises à jour)
        # Version 2 : correction du bug mois base-0 (v1 avait des mois_index décalés d'un rang).
        # RebuildableStore migre une ancienne version en repartant d'un cache vide.
        self._monthly_history_store = RebuildableStore(hass, 2, f"{DOMAIN}_{entry.entry_id}_monthly_history")
        self._monthly_history: dict[str, list[MonthlyConsumption]] = {}

        # Historique journalier pour reconstruire la statistique dédiée sans
        # perdre les jours sortis de la fenêtre renvoyée par l'API.
        self._daily_history_store = RebuildableStore(hass, 1, f"{DOMAIN}_{entry.entry_id}_daily_history")
        self._daily_history: dict[str, list[DailyConsumption]] = {}

        if experimental:
            _LOGGER.info(
                "Eau du Grand Lyon — EXPERIMENTAL mode enabled: /rest/produits/ endpoints active. "
                "Disable in integration options if you hit issues."
            )

    async def async_initialize(self) -> None:
        """Charge le cache persistant avant le premier rafraîchissement."""
        if self._persistent_data_loaded:
            return

        async with self._persistent_data_lock:
            # Re-read through a method: another waiter may have initialized the
            # stores while this coroutine was suspended on the lock.
            if self._is_persistent_data_loaded():
                return
            await self._load_persistent_data()
            self._persistent_data_loaded = True

    def _is_persistent_data_loaded(self) -> bool:
        """Return the current initialization state after an await boundary."""
        return self._persistent_data_loaded

    async def _load_persistent_data(self) -> None:
        """Charge les données persistantes depuis le store."""
        try:
            stored_history = await self._monthly_history_store.async_load()
            if stored_history and isinstance(stored_history, dict):
                self._monthly_history = cast(dict[str, list[MonthlyConsumption]], stored_history)
                _LOGGER.debug(
                    "Loaded monthly history: %d contract(s)",
                    len(self._monthly_history),
                )
        except (json.JSONDecodeError, OSError, NotImplementedError, ValueError) as err:
            _LOGGER.warning(
                "Failed to load monthly history (cache ignoré, reconstruit depuis l'API) : %s",
                err,
            )

        try:
            stored_daily_history = await self._daily_history_store.async_load()
            if stored_daily_history and isinstance(stored_daily_history, dict):
                self._daily_history = cast(
                    dict[str, list[DailyConsumption]],
                    {
                        ref: entries
                        for ref, entries in stored_daily_history.items()
                        if isinstance(ref, str)
                        and isinstance(entries, list)
                        and all(isinstance(entry, dict) for entry in entries)
                    },
                )
        except (json.JSONDecodeError, OSError, NotImplementedError, ValueError) as err:
            _LOGGER.warning(
                "Failed to load daily history (cache ignoré, reconstruit depuis l'API) : %s",
                err,
            )

        try:
            stored = await self._store.async_load()
            if stored:
                for key in (
                    "last_update_success_time",
                    "offline_since",
                    "last_failure_time",
                    "cache_saved_at",
                ):
                    ts = stored.get(key)
                    if isinstance(ts, str):
                        try:
                            stored[key] = datetime.fromisoformat(ts)
                        except ValueError:
                            stored[key] = None
                cache_saved_at = stored.get("cache_saved_at")
                if isinstance(cache_saved_at, datetime) and datetime.now(timezone.utc) - cache_saved_at > timedelta(
                    days=CACHE_MAX_AGE_DAYS
                ):
                    _LOGGER.warning(
                        "Discarding persistent cache (older than %d days)",
                        CACHE_MAX_AGE_DAYS,
                    )
                    await self._store.async_remove()
                    return
                stored["offline_mode"] = False
                stored["offline_since"] = None
                last_success = stored.get("last_update_success_time")
                stored["cache_age_days"] = self._calculate_cache_age_days(
                    last_success if isinstance(last_success, datetime) else None
                )
                restored_data = cast(EauGrandLyonData, stored)
                self.data = restored_data
                self._last_good_data = restored_data
                _LOGGER.debug("Loaded persistent data (offline cache available)")
        except (
            json.JSONDecodeError,
            OSError,
            KeyError,
            NotImplementedError,
            ValueError,
        ) as err:
            _LOGGER.warning("Failed to load persisted data: %s", err)

    async def _save_persistent_data(self) -> None:
        """Sauvegarde les données persistantes (jamais l'état offline)."""
        try:
            source = self._last_good_data or self.data or {}
            data_to_save = {
                **source,
                "offline_mode": False,
                "offline_since": None,
                "cache_saved_at": datetime.now(timezone.utc),
            }
            for key in (
                "last_update_success_time",
                "offline_since",
                "last_failure_time",
                "cache_saved_at",
            ):
                ts = data_to_save.get(key)
                if isinstance(ts, datetime):
                    data_to_save[key] = ts.isoformat()
            await self._store.async_save(data_to_save)
            _LOGGER.debug("Persistent data saved")
        except (json.JSONDecodeError, OSError, TypeError) as err:
            _LOGGER.warning("Failed to persist data: %s", err)

    async def _save_monthly_history(self) -> None:
        """Persiste l'historique mensuel cumulatif sur disque."""
        try:
            await self._monthly_history_store.async_save(cast(dict[str, object], self._monthly_history))
            _LOGGER.debug("Saved monthly history: %d contract(s)", len(self._monthly_history))
        except (OSError, TypeError) as err:
            _LOGGER.warning("Failed to save monthly history: %s", err)

    async def _save_daily_history(self) -> None:
        """Persiste l'historique journalier utilisé par les statistiques."""
        try:
            await self._daily_history_store.async_save(cast(dict[str, object], self._daily_history))
        except (OSError, TypeError) as err:
            _LOGGER.warning("Failed to save daily history: %s", err)

    async def async_clear_cache(self) -> None:
        """Supprime le cache persistant et réinitialise les données locales."""
        await self._store.async_remove()
        await self._monthly_history_store.async_remove()
        await self._daily_history_store.async_remove()
        self._monthly_history = {}
        self._daily_history = {}
        self.data = {}
        self._last_good_data = None
        _LOGGER.info("Eau du Grand Lyon persistent cache cleared")

    async def async_close(self) -> None:
        """Révoque le token et ferme la session aiohttp dédiée."""
        await self.api.async_revoke_token()
        if not self._own_session.closed:
            await self._own_session.close()

    # ------------------------------------------------------------------
    # Mise à jour principale avec retry
    # ------------------------------------------------------------------

    def _compute_retry_delay(self, base_delay_s: float, attempt: int) -> float:
        """Return exponential backoff delay with bounded jitter for one retry."""
        raw_delay = base_delay_s * (RETRY_BACKOFF_MULTIPLIER**attempt)
        jitter_window = raw_delay * RETRY_JITTER_RATIO
        jitter = random.uniform(-jitter_window, jitter_window)
        return max(0.0, raw_delay + jitter)

    @staticmethod
    def _calculate_cache_age_days(
        last_update_success_time: datetime | None,
    ) -> int | None:
        if not isinstance(last_update_success_time, datetime):
            return None
        return max(0, (datetime.now(timezone.utc) - last_update_success_time).days)

    async def _async_update_data(self) -> EauGrandLyonData:
        """Récupère toutes les données depuis l'API avec retry intelligent."""
        # Rate limiting — time.monotonic() insensible aux changements NTP
        mono_now = time.monotonic()
        if self._last_request_mono is not None:
            elapsed = mono_now - self._last_request_mono
            if elapsed < self._min_request_delay_s:
                delay_needed = self._min_request_delay_s - elapsed
                _LOGGER.debug("Rate limiting: waiting %.1fs", delay_needed)
                await asyncio.sleep(delay_needed)
        self._last_request_mono = time.monotonic()

        last_exc: Exception | None = None
        last_err_type: str = "UnknownError"

        for attempt in range(self._max_retries):
            try:
                data = await self._fetch_all_data()
                was_offline = bool(
                    getattr(self, "_api_offline", False) or (self.data and self.data.get("offline_mode"))
                )
                now = datetime.now(timezone.utc)
                data["last_update_success_time"] = now
                data["last_error"] = None
                data["last_error_type"] = None
                data["last_failure_time"] = None
                data["last_failure_reason"] = None
                data["offline_mode"] = False
                data["offline_since"] = None
                data["cache_age_days"] = 0
                data["consecutive_failures"] = 0
                self._consecutive_failures = 0
                self._api_offline = False
                self._cumulative_index_cache = {}
                self._last_good_data = data
                await self._save_persistent_data()
                await check_long_outage_issue(self.hass, 0)
                if was_offline:
                    _LOGGER.info("Eau du Grand Lyon API available again")
                return data

            except WafBlockedError as err:
                last_exc = err
                last_err_type = "WafBlockedError"
                self._consecutive_failures += 1
                if attempt < self._max_retries - 1:
                    delay = self._compute_retry_delay(WAF_RETRY_BASE_DELAY_S, attempt)
                    _LOGGER.debug(
                        "WAF blocked (attempt %d/%d), retrying in %.1fs — %s",
                        attempt + 1,
                        self._max_retries,
                        delay,
                        err,
                    )
                    await asyncio.sleep(delay)

            except NetworkError as err:
                last_exc = err
                last_err_type = "NetworkError"
                self._consecutive_failures += 1
                if attempt < self._max_retries - 1:
                    delay = self._compute_retry_delay(NETWORK_RETRY_BASE_DELAY_S, attempt)
                    _LOGGER.debug(
                        "Network error (attempt %d/%d), retrying in %.1fs — %s",
                        attempt + 1,
                        self._max_retries,
                        delay,
                        err,
                    )
                    await asyncio.sleep(delay)

            except ApiError as err:
                # HTTP 5xx / réponse malformée : transitoire côté serveur.
                # On retente comme une erreur réseau, puis on bascule sur le cache.
                last_exc = err
                last_err_type = "ApiError"
                self._consecutive_failures += 1
                if attempt < self._max_retries - 1:
                    delay = self._compute_retry_delay(NETWORK_RETRY_BASE_DELAY_S, attempt)
                    _LOGGER.debug(
                        "API error (attempt %d/%d), retrying in %.1fs — %s",
                        attempt + 1,
                        self._max_retries,
                        delay,
                        err,
                    )
                    await asyncio.sleep(delay)

            except AuthenticationError as err:
                raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err

            except Exception as err:  # noqa: BLE001
                # Erreur inattendue : plutôt que de faire tomber toutes les entités,
                # on mémorise l'erreur et on tente le cache offline ci-dessous.
                last_exc = err
                last_err_type = type(err).__name__
                self._consecutive_failures += 1
                _LOGGER.exception("Unexpected error during update — falling back to cache if available")
                break

        # Toutes les tentatives ont échoué — mode hors-ligne si cache disponible
        cache = self._last_good_data
        if cache and cache.get("contracts"):
            already_offline = bool(
                getattr(self, "_api_offline", False) or (self.data and self.data.get("offline_mode"))
            )
            offline_since = (
                self.data.get("offline_since")
                if self.data and self.data.get("offline_mode")
                else datetime.now(timezone.utc)
            )
            if not isinstance(offline_since, datetime):
                offline_since = datetime.now(timezone.utc)
            if not already_offline:
                _LOGGER.warning(
                    "API unavailable after %d attempts (%s) — offline mode active " "(data from %s)",
                    self._max_retries,
                    last_err_type,
                    cache.get("last_update_success_time", "inconnu"),
                )
            self._api_offline = True
            days_offline = (datetime.now(timezone.utc) - offline_since).days
            await check_long_outage_issue(self.hass, days_offline)

            return {
                **cache,
                "offline_mode": True,
                "offline_since": offline_since,
                "last_error": str(last_exc),
                "last_error_type": last_err_type,
                "last_failure_time": datetime.now(timezone.utc),
                "last_failure_reason": str(last_exc),
                "cache_age_days": self._calculate_cache_age_days(cache.get("last_update_success_time")),
                "consecutive_failures": self._consecutive_failures,
            }

        raise UpdateFailed(f"Échec après {self._max_retries} tentatives (aucun cache disponible): {last_exc}")

    async def _fetch_all_data(self) -> EauGrandLyonData:
        """Effectue tous les appels API et construit le dictionnaire de données."""
        experimental = self.api.experimental
        cycle_api = CycleCachedApi(self.api)

        raw_contracts = await cycle_api.get_contracts()
        _LOGGER.debug("Found %d contract(s)", len(raw_contracts))

        alertes = await cycle_api.get_alertes()
        nb_alertes = len(alertes)
        interruptions = parse_outage_alertes(alertes)
        prochaine_coupure = interruptions[0] if interruptions else None

        commune = self._entry.options.get(CONF_WATER_QUALITY_COMMUNE) or None
        water_quality_task = asyncio.create_task(self._hubeau_client.async_get_water_quality(commune))
        interventions_task = asyncio.create_task(cycle_api.get_interventions())
        pfas_enabled = bool(self._entry.options.get(CONF_PFAS_ENABLED, DEFAULT_PFAS_ENABLED))
        vigieau_enabled = bool(self._entry.options.get(CONF_VIGIEAU_ENABLED, DEFAULT_VIGIEAU_ENABLED))
        pfas_task = asyncio.create_task(self._pfas_client.async_get(commune)) if pfas_enabled and commune else None
        vigieau_task = (
            asyncio.create_task(self._vigieau_client.async_get(commune)) if vigieau_enabled and commune else None
        )

        try:
            tarif_m3 = self._calculate_tarif_m3()

            # Le montant TTC réel est une donnée de facturation essentielle,
            # pas une expérimentation. Un 404 reste géré comme endpoint absent.
            factures_raw = await cycle_api.get_factures()
            factures = cast(list[InvoiceData], EauGrandLyonApi.format_factures(factures_raw)) if factures_raw else []

            contracts_data: dict[str, ContractData] = {}
            global_data: GlobalData = {
                "total_conso_courant": 0.0,
                "total_cout_courant_eur": 0.0,
                "total_prediction_cout_eur": 0.0,
                "total_consommation_annuelle": 0.0,
                "nb_contracts": 0,
            }

            valid_contracts: list[dict[str, Any]] = []
            for raw in raw_contracts:
                details = EauGrandLyonApi.parse_contract_details(raw)
                ref = details["reference"]
                cid = details.get("id")
                if not ref or not cid:
                    _LOGGER.warning("Invalid contract (missing reference or ID); skipping")
                    continue
                valid_contracts.append(details)

            contract_results = await asyncio.gather(
                *[
                    self._process_contract(cycle_api, details, tarif_m3, factures, experimental)
                    for details in valid_contracts
                ],
                return_exceptions=True,
            )

            first_contract_error: BaseException | None = None
            for details, contract_data in zip(valid_contracts, contract_results):
                ref = details["reference"]
                # Un contrat en échec ne doit pas faire tomber les autres du compte.
                if isinstance(contract_data, BaseException):
                    _LOGGER.debug(
                        "Contract %s skipped for this cycle (error=%s: %s)",
                        ref,
                        type(contract_data).__name__,
                        contract_data,
                    )
                    if first_contract_error is None:
                        first_contract_error = contract_data
                    continue
                contracts_data[ref] = contract_data

                # Mise à jour des agrégats globaux
                global_data["total_conso_courant"] += contract_data.get("consommation_mois_courant") or 0
                global_data["total_cout_courant_eur"] += contract_data.get("cout_mois_courant_eur") or 0
                global_data["total_prediction_cout_eur"] += contract_data.get("prediction_cout_mois") or 0
                global_data["total_consommation_annuelle"] += contract_data.get("consommation_annuelle") or 0
                global_data["nb_contracts"] += 1

            # Si TOUS les contrats ont échoué, propager l'erreur pour que le
            # coordinator déclenche retry + cache offline plutôt que d'écraser le
            # cache avec des données vides.
            if valid_contracts and not contracts_data and first_contract_error is not None:
                raise first_contract_error

            try:
                water_quality = await water_quality_task
            except Exception as err:  # noqa: BLE001 - public source must never break private account refresh
                _LOGGER.debug("Hub'Eau water-quality fetch failed unexpectedly: %s", err)
                water_quality = empty_water_quality()
            pfas = await pfas_task if pfas_task is not None else empty_pfas_data()
            vigieau = await vigieau_task if vigieau_task is not None else empty_vigieau_data()
            try:
                interventions_planifiees = await interventions_task
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                ValueError,
                KeyError,
            ) as err:
                _LOGGER.debug("Lazy interventions fetch failed: %s", err)
                interventions_planifiees = []

            drought_level = analytics.drought_level()

            vacation_alert = self._check_vacation_alert(contracts_data)

            # Purge l'historique des contrats disparus de l'API (évite une
            # croissance illimitée du .storage). On se base sur la liste des
            # contrats renvoyés, pas sur contracts_data, pour ne PAS supprimer
            # l'historique d'un contrat dont seule la récupération a échoué.
            valid_refs = {d["reference"] for d in valid_contracts}
            if valid_refs:
                self._monthly_history = {ref: hist for ref, hist in self._monthly_history.items() if ref in valid_refs}
                self._daily_history = {ref: hist for ref, hist in self._daily_history.items() if ref in valid_refs}

            await self._inject_statistics(contracts_data)
            self._handle_alert_notifications(nb_alertes)
            await self._save_monthly_history()
            await self._save_daily_history()

            return {
                "contracts": contracts_data,
                "global": global_data,
                "drought_level": drought_level,
                "vacation_alert": vacation_alert,
                "nb_alertes": nb_alertes,
                "interruptions": interruptions,
                "prochaine_coupure": prochaine_coupure,
                "interventions_planifiees": interventions_planifiees,
                "water_quality": water_quality,
                "pfas": pfas,
                "pfas_enabled": pfas_enabled,
                "vigieau": vigieau,
                "vigieau_enabled": vigieau_enabled,
                "experimental_mode": experimental,
                "api_mode": "Experimental (2026)" if experimental else "Legacy",
                "last_update_success_time": datetime.now(tz=timezone.utc),
                "last_error": None,
                "last_error_type": None,
                "last_failure_time": None,
                "last_failure_reason": None,
                "cache_age_days": 0,
            }
        finally:
            # Annuler les tâches encore en vol (chemins d'erreur) pour éviter
            # requêtes fantômes et « Task exception was never retrieved ».
            optional_tasks = (
                water_quality_task,
                interventions_task,
                pfas_task,
                vigieau_task,
            )
            leftovers = [t for t in optional_tasks if t is not None and not t.done()]
            for task in leftovers:
                task.cancel()
            if leftovers:
                await asyncio.gather(*leftovers, return_exceptions=True)
            await cycle_api.aclose()

    def _calculate_tarif_m3(self) -> float:
        """Calcule le tarif au m3 selon les options ou l'entité dynamique."""
        opts: dict[str, Any] = dict(self._entry.options)
        price_entity = opts.get(CONF_PRICE_ENTITY)

        if price_entity:
            state = self.hass.states.get(price_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    _LOGGER.warning(
                        "Invalid value for price entity %s: %s",
                        price_entity,
                        state.state,
                    )

        try:
            return float(opts.get(CONF_TARIF_M3, self._entry.data.get(CONF_TARIF_M3, DEFAULT_TARIF_M3)))
        except (ValueError, TypeError):
            return DEFAULT_TARIF_M3

    def _get_tariff_mode(self) -> str:
        """Return the configured billing mode with a legacy-safe fallback."""
        opts: dict[str, Any] = dict(self._entry.options)
        mode = opts.get(CONF_TARIFF_MODE)
        if mode in TARIFF_MODES:
            return str(mode)
        return TARIFF_MODE_DYNAMIC if opts.get(CONF_PRICE_ENTITY) else TARIFF_MODE_MANUAL

    def _calculate_billing(
        self,
        details: dict[str, Any],
        latest_invoice: InvoiceData | None,
        conso_courant: float | None,
        conso_annuelle: float,
        conso_cumulee_annee: float,
        configured_rate: float,
    ) -> BillingData:
        """Build transparent monthly and rolling-annual cost estimates."""
        return build_billing_data(
            self._get_tariff_mode(),
            details,
            latest_invoice,
            conso_courant,
            conso_annuelle,
            conso_cumulee_annee,
            configured_rate,
            self._entry.options.get(CONF_SUBSCRIPTION_ANNUAL, DEFAULT_SUBSCRIPTION_ANNUAL),
        )

    async def _process_contract(
        self,
        cycle_api: CycleCachedApi,
        details: dict[str, Any],
        tarif_m3: float,
        factures: list[InvoiceData],
        experimental: bool,
    ) -> ContractData:
        """Traite les données d'un contrat spécifique."""
        ref = details["reference"]
        cid = details["id"]

        # ── Consommations mensuelles + journalières + données PdS (en parallèle) ──
        (
            raw_consos,
            raw_daily_data,
            date_prochaine_facture,
            pds_etendu,
            alerte_surconso,
        ) = await asyncio.gather(
            cycle_api.get_monthly_consumptions(cid),
            cycle_api.get_daily_consumptions(cid, nb_jours=365),
            cycle_api.get_date_prochaine_facture(cid),
            cycle_api.get_point_de_service_etendu(cid),
            cycle_api.get_alerte_surconsommation(cid),
        )
        consos = cast(list[MonthlyConsumption], EauGrandLyonApi.format_consumptions(raw_consos))
        consos_journalieres = cast(list[DailyConsumption], raw_daily_data["entries"])
        consos_journalieres = merge_daily_history(
            self._daily_history.get(ref, []),
            consos_journalieres,
        )
        self._daily_history[ref] = consos_journalieres

        # Merge avec l'historique persistant (N-1 annuel et comparaison sur trois ans).
        merged_consos = merge_monthly_history(
            self._monthly_history.get(ref, []),
            consos,
        )
        self._monthly_history[ref] = merged_consos
        _LOGGER.debug(
            "Contrat %s : %d mois API + historique → %d mois total",
            ref,
            len(consos),
            len(merged_consos),
        )

        conso_courant = consos[-1]["consommation_m3"] if consos else None
        label_courant = consos[-1]["label"] if consos else None
        conso_precedent = consos[-2]["consommation_m3"] if len(consos) >= 2 else None
        label_precedent = consos[-2]["label"] if len(consos) >= 2 else None

        last_12 = consos[-12:] if len(consos) >= 12 else consos
        conso_annuelle = round(sum(e["consommation_m3"] for e in last_12), 1)

        current_year = datetime.now(timezone.utc).year
        conso_cumulee_annee = round(
            sum(e["consommation_m3"] for e in consos if e.get("annee") == current_year),
            1,
        )

        factures_contrat = [f for f in factures if str(f.get("contrat_id") or "") == str(cid)]
        derniere_facture = factures_contrat[0] if factures_contrat else None
        billing = self._calculate_billing(
            details,
            derniere_facture,
            conso_courant,
            conso_annuelle,
            conso_cumulee_annee,
            tarif_m3,
        )
        # Tarif proxy conservé pour les statistiques historiques et les
        # prédictions existantes. Les capteurs de coût utilisent le détail
        # mensuel/annuel calculé ci-dessus.
        tarif_m3 = billing["tarif_m3"]

        # Comparaison N-1 (Mois vs Mois N-1) — utilise les données fraîches uniquement
        conso_mois_n1, label_n1 = analytics.consumption_n1(consos)

        # Consommation annuelle N-1 — utilise l'historique étendu.
        last_24 = merged_consos[-24:-12] if len(merged_consos) >= 24 else []
        conso_annuelle_n1 = round(sum(e["consommation_m3"] for e in last_24), 1) if last_24 else None

        conso_7j, conso_30j = analytics.daily_aggregates(consos_journalieres)
        warsmann_assessment = assess_warsmann(
            merged_consos,
            consos_journalieres,
            teleo=bool(details.get("teleo_compatible") or raw_daily_data.get("nb_entries", 0) > 0),
        )

        # Index journalier le plus récent, disponible sur compteurs Téléo.
        index_journalier_dernier, index_journalier_dernier_date = analytics.latest_daily_index(consos_journalieres)

        prediction_conso_mois, prediction_cout_mois, tendance_n1_pct = analytics.trend_and_prediction(
            conso_courant, conso_mois_n1, consos_journalieres, tarif_m3
        )

        nb_hab = analytics.household_size(details, self._entry.options.get(CONF_HOUSEHOLD_SIZE), DEFAULT_HOUSEHOLD_SIZE)
        eco_score, eco_score_grade = analytics.eco_score(conso_courant, nb_hab)

        # ── [BILLING] Dates clés ──────────────────────────────────────────
        next_payment_date = details.get("date_echeance")
        # L'état public reste strictement la valeur fournisseur. L'ancienne
        # estimation locale est conservée séparément à titre indicatif.
        next_bill_date = date_prochaine_facture

        # ── [EXPÉRIMENTAL] Courbe de charge et analyse horaire ────────────
        courbe_de_charge: list[dict[str, Any]] = []
        if experimental and consos_journalieres:
            courbe_de_charge = await cycle_api.get_courbe_de_charge(cid, nb_jours=7)
        consommation_derniere_heure_m3, heure_pic, debit_moyen_m3h = analytics.analyze_load_curve(courbe_de_charge)

        multiplier = float(self._entry.options.get(CONF_LEAK_MULTIPLIER, DEFAULT_LEAK_MULTIPLIER))
        local_leak_pattern = analytics.detect_local_leak(courbe_de_charge, consos_journalieres, ref, multiplier)

        # ── [EXPÉRIMENTAL] Index réel ─────────────────────────────────────
        real_index = await self._get_real_index(cycle_api, experimental, cid, consos_journalieres)

        hardness = float(self._entry.options.get(CONF_WATER_HARDNESS, DEFAULT_WATER_HARDNESS))
        limescale_g, limescale_alert = analytics.limescale(consos, hardness)

        # ── [ALERTES SERVEUR] Seuils de surconsommation configurés côté Eau du Grand Lyon ──
        seuil_surconso_jour = alerte_surconso.get("seuil_surconso_jour_m3")
        seuil_surconso_mois = alerte_surconso.get("seuil_surconso_mois_m3")
        derniere_conso_jour = consos_journalieres[-1]["consommation_m3"] if consos_journalieres else None
        surconso_jour_depassee = (
            seuil_surconso_jour is not None
            and derniere_conso_jour is not None
            and derniere_conso_jour > seuil_surconso_jour
        )
        surconso_mois_depassee = (
            seuil_surconso_mois is not None and conso_courant is not None and conso_courant > seuil_surconso_mois
        )

        return cast(
            ContractData,
            {
                **details,
                "consommations": consos,
                "consommation_mois_courant": conso_courant,
                "label_mois_courant": label_courant,
                "consommation_mois_precedent": conso_precedent,
                "label_mois_precedent": label_precedent,
                "consommation_annuelle": conso_annuelle,
                "consommation_cumulee_annee": conso_cumulee_annee,
                "consommation_n1": conso_mois_n1,
                "consommation_annuelle_n1": conso_annuelle_n1,
                "label_n1": label_n1,
                "mois_manquants": analytics.find_missing_months(consos),
                "consommations_journalieres": consos_journalieres,
                "daily_source": raw_daily_data.get("source"),
                "daily_nb_entries": raw_daily_data.get("nb_entries"),
                "daily_last_date": raw_daily_data.get("last_date"),
                "consommation_7j": conso_7j,
                "conso_moyenne_7j_litres": (round((conso_7j * 1000) / 7, 1) if conso_7j is not None else None),
                "consommation_30j": conso_30j,
                **billing,
                "tendance_n1_pct": tendance_n1_pct,
                "prediction_conso_mois": prediction_conso_mois,
                "prediction_cout_mois": prediction_cout_mois,
                "local_leak_pattern": local_leak_pattern,
                "eco_score_m3_pers": eco_score,
                "eco_score_grade": eco_score_grade,
                "nb_habitants": nb_hab,
                "co2_footprint_kg": analytics.co2_footprint_kg(conso_courant),
                "next_payment_date": next_payment_date,
                "next_bill_date": next_bill_date,
                "estimated_next_bill_date": analytics.estimate_next_bill_date(next_payment_date),
                "date_prochaine_releve": pds_etendu.get("date_prochaine_releve"),
                "conso_annuelle_ref_m3": pds_etendu.get("conso_annuelle_ref_m3"),
                "pds_mode_releve": pds_etendu.get("mode_releve"),
                "pds_communicabilite_amm": pds_etendu.get("communicabilite_amm"),
                "limescale_g": limescale_g,
                "limescale_alert": limescale_alert,
                "hardness_fh": hardness,
                "real_index": real_index,
                "factures": factures_contrat,
                "derniere_facture": derniere_facture,
                "fuite_estime_30j_m3": analytics.experimental_leak_30d(experimental, consos_journalieres),
                "courbe_de_charge": courbe_de_charge,
                # [HORAIRE] Données infra-journalières (compteur Téléo uniquement)
                "consommation_derniere_heure_m3": consommation_derniere_heure_m3,
                "heure_pic": heure_pic,
                "debit_moyen_m3h": debit_moyen_m3h,
                # [HARDWARE] État du module Téléo — parsé depuis pointDeReleve
                "teleo_compatible": details.get("teleo_compatible") or (raw_daily_data.get("nb_entries", 0) > 0),
                "signal_pct": details.get("signal_pct"),
                "battery_ok": details.get("battery_ok"),
                # [INDEX JOURNALIER] Dernier index connu depuis données journalières (Téléo uniquement)
                "index_journalier_dernier": index_journalier_dernier,
                "index_journalier_dernier_date": index_journalier_dernier_date,
                # [ALERTES SERVEUR] Seuils surconsommation configurés côté Eau du Grand Lyon
                "seuil_surconso_jour_m3": seuil_surconso_jour,
                "seuil_surconso_mois_m3": seuil_surconso_mois,
                "abonne_alerte_fuite": alerte_surconso.get("abonne_alerte_fuite"),
                "derniere_conso_jour_m3": derniere_conso_jour,
                "surconso_jour_depassee": surconso_jour_depassee,
                "surconso_mois_depassee": surconso_mois_depassee,
                "warsmann_assessment": warsmann_assessment,
            },
        )

    async def _get_real_index(
        self,
        cycle_api: CycleCachedApi,
        experimental: bool,
        cid: str,
        daily: list[DailyConsumption],
    ) -> float | None:
        """Récupère l'index réel du compteur."""
        if not experimental:
            return None
        siamm = await cycle_api.get_derniere_releve_siamm(cid)
        index = EauGrandLyonApi.parse_siamm_index(siamm) if siamm is not None else None
        if index is None and daily:
            for e in reversed(daily):
                if "index_m3" in e:
                    return float(e["index_m3"])
        return index

    def _check_vacation_alert(self, contracts_data: dict[str, ContractData]) -> bool:
        """Vérifie si une alerte vacances doit être levée."""
        if not self.vacation_mode:
            return False
        total_24h = 0.0
        for c in contracts_data.values():
            daily = c.get("consommations_journalieres", [])
            if daily:
                total_24h += daily[-1].get("consommation_m3", 0)
        if total_24h > 0.001:
            _LOGGER.warning("VACATION ALERT: %.3f m3 consumption detected", total_24h)
            return True
        return False

    async def _inject_statistics(self, contracts_data: dict[str, ContractData]) -> None:
        """Injecte l'historique mensuel et journalier dans les statistiques longue durée HA."""
        await async_inject_contract_statistics(
            self.hass,
            contracts_data,
            self._monthly_history,
            getattr(self, "_daily_history", {}),
        )

    def _handle_alert_notifications(self, nb_alertes: int) -> None:
        """Crée ou supprime une notification HA persistante selon les alertes."""
        try:
            from homeassistant.components.persistent_notification import (
                async_create as pn_create,
            )
            from homeassistant.components.persistent_notification import (
                async_dismiss as pn_dismiss,
            )
        except ImportError:
            return

        notif_id = f"{DOMAIN}_alertes"

        # pn_create / pn_dismiss are synchronous @callback functions (return None);
        # call them directly. Wrapping in async_create_task(pn_create(...)) would
        # pass None to async_create_task ("a coroutine was expected, got None").
        if nb_alertes > 0 and nb_alertes != self._prev_nb_alertes:
            pn_create(
                self.hass,
                message=(
                    f"Vous avez **{nb_alertes} alerte(s) active(s)** sur votre compte "
                    f"Eau du Grand Lyon.\n\n"
                    f"Consultez [l'espace client](https://agence.eaudugrandlyon.com)."
                ),
                title="⚠️ Eau du Grand Lyon — Alerte",
                notification_id=notif_id,
            )
            _LOGGER.info("%d Eau du Grand Lyon alert(s) detected", nb_alertes)

        elif nb_alertes == 0 and self._prev_nb_alertes > 0:
            pn_dismiss(self.hass, notification_id=notif_id)
            _LOGGER.info("Eau du Grand Lyon alerts cleared")

        self._prev_nb_alertes = nb_alertes

    def get_cumulative_index(self, contract_ref: str) -> float | None:
        """Récupère l'index cumulatif (index réel si dispo, sinon somme des consos).

        Le résultat est mis en cache jusqu'à la prochaine mise à jour réussie —
        plusieurs sensors (Index, Énergie eau, Énergie coût) appellent cette méthode
        à chaque lecture d'état, ce qui évite de resommer toutes les consos à chaque fois.
        """
        if not self.data:
            return None
        if contract_ref in self._cumulative_index_cache:
            return self._cumulative_index_cache[contract_ref]
        contract = self.data.get("contracts", {}).get(contract_ref)
        if contract is None:
            return None
        # Priority 1: real index from experimental SIAMM endpoint
        real = contract.get("real_index")
        if real is not None:
            result: float | None = round(real, 3)
        # Priority 2: last known meter index from daily Téléo data (no experimental needed)
        elif contract.get("index_journalier_dernier") is not None:
            daily_index = contract["index_journalier_dernier"]
            result = round(daily_index, 3) if daily_index is not None else None
        # Priority 3: sum of monthly consumptions (relative, but works for Energy dashboard)
        else:
            consos = contract.get("consommations", [])
            valid = [e["consommation_m3"] for e in consos if e.get("consommation_m3") is not None]
            result = round(sum(valid), 3) if valid else None
        self._cumulative_index_cache[contract_ref] = result
        return result
