"""Coordinateur de mise à jour pour Eau du Grand Lyon."""
from __future__ import annotations

import asyncio
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
from .const import (
    CONF_TARIF_M3,
    CONF_UPDATE_INTERVAL_HOURS,
    DEFAULT_TARIF_M3,
    DEFAULT_UPDATE_INTERVAL_HOURS,
    CONF_EMAIL,
    CONF_PASSWORD,
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
                "id":                     str,
                "reference":              str,
                "statut":                 str,
                "date_effet":             str,
                "date_echeance":          str,
                "solde_eur":              float,
                "mensualise":             bool,
                "mode_paiement":          str,
                "calibre_compteur":       str,
                "usage":                  str,
                "nombre_habitants":       str,
                "reference_pds":          str,
                # — Consommations mensuelles —
                "consommations":          list[dict],
                "consommation_mois_courant":   float | None,
                "label_mois_courant":          str | None,
                "consommation_mois_precedent": float | None,
                "label_mois_precedent":        str | None,
                "consommation_annuelle":       float,
                "consommation_cumulee_annee": float,
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
            },
            ...
        },
        "nb_alertes": int,
        "last_update_success_time": datetime | None,
        "last_error": str | None,
        "last_error_type": str | None,
    }
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        options = entry.options or {}
        interval_hours = int(
            options.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=interval_hours),
        )
        self._entry = entry
        # Session dédiée — CookieJar(unsafe=True) pour conserver le cookie HttpOnly OAuth2
        self._own_session = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(unsafe=True)
        )
        self.api = EauGrandLyonApi(
            self._own_session,
            entry.data[CONF_EMAIL],
            entry.data[CONF_PASSWORD],
        )
        self._prev_nb_alertes: int = 0
        self._last_request_time: datetime | None = None
        self._min_request_delay = timedelta(seconds=30)  # Rate limiting: 30s min entre requêtes
        # Cache persistant pour l'historique
        self._store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_history")
        # Charger les données persistantes au démarrage
        hass.async_create_task(self._load_persistent_data())

    async def _load_persistent_data(self) -> None:
        """Charge les données persistantes depuis le store."""
        try:
            stored = await self._store.async_load()
            if stored:
                # Deserialize last_update_success_time from ISO string back to datetime
                ts = stored.get("last_update_success_time")
                if isinstance(ts, str):
                    try:
                        stored["last_update_success_time"] = datetime.fromisoformat(ts)
                    except ValueError:
                        stored["last_update_success_time"] = None
                self.data = stored
                _LOGGER.debug("Données persistantes chargées")
        except Exception as err:
            _LOGGER.warning("Erreur chargement données persistantes: %s", err)

    async def _save_persistent_data(self) -> None:
        """Sauvegarde les données persistantes."""
        try:
            # Serialize datetime objects to ISO strings for JSON storage
            data_to_save = {**(self.data or {})}
            ts = data_to_save.get("last_update_success_time")
            if isinstance(ts, datetime):
                data_to_save["last_update_success_time"] = ts.isoformat()
            await self._store.async_save(data_to_save)
            _LOGGER.debug("Données persistantes sauvegardées")
        except Exception as err:
            _LOGGER.warning("Erreur sauvegarde données persistantes: %s", err)

    async def async_close(self) -> None:
        """Ferme la session aiohttp dédiée."""
        if not self._own_session.closed:
            await self._own_session.close()

    # ------------------------------------------------------------------
    # Mise à jour principale avec retry
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        """Récupère toutes les données depuis l'API avec retry intelligent."""
        # Rate limiting: éviter les requêtes trop fréquentes
        now = datetime.now(timezone.utc)
        if self._last_request_time and (now - self._last_request_time) < self._min_request_delay:
            delay_needed = self._min_request_delay - (now - self._last_request_time)
            _LOGGER.debug("Rate limiting: attente %.1f s avant requête", delay_needed.total_seconds())
            await asyncio.sleep(delay_needed.total_seconds())
        self._last_request_time = datetime.now(timezone.utc)

        last_exc: Exception | None = None

        for attempt in range(3):
            # Auto-recovery: reset erreur après 1h
            if self.data and self.data.get("last_error") and self.data.get("last_update_success_time"):
                time_since_success = now - self.data["last_update_success_time"]
                if time_since_success > timedelta(hours=1):
                    _LOGGER.info("Auto-recovery: reset erreur après 1h sans succès")
                    self.data["last_error"] = None
                    self.data["last_error_type"] = None

            try:
                data = await self._fetch_all_data()
                data["last_update_success_time"] = datetime.now(timezone.utc)
                data["last_error"] = None
                data["last_error_type"] = None
                # Sauvegarder en cache persistant
                await self._save_persistent_data()
                return data

            except WafBlockedError as err:
                last_exc = err
                self.data = {
                    **(self.data or {}),
                    "last_update_success_time": None,
                    "last_error": str(err),
                    "last_error_type": "WafBlockedError",
                }
                if attempt < len(_WAF_RETRY_DELAYS):
                    delay = _WAF_RETRY_DELAYS[attempt]
                    _LOGGER.warning(
                        "WAF bloqué (tentative %d/3), retry dans %.0f s — %s",
                        attempt + 1,
                        delay,
                        err,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise UpdateFailed(
                        f"WAF bloqué après 3 tentatives. "
                        f"Augmentez l'intervalle dans les options. ({err})"
                    ) from err

            except NetworkError as err:
                last_exc = err
                self.data = {
                    **(self.data or {}),
                    "last_update_success_time": None,
                    "last_error": str(err),
                    "last_error_type": "NetworkError",
                }
                if attempt < len(_NET_RETRY_DELAYS):
                    delay = _NET_RETRY_DELAYS[attempt]
                    _LOGGER.warning(
                        "Erreur réseau (tentative %d/3), retry dans %.0f s — %s",
                        attempt + 1,
                        delay,
                        err,
                    )
                    await asyncio.sleep(delay)
                else:
                    raise UpdateFailed(f"Erreur réseau persistante: {err}") from err

            except AuthenticationError as err:
                self.data = {
                    **(self.data or {}),
                    "last_update_success_time": None,
                    "last_error": str(err),
                    "last_error_type": "AuthenticationError",
                }
                raise UpdateFailed(f"Erreur d'authentification: {err}") from err

            except Exception as err:  # noqa: BLE001
                self.data = {
                    **(self.data or {}),
                    "last_update_success_time": None,
                    "last_error": str(err),
                    "last_error_type": "UnknownError",
                }
                raise UpdateFailed(f"Erreur inattendue: {err}") from err

        raise UpdateFailed(f"Échec après 3 tentatives: {last_exc}")

    async def _fetch_all_data(self) -> dict:
        """Effectue tous les appels API et construit le dictionnaire de données."""
        raw_contracts = await self.api.get_contracts()
        _LOGGER.debug("%d contrat(s) trouvé(s)", len(raw_contracts))

        alertes = await self.api.get_alertes()
        nb_alertes = len(alertes)

        # Read tarif from options (updatable) first, fall back to initial config data
        opts = self._entry.options or {}
        tarif_m3 = float(
            opts[CONF_TARIF_M3]
            if CONF_TARIF_M3 in opts
            else self._entry.data.get(CONF_TARIF_M3, DEFAULT_TARIF_M3)
        )

        contracts_data: dict[str, dict] = {}

        for raw in raw_contracts:
            details = EauGrandLyonApi.parse_contract_details(raw)
            ref = details["reference"]
            if not ref:
                continue

            cid = details["id"]

            # ── Consommations mensuelles ─────────────────────────────
            raw_consos = await self.api.get_monthly_consumptions(cid)
            consos = EauGrandLyonApi.format_consumptions(raw_consos)

            conso_courant = consos[-1]["consommation_m3"] if consos else None
            label_courant = consos[-1]["label"] if consos else None
            conso_precedent = consos[-2]["consommation_m3"] if len(consos) >= 2 else None
            label_precedent = consos[-2]["label"] if len(consos) >= 2 else None

            last_12 = consos[-12:] if len(consos) >= 12 else consos
            conso_annuelle = round(sum(e["consommation_m3"] for e in last_12), 1)

            # Consommation cumulée année courante
            current_year = datetime.now().year
            conso_cumulee_annee = 0.0
            for e in consos:
                if e.get("annee") == current_year:
                    conso_cumulee_annee += e["consommation_m3"]
            conso_cumulee_annee = round(conso_cumulee_annee, 1)

            # Comparaison N-1
            conso_n1: float | None = None
            label_n1: str | None = None
            if consos:
                target_mois = consos[-1]["mois_index"]
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
                    "Contrat %s — %d mois manquant(s) dans l'historique : %s",
                    ref, len(mois_manquants), ", ".join(mois_manquants),
                )

            # ── Consommations journalières (si compteur compatible) ──
            raw_daily = await self.api.get_daily_consumptions(cid, nb_jours=90)
            consos_journalieres = EauGrandLyonApi.format_daily_consumptions(raw_daily)

            conso_7j: float | None = None
            conso_30j: float | None = None
            if consos_journalieres:
                recent_7 = consos_journalieres[-7:]
                recent_30 = consos_journalieres[-30:]
                conso_7j = round(sum(e["consommation_m3"] for e in recent_7), 2)
                conso_30j = round(sum(e["consommation_m3"] for e in recent_30), 2)

            # ── Coûts estimés ────────────────────────────────────────
            cout_mois = (
                round(conso_courant * tarif_m3, 2)
                if conso_courant is not None
                else None
            )
            cout_annuel = round(conso_annuelle * tarif_m3, 2)

            contracts_data[ref] = {
                **details,
                "consommations": consos,
                "consommation_mois_courant": conso_courant,
                "label_mois_courant": label_courant,
                "consommation_mois_precedent": conso_precedent,
                "label_mois_precedent": label_precedent,
                "consommation_annuelle": conso_annuelle,
                "consommation_cumulee_annee": conso_cumulee_annee,
                "consommation_n1": conso_n1,
                "label_n1": label_n1,
                "mois_manquants": mois_manquants,
                "consommations_journalieres": consos_journalieres,
                "consommation_7j": conso_7j,
                "consommation_30j": conso_30j,
                "cout_mois_courant_eur": cout_mois,
                "cout_annuel_eur": cout_annuel,
                "tarif_m3": tarif_m3,
            }

            _LOGGER.debug(
                "Contrat %s : %d mois | courant=%.1f m³ | annuel=%.1f m³ | "
                "coût mois=%.2f € | journalier=%s",
                ref, len(consos),
                conso_courant or 0,
                conso_annuelle,
                cout_mois or 0,
                f"{len(consos_journalieres)} jours" if consos_journalieres else "non disponible",
            )

        now = datetime.now(tz=timezone.utc)

        await self._inject_statistics(contracts_data)
        self._handle_alert_notifications(nb_alertes)

        return {
            "contracts": contracts_data,
            "nb_alertes": nb_alertes,
            "last_update_success_time": now,
            "last_error": None,
            "last_error_type": None,
        }

    # ------------------------------------------------------------------
    # Injection historique statistiques
    # ------------------------------------------------------------------

    async def _inject_statistics(self, contracts_data: dict) -> None:
        """Injecte l'historique mensuel dans les statistiques longues durée HA."""
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

        for ref, contract in contracts_data.items():
            consos = contract.get("consommations", [])
            if not consos:
                continue

            statistic_id = f"{DOMAIN}:water_{ref}"
            metadata = StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name=f"Eau Grand Lyon - Compteur {ref}",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_of_measurement="m³",
            )

            stats: list[StatisticData] = []
            cumulative = 0.0
            for entry in consos:
                mois_num = entry["mois_index"] + 1
                annee = entry["annee"]
                dt = datetime(annee, mois_num, 1, 0, 0, 0, tzinfo=timezone.utc)
                cumulative += entry["consommation_m3"]
                stats.append(
                    StatisticData(
                        start=dt,
                        sum=round(cumulative, 3),
                        state=round(entry["consommation_m3"], 3),
                    )
                )

            try:
                async_add_external_statistics(self.hass, metadata, stats)
                _LOGGER.debug(
                    "Statistiques injectées : contrat %s, %d mois, %.1f m³ cumulés",
                    ref, len(stats), cumulative,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Injection statistiques échouée pour %s : %s", ref, err)

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

def _find_missing_months(consos: list[dict]) -> list[str]:
    """Détecte les mois manquants entre le premier et le dernier relevé disponible.

    Retourne une liste de labels (ex. ["Mars 2024", "Avril 2024"]).
    """
    if len(consos) < 2:
        return []

    present = {(e["annee"], e["mois_index"]) for e in consos}

    first = consos[0]
    last = consos[-1]

    missing: list[str] = []
    year = first["annee"]
    month_idx = first["mois_index"]
    end_year = last["annee"]
    end_month_idx = last["mois_index"]

    while (year, month_idx) <= (end_year, end_month_idx):
        if (year, month_idx) not in present:
            missing.append(f"{MONTHS_FR[month_idx]} {year}")
        month_idx += 1
        if month_idx > 11:
            month_idx = 0
            year += 1

    return missing
