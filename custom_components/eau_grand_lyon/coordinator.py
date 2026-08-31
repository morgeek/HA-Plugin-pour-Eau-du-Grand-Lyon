"""Coordinateur de mise à jour pour Eau du Grand Lyon."""

from __future__ import annotations

import asyncio
import calendar
import inspect
import json
import logging
import math
import random
import re
import time
from datetime import datetime, timedelta, timezone
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

try:
    from homeassistant.components.recorder.models import (
        StatisticData,
        StatisticMetaData,
    )
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
    )

    _HAS_RECORDER = True
except ImportError:
    _HAS_RECORDER = False

# Importé séparément : absent sur les versions HA plus anciennes, où l'on
# retombe sur has_mean sans désactiver toute l'injection de statistiques.
if TYPE_CHECKING:
    from homeassistant.components.recorder.models.statistics import StatisticMeanType
else:
    try:
        from homeassistant.components.recorder.statistics import StatisticMeanType
    except ImportError:
        StatisticMeanType = None

# Lecture de la dernière somme connue du recorder pour ancrer le cumul et éviter
# les deltas négatifs quand la fenêtre glissante perd son plus vieux
# mois. Optionnel : toute absence/erreur retombe sur un cumul à partir de 0.
try:
    if TYPE_CHECKING:
        from homeassistant.helpers.recorder import (
            get_instance as _get_recorder_instance,
        )
    else:
        from homeassistant.components.recorder import (
            get_instance as _get_recorder_instance,
        )
    from homeassistant.components.recorder.statistics import (
        get_last_statistics as _get_last_statistics,
    )

    _HAS_LAST_STATS = True
except ImportError:
    _HAS_LAST_STATS = False

if TYPE_CHECKING:
    from . import EauGrandLyonConfigEntry

from .api import (
    MONTHS_FR,
    ApiError,
    AuthenticationError,
    EauGrandLyonApi,
    NetworkError,
    WafBlockedError,
)
from .billing import (
    OFFICIAL_2026_TIER_2_TOTAL_TTC_M3,
    effective_invoice_rate,
    linear_estimate,
    official_2026_estimate,
    official_2026_subscription,
)
from .models import (
    BillingData,
    ContractData,
    DailyConsumption,
    EauGrandLyonData,
    GlobalData,
    InvoiceData,
    MonthlyConsumption,
    OutageData,
    WaterQualityData,
)
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
    STATISTIC_COST,
    STATISTIC_COST_DAILY,
    STATISTIC_WATER,
    STATISTIC_WATER_DAILY,
    TARIFF_MODE_DYNAMIC,
    TARIFF_MODE_LATEST_INVOICE,
    TARIFF_MODE_MANUAL,
    TARIFF_MODE_OFFICIAL_2026,
    TARIFF_MODES,
    WAF_RETRY_BASE_DELAY_S,
)
from .repairs import check_long_outage_issue

_LOGGER = logging.getLogger(__name__)


