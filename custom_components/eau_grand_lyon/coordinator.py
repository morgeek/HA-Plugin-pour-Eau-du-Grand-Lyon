"""Coordinateur de mise à jour pour Eau du Grand Lyon."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AuthenticationError,
    EauGrandLyonApi,
    MONTHS_FR,
    NetworkError,
    WafBlockedError,
)
from .repairs import async_check_drought_issue
from .const import (
    CONF_EMAIL,
    CONF_EXPERIMENTAL,
    CONF_PASSWORD,
    CONF_PRICE_ENTITY,
    CONF_TARIF_M3,
    CONF_UPDATE_INTERVAL_HOURS,
    CONF_HOUSEHOLD_SIZE,
    CONF_WATER_HARDNESS,
    DEFAULT_EXPERIMENTAL,
    DEFAULT_HOUSEHOLD_SIZE,
    DEFAULT_TARIF_M3,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    DEFAULT_WATER_HARDNESS,
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

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
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
        except Exception as err:  # noqa: BLE001
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
        except Exception as err:  # noqa: BLE001
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

            except Exception as err:  # noqa: BLE001
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

        # Tarif — entité dynamique en priorité, puis options, puis config initiale
        opts = self._entry.options or {}
        tarif_m3 = DEFAULT_TARIF_M3
        price_entity_found = False

        price_entity = opts.get(CONF_PRICE_ENTITY)
        if price_entity:
            state = self.hass.states.get(price_entity)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    tarif_m3 = float(state.state)
                    price_entity_found = True
                except (ValueError, TypeError):
                    _LOGGER.warning(
                        "Valeur invalide pour l'entité de prix %s : %s",
                        price_entity, state.state
                    )

        if not price_entity_found:
            try:
                tarif_m3 = float(
                    opts[CONF_TARIF_M3]
                    if CONF_TARIF_M3 in opts
                    else self._entry.data.get(CONF_TARIF_M3, DEFAULT_TARIF_M3)
                )
            except (ValueError, TypeError):
                tarif_m3 = DEFAULT_TARIF_M3

        # [EXPÉRIMENTAL] Factures — récupérées une seule fois (données globales compte)
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
            conso_n1: float | None = None
            label_n1: str | None   = None
            if consos:
                target_mois  = consos[-1]["mois_index"]
                target_annee = consos[-1]["annee"] - 1
                for e in consos:
                    if e["mois_index"] == target_mois and e["annee"] == target_annee:
                        conso_n1 = e["consommation_m3"]
                        label_n1 = e["label"]
                        break

            # Détection des mois manquants
            mois_manquants = _find_missing_months(consos)
            if mois_manquants:
                _LOGGER.debug(
                    "Contrat %s — %d mois manquant(s) : %s",
                    ref, len(mois_manquants), ", ".join(mois_manquants),
                )

            conso_7j:  float | None = None
            conso_30j: float | None = None
            if consos_journalieres:
                recent_7  = consos_journalieres[-7:]
                recent_30 = consos_journalieres[-30:]
                conso_7j  = round(sum(e["consommation_m3"] for e in recent_7),  2)
                conso_30j = round(sum(e["consommation_m3"] for e in recent_30), 2)

            # ── [INTELLIGENCE] Tendance & Prédiction ──────────────────────────
            prediction_conso_mois: float | None = None
            prediction_cout_mois:  float | None = None
            tendance_n1_pct:       float | None = None

            if conso_courant is not None:
                # 1. Tendance N-1
                if conso_n1 and conso_n1 > 0:
                    tendance_n1_pct = round(((conso_courant - conso_n1) / conso_n1) * 100, 1)

                # 2. Prédiction fin de mois
                now = datetime.now()
                last_data_date = now
                if consos_journalieres:
                    try:
                        last_data_date = datetime.strptime(consos_journalieres[-1]["date"], "%Y-%m-%d")
                    except (ValueError, KeyError, TypeError):
                        pass

                if last_data_date.month == now.month and last_data_date.year == now.year:
                    import calendar
                    jours_ecoules = last_data_date.day
                    _, jours_total = calendar.monthrange(now.year, now.month)
                    if jours_ecoules > 0:
                        prediction_conso_mois = round((conso_courant / jours_ecoules) * jours_total, 1)
                        prediction_cout_mois  = round(prediction_conso_mois * tarif_m3, 2)

            # ── [ECO-SCORE] Analyse de performance ────────────────────────────
            eco_score = None
            eco_score_grade = "Inconnu"
            
            # Priorité 1 : Option HA, Priorité 2 : API Grand Lyon, Priorité 3 : Default (2)
            opt_hab = self._entry.options.get(CONF_HOUSEHOLD_SIZE)
            api_hab = _parse_nb_habitants(details.get("nombre_habitants", ""))
            nb_hab = int(opt_hab) if opt_hab is not None else (api_hab if api_hab > 0 else DEFAULT_HOUSEHOLD_SIZE)
            
            if conso_courant is not None and nb_hab > 0:
                # Conso mensuelle moyenne par habitant
                m3_per_hab = conso_courant / nb_hab
                # Barème Eco-Score (m3/pers/mois)
                # A: <2.5, B: <4, C: <6, D: <8, E: <10, F: <13, G: >13
                if m3_per_hab < 2.5:   eco_score_grade = "A"
                elif m3_per_hab < 4.0: eco_score_grade = "B"
                elif m3_per_hab < 6.0: eco_score_grade = "C"
                elif m3_per_hab < 8.0: eco_score_grade = "D"
                elif m3_per_hab < 10.0: eco_score_grade = "E"
                elif m3_per_hab < 13.0: eco_score_grade = "F"
                else:                  eco_score_grade = "G"
                eco_score = round(m3_per_hab, 2)

            # ── [CO2-FOOTPRINT] Impact environnemental ───────────────────────
            co2_footprint = None
            if conso_courant is not None:
                # Moyenne ADEME France : 0.52 kg CO2e / m3
                co2_footprint = round(conso_courant * 0.52, 2)


            # ── [BILLING] Dates clés ──────────────────────────────────────────
            # Extraction des dates de facturation futures si disponibles
            next_payment_date = details.get("date_echeance")
            # Simulation d'une date de prochaine facture (souvent 6 mois après)
            next_bill_date = None
            if next_payment_date:
                try:
                    dt_pay = datetime.strptime(next_payment_date, "%Y-%m-%d")
                    next_bill_date = (dt_pay + timedelta(days=180)).strftime("%Y-%m-%d")
                except ValueError:
                    pass

            # ── [EXPÉRIMENTAL] Fuite estimée ──────────────────────────────────
            fuite_estime_30j_m3: float | None = None
            if experimental and consos_journalieres:
                recent_30 = consos_journalieres[-30:]
                valeurs_fuite = [
                    e["volume_fuite_estime_m3"]
                    for e in recent_30
                    if "volume_fuite_estime_m3" in e
                ]
                if valeurs_fuite:
                    fuite_estime_30j_m3 = round(sum(valeurs_fuite), 3)

            # ── [EXPÉRIMENTAL] Courbe de charge ───────────────────────────
            courbe_de_charge: list[dict] = []
            if experimental and consos_journalieres:
                courbe_de_charge = await self.api.get_courbe_de_charge(cid, nb_jours=7)

            # ── [INTELLIGENCE] Détection de fuite locale (Pattern) ────────────
            local_leak_pattern = False
            if courbe_de_charge:
                # Si on a la courbe de charge (horaire), on cherche si conso > 0 sur TOUTES les heures
                # (Indicateur très fiable de fuite constante)
                vals = [e.get("valeur", 0) for e in courbe_de_charge if "valeur" in e]
                if len(vals) >= 24 and all(v > 0 for v in vals):
                    local_leak_pattern = True
                    _LOGGER.warning(
                        "Fuite suspectée par pattern local (conso constante > 0 sur 24h+) pour le contrat %s",
                        ref
                    )
            elif consos_journalieres:
                # Fallback sur le journalier : si le minimum journalier est élevé sur 7 jours
                recent_7 = [e["consommation_m3"] for e in consos_journalieres[-7:]]
                if len(recent_7) >= 7 and all(v > 0.05 for v in recent_7): # 50L/jour min
                    local_leak_pattern = True

            # ── [EXPÉRIMENTAL] Index réel & Factures ──────────────────────────
            real_index: float | None = None
            if experimental:
                siamm_raw = await self.api.get_derniere_releve_siamm(cid)
                real_index = EauGrandLyonApi.parse_siamm_index(siamm_raw)
                if real_index is None and consos_journalieres:
                    for e in reversed(consos_journalieres):
                        if "index_m3" in e:
                            real_index = e["index_m3"]
                            break

            # ── [LIMESCALE] Entartrage Virtuel ───────────────────────────────
            hardness = float(self._entry.options.get(CONF_WATER_HARDNESS, DEFAULT_WATER_HARDNESS))
            # Utilisation de l'index cumulatif (total volume historique)
            idx_cumul = real_index if real_index is not None else sum(e["consommation_m3"] for e in consos)
            limescale_g = round(idx_cumul * hardness * 10, 0)
            limescale_alert = limescale_g > 100000 # Alerte arbitraire à 100kg de calcaire cumulé

            factures_contrat = [f for f in factures if f.get("contrat_id") == cid]
            derniere_facture = factures_contrat[0] if factures_contrat else None

            # ── Coûts estimés ─────────────────────────────────────────────────
            cout_mois   = (
                round(conso_courant * tarif_m3, 2) if conso_courant is not None else None
            )
            cout_annuel = round(conso_annuelle * tarif_m3, 2)

            # Mise à jour des agrégats globaux
            global_data["total_conso_courant"]      += conso_courant or 0
            global_data["total_cout_courant_eur"]   += cout_mois or 0
            global_data["total_prediction_cout_eur"] += prediction_cout_mois or 0
            global_data["total_consommation_annuelle"] += conso_annuelle or 0
            global_data["nb_contracts"] += 1

            contracts_data[ref] = {
                **details,
                # Consommations mensuelles
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
                # Journalier
                "consommations_journalieres":  consos_journalieres,
                "consommation_7j":             conso_7j,
                "consommation_30j":            conso_30j,
                # Coûts
                "cout_mois_courant_eur":       cout_mois,
                "cout_annuel_eur":             cout_annuel,
                "tarif_m3":                    tarif_m3,
                # Intelligence
                "tendance_n1_pct":             tendance_n1_pct,
                "prediction_conso_mois":       prediction_conso_mois,
                "prediction_cout_mois":        prediction_cout_mois,
                "local_leak_pattern":          local_leak_pattern,
                # Eco-Score
                "eco_score_m3_pers":           eco_score,
                "eco_score_grade":             eco_score_grade,
                "nb_habitants":                nb_hab,
                # CO2
                "co2_footprint_kg":            co2_footprint,
                # Billing
                "next_payment_date":           next_payment_date,
                "next_bill_date":              next_bill_date,
                # Limescale
                "limescale_g":                 limescale_g,
                "limescale_alert":             limescale_alert,
                "hardness_fh":                 hardness,
                # Expérimental
                "real_index":                  real_index,
                "factures":                    factures_contrat,
                "derniere_facture":            derniere_facture,
                "fuite_estime_30j_m3":         fuite_estime_30j_m3,
                "courbe_de_charge":            courbe_de_charge,
            }

            _LOGGER.debug(
                "Contrat %s : %d mois | courant=%.1f m³ | annuel=%.1f m³ | "
                "coût mois=%.2f € | journalier=%s%s | tendance=%s%%",
                ref, len(consos),
                conso_courant or 0,
                conso_annuelle,
                cout_mois or 0,
                f"{len(consos_journalieres)} jours" if consos_journalieres else "non disponible",
                f" | fuite_30j={fuite_estime_30j_m3:.3f}m³" if fuite_estime_30j_m3 else "",
                tendance_n1_pct or "N/A"
            )

        # ── [RÉGIONAL] Statut Sécheresse 69 ─────────────────────────────────
        # On simule la détection (placeholder pour futur API Propluvia/VigiEau)
        drought_level = "Normal"
        current_month = datetime.now().month
        if 6 <= current_month <= 9: # Été
            drought_level = "Vigilance" # Valeur par défaut en période estivale à Lyon
        
        # Vérification des issues de réparation (Sécheresse)
        async_check_drought_issue(self.hass, drought_level)
        
        # ── [VACATION] Surveillance mode vacances ──────────────────────────
        vacation_mode = self.hass.data.get(DOMAIN, {}).get("vacation_mode", False)
        vacation_alert = False
        if vacation_mode:
            # Si mode vacances actif, on vérifie si conso > 0 sur les dernières 24h
            total_24h = 0
            for ref, c in contracts_data.items():
                daily = c.get("consommations_journalieres", [])
                if daily:
                    total_24h += daily[-1].get("consommation_m3", 0)
            if total_24h > 0.001: # 1 Litre
                vacation_alert = True
                _LOGGER.warning("ALERTE VACANCES : Consommation de %.3f m³ détectée !", total_24h)

        await self._inject_statistics(contracts_data)
        self._handle_alert_notifications(nb_alertes)

        now = datetime.now(tz=timezone.utc)
        return {
            "contracts":         contracts_data,
            "global":            global_data,
            "drought_level":     drought_level,
            "vacation_alert":    vacation_alert,
            "nb_alertes":        nb_alertes,
            "experimental_mode": experimental,
            "api_mode":          "Experimental (2026)" if experimental else "Legacy",
            "last_update_success_time": now,
            "last_error":        None,
            "last_error_type":   None,
        }

    # ------------------------------------------------------------------
    # Injection historique statistiques
    # ------------------------------------------------------------------

    async def _inject_statistics(self, contracts_data: dict) -> None:
        """Injecte l'historique mensuel dans les statistiques longues durée HA.

        Optimisation : n'injecte que si le nombre de mois a changé par rapport
        à la dernière injection réussie (évite des écritures redondantes).
        """
        try:
            from homeassistant.components.recorder.models import (  # noqa: PLC0415
                StatisticData,
                StatisticMetaData,
            )
            from homeassistant.components.recorder.statistics import (  # noqa: PLC0415
                async_add_external_statistics,
            )
        except ImportError:
            _LOGGER.debug("Module recorder non disponible")
            return

        if not hasattr(self, "_stats_month_counts"):
            self._stats_month_counts: dict[str, int] = {}

        for ref, contract in contracts_data.items():
            consos = contract.get("consommations", [])
            if not consos:
                continue

            # Skip si le nombre de mois n'a pas changé
            current_count = len(consos)
            if self._stats_month_counts.get(ref) == current_count:
                _LOGGER.debug(
                    "Statistiques contrat %s : %d mois inchangés, injection ignorée",
                    ref, current_count,
                )
                continue

            statistic_id = f"{DOMAIN}:water_{ref}"
            metadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                mean_type=None,
                name=f"Eau Grand Lyon - Compteur {ref}",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_of_measurement="m³",
            )

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
                    _LOGGER.debug(
                        "Entrée statistique ignorée : %s — %s", entry, err
                    )
                    continue

            try:
                async_add_external_statistics(self.hass, metadata, stats)
                self._stats_month_counts[ref] = current_count
                _LOGGER.debug(
                    "Statistiques injectées : contrat %s, %d mois, %.1f m³ cumulés",
                    ref, len(stats), cumulative,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Erreur injection statistiques pour %s : %s", ref, err
                )


    # ------------------------------------------------------------------
    # Notifications alertes
    # ------------------------------------------------------------------

    def _handle_alert_notifications(self, nb_alertes: int) -> None:
        """Crée ou supprime une notification HA persistante selon les alertes."""
        try:
            from homeassistant.components.persistent_notification import (  # noqa: PLC0415
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
            self.hass.async_create_task(
                pn_dismiss(self.hass, notification_id=notif_id)
            )
            _LOGGER.info("Alertes Eau du Grand Lyon résolues")

        self._prev_nb_alertes = nb_alertes


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _parse_nb_habitants(val: str) -> int:
    """Extrait le nombre d'habitants depuis une chaîne (ex: '4 personnes')."""
    import re
    if not val:
        return 1
    match = re.search(r'(\d+)', val)
    if match:
        return int(match.group(1))
    return 1


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
