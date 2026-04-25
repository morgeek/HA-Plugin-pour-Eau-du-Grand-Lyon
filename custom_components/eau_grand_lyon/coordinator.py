"""Coordinateur de mise à jour pour Eau du Grand Lyon."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
import logging

import aiohttp

import calendar
import re
from typing import TYPE_CHECKING, Any
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

try:
    from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
    from homeassistant.components.recorder.statistics import (
        async_add_external_statistics,
        StatisticMeanType,
    )
    _HAS_RECORDER = True
except ImportError:
    _HAS_RECORDER = False

if TYPE_CHECKING:
    from .__init__ import EauGrandLyonConfigEntry

from .api import (
    AuthenticationError,
    EauGrandLyonApi,
    MONTHS_FR,
    NetworkError,
    WafBlockedError,
)
from .repairs import async_check_drought_issue, async_check_long_outage_issue
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

# Délais de retry en cas de blocage WAF ou d'erreur réseau
_WAF_RETRY_DELAYS = (60.0, 300.0)   # 1 min, 5 min
_NET_RETRY_DELAYS = (10.0, 30.0)    # 10 s, 30 s


class EauGrandLyonCoordinator(DataUpdateCoordinator[dict]):
    """Gère les mises à jour périodiques des données Eau du Grand Lyon.

    Structure de coordinator.data :
    {
        "contracts": {
            "<reference>": {
                # — Infos contrat —
                "id":                          str,
                "reference":                   str,
                "statut":                      str,
                "date_effet":                  str,
                "date_echeance":               str,
                "solde_eur":                   float,
                "mensualise":                  bool,
                "mode_paiement":               str,
                "calibre_compteur":            str,
                "usage":                       str,
                "nombre_habitants":            str,
                "reference_pds":               str,
                # — Consommations mensuelles —
                "consommations":               list[dict],
                "consommation_mois_courant":   float | None,
                "label_mois_courant":          str | None,
                "consommation_mois_precedent": float | None,
                "label_mois_precedent":        str | None,
                "consommation_annuelle":       float,
                "consommation_cumulee_annee":  float,
                "consommation_n1":             float | None,
                "label_n1":                    str | None,
                "mois_manquants":              list[str],
                # — Consommations journalières (si compteur compatible) —
                "consommations_journalieres":  list[dict],   # [] si non disponible
                "consommation_7j":             float | None,
                "consommation_30j":            float | None,
                # — Coûts estimés —
                "cout_mois_courant_eur":       float | None,
                "cout_annuel_eur":             float | None,
                "tarif_m3":                    float,
                # — Mode expérimental uniquement —
                "factures":                    list[dict],   # [] si désactivé ou indispo
                "derniere_facture":            dict | None,  # facture la plus récente
                "fuite_estime_30j_m3":         float | None, # somme volume_fuite_estime 30j
                "courbe_de_charge":            list[dict],   # [] si désactivé ou indispo
            },
            ...
        },
        "nb_alertes":               int,
        "last_update_success_time": datetime | None,
        "last_error":               str | None,
        "last_error_type":          str | None,
        "experimental_mode":        bool,   # indique si le mode expérimental est actif
        # — Mode hors-ligne —
        "offline_mode":             bool,
        "offline_since":            datetime | None,
    }
    """

    def __init__(self, hass: HomeAssistant, entry: EauGrandLyonConfigEntry) -> None:
        options = entry.options or {}
        try:
            interval_hours = int(
                options.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS)
            )
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

        # Mode expérimental — lu depuis les options

        experimental = bool(
            options.get(CONF_EXPERIMENTAL, DEFAULT_EXPERIMENTAL)
        )

        # Session dédiée — CookieJar(unsafe=True) pour conserver le cookie HttpOnly OAuth2
        self._own_session = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(unsafe=True)
        )
        self.api = EauGrandLyonApi(
            self._own_session,
            entry.data[CONF_EMAIL],
            entry.data[CONF_PASSWORD],
            experimental=experimental,
        )
        self._prev_nb_alertes: int = 0
        self._last_request_mono: float | None = None
        self._min_request_delay_s: float = 30.0  # rate limiting : 30 s min entre requêtes

        # Dernières données valides connues (utilisées en mode hors-ligne)
        self._last_good_data: dict | None = None
        self._persistent_data_loaded = False
        self._persistent_data_lock = asyncio.Lock()

        # Cache persistant pour l'historique
        self._store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_history")

        if experimental:
            _LOGGER.info(
                "Eau du Grand Lyon — mode EXPÉRIMENTAL activé : nouveaux endpoints /rest/produits/"
                " actifs. En cas de problème, désactivez dans les options de l'intégration."
            )

    async def async_initialize(self) -> None:
        """Charge le cache persistant avant le premier rafraîchissement."""
        if self._persistent_data_loaded:
            return

        async with self._persistent_data_lock:
            if self._persistent_data_loaded:
                return
            await self._load_persistent_data()
            self._persistent_data_loaded = True

    async def _load_persistent_data(self) -> None:
        """Charge les données persistantes depuis le store."""
        try:
            stored = await self._store.async_load()
            if stored:
                ts = stored.get("last_update_success_time")
                if isinstance(ts, str):
                    try:
                        stored["last_update_success_time"] = datetime.fromisoformat(ts)
                    except ValueError:
                        stored["last_update_success_time"] = None
                stored["offline_mode"]  = False
                stored["offline_since"] = None
                self.data = stored
                self._last_good_data = stored
                _LOGGER.debug("Données persistantes chargées (cache hors-ligne disponible)")
        except (json.JSONDecodeError, OSError, KeyError) as err:
            _LOGGER.warning("Erreur chargement données persistantes : %s", err)
        except Exception as err:
            _LOGGER.warning("Erreur inattendue chargement données persistantes : %s", err)

    async def _save_persistent_data(self) -> None:
        """Sauvegarde les données persistantes (jamais l'état offline)."""
        try:
            source = self._last_good_data or self.data or {}
            data_to_save = {**source, "offline_mode": False, "offline_since": None}
            ts = data_to_save.get("last_update_success_time")
            if isinstance(ts, datetime):
                data_to_save["last_update_success_time"] = ts.isoformat()
            await self._store.async_save(data_to_save)
            _LOGGER.debug("Données persistantes sauvegardées")
        except (json.JSONDecodeError, OSError, TypeError) as err:
            _LOGGER.warning("Erreur sauvegarde données persistantes : %s", err)
        except Exception as err:
            _LOGGER.warning("Erreur inattendue sauvegarde données persistantes : %s", err)

    async def async_clear_cache(self) -> None:
        """Supprime le cache persistant et réinitialise les données locales."""
        await self._store.async_remove()
        self.data = {}
        self._last_good_data = None
        _LOGGER.info("Cache persistant Eau du Grand Lyon supprimé")

    async def async_close(self) -> None:
        """Révoque le token et ferme la session aiohttp dédiée."""
        await self.api.async_revoke_token()
        if not self._own_session.closed:
            await self._own_session.close()

    # ------------------------------------------------------------------
    # Mise à jour principale avec retry
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        """Récupère toutes les données depuis l'API avec retry intelligent."""
        # Rate limiting — time.monotonic() insensible aux changements NTP
        mono_now = time.monotonic()
        if self._last_request_mono is not None:
            elapsed = mono_now - self._last_request_mono
            if elapsed < self._min_request_delay_s:
                delay_needed = self._min_request_delay_s - elapsed
                _LOGGER.debug("Rate limiting : attente %.1f s", delay_needed)
                await asyncio.sleep(delay_needed)
        self._last_request_mono = time.monotonic()

        last_exc: Exception | None = None
        last_err_type: str = "UnknownError"

        for attempt in range(3):
            try:
                data = await self._fetch_all_data()
                now = datetime.now(timezone.utc)
                data["last_update_success_time"] = now
                data["last_error"]      = None
                data["last_error_type"] = None
                data["offline_mode"]    = False
                data["offline_since"]   = None
                self._last_good_data = data
                await self._save_persistent_data()
                async_check_long_outage_issue(self.hass, 0)
                return data

            except WafBlockedError as err:
                last_exc = err
                last_err_type = "WafBlockedError"
                if attempt < len(_WAF_RETRY_DELAYS):
                    delay = _WAF_RETRY_DELAYS[attempt]
                    _LOGGER.warning(
                        "WAF bloqué (tentative %d/3), retry dans %.0f s — %s",
                        attempt + 1, delay, err,
                    )
                    await asyncio.sleep(delay)

            except NetworkError as err:
                last_exc = err
                last_err_type = "NetworkError"
                if attempt < len(_NET_RETRY_DELAYS):
                    delay = _NET_RETRY_DELAYS[attempt]
                    _LOGGER.warning(
                        "Erreur réseau (tentative %d/3), retry dans %.0f s — %s",
                        attempt + 1, delay, err,
                    )
                    await asyncio.sleep(delay)

            except AuthenticationError as err:
                raise UpdateFailed(f"Erreur d'authentification: {err}") from err

            except Exception as err:
                raise UpdateFailed(f"Erreur inattendue: {err}") from err

        # Toutes les tentatives ont échoué — mode hors-ligne si cache disponible
        cache = self._last_good_data
        if cache and cache.get("contracts"):
            offline_since = (
                self.data.get("offline_since")
                if self.data and self.data.get("offline_mode")
                else datetime.now(timezone.utc)
            )
            _LOGGER.warning(
                "API indisponible après 3 tentatives (%s) — mode hors-ligne activé "
                "(données du %s)",
                last_err_type,
                cache.get("last_update_success_time", "inconnu"),
            )
            days_offline = (datetime.now(timezone.utc) - offline_since).days
            async_check_long_outage_issue(self.hass, days_offline)

            return {
                **cache,
                "offline_mode":    True,
                "offline_since":   offline_since,
                "last_error":      str(last_exc),
                "last_error_type": last_err_type,
            }

        raise UpdateFailed(f"Échec après 3 tentatives (aucun cache disponible): {last_exc}")

    async def _fetch_all_data(self) -> dict:
        """Effectue tous les appels API et construit le dictionnaire de données."""
        experimental = self.api.experimental

        raw_contracts = await self.api.get_contracts()
        _LOGGER.debug("%d contrat(s) trouvé(s)", len(raw_contracts))

        alertes    = await self.api.get_alertes()
        nb_alertes = len(alertes)
        interruptions = _parse_outage_alertes(alertes)
        prochaine_coupure = interruptions[0] if interruptions else None

        # Qualité de l'eau (Open Data Métropole Lyon) — best-effort, sans auth
        water_quality = await self.api.get_water_quality()

        tarif_m3 = self._calculate_tarif_m3()

        factures_raw: list[dict] = []
        if experimental:
            factures_raw = await self.api.get_factures()

        factures = EauGrandLyonApi.format_factures(factures_raw) if factures_raw else []

        contracts_data: dict[str, dict] = {}
        global_data = {
            "total_conso_courant":      0.0,
            "total_cout_courant_eur":   0.0,
            "total_prediction_cout_eur": 0.0,
            "total_consommation_annuelle": 0.0,
            "nb_contracts":             0,
        }

        for raw in raw_contracts:
            details = EauGrandLyonApi.parse_contract_details(raw)
            ref = details["reference"]
            if not ref:
                continue

            contract_data = await self._process_contract(details, tarif_m3, factures, experimental)
            contracts_data[ref] = contract_data
            
            # Mise à jour des agrégats globaux
            global_data["total_conso_courant"]      += contract_data.get("consommation_mois_courant") or 0
            global_data["total_cout_courant_eur"]   += contract_data.get("cout_mois_courant_eur") or 0
            global_data["total_prediction_cout_eur"] += contract_data.get("prediction_cout_mois") or 0
            global_data["total_consommation_annuelle"] += contract_data.get("consommation_annuelle") or 0
            global_data["nb_contracts"] += 1

        drought_level = self._get_drought_level()
        async_check_drought_issue(self.hass, drought_level)
        
        vacation_alert = self._check_vacation_alert(contracts_data)

        await self._inject_statistics(contracts_data)
        self._handle_alert_notifications(nb_alertes)

        return {
            "contracts":           contracts_data,
            "global":             global_data,
            "drought_level":      drought_level,
            "vacation_alert":     vacation_alert,
            "nb_alertes":         nb_alertes,
            "interruptions":      interruptions,
            "prochaine_coupure":  prochaine_coupure,
            "water_quality":      water_quality,
            "experimental_mode":  experimental,
            "api_mode":           "Experimental (2026)" if experimental else "Legacy",
            "last_update_success_time": datetime.now(tz=timezone.utc),
            "last_error":         None,
            "last_error_type":    None,
        }

    def _calculate_tarif_m3(self) -> float:
        """Calcule le tarif au m3 selon les options ou l'entité dynamique."""
        opts = self._entry.options or {}
        tarif_m3 = DEFAULT_TARIF_M3
        price_entity = opts.get(CONF_PRICE_ENTITY)
        
        if price_entity:
            state = self.hass.states.get(price_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    _LOGGER.warning("Valeur invalide pour l'entité de prix %s : %s", price_entity, state.state)

        try:
            return float(opts.get(CONF_TARIF_M3, self._entry.data.get(CONF_TARIF_M3, DEFAULT_TARIF_M3)))
        except (ValueError, TypeError):
            return DEFAULT_TARIF_M3

    async def _process_contract(self, details: dict, tarif_m3: float, factures: list[dict], experimental: bool) -> dict:
        """Traite les données d'un contrat spécifique."""
        ref = details["reference"]
        cid = details["id"]

        # ── Consommations mensuelles + journalières (en parallèle) ────────
        raw_consos, raw_daily = await asyncio.gather(
            self.api.get_monthly_consumptions(cid),
            self.api.get_daily_consumptions(cid, nb_jours=90),
        )
        consos              = EauGrandLyonApi.format_consumptions(raw_consos)
        consos_journalieres = EauGrandLyonApi.format_daily_consumptions(raw_daily)

        conso_courant   = consos[-1]["consommation_m3"] if consos else None
        label_courant   = consos[-1]["label"]           if consos else None
        conso_precedent = consos[-2]["consommation_m3"] if len(consos) >= 2 else None
        label_precedent = consos[-2]["label"]           if len(consos) >= 2 else None

        last_12        = consos[-12:] if len(consos) >= 12 else consos
        conso_annuelle = round(sum(e["consommation_m3"] for e in last_12), 1)

        current_year        = datetime.now().year
        conso_cumulee_annee = round(
            sum(e["consommation_m3"] for e in consos if e.get("annee") == current_year), 1
        )

        # Comparaison N-1
        conso_n1, label_n1 = self._get_consumption_n1(consos)

        # Détection des mois manquants
        mois_manquants = _find_missing_months(consos)

        conso_7j, conso_30j = self._calculate_daily_aggregates(consos_journalieres)

        # ── [INTELLIGENCE] Tendance & Prédiction ──────────────────────────
        prediction_conso_mois, prediction_cout_mois, tendance_n1_pct = self._calculate_intelligence(
            conso_courant, conso_n1, consos_journalieres, tarif_m3
        )

        # ── [ECO-SCORE] Analyse de performance ────────────────────────────
        eco_score, eco_score_grade, nb_hab = self._calculate_eco_score(details, conso_courant)

        # ── [CO2-FOOTPRINT] Impact environnemental ───────────────────────
        co2_footprint = round(conso_courant * 0.52, 2) if conso_courant is not None else None

        # ── [BILLING] Dates clés ──────────────────────────────────────────
        next_payment_date = details.get("date_echeance")
        next_bill_date = self._estimate_next_bill_date(next_payment_date)

        # ── [EXPÉRIMENTAL] Fuite estimée ──────────────────────────────────
        fuite_estime_30j_m3 = self._calculate_experimental_leak(experimental, consos_journalieres)

        # ── [EXPÉRIMENTAL] Courbe de charge ───────────────────────────
        courbe_de_charge = []
        if experimental and consos_journalieres:
            courbe_de_charge = await self.api.get_courbe_de_charge(cid, nb_jours=7)

        # ── [HORAIRE] Analyse de la courbe de charge ──────────────────
        consommation_derniere_heure_m3: float | None = None
        heure_pic: str | None = None
        debit_moyen_m3h: float | None = None
        if courbe_de_charge:
            raw_vals = []
            for e in courbe_de_charge:
                v = e.get("valeur") or e.get("consommation") or 0
                try:
                    raw_vals.append(float(v))
                except (ValueError, TypeError):
                    raw_vals.append(0.0)
            if raw_vals:
                last_e = courbe_de_charge[-1]
                consommation_derniere_heure_m3 = raw_vals[-1]
                max_idx = raw_vals.index(max(raw_vals))
                try:
                    peak_dt = datetime.fromisoformat(
                        courbe_de_charge[max_idx].get("date", "")
                    )
                    heure_pic = peak_dt.strftime("%H:%M")
                except (ValueError, TypeError, AttributeError):
                    heure_pic = None
                non_zero = [v for v in raw_vals if v > 0]
                if non_zero:
                    debit_moyen_m3h = round(sum(non_zero) / len(non_zero), 4)

        # ── [INTELLIGENCE] Détection de fuite locale (Pattern) ────────────
        local_leak_pattern = self._detect_local_leak(courbe_de_charge, consos_journalieres, ref)

        # ── [EXPÉRIMENTAL] Index réel & Factures ──────────────────────────
        real_index = await self._get_real_index(experimental, cid, consos_journalieres)

        # ── [LIMESCALE] Entartrage Virtuel ───────────────────────────────
        hardness = float(self._entry.options.get(CONF_WATER_HARDNESS, DEFAULT_WATER_HARDNESS))
        idx_cumul = real_index if real_index is not None else sum(e["consommation_m3"] for e in consos)
        limescale_g = round(idx_cumul * hardness * 10, 0)
        limescale_alert = limescale_g > 100000

        factures_contrat = [f for f in factures if f.get("contrat_id") == cid]
        derniere_facture = factures_contrat[0] if factures_contrat else None

        return {
            **details,
            "consommations":               consos,
            "consommation_mois_courant":   conso_courant,
            "label_mois_courant":          label_courant,
            "consommation_mois_precedent": conso_precedent,
            "label_mois_precedent":        label_precedent,
            "consommation_annuelle":       conso_annuelle,
            "consommation_cumulee_annee":  conso_cumulee_annee,
            "consommation_n1":             conso_n1,
            "label_n1":                    label_n1,
            "mois_manquants":              mois_manquants,
            "consommations_journalieres":  consos_journalieres,
            "consommation_7j":             conso_7j,
            "consommation_30j":            conso_30j,
            "cout_mois_courant_eur":       round(conso_courant * tarif_m3, 2) if conso_courant is not None else None,
            "cout_annuel_eur":             round(conso_annuelle * tarif_m3, 2),
            "tarif_m3":                    tarif_m3,
            # Coût réel = variable (conso × tarif) + fixe (abonnement proratisé)
            "cout_reel_mois":              self._get_real_monthly_cost(conso_courant, tarif_m3),
            "cout_reel_annuel":            self._get_real_annual_cost(conso_annuelle, tarif_m3),
            "subscription_annual":         float(self._entry.options.get(CONF_SUBSCRIPTION_ANNUAL, DEFAULT_SUBSCRIPTION_ANNUAL)),
            "tendance_n1_pct":             tendance_n1_pct,
            "prediction_conso_mois":       prediction_conso_mois,
            "prediction_cout_mois":        prediction_cout_mois,
            "local_leak_pattern":          local_leak_pattern,
            "eco_score_m3_pers":           eco_score,
            "eco_score_grade":             eco_score_grade,
            "nb_habitants":                nb_hab,
            "co2_footprint_kg":            co2_footprint,
            "next_payment_date":           next_payment_date,
            "next_bill_date":              next_bill_date,
            "limescale_g":                 limescale_g,
            "limescale_alert":             limescale_alert,
            "hardness_fh":                 hardness,
            "real_index":                  real_index,
            "factures":                    factures_contrat,
            "derniere_facture":            derniere_facture,
            "fuite_estime_30j_m3":         fuite_estime_30j_m3,
            "courbe_de_charge":            courbe_de_charge,
            # [HORAIRE] Données infra-journalières (compteur Téléo uniquement)
            "consommation_derniere_heure_m3": consommation_derniere_heure_m3,
            "heure_pic":                   heure_pic,
            "debit_moyen_m3h":             debit_moyen_m3h,
            # [HARDWARE] État du module Téléo — parsé depuis pointDeReleve
            "signal_pct":                  details.get("signal_pct"),
            "battery_ok":                  details.get("battery_ok"),
        }

    def _get_consumption_n1(self, consos: list[dict]) -> tuple[float | None, str | None]:
        """Récupère la consommation à N-1 pour le même mois."""
        if not consos:
            return None, None
        target_mois = consos[-1]["mois_index"]
        target_annee = consos[-1]["annee"] - 1
        for e in consos:
            if e["mois_index"] == target_mois and e["annee"] == target_annee:
                return e["consommation_m3"], e["label"]
        return None, None

    def _calculate_daily_aggregates(self, daily: list[dict]) -> tuple[float | None, float | None]:
        """Calcule les agrégats sur 7 et 30 jours."""
        if not daily:
            return None, None
        conso_7j = round(sum(e["consommation_m3"] for e in daily[-7:]), 2)
        conso_30j = round(sum(e["consommation_m3"] for e in daily[-30:]), 2)
        return conso_7j, conso_30j

    def _calculate_intelligence(self, current: float | None, n1: float | None, daily: list[dict], tarif: float) -> tuple[float | None, float | None, float | None]:
        """Calcule les tendances et prédictions."""
        if current is None:
            return None, None, None
            
        tendance = round(((current - n1) / n1) * 100, 1) if n1 and n1 > 0 else None
        
        now = datetime.now()
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

    def _calculate_eco_score(self, details: dict, current: float | None) -> tuple[float | None, str, int]:
        """Calcule l'Eco-Score."""
        opt_hab = self._entry.options.get(CONF_HOUSEHOLD_SIZE)
        api_hab = _parse_nb_habitants(details.get("nombre_habitants", ""))
        nb_hab = int(opt_hab) if opt_hab is not None else (api_hab if api_hab > 0 else DEFAULT_HOUSEHOLD_SIZE)
        
        if current is None or nb_hab <= 0:
            return None, "Inconnu", nb_hab
            
        m3_per_hab = current / nb_hab
        grade = "G"
        if m3_per_hab < 2.5: grade = "A"
        elif m3_per_hab < 4.0: grade = "B"
        elif m3_per_hab < 6.0: grade = "C"
        elif m3_per_hab < 8.0: grade = "D"
        elif m3_per_hab < 10.0: grade = "E"
        elif m3_per_hab < 13.0: grade = "F"
        
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

    def _calculate_experimental_leak(self, experimental: bool, daily: list[dict]) -> float | None:
        """Calcule la fuite estimée (mode expérimental)."""
        if not (experimental and daily):
            return None
        valeurs = [e["volume_fuite_estime_m3"] for e in daily[-30:] if "volume_fuite_estime_m3" in e]
        return round(sum(valeurs), 3) if valeurs else None

    def _detect_local_leak(self, courbe: list[dict], daily: list[dict], ref: str) -> bool:
        """Détecte une fuite locale par analyse de pattern."""
        if courbe:
            vals = [e.get("valeur", 0) for e in courbe if "valeur" in e]
            if len(vals) >= 24 and all(v > 0 for v in vals):
                _LOGGER.warning("Fuite suspectée (pattern constant 24h+) : %s", ref)
                return True
        elif daily:
            recent_7 = [e["consommation_m3"] for e in daily[-7:]]
            if len(recent_7) >= 7 and all(v > 0.05 for v in recent_7):
                return True
        return False

    async def _get_real_index(self, experimental: bool, cid: str, daily: list[dict]) -> float | None:
        """Récupère l'index réel du compteur."""
        if not experimental:
            return None
        siamm = await self.api.get_derniere_releve_siamm(cid)
        index = EauGrandLyonApi.parse_siamm_index(siamm)
        if index is None and daily:
            for e in reversed(daily):
                if "index_m3" in e:
                    return e["index_m3"]
        return index

    def _get_drought_level(self) -> str:
        """Détermine le niveau de sécheresse simulé."""
        current_month = datetime.now().month
        return "Vigilance" if 6 <= current_month <= 9 else "Normal"

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

    def _check_vacation_alert(self, contracts_data: dict) -> bool:
        """Vérifie si une alerte vacances doit être levée."""
        if not self.hass.data.get(DOMAIN, {}).get("vacation_mode", False):
            return False
        total_24h = 0
        for c in contracts_data.values():
            daily = c.get("consommations_journalieres", [])
            if daily:
                total_24h += daily[-1].get("consommation_m3", 0)
        if total_24h > 0.001:
            _LOGGER.warning("ALERTE VACANCES : Consommation de %.3f m³ détectée !", total_24h)
            return True
        return False

    # ------------------------------------------------------------------
    # Injection historique statistiques
    # ------------------------------------------------------------------

    async def _inject_statistics(self, contracts_data: dict) -> None:
        """Injecte l'historique mensuel dans les statistiques longues durée HA."""
        if not _HAS_RECORDER:
            return

        # Tente d'utiliser StatisticMeanType (HA >= 2026.x) sinon fallback
        try:
            _mean_kwargs: dict = {"mean_type": StatisticMeanType.NONE}
        except (NameError, AttributeError):
            _mean_kwargs = {"has_mean": False}

        if not hasattr(self, "_stats_month_counts"):
            self._stats_month_counts: dict[str, int] = {}

        for ref, contract in contracts_data.items():
            consos = contract.get("consommations", [])
            if not consos:
                continue

            current_count = len(consos)
            if self._stats_month_counts.get(ref) == current_count:
                continue

            statistic_id = f"{DOMAIN}:water_{ref}"
            metadata: StatisticMetaData = {
                **_mean_kwargs,
                "has_sum": True,
                "name": f"Eau Grand Lyon - Compteur {ref}",
                "source": DOMAIN,
                "statistic_id": statistic_id,
                "unit_of_measurement": "m³",
                "unit_class": "volume",
            }

            stats: list[StatisticData] = []
            cumulative = 0.0
            for entry in consos:
                try:
                    mois_num   = entry["mois_index"] + 1
                    annee      = entry["annee"]
                    conso      = entry["consommation_m3"]
                    dt         = datetime(annee, mois_num, 1, 0, 0, 0, tzinfo=timezone.utc)
                    cumulative += conso
                    stats.append(
                        StatisticData(
                            start=dt,
                            sum=round(cumulative, 3),
                            state=round(conso, 3),
                        )
                    )
                except (KeyError, ValueError, TypeError) as err:
                    _LOGGER.debug("Entrée statistique ignorée : %s — %s", entry, err)
                    continue

            try:
                async_add_external_statistics(self.hass, metadata, stats)
                self._stats_month_counts[ref] = current_count
                _LOGGER.debug("Statistiques injectées : contrat %s, %d mois", ref, len(stats))
            except Exception as err:
                _LOGGER.warning("Erreur injection statistiques pour %s : %s", ref, err)

    def _handle_alert_notifications(self, nb_alertes: int) -> None:
        """Crée ou supprime une notification HA persistante selon les alertes."""
        try:
            from homeassistant.components.persistent_notification import (
                async_create as pn_create,
                async_dismiss as pn_dismiss,
            )
        except ImportError:
            return

        notif_id = f"{DOMAIN}_alertes"

        if nb_alertes > 0 and nb_alertes != self._prev_nb_alertes:
            self.hass.async_create_task(
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
            )
            _LOGGER.info("%d alerte(s) Eau du Grand Lyon détectée(s)", nb_alertes)

        elif nb_alertes == 0 and self._prev_nb_alertes > 0:
            self.hass.async_create_task(pn_dismiss(self.hass, notification_id=notif_id))
            _LOGGER.info("Alertes Eau du Grand Lyon résolues")

        self._prev_nb_alertes = nb_alertes


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_nb_habitants(val: str) -> int:
    """Extrait le nombre d'habitants depuis une chaîne (ex: '4 personnes')."""
    if not val:
        return 1
    match = re.search(r'(\d+)', val)
    return int(match.group(1)) if match else 1


def _find_missing_months(consos: list[dict]) -> list[str]:
    """Détecte les mois manquants entre le premier et le dernier relevé disponible."""
    if len(consos) < 2:
        return []

    present    = {(e["annee"], e["mois_index"]) for e in consos}
    first      = consos[0]
    last       = consos[-1]
    missing:   list[str] = []
    year       = first["annee"]
    month_idx  = first["mois_index"]
    end_year   = last["annee"]
    end_m_idx  = last["mois_index"]

    while (year, month_idx) <= (end_year, end_m_idx):
        if (year, month_idx) not in present:
            missing.append(f"{MONTHS_FR[month_idx]} {year}")
        month_idx += 1
        if month_idx > 11:
            month_idx = 0
            year += 1

    return missing


def _parse_outage_alertes(alertes: list[dict]) -> list[dict]:
    """Extrait les interruptions de service (travaux, coupures) depuis la liste d'alertes.

    Filtre les alertes de type travaux/coupure et les normalise pour le calendrier
    et le binary_sensor. Retourne une liste triée par date de début (la plus proche en tête).
    """
    interruptions: list[dict] = []

    for alerte in alertes:
        try:
            info   = alerte.get("infosAlarme") or alerte
            modele = alerte.get("modeleAction") or {}
            type_alerte = (
                (info.get("type") or {}).get("libelle", "")
                or str(info.get("typeCode", ""))
            ).upper()
            libelle_modele = str(modele.get("libelle", "")).upper()

            is_outage = any(
                k in (type_alerte + " " + libelle_modele)
                for k in ("TRAVAUX", "COUPURE", "INTERRUPT", "MAINTENANCE")
            )
            if not is_outage:
                continue

            date_debut_raw = info.get("dateDebut") or alerte.get("dateDebut") or ""
            date_fin_raw   = info.get("dateFin")   or alerte.get("dateFin")   or ""

            interruptions.append({
                "titre":       info.get("libelle") or modele.get("libelle") or "Interruption service eau",
                "date_debut":  date_debut_raw[:10] if date_debut_raw else None,
                "date_fin":    date_fin_raw[:10]   if date_fin_raw   else None,
                "type":        type_alerte or "TRAVAUX",
                "description": info.get("description") or alerte.get("description") or "",
                "reference":   str(alerte.get("id") or ""),
            })
        except Exception:  # noqa: BLE001
            continue

    interruptions.sort(key=lambda x: x.get("date_debut") or "9999-99-99")
    return interruptions