class _RebuildableStore(Store[dict[str, object]]):
    """Store pour caches reconstructibles (historique mensuel, cache offline).

    Le Store par défaut lève NotImplementedError au chargement quand le fichier
    `.storage` porte une version antérieure à celle du code sans fonction de
    migration — ce qui plante le setup de l'intégration après une montée de
    version du schéma (ex. v1 -> v2 de l'historique mensuel).

    Ici les données sont entièrement reconstruites depuis l'API aux cycles
    suivants : une migration se résume donc à repartir d'un cache vide, ce qui
    est sûr et évite tout crash au démarrage.
    """

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, object],
    ) -> dict[str, object]:
        _LOGGER.debug(
            "Cache %s en version %s.%s — reconstruction depuis l'API (reset)",
            self.key,
            old_major_version,
            old_minor_version,
        )
        return {}


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
        self._pfas_client = PfasClient(self._own_session)
        self._vigieau_client = VigieauClient(self._own_session)
        self._last_request_mono: float | None = None
        self._min_request_delay_s: float = RATE_LIMIT_DELAY_S

        # Suivi de la santé des mises à jour
        self._consecutive_failures: int = 0
        self._api_offline: bool = False

        # Cache du résultat de get_cumulative_index — invalidé à chaque mise à jour réussie
        self._cumulative_index_cache: dict[str, float | None] = {}

        # Nombre de mois déjà injectés dans les statistiques, par contrat
        self._stats_month_counts: dict[str, int] = {}

        # Dernières données valides connues (utilisées en mode hors-ligne)
        self._last_good_data: EauGrandLyonData | None = None
        self._persistent_data_loaded = False
        self._persistent_data_lock = asyncio.Lock()

        # Cache persistant pour l'historique offline
        self._store = _RebuildableStore(hass, 1, f"{DOMAIN}_{entry.entry_id}_history")

        # Historique mensuel cumulatif — 37 mois couvrent le mois courant et
        # les trois périodes homologues nécessaires au calcul Warsmann.
        # (l'API ne retourne que 12 mois ; ce store persiste les mois précédents entre mises à jour)
        # Version 2 : correction du bug mois base-0 (v1 avait des mois_index décalés d'un rang).
        # _RebuildableStore migre une ancienne version en repartant d'un cache vide.
        self._monthly_history_store = _RebuildableStore(hass, 2, f"{DOMAIN}_{entry.entry_id}_monthly_history")
        self._monthly_history: dict[str, list[MonthlyConsumption]] = {}

        # Historique journalier pour reconstruire la statistique dédiée sans
        # perdre les jours sortis de la fenêtre renvoyée par l'API.
        self._daily_history_store = _RebuildableStore(hass, 1, f"{DOMAIN}_{entry.entry_id}_daily_history")
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

    @staticmethod
    def _merge_monthly_history(
        stored: list[MonthlyConsumption],
        fresh: list[MonthlyConsumption],
        max_months: int = 37,
    ) -> list[MonthlyConsumption]:
        """Fusionne l'historique stocké avec les données fraîches de l'API.

        Les données fraîches priment sur les données stockées pour le même mois.
        Retourne la liste triée chronologiquement, plafonnée à max_months.
        """
        by_key: dict[tuple[object, object], MonthlyConsumption] = {}
        for entry in stored:
            key = (entry.get("annee"), entry.get("mois_index"))
            if None not in key:
                by_key[key] = entry
        for entry in fresh:
            key = (entry.get("annee"), entry.get("mois_index"))
            if None not in key:
                by_key[key] = entry  # API prime sur le stocké
        merged = sorted(
            by_key.values(),
            key=lambda e: (e.get("annee", 0), e.get("mois_index", 0)),
        )
        return merged[-max_months:]

    @staticmethod
    def _merge_daily_history(
        stored: list[DailyConsumption],
        fresh: list[DailyConsumption],
        max_days: int = 1097,
    ) -> list[DailyConsumption]:
        """Fusionne les journées, les données fraîches remplaçant les anciennes."""
        by_date: dict[str, DailyConsumption] = {}
        entries = stored if isinstance(stored, list) else []
        fresh_entries = fresh if isinstance(fresh, list) else []
        for entry in (*entries, *fresh_entries):
            date = entry.get("date")
            if date:
                by_date[str(date)] = entry
        return sorted(by_date.values(), key=lambda entry: str(entry.get("date", "")))[-max_days:]

    @staticmethod
    def _sanitize_daily_history(stored: object) -> dict[str, list[DailyConsumption]]:
        """Conserve uniquement les contrats et journées valides du cache."""
        if not isinstance(stored, dict):
            return {}
        sanitized: dict[str, list[DailyConsumption]] = {}
        for ref, entries in stored.items():
            if not isinstance(ref, str) or not isinstance(entries, list):
                continue
            valid_entries = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                try:
                    datetime.fromisoformat(str(entry["date"]))
                    value = float(entry["consommation_m3"])
                    if not math.isfinite(value):
                        continue
                except (KeyError, TypeError, ValueError):
                    continue
                valid_entries.append(cast(DailyConsumption, entry))
            if valid_entries:
                sanitized[ref] = valid_entries
        return sanitized

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
        cycle_api = _CycleCachedApi(self.api)

        raw_contracts = await cycle_api.get_contracts()
        _LOGGER.debug("Found %d contract(s)", len(raw_contracts))

        alertes = await cycle_api.get_alertes()
        nb_alertes = len(alertes)
        interruptions = _parse_outage_alertes(alertes)
        prochaine_coupure = interruptions[0] if interruptions else None

        commune = self._entry.options.get(CONF_WATER_QUALITY_COMMUNE) or None
        water_quality_task = asyncio.create_task(cycle_api.get_water_quality(commune))
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

            water_quality = await water_quality_task
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

            drought_level = self._get_drought_level()

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
        mode = self._get_tariff_mode()
        monthly_volume = conso_courant or 0.0

        if mode == TARIFF_MODE_LATEST_INVOICE:
            invoice_rate = effective_invoice_rate(latest_invoice)
            if invoice_rate is not None:
                source = "latest_invoice_ttc_per_m3"
                monthly = linear_estimate(monthly_volume, invoice_rate, source=source)
                annual = linear_estimate(conso_annuelle, invoice_rate, source=source)
                rate = invoice_rate
                subscription = 0.0
            else:
                # Aucune facture exploitable : la grille officielle vaut mieux
                # que l'ancien tarif indicatif 5,20 €/m³.
                mode = TARIFF_MODE_OFFICIAL_2026

        if mode == TARIFF_MODE_OFFICIAL_2026:
            subscription, subscription_source = official_2026_subscription(details.get("calibre_compteur"))
            annual = official_2026_estimate(conso_annuelle, fixed_eur=subscription)
            volume_before_month = max(0.0, conso_cumulee_annee - monthly_volume)
            monthly = official_2026_estimate(
                monthly_volume,
                fixed_eur=subscription / 12.0,
                starting_annual_volume_m3=volume_before_month,
            )
            rate = OFFICIAL_2026_TIER_2_TOTAL_TTC_M3
            source = subscription_source
        elif mode in (TARIFF_MODE_MANUAL, TARIFF_MODE_DYNAMIC):
            subscription = float(self._entry.options.get(CONF_SUBSCRIPTION_ANNUAL, DEFAULT_SUBSCRIPTION_ANNUAL))
            source = "dynamic_entity" if mode == TARIFF_MODE_DYNAMIC else "manual_flat_rate"
            monthly = linear_estimate(
                monthly_volume,
                configured_rate,
                subscription / 12.0,
                source=source,
            )
            annual = linear_estimate(conso_annuelle, configured_rate, subscription, source=source)
            rate = configured_rate

        invoice_amount = None
        invoice_volume = None
        invoice_rate = effective_invoice_rate(latest_invoice)
        if latest_invoice:
            invoice_amount = latest_invoice.get("montant_ttc")
            invoice_volume = latest_invoice.get("volume_m3")

        return {
            "billing_mode": mode,
            "tariff_source": source,
            "estimation": True,
            "tarif_m3": round(rate, 6),
            "subscription_annual": round(subscription, 2),
            "cout_mois_courant_eur": (monthly.variable_eur if conso_courant is not None else None),
            "cout_annuel_eur": annual.variable_eur,
            "cout_reel_mois": (monthly.total_eur if conso_courant is not None or monthly.fixed_eur else None),
            "cout_reel_annuel": annual.total_eur,
            "cost_breakdown_monthly": monthly.as_dict(),
            "cost_breakdown_annual": annual.as_dict(),
            "latest_invoice_ttc": invoice_amount,
            "latest_invoice_volume_m3": invoice_volume,
            "latest_invoice_effective_rate_eur_m3": (round(invoice_rate, 6) if invoice_rate is not None else None),
        }

    async def _process_contract(
        self,
        cycle_api: "_CycleCachedApi",
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
        consos_journalieres = self._merge_daily_history(
            self._daily_history.get(ref, []),
            consos_journalieres,
        )
        self._daily_history[ref] = consos_journalieres

        # Merge avec l'historique persistant (N-1 annuel et comparaison sur trois ans).
        merged_consos = self._merge_monthly_history(
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
        conso_mois_n1, label_n1 = self._get_consumption_n1(consos)

        # Consommation annuelle N-1 — utilise l'historique étendu.
        last_24 = merged_consos[-24:-12] if len(merged_consos) >= 24 else []
        conso_annuelle_n1 = round(sum(e["consommation_m3"] for e in last_24), 1) if last_24 else None

        # Détection des mois manquants
        mois_manquants = _find_missing_months(consos)

        conso_7j, conso_30j = self._calculate_daily_aggregates(consos_journalieres)
        warsmann_assessment = assess_warsmann(
            merged_consos,
            consos_journalieres,
            teleo=bool(details.get("teleo_compatible") or raw_daily_data.get("nb_entries", 0) > 0),
        )

        # ── Index journalier le plus récent (capteur EauGrandLyonIndexJournalierSensor) ──
        # Extrait depuis les données journalières, disponible sur compteurs Téléo.
        index_journalier_dernier: float | None = None
        index_journalier_dernier_date: str | None = None
        for e in reversed(consos_journalieres):
            idx = e.get("index_m3")
            if idx is not None:
                try:
                    index_journalier_dernier = float(idx)
                    index_journalier_dernier_date = e.get("date")
                except (ValueError, TypeError):
                    pass
                break

        # ── [INTELLIGENCE] Tendance & Prédiction ──────────────────────────
        prediction_conso_mois, prediction_cout_mois, tendance_n1_pct = self._calculate_intelligence(
            conso_courant, conso_mois_n1, consos_journalieres, tarif_m3
        )

        # ── [ECO-SCORE] Analyse de performance ────────────────────────────
        eco_score, eco_score_grade, nb_hab = self._calculate_eco_score(details, conso_courant)

        # ── [CO2-FOOTPRINT] Impact environnemental ───────────────────────
        co2_footprint = round(conso_courant * 0.52, 2) if conso_courant is not None else None

        # ── [BILLING] Dates clés ──────────────────────────────────────────
        next_payment_date = details.get("date_echeance")
        # L'état public reste strictement la valeur fournisseur. L'ancienne
        # estimation locale est conservée séparément à titre indicatif.
        next_bill_date = date_prochaine_facture
        estimated_next_bill_date = self._estimate_next_bill_date(next_payment_date)
        # Date du prochain relevé compteur (endpoint /pointDeService)
        date_prochaine_releve = pds_etendu.get("date_prochaine_releve")
        conso_annuelle_ref_m3 = pds_etendu.get("conso_annuelle_ref_m3")

        # ── [EXPÉRIMENTAL] Fuite estimée ──────────────────────────────────
        fuite_estime_30j_m3 = self._calculate_experimental_leak(experimental, consos_journalieres)

        # ── [EXPÉRIMENTAL] Courbe de charge ───────────────────────────
        courbe_de_charge = []
        if experimental and consos_journalieres:
            courbe_de_charge = await cycle_api.get_courbe_de_charge(cid, nb_jours=7)

        # ── [HORAIRE] Analyse de la courbe de charge ──────────────────
        consommation_derniere_heure_m3: float | None = None
        heure_pic: str | None = None
        debit_moyen_m3h: float | None = None
        if courbe_de_charge:
            raw_vals = []
            for curve_entry in courbe_de_charge:
                v = curve_entry.get("valeur") or curve_entry.get("consommation") or 0
                try:
                    raw_vals.append(float(v) if isinstance(v, (str, int, float)) else 0.0)
                except (ValueError, TypeError):
                    raw_vals.append(0.0)
            if raw_vals:
                consommation_derniere_heure_m3 = raw_vals[-1]
                max_idx = raw_vals.index(max(raw_vals))
                try:
                    peak_dt = datetime.fromisoformat(courbe_de_charge[max_idx].get("date", ""))
                    heure_pic = peak_dt.strftime("%H:%M")
                except (ValueError, TypeError, AttributeError):
                    heure_pic = None
                non_zero = [v for v in raw_vals if v > 0]
                if non_zero:
                    debit_moyen_m3h = round(sum(non_zero) / len(non_zero), 4)

        # ── [INTELLIGENCE] Détection de fuite locale (Pattern) ────────────
        local_leak_pattern = self._detect_local_leak(courbe_de_charge, consos_journalieres, ref)

        # ── [EXPÉRIMENTAL] Index réel & Factures ──────────────────────────
        real_index = await self._get_real_index(cycle_api, experimental, cid, consos_journalieres)

        # ── [LIMESCALE] Entartrage estimé sur 12 mois glissants ──────────
        # Basé sur la conso des 12 derniers mois (fenêtre bornée), et NON sur
        # l'index absolu du compteur (cumul depuis la pose) qui faisait dépasser
        # le seuil en permanence — l'alerte était donc toujours active.
        hardness = float(self._entry.options.get(CONF_WATER_HARDNESS, DEFAULT_WATER_HARDNESS))
        annual_volume = sum(e["consommation_m3"] for e in consos[-12:])
        limescale_g = round(annual_volume * hardness * 10, 0)
        limescale_alert = limescale_g > 100000

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
                "mois_manquants": mois_manquants,
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
                "co2_footprint_kg": co2_footprint,
                "next_payment_date": next_payment_date,
                "next_bill_date": next_bill_date,
                "estimated_next_bill_date": estimated_next_bill_date,
                "date_prochaine_releve": date_prochaine_releve,
                "conso_annuelle_ref_m3": conso_annuelle_ref_m3,
                "pds_mode_releve": pds_etendu.get("mode_releve"),
                "pds_communicabilite_amm": pds_etendu.get("communicabilite_amm"),
                "limescale_g": limescale_g,
                "limescale_alert": limescale_alert,
                "hardness_fh": hardness,
                "real_index": real_index,
                "factures": factures_contrat,
                "derniere_facture": derniere_facture,
                "fuite_estime_30j_m3": fuite_estime_30j_m3,
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

    def _get_consumption_n1(self, consos: list[MonthlyConsumption]) -> tuple[float | None, str | None]:
        """Récupère la consommation à N-1 pour le même mois."""
        if not consos:
            return None, None
        target_mois = consos[-1]["mois_index"]
        target_annee = consos[-1]["annee"] - 1
        for e in consos:
            if e["mois_index"] == target_mois and e["annee"] == target_annee:
                return e["consommation_m3"], e["label"]
        return None, None

    def _calculate_daily_aggregates(self, daily: list[DailyConsumption]) -> tuple[float | None, float | None]:
        """Calcule les agrégats sur 7 et 30 jours."""
        if not daily:
            return None, None
        conso_7j = round(sum(e["consommation_m3"] for e in daily[-7:]), 2)
        conso_30j = round(sum(e["consommation_m3"] for e in daily[-30:]), 2)
        return conso_7j, conso_30j

    def _calculate_intelligence(
        self,
        current: float | None,
        n1: float | None,
        daily: list[DailyConsumption],
        tarif: float,
    ) -> tuple[float | None, float | None, float | None]:
        """Calcule les tendances et prédictions."""
        if current is None:
            return None, None, None

        tendance = round(((current - n1) / n1) * 100, 1) if n1 and n1 > 0 else None

        now = datetime.now(timezone.utc)
        last_data_date = now
        if daily:
            try:
                last_data_date = datetime.strptime(daily[-1]["date"], "%Y-%m-%d")
            except (ValueError, KeyError, TypeError):
                pass

        if last_data_date.month == now.month and last_data_date.year == now.year:
            jours_ecoules = last_data_date.day
            _, jours_total = calendar.monthrange(now.year, now.month)
            if jours_ecoules > 0:
                pred_conso = round((current / jours_ecoules) * jours_total, 1)
                return pred_conso, round(pred_conso * tarif, 2), tendance

        return None, None, tendance

    def _calculate_eco_score(self, details: dict[str, Any], current: float | None) -> tuple[float | None, str, int]:
        """Calcule l'Eco-Score."""
        opt_hab = self._entry.options.get(CONF_HOUSEHOLD_SIZE)
        api_hab = _parse_nb_habitants(details.get("nombre_habitants", ""))
        nb_hab = int(opt_hab) if opt_hab is not None else (api_hab if api_hab > 0 else DEFAULT_HOUSEHOLD_SIZE)

        if current is None or nb_hab <= 0:
            return None, "Inconnu", nb_hab

        m3_per_hab = current / nb_hab
        grade = "G"
        if m3_per_hab < 2.5:
            grade = "A"
        elif m3_per_hab < 4.0:
            grade = "B"
        elif m3_per_hab < 6.0:
            grade = "C"
        elif m3_per_hab < 8.0:
            grade = "D"
        elif m3_per_hab < 10.0:
            grade = "E"
        elif m3_per_hab < 13.0:
            grade = "F"

        return round(m3_per_hab, 2), grade, nb_hab

    def _estimate_next_bill_date(self, next_payment: str | None) -> str | None:
        """Estime la prochaine date de facture."""
        if not next_payment:
            return None
        try:
            dt_pay = datetime.strptime(next_payment, "%Y-%m-%d")
            return (dt_pay + timedelta(days=180)).strftime("%Y-%m-%d")
        except ValueError:
            return None

    def _calculate_experimental_leak(self, experimental: bool, daily: list[DailyConsumption]) -> float | None:
        """Calcule la fuite estimée (mode expérimental)."""
        if not (experimental and daily):
            return None
        valeurs = [e["volume_fuite_estime_m3"] for e in daily[-30:] if "volume_fuite_estime_m3" in e]
        return round(sum(valeurs), 3) if valeurs else None

    def _detect_local_leak(self, courbe: list[dict[str, Any]], daily: list[DailyConsumption], ref: str) -> bool:
        """Détecte une fuite locale par analyse de pattern.

        L'API Téléo ne pousse qu'un index par 24h, donc la règle "jamais à 0 sur
        24h" est toujours vraie dans un logement habité. On utilise à la place un
        seuil statistique : alerte si la conso du dernier jour dépasse
        `CONF_LEAK_MULTIPLIER`× la moyenne glissante des 7 derniers jours (minimum
        500 L/j pour éviter les faux positifs sur de très faibles consos). Le
        multiplicateur est celui configuré dans les options, unifié avec la
        détection mensuelle du binary_sensor.
        """
        if courbe:
            vals = [e.get("valeur", 0) for e in courbe if "valeur" in e]
            # Courbe intra-journalière : flux non-nul en permanence sur 24h+ = fuite probable.
            if len(vals) >= 24 and all(v > 0 for v in vals):
                _LOGGER.warning("Suspected leak (flat 24h+ pattern): %s", ref)
                return True
        elif daily and len(daily) >= 7:
            recent = [e["consommation_m3"] for e in daily[-7:]]
            moyenne_7j = sum(recent) / len(recent)
            last = recent[-1]
            multiplier = float(self._entry.options.get(CONF_LEAK_MULTIPLIER, DEFAULT_LEAK_MULTIPLIER))
            seuil = max(moyenne_7j * multiplier, 0.5)  # au moins 500 L/j pour déclencher
            if moyenne_7j > 0 and last > seuil:
                _LOGGER.warning(
                    "Suspected leak (daily spike): %s — last=%.3f m³, avg7j=%.3f m³",
                    ref,
                    last,
                    moyenne_7j,
                )
                return True
        return False

    async def _get_real_index(
        self,
        cycle_api: "_CycleCachedApi",
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

    def _get_drought_level(self) -> str:
        """Niveau de sécheresse (heuristique calendaire). Valeurs = clés ENUM traduites."""
        current_month = datetime.now(timezone.utc).month
        return "vigilance" if 6 <= current_month <= 9 else "normal"

    def _get_real_monthly_cost(self, conso_courant: float | None, tarif_m3: float) -> float | None:
        """Calcule le coût mensuel réel = variable (conso × tarif) + part fixe (abonnement/12)."""
        sub = float(self._entry.options.get(CONF_SUBSCRIPTION_ANNUAL, DEFAULT_SUBSCRIPTION_ANNUAL))
        if conso_courant is None and sub == 0.0:
            return None
        variable = (conso_courant * tarif_m3) if conso_courant is not None else 0.0
        return round(variable + (sub / 12.0), 2)

    def _get_real_annual_cost(self, conso_annuelle: float, tarif_m3: float) -> float:
        """Calcule le coût annuel réel = variable + abonnement annuel complet."""
        sub = float(self._entry.options.get(CONF_SUBSCRIPTION_ANNUAL, DEFAULT_SUBSCRIPTION_ANNUAL))
        return round((conso_annuelle * tarif_m3) + sub, 2)

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

    # ------------------------------------------------------------------
    # Injection historique statistiques
    # ------------------------------------------------------------------

    @staticmethod
    def _statistic_ref(ref: str) -> str:
        """Normalise une référence contrat en object_id de statistique valide.

        Le recorder n'accepte que [a-z0-9_] (minuscules, pas d'underscore en
        bordure ni doublé) — une référence avec majuscules ou tirets rendait
        le statistic_id invalide et l'injection échouait silencieusement.
        Pour les références purement numériques (cas courant), no-op.
        """
        sanitized = re.sub(r"[^a-z0-9]+", "_", str(ref).lower()).strip("_")
        return sanitized or "contract"

    @classmethod
    def _statistic_id(cls, prefix: str, ref: str) -> str:
        """Construit un statistic ID stable pour un contrat."""
        return f"{DOMAIN}:{prefix}_{cls._statistic_ref(ref)}"

    @staticmethod
    def _build_stat_series(
        consos: list[MonthlyConsumption],
        value_fn: Callable[[float], float],
        anchor: tuple[tuple[int, int], float] | None,
        ndigits: int,
    ) -> list["StatisticData"]:
        """Construit une série cumulative (state + sum) prête pour le recorder.

        `value_fn(conso_m3) -> valeur du mois` (m³ ou EUR). `anchor`, s'il est
        fourni, vaut ((année, mois) du dernier mois déjà enregistré, somme cumulée
        AVANT ce mois) : le cumul repart de cette base et les mois antérieurs sont
        laissés intacts. Sans ancrage, le cumul part de 0 sur toute la fenêtre.
        Ancrer sur le recorder évite les deltas négatifs quand la fenêtre glissante
        glissante perd son plus ancien mois (le cumul repartait sinon de 0).
        """
        series: list["StatisticData"] = []
        cumulative = anchor[1] if anchor else 0.0
        last_ym = anchor[0] if anchor else None
        for entry in sorted(consos, key=lambda e: (e.get("annee", 0), e.get("mois_index", 0))):
            try:
                mois_num = entry["mois_index"] + 1
                annee = entry["annee"]
                value = value_fn(entry["consommation_m3"])
                dt = datetime(annee, mois_num, 1, 0, 0, 0, tzinfo=timezone.utc)
            except (KeyError, ValueError, TypeError) as err:
                _LOGGER.debug("Skipping statistic entry: %s — %s", entry, err)
                continue
            if last_ym is not None and (annee, mois_num) < last_ym:
                continue  # déjà enregistré : préserver la somme existante
            cumulative += value
            series.append(
                StatisticData(
                    start=dt,
                    sum=round(cumulative, ndigits),
                    state=round(value, ndigits),
                )
            )
        return series

    async def _last_recorded_anchor(self, statistic_id: str) -> tuple[tuple[int, int], float] | None:
        """Retourne ((année, mois), somme cumulée avant ce mois) du dernier point enregistré.

        Best-effort : toute absence de recorder ou erreur renvoie None, et
        l'injection retombe alors sur un cumul depuis 0 (comportement historique).
        """
        if not _HAS_LAST_STATS:
            return None
        try:
            recorder = _get_recorder_instance(self.hass)
            rows = await recorder.async_add_executor_job(
                _get_last_statistics, self.hass, 1, statistic_id, True, {"sum", "state"}
            )
            points = rows.get(statistic_id) if rows else None
            if not points:
                return None
            last = points[0]
            raw_start: object = last["start"]
            if isinstance(raw_start, datetime):
                start = raw_start
            elif isinstance(raw_start, (str, int, float)):
                start = datetime.fromtimestamp(float(raw_start), tz=timezone.utc)
            else:
                return None
            last_sum = float(last.get("sum") or 0.0)
            last_state = float(last.get("state") or 0.0)
            # baseline = cumul jusqu'au mois PRÉCÉDENT ce dernier point.
            return ((start.year, start.month), last_sum - last_state)
        except Exception as err:  # noqa: BLE001 - lecture optionnelle, jamais bloquante
            _LOGGER.debug("Lecture last_statistics indisponible pour %s : %s", statistic_id, err)
            return None

    async def _inject_series(self, metadata: "StatisticMetaData", series: list["StatisticData"], label: str) -> None:
        if not series:
            return
        try:
            result: object = async_add_external_statistics(self.hass, metadata, series)
            if inspect.isawaitable(result):
                await result
            _LOGGER.debug("Injected %s statistics: %d months", label, len(series))
        except (HomeAssistantError, ValueError) as err:
            _LOGGER.warning("Failed to inject %s statistics: %s", label, err)

    @staticmethod
    def _build_daily_stat_series(
        consos: list[DailyConsumption],
        value_fn: Callable[[float], float] = float,
        ndigits: int = 3,
    ) -> list["StatisticData"]:
        """Reconstruit un cumul journalier à la date réelle de chaque journée."""
        series: list["StatisticData"] = []
        cumulative = 0.0
        by_date: dict[str, DailyConsumption] = {}
        for entry in consos:
            if isinstance(entry, dict) and entry.get("date"):
                by_date[str(entry["date"])] = entry
        for entry in sorted(by_date.values(), key=lambda item: str(item.get("date", ""))):
            try:
                date = datetime.fromisoformat(str(entry["date"])).date()
                value = float(value_fn(float(entry["consommation_m3"])))
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.debug("Skipping daily statistic entry: %s — %s", entry, err)
                continue
            cumulative += value
            series.append(
                StatisticData(
                    start=datetime.combine(date, datetime.min.time(), tzinfo=timezone.utc),
                    sum=round(cumulative, ndigits),
                    state=round(value, ndigits),
                )
            )
        return series

    async def _inject_statistics(self, contracts_data: dict[str, ContractData]) -> None:
        """Injecte l'historique mensuel dans les statistiques longues durée HA."""
        if not _HAS_RECORDER:
            return

        # StatisticMeanType sur les HA récents, has_mean en fallback sur les anciens
        if StatisticMeanType is not None:
            _mean_kwargs: dict[str, Any] = {"mean_type": StatisticMeanType.NONE}
        else:
            _mean_kwargs = {"has_mean": False}

        for ref, contract in contracts_data.items():
            daily_consos = getattr(self, "_daily_history", {}).get(ref) or contract.get(
                "consommations_journalieres", []
            )
            if daily_consos:
                daily_metadata = cast(
                    StatisticMetaData,
                    {
                        **_mean_kwargs,
                        "has_sum": True,
                        "name": f"Eau Grand Lyon - Journalier {ref}",
                        "source": DOMAIN,
                        "statistic_id": self._statistic_id(STATISTIC_WATER_DAILY, ref),
                        "unit_of_measurement": "m³",
                        "unit_class": "volume",
                    },
                )
                daily_series = self._build_daily_stat_series(daily_consos)
                await self._inject_series(daily_metadata, daily_series, f"journalier contrat {ref}")

                tarif = contract.get("tarif_m3", 0)
                if tarif > 0:
                    daily_cost_metadata = cast(
                        StatisticMetaData,
                        {
                            **_mean_kwargs,
                            "has_sum": True,
                            "name": f"Eau Grand Lyon - Coût journalier {ref}",
                            "source": DOMAIN,
                            "statistic_id": self._statistic_id(STATISTIC_COST_DAILY, ref),
                            "unit_of_measurement": "EUR",
                            "unit_class": None,
                        },
                    )
                    daily_cost_series = self._build_daily_stat_series(
                        daily_consos,
                        lambda conso: round(conso * tarif, 2),
                        2,
                    )
                    await self._inject_series(
                        daily_cost_metadata,
                        daily_cost_series,
                        f"coût journalier {ref}",
                    )

            # Historique fusionné pour que le passé soit toujours
            # injecté, pas seulement les ~12 mois renvoyés par l'API à chaque appel.
            consos = self._monthly_history.get(ref) or contract.get("consommations", [])
            if not consos:
                continue

            statistic_id = self._statistic_id(STATISTIC_WATER, ref)
            metadata = cast(
                StatisticMetaData,
                {
                    **_mean_kwargs,
                    "has_sum": True,
                    "name": f"Eau Grand Lyon - Compteur {ref}",
                    "source": DOMAIN,
                    "statistic_id": statistic_id,
                    "unit_of_measurement": "m³",
                    "unit_class": "volume",
                },
            )
            anchor = await self._last_recorded_anchor(statistic_id)
            water_series = self._build_stat_series(consos, lambda conso: conso, anchor, 3)
            await self._inject_series(metadata, water_series, f"contrat {ref}")

            # Statistiques de coût (EUR/mois) si un tarif est configuré.
            tarif = contract.get("tarif_m3", 0)
            if tarif <= 0:
                continue
            cost_statistic_id = self._statistic_id(STATISTIC_COST, ref)
            cost_metadata = cast(
                StatisticMetaData,
                {
                    **_mean_kwargs,
                    "has_sum": True,
                    "name": f"Eau Grand Lyon - Coût {ref}",
                    "source": DOMAIN,
                    "statistic_id": cost_statistic_id,
                    "unit_of_measurement": "EUR",
                    # Currency has no unit converter -> unit_class must be None (not
                    # "monetary"). Omitting it entirely is deprecated (removed in HA
                    # 2025.11); "monetary" is rejected as an unsupported converter.
                    "unit_class": None,
                },
            )
            cost_anchor = await self._last_recorded_anchor(cost_statistic_id)
            cost_series = self._build_stat_series(consos, lambda conso: round(conso * tarif, 2), cost_anchor, 2)
            await self._inject_series(cost_metadata, cost_series, f"coût {ref}")

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


class _CycleCachedApi:
    """Per-update-cycle cached facade around EauGrandLyonApi.

    Le cache (un dict de tasks) vit dans l'instance et meurt avec elle à la fin
    du cycle. Un décorateur de cache au niveau classe (ex. alru_cache) garderait
    une référence sur chaque instance et accumulerait les réponses API de tous
    les cycles précédents. Les appels concurrents sur la même clé partagent la
    même task (un seul appel API par clé et par cycle).
    """

    def __init__(self, api: EauGrandLyonApi) -> None:
        self._api = api
        self._tasks: dict[tuple[object, ...], asyncio.Task[Any]] = {}

    def _cached(self, method: str, *args: object, **kwargs: object) -> asyncio.Task[Any]:
        key = (method, args, tuple(sorted(kwargs.items())))
        if key not in self._tasks:
            self._tasks[key] = asyncio.ensure_future(getattr(self._api, method)(*args, **kwargs))
        return self._tasks[key]

    async def aclose(self) -> None:
        """Annule les tasks encore en vol à la fin du cycle (chemins d'erreur).

        Évite les requêtes fantômes et les avertissements « Task exception was
        never retrieved » quand le cycle se termine sur une exception.
        """
        pending = [t for t in self._tasks.values() if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def get_contracts(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._cached("get_contracts"))

    async def get_alertes(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._cached("get_alertes"))

    async def get_water_quality(self, commune: str | None = None) -> WaterQualityData:
        return cast(WaterQualityData, await self._cached("get_water_quality", commune))

    async def get_interventions(self) -> list[OutageData]:
        return cast(list[OutageData], await self._cached("get_interventions"))

    async def get_factures(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._cached("get_factures"))

    async def get_monthly_consumptions(self, contract_id: str) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            await self._cached("get_monthly_consumptions", contract_id),
        )

    async def get_daily_consumptions(self, contract_id: str, nb_jours: int = 90) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._cached("get_daily_consumptions", contract_id, nb_jours=nb_jours),
        )

    async def get_alerte_surconsommation(self, contract_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._cached("get_alerte_surconsommation", contract_id),
        )

    async def get_date_prochaine_facture(self, contract_id: str) -> str | None:
        return cast(str | None, await self._cached("get_date_prochaine_facture", contract_id))

    async def get_point_de_service_etendu(self, contract_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._cached("get_point_de_service_etendu", contract_id),
        )

    async def get_courbe_de_charge(self, contract_id: str, nb_jours: int = 7) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            await self._cached("get_courbe_de_charge", contract_id, nb_jours=nb_jours),
        )

    async def get_derniere_releve_siamm(self, contract_id: str) -> dict[str, Any] | None:
        return cast(
            dict[str, Any] | None,
            await self._cached("get_derniere_releve_siamm", contract_id),
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _parse_nb_habitants(val: str) -> int:
    """Extrait le nombre d'habitants depuis une chaîne (ex: '4 personnes')."""
    if not val:
        return 1
    match = re.search(r"(\d+)", val)
    return int(match.group(1)) if match else 1


def _find_missing_months(consos: list[MonthlyConsumption]) -> list[str]:
    """Détecte les mois manquants entre le premier et le dernier relevé disponible."""
    if len(consos) < 2:
        return []

    present = {(e["annee"], e["mois_index"]) for e in consos}
    first = consos[0]
    last = consos[-1]
    missing: list[str] = []
    year = first["annee"]
    month_idx = first["mois_index"]
    end_year = last["annee"]
    end_m_idx = last["mois_index"]

    while (year, month_idx) <= (end_year, end_m_idx):
        if (year, month_idx) not in present:
            missing.append(f"{MONTHS_FR[month_idx]} {year}")
        month_idx += 1
        if month_idx > 11:
            month_idx = 0
            year += 1

    return missing


def _parse_outage_alertes(alertes: list[dict[str, Any]]) -> list[OutageData]:
    """Extrait les interruptions de service (travaux, coupures) depuis la liste d'alertes.

    Filtre les alertes de type travaux/coupure et les normalise pour le calendrier
    et le binary_sensor. Retourne une liste triée par date de début (la plus proche en tête).
    """
    interruptions: list[OutageData] = []

    for alerte in alertes:
        try:
            info = alerte.get("infosAlarme") or alerte
            modele = alerte.get("modeleAction") or {}
            type_alerte = ((info.get("type") or {}).get("libelle", "") or str(info.get("typeCode", ""))).upper()
            libelle_modele = str(modele.get("libelle", "")).upper()

            is_outage = any(
                k in (type_alerte + " " + libelle_modele) for k in ("TRAVAUX", "COUPURE", "INTERRUPT", "MAINTENANCE")
            )
            if not is_outage:
                continue

            date_debut_raw = info.get("dateDebut") or alerte.get("dateDebut") or ""
            date_fin_raw = info.get("dateFin") or alerte.get("dateFin") or ""

            interruptions.append(
                {
                    "titre": info.get("libelle") or modele.get("libelle") or "Interruption service eau",
                    "date_debut": date_debut_raw[:10] if date_debut_raw else None,
                    "date_fin": date_fin_raw[:10] if date_fin_raw else None,
                    "type": type_alerte or "TRAVAUX",
                    "description": info.get("description") or alerte.get("description") or "",
                    "reference": str(alerte.get("id") or ""),
                }
            )
        except Exception:  # noqa: BLE001
            continue

    interruptions.sort(key=lambda x: x.get("date_debut") or "9999-99-99")
    return interruptions
