"""Main API client for Eau du Grand Lyon."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .auth import (
    ApiError,
    AuthenticationError,
    EauGrandLyonAuth,
    NetworkError,
    WafBlockedError,
    _log_http_event,
    _new_correlation_id,
)
from .endpoints import (
    BASE_URL,
    CONTRACTS_EXPAND,
    CONTRACTS_SELECT,
    INTERFACES_AEL_BASE,
    MONTHS_FR,
    PRODUITS_BASE,
)

_LOGGER = logging.getLogger(__name__)


def _detect_month_offset(entries: list[dict]) -> int:
    score_0indexed = 0
    score_1indexed = 0
    for entry in entries[:30]:
        month = entry.get("mois")
        if month is None:
            continue
        try:
            month_int = int(month)
        except (ValueError, TypeError):
            continue
        if month_int == 0:
            score_0indexed += 3
        elif month_int == 12:
            score_1indexed += 3
    return 1 if score_0indexed > score_1indexed else 0


def _infer_unit_from_magnitude(entries: list[dict]) -> str:
    values: list[float] = []
    for entry in entries[:50]:
        value = entry.get("consommation")
        if value is None:
            continue
        try:
            float_value = float(value)
        except (ValueError, TypeError):
            continue
        if float_value > 0:
            values.append(float_value)

    if not values:
        return ""
    values.sort()
    median = values[len(values) // 2]
    return "L" if median > 50 else "M3"


class EauGrandLyonApi:
    """Client pour l'API Eau du Grand Lyon avec authentification PKCE OAuth2."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        experimental: bool = False,
    ) -> None:
        self._session = session
        self._experimental = experimental
        self._auth = EauGrandLyonAuth(session, email, password, experimental=experimental)
        _LOGGER.debug(
            "EauGrandLyonApi initialise - mode=%s",
            "experimental" if experimental else "legacy",
        )

    @property
    def access_token(self) -> str | None:
        return self._auth.access_token

    @property
    def experimental(self) -> bool:
        return self._experimental

    async def authenticate(self) -> str:
        return await self._auth.authenticate()

    async def async_revoke_token(self) -> None:
        await self._auth.revoke_token()

    async def _ensure_auth(self, correlation_id: str | None = None) -> None:
        if not self._auth.access_token:
            await self._auth.authenticate(correlation_id=correlation_id)

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        correlation_id = _new_correlation_id()
        await self._ensure_auth(correlation_id=correlation_id)
        headers = {"Authorization": f"Bearer {self._auth.access_token}"}
        _LOGGER.debug("api_request_start cid=%s method=%s url=%s", correlation_id, method, url)

        try:
            start = time.perf_counter()
            async with self._session.request(method, url, headers=headers, **kwargs) as resp:
                duration_ms = (time.perf_counter() - start) * 1000
                _log_http_event(
                    phase="api_request",
                    correlation_id=correlation_id,
                    method=method,
                    url=url,
                    duration_ms=duration_ms,
                    status=resp.status,
                )
                if resp.status == 401:
                    _LOGGER.debug("api_request_reauth cid=%s method=%s url=%s", correlation_id, method, url)
                    await self._auth.authenticate(correlation_id=correlation_id)
                    headers = {"Authorization": f"Bearer {self._auth.access_token}"}
                    retry_start = time.perf_counter()
                    async with self._session.request(
                        method, url, headers=headers, **kwargs
                    ) as retry_resp:
                        retry_duration_ms = (time.perf_counter() - retry_start) * 1000
                        _log_http_event(
                            phase="api_request_retry",
                            correlation_id=correlation_id,
                            method=method,
                            url=url,
                            duration_ms=retry_duration_ms,
                            status=retry_resp.status,
                        )
                        if retry_resp.status == 403:
                            raise WafBlockedError(
                                f"WAF 403 sur {method} {url} (apres re-auth)."
                            )
                        retry_resp.raise_for_status()
                        return json.loads(await retry_resp.text())
                if resp.status == 403:
                    raise WafBlockedError(f"WAF 403 sur {method} {url}.")
                resp.raise_for_status()
                return json.loads(await resp.text())
        except (WafBlockedError, AuthenticationError):
            raise
        except aiohttp.ClientResponseError as err:
            _LOGGER.warning(
                "api_request_failed cid=%s method=%s url=%s status=%s error=%s",
                correlation_id,
                method,
                url,
                err.status,
                type(err).__name__,
            )
            raise ApiError(f"HTTP {err.status} sur {method} {url}: {err.message}") from err
        except aiohttp.ClientError as err:
            _LOGGER.warning(
                "api_request_failed cid=%s method=%s url=%s error=%s",
                correlation_id,
                method,
                url,
                type(err).__name__,
            )
            raise NetworkError(f"Erreur reseau sur {method} {url}: {err}") from err

    async def _do_get(self, url: str, params: dict | None = None) -> Any:
        return await self._request("GET", url, params=params)

    async def _do_post(self, url: str, body: dict | None = None) -> Any:
        return await self._request("POST", url, json=body or {})

    async def _get(self, path: str) -> Any:
        return await self._do_get(f"{BASE_URL}{path}")

    async def _post(self, path: str, body: dict | None = None) -> Any:
        return await self._do_post(f"{BASE_URL}{path}", body)

    async def _get_produits(self, sub_path: str, params: dict | None = None) -> Any:
        return await self._do_get(f"{PRODUITS_BASE}/{sub_path.lstrip('/')}", params)

    async def _get_interfaces(self, sub_path: str, params: dict | None = None) -> Any:
        return await self._do_get(f"{INTERFACES_AEL_BASE}/{sub_path.lstrip('/')}", params)

    async def get_contracts(self) -> list[dict]:
        data = await self._post(
            f"/application/rest/interfaces/ael/contrats/rechercher"
            f"?expand={CONTRACTS_EXPAND}&select={CONTRACTS_SELECT}"
        )
        if not isinstance(data, (dict, list)):
            _LOGGER.warning(
                "Reponse inattendue pour get_contracts (type=%s)", type(data).__name__
            )
            return []
        contracts = data.get("content", data) if isinstance(data, dict) else data
        return list(contracts) if contracts else []

    async def get_monthly_consumptions(self, contract_id: str) -> list[dict]:
        data = await self._get(
            f"/application/rest/interfaces/ael/contrats/{contract_id}/consommationsMensuelles"
        )
        entries: list[dict] = []
        if not isinstance(data, dict):
            _LOGGER.warning(
                "Reponse inattendue pour consommationsMensuelles (type=%s)",
                type(data).__name__,
            )
            return entries
        for poste in data.get("postes", []):
            entries.extend(poste.get("data", []))
        entries.sort(key=lambda item: (int(item.get("annee", 0)), int(item.get("mois", 0))))
        return entries

    async def get_daily_consumptions(
        self, contract_id: str, nb_jours: int = 90
    ) -> dict[str, Any]:
        result = await self._fetch_daily_raw(contract_id, nb_jours)
        if not result["entries"] and nb_jours > 30:
            _LOGGER.debug(
                "Zero donnee journaliere pour %s sur %d jours, tentative sur 30 jours...",
                contract_id,
                nb_jours,
            )
            result = await self._fetch_daily_raw(contract_id, 30)
        return result

    async def _fetch_daily_raw(self, contract_id: str, nb_jours: int) -> dict[str, Any]:
        entries = await self._get_daily_new(contract_id, nb_jours)
        source = "Produits (2026)" if entries else "Aucune"
        if not entries:
            entries, source = await self._get_daily_legacy(contract_id, nb_jours)
        last_date = entries[-1].get("date") if entries else None
        return {
            "entries": self.format_daily_consumptions(entries, contract_id),
            "source": source,
            "nb_entries": len(entries),
            "last_date": last_date,
        }

    async def _get_daily_new(self, contract_id: str, nb_jours: int) -> list[dict]:
        del nb_jours
        try:
            date_fin = datetime.now(timezone.utc)
            date_debut = date_fin.replace(year=date_fin.year - 2)
            params = {
                "dateDebut": date_debut.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "dateFin": date_fin.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
            data = await self._get_produits(
                f"contrats/{contract_id}/consommationsJournalieres", params
            )
            entries = self._parse_daily_response(data)
            if entries:
                entries.sort(key=lambda item: item.get("date", ""))
                _LOGGER.debug(
                    "Donnees journalieres /rest/produits/ OK contrat %s : %d entrees",
                    contract_id,
                    len(entries),
                )
            return entries
        except ApiError as err:
            if "404" in str(err):
                _LOGGER.debug(
                    "Endpoint /rest/produits/.../consommationsJournalieres -> 404 (contrat %s)",
                    contract_id,
                )
            else:
                _LOGGER.debug(
                    "Erreur endpoint journalier /rest/produits/ (contrat %s) : %s",
                    contract_id,
                    err,
                )
            return []
        except Exception as err:
            _LOGGER.debug(
                "Erreur inattendue endpoint journalier /rest/produits/ (contrat %s) : %s",
                contract_id,
                err,
            )
            return []

    async def _get_daily_legacy(
        self, contract_id: str, nb_jours: int
    ) -> tuple[list[dict], str]:
        endpoints = [
            (
                f"/application/rest/interfaces/ael/contrats/{contract_id}"
                f"/consommationsJournalieres?nbJours={nb_jours}",
                "Legacy (Standard)",
            ),
            (
                f"/application/rest/interfaces/ael/contrats/{contract_id}"
                f"/consommationsDailyPeriode?nbJours={nb_jours}",
                "Legacy (Periode)",
            ),
        ]
        for url, source_name in endpoints:
            try:
                data = await self._get(url)
                entries = self._parse_daily_response(data)
                if entries:
                    entries.sort(key=lambda item: item.get("date", ""))
                    _LOGGER.debug(
                        "Donnees journalieres %s OK contrat %s : %d entrees",
                        source_name,
                        contract_id,
                        len(entries),
                    )
                    return entries, source_name
            except ApiError as err:
                _LOGGER.debug(
                    "Endpoint journalier %s non disponible pour %s : %s",
                    source_name,
                    contract_id,
                    err,
                )
            except Exception as err:
                _LOGGER.debug("Erreur sur %s (contrat %s) : %s", source_name, contract_id, err)
        return [], "Aucune"

    async def get_alertes(self) -> list[dict]:
        try:
            data = await self._get(
                "/application/rest/interfaces/ael/contrats/alertes"
                "?expand=infosAlarme,modeleAction,objetMaitre"
            )
            return data if isinstance(data, list) else []
        except Exception as err:
            _LOGGER.debug("Erreur recuperation alertes : %s", err)
            return []

    async def get_date_prochaine_facture(self, contract_id: str) -> str | None:
        try:
            data = await self._do_get(
                f"{BASE_URL}/application/rest/produits/contrats/{contract_id}/dateProchaineFacture"
            )
            if isinstance(data, str):
                return data[:10] if len(data) >= 10 else None
            if isinstance(data, dict):
                raw = data.get("date") or data.get("value") or data.get("dateProchaineFacture")
                return str(raw)[:10] if raw else None
            return None
        except Exception as err:
            _LOGGER.debug("Erreur get_date_prochaine_facture (contrat %s) : %s", contract_id, err)
            return None

    async def get_point_de_service_etendu(self, contract_id: str) -> dict:
        select = (
            "communicabiliteAMM,modeReleve,activite,"
            "dateProchaineReleveReelle,reference,referenceExterne,"
            "niveauDeTension,typeTension,nbCadransCompteur,"
            "periodesActiviteProfil(dateDebut,consommationAnnuelleReference,"
            "profil(libelle))"
        )
        expand = "periodesActiviteProfil(profil,contrat),concession(gestionnaire)"
        try:
            data = await self._do_get(
                f"{BASE_URL}/application/rest/produits/contrats/{contract_id}/pointDeService",
                params={"select": select, "expand": expand},
            )
            if not isinstance(data, dict):
                return {}
            conso_ref = None
            for periode in data.get("periodesActiviteProfil", []):
                value = periode.get("consommationAnnuelleReference")
                if value is not None:
                    try:
                        conso_ref = float(value)
                    except (ValueError, TypeError):
                        pass
            return {
                "communicabilite_amm": data.get("communicabiliteAMM"),
                "mode_releve": data.get("modeReleve"),
                "date_prochaine_releve": (data.get("dateProchaineReleveReelle") or "")[:10]
                or None,
                "niveau_tension": data.get("niveauDeTension"),
                "type_tension": data.get("typeTension"),
                "nb_cadrans": data.get("nbCadransCompteur"),
                "conso_annuelle_ref_m3": conso_ref,
                "reference_pds": data.get("reference"),
            }
        except Exception as err:
            _LOGGER.debug(
                "Erreur get_point_de_service_etendu (contrat %s) : %s", contract_id, err
            )
            return {}

    async def get_interventions(self) -> list[dict]:
        select = (
            "reference,modePlanification,sousType,modeRealisation,"
            "presenceDuClientNecessaire,statut,dateDebutPrevue,dateFinPrevue,"
            "activite,serviceSouscrit(contrat(reference,espaceDeLivraison)),"
            "jourDemande"
        )
        filt = (
            "(modePlanification eq 7)"
            " and (modeRealisation eq 1)"
            " and (presenceDuClientNecessaire eq true)"
            " and (statut eq 4 or statut eq 9 or statut eq 0)"
        )
        try:
            data = await self._do_get(
                f"{BASE_URL}/application/rest/produits/interventions",
                params={
                    "expand": "serviceSouscrit(contrat)",
                    "select": select,
                    "$filter": filt,
                },
            )
            raw_list = data if isinstance(data, list) else data.get(
                "content", data.get("_embedded", {}).get("interventions", [])
            ) if isinstance(data, dict) else []
            result = []
            for item in raw_list:
                try:
                    svc = item.get("serviceSouscrit") or {}
                    contrat = svc.get("contrat") or {}
                    sous_type = item.get("sousType") or {}
                    statut_raw = item.get("statut")
                    date_debut = (item.get("dateDebutPrevue") or "")[:10] or None
                    date_fin = (item.get("dateFinPrevue") or date_debut or "")[:10] or None
                    result.append(
                        {
                            "reference": item.get("reference", ""),
                            "type": sous_type.get("libelle", "")
                            if isinstance(sous_type, dict)
                            else str(sous_type),
                            "statut": str(statut_raw) if statut_raw is not None else "",
                            "date_debut": date_debut,
                            "date_fin": date_fin,
                            "presence_requise": bool(
                                item.get("presenceDuClientNecessaire", False)
                            ),
                            "contrat_ref": contrat.get("reference", ""),
                        }
                    )
                except (KeyError, TypeError, AttributeError):
                    continue
            _LOGGER.debug("Interventions planifiees : %d trouvees", len(result))
            return result
        except Exception as err:
            _LOGGER.debug("Erreur get_interventions : %s", err)
            return []

    async def get_factures(self) -> list[dict]:
        try:
            data = await self._get_produits("factures")
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("content", [])
            return []
        except ApiError as err:
            if "404" in str(err):
                _LOGGER.debug("[EXPERIMENTAL] /rest/produits/factures -> 404")
            else:
                _LOGGER.debug("[EXPERIMENTAL] Erreur get_factures : %s", err)
            return []
        except Exception as err:
            _LOGGER.debug("[EXPERIMENTAL] Erreur inattendue get_factures : %s", err)
            return []

    async def get_courbe_de_charge(
        self, contract_id: str, nb_jours: int = 30
    ) -> list[dict]:
        try:
            date_fin = datetime.now(timezone.utc)
            date_debut = date_fin - timedelta(days=nb_jours)
            params = {
                "dateDebut": date_debut.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "dateFin": date_fin.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
            data = await self._get_interfaces(f"contrats/{contract_id}/courbeDeCharge", params)
            entries = self._parse_daily_response(data)
            if entries:
                entries.sort(key=lambda item: item.get("date", ""))
                _LOGGER.debug(
                    "[EXPERIMENTAL] Courbe de charge OK contrat %s : %d points",
                    contract_id,
                    len(entries),
                )
            return entries
        except ApiError as err:
            if "404" in str(err):
                _LOGGER.debug(
                    "[EXPERIMENTAL] Courbe de charge non dispo contrat %s "
                    "(compteur non communicant ou endpoint absent)",
                    contract_id,
                )
            else:
                _LOGGER.debug(
                    "[EXPERIMENTAL] Erreur get_courbe_de_charge (contrat %s) : %s",
                    contract_id,
                    err,
                )
            return []
        except Exception as err:
            _LOGGER.debug(
                "[EXPERIMENTAL] Erreur inattendue get_courbe_de_charge (contrat %s) : %s",
                contract_id,
                err,
            )
            return []

    async def get_derniere_releve_siamm(self, contract_id: str) -> dict | None:
        try:
            data = await self._get_produits(
                f"contrats/{contract_id}/derniereReleveSIAMM"
                "?expand=grandeursPhysiques(modeleGrandeurPhysique)"
            )
            return data if isinstance(data, dict) else None
        except ApiError as err:
            if "404" in str(err):
                _LOGGER.debug(
                    "[EXPERIMENTAL] Derniere releve SIAMM non dispo (contrat %s)",
                    contract_id,
                )
            else:
                _LOGGER.debug(
                    "[EXPERIMENTAL] Erreur get_derniere_releve_siamm (contrat %s) : %s",
                    contract_id,
                    err,
                )
            return None
        except Exception as err:
            _LOGGER.debug(
                "[EXPERIMENTAL] Erreur inattendue get_derniere_releve_siamm "
                "(contrat %s) : %s",
                contract_id,
                err,
            )
            return None

    async def get_invoice_pdf(self, invoice_ref: str) -> bytes:
        correlation_id = _new_correlation_id()
        await self._ensure_auth(correlation_id=correlation_id)
        url = f"{BASE_URL}/rest/produits/factures/{invoice_ref}/document"
        headers = {"Authorization": f"Bearer {self._auth.access_token}"}
        start = time.perf_counter()
        try:
            async with self._session.get(url, headers=headers) as resp:
                _log_http_event(
                    phase="invoice_pdf",
                    correlation_id=correlation_id,
                    method="GET",
                    url=url,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    status=resp.status,
                )
                if resp.status != 200:
                    raise NetworkError(f"Erreur telechargement PDF ({resp.status})")
                return await resp.read()
        except aiohttp.ClientError as err:
            _log_http_event(
                phase="invoice_pdf",
                correlation_id=correlation_id,
                method="GET",
                url=url,
                duration_ms=(time.perf_counter() - start) * 1000,
                error=err,
            )
            raise NetworkError(f"Erreur reseau lors du telechargement PDF: {err}") from err

    async def get_water_quality(self) -> dict:
        opendata_url = (
            "https://data.grandlyon.com/fr/datapusher/ws/grandlyon"
            "/eau_eau.eauqualite/json/?maxfeatures=1&start=1"
            "&fields=commune,durete,nitrates,chloreresiduel,turbidite,dateanalyse"
        )
        empty: dict = {
            "durete_fh": None,
            "nitrates_mgl": None,
            "chlore_mgl": None,
            "turbidite_ntu": None,
            "commune": None,
            "date_analyse": None,
            "source": "Open Data Metropole de Lyon",
        }
        try:
            async with self._session.get(
                opendata_url,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("[OPEN DATA] Qualite eau -> HTTP %s", resp.status)
                    return empty
                data = json.loads(await resp.text())
            values = data.get("values", [])
            if not values:
                _LOGGER.debug("[OPEN DATA] Qualite eau -> reponse vide")
                return empty
            row = values[0]

            def _safe_float(val: object) -> float | None:
                try:
                    return float(val) if val is not None else None
                except (ValueError, TypeError):
                    return None

            return {
                "durete_fh": _safe_float(row.get("durete")),
                "nitrates_mgl": _safe_float(row.get("nitrates")),
                "chlore_mgl": _safe_float(row.get("chloreresiduel")),
                "turbidite_ntu": _safe_float(row.get("turbidite")),
                "commune": row.get("commune"),
                "date_analyse": (row.get("dateanalyse") or "")[:10] or None,
                "source": "Open Data Metropole de Lyon",
            }
        except aiohttp.ClientError as err:
            _LOGGER.debug("[OPEN DATA] Erreur reseau qualite eau : %s", err)
            return empty
        except Exception as err:
            _LOGGER.debug("[OPEN DATA] Erreur inattendue qualite eau : %s", err)
            return empty

    @staticmethod
    def format_consumptions(raw_entries: list[dict]) -> list[dict]:
        result = []
        for entry in raw_entries:
            try:
                month_raw = int(entry["mois"])
                if not 1 <= month_raw <= 12:
                    continue
                month_idx = month_raw - 1
                year = int(entry["annee"])
                result.append(
                    {
                        "mois_index": month_idx,
                        "mois": MONTHS_FR[month_idx],
                        "annee": year,
                        "label": f"{MONTHS_FR[month_idx]} {year}",
                        "consommation_m3": float(entry.get("consommation", 0)),
                    }
                )
            except (KeyError, ValueError, TypeError):
                _LOGGER.debug("Entree mensuelle ignoree (format inattendu) : %s", entry)
        return result

    @staticmethod
    def format_daily_consumptions(
        raw_entries: list[dict], contract_id: str = "inconnu"
    ) -> list[dict]:
        result = []
        nb_with_conso = 0
        for entry in raw_entries:
            try:
                conso = EauGrandLyonApi._extract_conso(entry)
                normalized: dict[str, Any] = {
                    "date": entry.get("date", ""),
                    "consommation_m3": conso if conso is not None else 0.0,
                }
                if conso is not None:
                    nb_with_conso += 1
                has_exp = False
                for src_key, dst_key in [
                    ("volumeFuiteEstime", "volume_fuite_estime_m3"),
                    ("debitMin", "debit_min_m3h"),
                ]:
                    value = entry.get(src_key)
                    if value is not None:
                        try:
                            normalized[dst_key] = float(value)
                            has_exp = True
                        except (ValueError, TypeError):
                            pass
                index_value = EauGrandLyonApi._extract_index(entry)
                if index_value is not None:
                    normalized["index_m3"] = index_value
                    has_exp = True
                if conso is not None or has_exp:
                    result.append(normalized)
            except (ValueError, TypeError):
                _LOGGER.debug("Entree journaliere ignoree (format inattendu) : %s", entry)
        if raw_entries and nb_with_conso == 0:
            _LOGGER.warning(
                "Le parsing des volumes journaliers pour le contrat %s a echoue : "
                "aucune cle reconnue (consommation, volume, quantite, valeur) "
                "dans les %d entrees recues. Les compteurs d'eau ne seront pas mis a jour.",
                contract_id,
                len(raw_entries),
            )
        elif not raw_entries:
            _LOGGER.warning(
                "Aucune donnee journaliere recue de l'API pour le contrat %s "
                "(le compteur n'est probablement pas compatible Teleo/TIC).",
                contract_id,
            )
        return result

    @staticmethod
    def _extract_index(entry: dict) -> float | None:
        for key in (
            "index",
            "indexCompteur",
            "index_compteur",
            "releve",
            "releveCompteur",
            "volumeCompteur",
            "volume_cumule",
            "consommationCumulee",
            "consommation_cumulee",
        ):
            if key in entry:
                try:
                    value = float(entry[key] or 0)
                except (ValueError, TypeError):
                    continue
                if value > 100000:
                    return round(value / 1000, 3)
                return round(value, 3)
        return None

    @staticmethod
    def _extract_conso(entry: dict) -> float | None:
        for key in ("consommation", "volume", "quantite", "valeur"):
            if key in entry:
                try:
                    return float(entry[key] or 0)
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _parse_daily_response(data: Any) -> list[dict]:
        entries: list[dict] = []
        from_postes = False
        unites: dict = {}
        if isinstance(data, dict):
            unites = data.get("unites") or {}
            if "postes" in data:
                from_postes = True
                for poste in data["postes"]:
                    entries.extend(poste.get("data", []))
            elif "data" in data and isinstance(data["data"], list):
                entries = data["data"]
            elif "consommationsJournalieres" in data and isinstance(
                data["consommationsJournalieres"], list
            ):
                entries = data["consommationsJournalieres"]
        elif isinstance(data, list):
            entries = data
        if not from_postes:
            return entries

        conso_unit = (unites.get("consommation") or "").upper()
        month_offset = _detect_month_offset(entries)
        if not conso_unit:
            conso_unit = _infer_unit_from_magnitude(entries)

        normalized: list[dict] = []
        for entry in entries:
            item = dict(entry)
            if "date" not in item and "annee" in item and "mois" in item:
                try:
                    year = int(item["annee"])
                    month_1based = int(item["mois"]) + month_offset
                    month_1based = max(1, min(12, month_1based))
                    day = int(item.get("jour") or 1)
                    item["date"] = f"{year}-{month_1based:02d}-{day:02d}"
                except (ValueError, TypeError):
                    pass
            if conso_unit == "L" and "consommation" in item:
                try:
                    item["consommation"] = float(item["consommation"]) / 1000.0
                except (ValueError, TypeError):
                    pass
            if "volumeEstimeFuite" in item and "volumeFuiteEstime" not in item:
                item["volumeFuiteEstime"] = item.pop("volumeEstimeFuite")
            normalized.append(item)
        return normalized

    @staticmethod
    def format_factures(raw_factures: list[dict]) -> list[dict]:
        result = []
        for facture in raw_factures:
            try:
                statut_raw = facture.get("statutPaiement") or {}
                date_ed = (facture.get("dateEdition") or "")[:10] or None
                date_ex = (facture.get("dateExigibilite") or "")[:10] or None
                result.append(
                    {
                        "reference": facture.get("reference", ""),
                        "date_edition": date_ed,
                        "date_exigibilite": date_ex,
                        "montant_ht": float(facture.get("montantHT", 0) or 0),
                        "montant_ttc": float(facture.get("montantTTC", 0) or 0),
                        "volume_m3": float(facture.get("volume", 0) or 0),
                        "statut_paiement": statut_raw.get("libelle", ""),
                        "contrat_id": (facture.get("contrat") or {}).get("id", ""),
                    }
                )
            except (KeyError, ValueError, TypeError):
                _LOGGER.debug("Facture ignoree (format inattendu) : %s", facture)
        result.sort(key=lambda item: item.get("date_edition") or "", reverse=True)
        return result

    @staticmethod
    def parse_contract_details(raw: dict) -> dict:
        ref = raw.get("reference", "")
        statut = (raw.get("statutExtrait") or {}).get("libelle", "")
        date_effet_raw = raw.get("dateEffet") or ""
        date_echeance_raw = raw.get("dateEcheance") or ""
        date_effet = date_effet_raw[:10] if date_effet_raw else None
        date_echeance = date_echeance_raw[:10] if date_echeance_raw else None
        condition = raw.get("conditionPaiement") or {}
        compte = condition.get("compteClient") or {}
        solde_obj = compte.get("solde") or {}
        try:
            solde_eur = float(solde_obj.get("value", 0))
        except (ValueError, TypeError):
            solde_eur = 0.0
        services = raw.get("servicesSouscrits") or []
        calibre_compteur = ""
        usage = ""
        nombre_habitants = ""
        if services:
            service = services[0]
            calibre_compteur = (service.get("calibreCompteur") or {}).get("libelle", "")
            usage = (service.get("usage") or {}).get("libelle", "")
            nb_h = service.get("nombreHabitants") or {}
            nombre_habitants = nb_h.get("libelle", "") if nb_h else ""
        eds = raw.get("espaceDeLivraison") or {}
        point_releve = raw.get("pointDeReleve") or {}
        module = (point_releve.get("moduleRadio") or {})
        signal_pct = None
        if "niveauSignal" in module:
            try:
                signal_pct = float(module["niveauSignal"])
            except (ValueError, TypeError):
                pass
        battery_ok = module["etatPile"] == "OK" if "etatPile" in module else None
        return {
            "id": raw.get("id", ""),
            "reference": ref,
            "statut": statut,
            "teleo_compatible": bool(module),
            "signal_pct": signal_pct,
            "battery_ok": battery_ok,
            "date_effet": date_effet,
            "date_echeance": date_echeance,
            "solde_eur": solde_eur,
            "mensualise": bool(condition.get("mensualise", False)),
            "mode_paiement": (condition.get("modePaiement") or {}).get("libelle", ""),
            "calibre_compteur": calibre_compteur,
            "usage": usage,
            "nombre_habitants": nombre_habitants,
            "reference_pds": eds.get("reference", ""),
        }

    @staticmethod
    def parse_siamm_index(data: dict) -> float | None:
        if not data or not isinstance(data, dict):
            return None
        for gp in data.get("grandeursPhysiques", []):
            modele = gp.get("modeleGrandeurPhysique") or {}
            if modele.get("code") == "VOLUME":
                try:
                    return float(gp.get("valeur", 0))
                except (ValueError, TypeError):
                    pass
        return None
