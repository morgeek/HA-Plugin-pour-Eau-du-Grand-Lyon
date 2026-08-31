"""Main API client for Eau du Grand Lyon."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import aiohttp

from .auth import (
    ApiError,
    AuthenticationError,
    EauGrandLyonAuth,
    HttpError,
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

type JsonObject = dict[str, Any]

_LOGGER = logging.getLogger(__name__)


# Synonymes de clé pour l'index compteur selon le format d'API (postes vs legacy).
_INDEX_KEYS = (
    "index",
    "indexCompteur",
    "index_compteur",
    "releve",
    "releveCompteur",
    "volumeCompteur",
    "volume_cumule",
    "consommationCumulee",
    "consommation_cumulee",
)


def _is_litre_unit(value: Any) -> bool:
    return str(value or "").strip().lower() in {"l", "litre", "litres", "liter", "liters"}


def _is_litre_rate_unit(value: Any) -> bool:
    normalized = str(value or "").strip().lower().replace(" ", "")
    return normalized in {"l/h", "litre/h", "litres/h", "liter/h", "liters/h"}


def _infer_unit_from_magnitude(entries: list[object]) -> str:
    values: list[float] = []
    for entry in entries[:50]:
        if not isinstance(entry, dict):
            continue
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
        self._auth = EauGrandLyonAuth(session, email, password)
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

    @staticmethod
    def _parse_json(text: str, method: str, url: str) -> Any:
        """Parse une réponse JSON, en convertissant un corps malformé en ApiError.

        Un HTTP 200 renvoyant une page HTML (WAF, portail de maintenance) ferait
        sinon remonter un json.JSONDecodeError brut jusqu'au except générique du
        coordinator, court-circuitant retry + cache offline.
        """
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError) as err:
            raise ApiError(f"Réponse non-JSON sur {method} {url}: {err}") from err

    @staticmethod
    async def _read_response_body(
        resp: aiohttp.ClientResponse, accepted_statuses: frozenset[int]
    ) -> tuple[int, str, str]:
        """Return response metadata and text without imposing a payload format."""
        if resp.status not in accepted_statuses:
            resp.raise_for_status()
        content_type = str(getattr(resp, "content_type", "") or "")
        return resp.status, content_type, await resp.text()

    async def _request_body(
        self,
        method: str,
        url: str,
        *,
        accepted_statuses: frozenset[int] = frozenset(),
        log_response_errors: bool = True,
        **kwargs: Any,
    ) -> tuple[int, str, str]:
        """Run an authenticated request and return its unparsed response body."""
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
                    async with self._session.request(method, url, headers=headers, **kwargs) as retry_resp:
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
                            raise WafBlockedError(f"WAF 403 sur {method} {url} (apres re-auth).")
                        if retry_resp.status == 401:
                            raise AuthenticationError(f"Identifiants refuses sur {method} {url}.")
                        return await self._read_response_body(retry_resp, accepted_statuses)
                if resp.status == 403:
                    raise WafBlockedError(f"WAF 403 sur {method} {url}.")
                return await self._read_response_body(resp, accepted_statuses)
        except (WafBlockedError, AuthenticationError, ApiError):
            raise
        except (TimeoutError, asyncio.TimeoutError) as err:
            # aiohttp.ClientTimeout lève asyncio.TimeoutError, qui n'est PAS un
            # aiohttp.ClientError — sans ce bloc il remonterait brut jusqu'au
            # except générique du coordinator et court-circuiterait retry + cache.
            _LOGGER.debug(
                "api_request_timeout cid=%s method=%s url=%s",
                correlation_id,
                method,
                url,
            )
            raise NetworkError(f"Timeout sur {method} {url}: {err}") from err
        except aiohttp.ClientResponseError as err:
            if log_response_errors:
                _LOGGER.debug(
                    "api_request_failed cid=%s method=%s url=%s status=%s error=%s",
                    correlation_id,
                    method,
                    url,
                    err.status,
                    type(err).__name__,
                )
            raise HttpError(err.status, method, url, err.message) from err
        except aiohttp.ClientError as err:
            _LOGGER.debug(
                "api_request_failed cid=%s method=%s url=%s error=%s",
                correlation_id,
                method,
                url,
                type(err).__name__,
            )
            raise NetworkError(f"Erreur reseau sur {method} {url}: {err}") from err

    async def _request(self, method: str, url: str, *, log_response_errors: bool = True, **kwargs: Any) -> Any:
        """Run a request whose response is required to contain valid JSON."""
        _status, _content_type, text = await self._request_body(
            method,
            url,
            log_response_errors=log_response_errors,
            **kwargs,
        )
        return self._parse_json(text, method, url)

    async def _request_text(
        self,
        method: str,
        url: str,
        *,
        accepted_statuses: frozenset[int] = frozenset(),
        **kwargs: Any,
    ) -> tuple[int, str, str]:
        """Run a request whose optional payload may be JSON or plain text."""
        return await self._request_body(
            method,
            url,
            accepted_statuses=accepted_statuses,
            **kwargs,
        )

    async def _do_get(self, url: str, params: JsonObject | None = None, *, log_response_errors: bool = True) -> Any:
        return await self._request("GET", url, params=params, log_response_errors=log_response_errors)

    async def _do_post(self, url: str, body: JsonObject | None = None) -> Any:
        return await self._request("POST", url, json=body or {})

    async def _get(self, path: str, params: JsonObject | None = None) -> Any:
        return await self._do_get(f"{BASE_URL}{path}", params)

    async def _post(self, path: str, body: JsonObject | None = None) -> Any:
        return await self._do_post(f"{BASE_URL}{path}", body)

    async def _get_produits(
        self,
        sub_path: str,
        params: JsonObject | None = None,
        *,
        log_response_errors: bool = True,
    ) -> Any:
        return await self._do_get(
            f"{PRODUITS_BASE}/{sub_path.lstrip('/')}",
            params,
            log_response_errors=log_response_errors,
        )

    async def _get_interfaces(self, sub_path: str, params: JsonObject | None = None) -> Any:
        return await self._do_get(f"{INTERFACES_AEL_BASE}/{sub_path.lstrip('/')}", params)

    async def get_contracts(self) -> list[JsonObject]:
        data = await self._post(
            f"/application/rest/interfaces/ael/contrats/rechercher"
            f"?expand={CONTRACTS_EXPAND}&select={CONTRACTS_SELECT}"
        )
        if not isinstance(data, (dict, list)):
            _LOGGER.warning("Reponse inattendue pour get_contracts (type=%s)", type(data).__name__)
            return []
        contracts = data.get("content", data) if isinstance(data, dict) else data
        return list(contracts) if contracts else []

    async def get_monthly_consumptions(self, contract_id: str, nb_jours: int = 1095) -> list[JsonObject]:
        """Fetch monthly consumptions with optional history parameter (36 months default).

        Args:
            contract_id: The contract ID
            nb_jours: Number of days of history to retrieve (default 1095 = 36 months)
        """
        params = {"nbJours": nb_jours} if nb_jours > 0 else {}
        data = await self._get(
            f"/application/rest/interfaces/ael/contrats/{contract_id}/consommationsMensuelles",
            params=params if params else None,
        )
        entries: list[JsonObject] = []
        if not isinstance(data, dict):
            _LOGGER.warning(
                "Reponse inattendue pour consommationsMensuelles (type=%s, nb_jours=%d)",
                type(data).__name__,
                nb_jours,
            )
            return entries
        for poste in data.get("postes", []):
            entries.extend(poste.get("data", []))
        entries.sort(key=lambda item: (int(item.get("annee", 0)), int(item.get("mois", 0))))
        _LOGGER.debug(
            "Monthly consumptions OK contrat %s (nb_jours=%d): %d mois recueillis",
            contract_id,
            nb_jours,
            len(entries),
        )
        return entries

    async def get_daily_consumptions(self, contract_id: str, nb_jours: int = 90) -> JsonObject:
        result = await self._fetch_daily_raw(contract_id, nb_jours)
        if not result["entries"] and nb_jours > 30:
            _LOGGER.debug(
                "Zero donnee journaliere pour %s sur %d jours, tentative sur 30 jours...",
                contract_id,
                nb_jours,
            )
            result = await self._fetch_daily_raw(contract_id, 30)
        return result

    async def get_alerte_surconsommation(self, contract_id: str) -> JsonObject:
        """Recupere les seuils d'alerte surconsommation configures cote serveur.

        Trois endpoints (espace client, compteur communicant) :
          - seuilAlerteSurconsommation/journaliere -> {"seuilAlerteSurconsommationJournaliere": <m3/jour>}
          - seuilAlerteSurconsommation/mensuelle   -> {"seuilAlerteSurconsommationMensuelle": <m3/mois>}
          - abonneAlerteFuite                        -> booleen (abonnement alerte fuite)

        Chaque appel est protege individuellement : un contrat sans ces services
        renvoie simplement None sur la cle concernee, sans casser le cycle.
        """

        async def _safe(sub_path: str, label: str) -> Any:
            try:
                return await self._get_produits(f"contrats/{contract_id}/{sub_path}", log_response_errors=False)
            except HttpError as err:
                if err.status != 404:
                    raise
                _LOGGER.debug("Endpoint %s indisponible (contrat %s) : %s", label, contract_id, err)
                return None

        raw_jour = await _safe("seuilAlerteSurconsommation/journaliere", "seuil journalier")
        raw_mois = await _safe("seuilAlerteSurconsommation/mensuelle", "seuil mensuel")
        raw_abonne = await _safe("abonneAlerteFuite", "abonnement alerte fuite")

        def _num(payload: Any, key: str) -> float | None:
            value = payload.get(key) if isinstance(payload, dict) else payload
            try:
                return round(float(value), 3) if value is not None else None
            except (ValueError, TypeError):
                return None

        abonne: bool | None = None
        if isinstance(raw_abonne, bool):
            abonne = raw_abonne
        elif isinstance(raw_abonne, dict):
            for cle in ("abonne", "value", "valeur", "actif"):
                if isinstance(raw_abonne.get(cle), bool):
                    abonne = raw_abonne[cle]
                    break

        return {
            "seuil_surconso_jour_m3": _num(raw_jour, "seuilAlerteSurconsommationJournaliere"),
            "seuil_surconso_mois_m3": _num(raw_mois, "seuilAlerteSurconsommationMensuelle"),
            "abonne_alerte_fuite": abonne,
        }

    async def _fetch_daily_raw(self, contract_id: str, nb_jours: int) -> JsonObject:
        entries = await self._get_daily_new(contract_id, nb_jours)
        source = "Produits (2026)" if entries else "Aucune"
        if not entries:
            entries, source = await self._get_daily_legacy(contract_id, nb_jours)
        formatted_entries = self.format_daily_consumptions(entries, contract_id)
        last_date = formatted_entries[-1].get("date") if formatted_entries else None
        return {
            "entries": formatted_entries,
            "source": source,
            "nb_entries": len(formatted_entries),
            "last_date": last_date,
        }

    async def _get_daily_new(self, contract_id: str, nb_jours: int) -> list[JsonObject]:
        try:
            date_fin = datetime.now(timezone.utc)
            date_debut = date_fin - timedelta(days=nb_jours)
            params = {
                "dateDebut": date_debut.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "dateFin": date_fin.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
            data = await self._get_produits(f"contrats/{contract_id}/consommationsJournalieres", params)
            entries = self._parse_daily_response(data)
            if entries:
                entries.sort(key=lambda item: item.get("date", ""))
                _LOGGER.debug(
                    "Donnees journalieres /rest/produits/ OK contrat %s : %d entrees",
                    contract_id,
                    len(entries),
                )
            return entries
        except HttpError as err:
            if err.status != 404:
                raise
            _LOGGER.debug(
                "Endpoint /rest/produits/.../consommationsJournalieres -> 404 (contrat %s)",
                contract_id,
            )
            return []

    async def _get_daily_legacy(self, contract_id: str, nb_jours: int) -> tuple[list[JsonObject], str]:
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
            except HttpError as err:
                if err.status != 404:
                    raise
                _LOGGER.debug(
                    "Endpoint journalier %s non disponible pour %s : %s",
                    source_name,
                    contract_id,
                    err,
                )
        return [], "Aucune"

    async def get_alertes(self) -> list[JsonObject]:
        data = await self._get(
            "/application/rest/interfaces/ael/contrats/alertes" "?expand=infosAlarme,modeleAction,objetMaitre"
        )
        return data if isinstance(data, list) else []

    async def get_date_prochaine_facture(self, contract_id: str) -> str | None:
        """Return the optional next invoice date from JSON or plain text."""
        url = f"{BASE_URL}/application/rest/produits/contrats/{contract_id}/dateProchaineFacture"
        status, content_type, text = await self._request_text(
            "GET",
            url,
            accepted_statuses=frozenset({204, 404}),
        )
        if status in (204, 404) or not text.strip():
            return None

        stripped = text.strip()
        payload: Any = stripped
        try:
            payload = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            # Plain ISO text is a documented provider variant for this endpoint.
            pass

        if isinstance(payload, dict):
            raw = (
                payload.get("dateProchaineFacture")
                or payload.get("date")
                or payload.get("value")
                or payload.get("valeur")
            )
        elif isinstance(payload, str):
            raw = payload
        else:
            raw = None

        candidate = str(raw or "").strip()
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[Tt ].*)?", candidate)
        if match:
            try:
                datetime.strptime(match.group(1), "%Y-%m-%d")
                return match.group(1)
            except ValueError:
                pass

        _LOGGER.debug(
            "Optional next invoice date is unusable for contract %s (status=%s, content_type=%s)",
            contract_id,
            status,
            content_type or "unknown",
        )
        return None

    async def get_point_de_service_etendu(self, contract_id: str) -> JsonObject:
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
                "date_prochaine_releve": (data.get("dateProchaineReleveReelle") or "")[:10] or None,
                "niveau_tension": data.get("niveauDeTension"),
                "type_tension": data.get("typeTension"),
                "nb_cadrans": data.get("nbCadransCompteur"),
                "conso_annuelle_ref_m3": conso_ref,
                "reference_pds": data.get("reference"),
            }
        except HttpError as err:
            if err.status != 404:
                raise
            _LOGGER.debug("Erreur get_point_de_service_etendu (contrat %s) : %s", contract_id, err)
            return {}

    async def get_interventions(self) -> list[JsonObject]:
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
            raw_list = (
                data
                if isinstance(data, list)
                else (
                    data.get("content", data.get("_embedded", {}).get("interventions", []))
                    if isinstance(data, dict)
                    else []
                )
            )
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
                            "type": sous_type.get("libelle", "") if isinstance(sous_type, dict) else str(sous_type),
                            "statut": str(statut_raw) if statut_raw is not None else "",
                            "date_debut": date_debut,
                            "date_fin": date_fin,
                            "presence_requise": bool(item.get("presenceDuClientNecessaire", False)),
                            "contrat_ref": contrat.get("reference", ""),
                        }
                    )
                except (KeyError, TypeError, AttributeError):
                    continue
            _LOGGER.debug("Interventions planifiees : %d trouvees", len(result))
            return result
        except HttpError as err:
            if err.status != 404:
                raise
            _LOGGER.debug("get_interventions failed: %s", err)
            return []

    async def get_factures(self) -> list[JsonObject]:
        try:
            data = await self._get_produits("factures")
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                content = data.get("content", [])
                return content if isinstance(content, list) else []
            return []
        except HttpError as err:
            if err.status != 404:
                raise
            _LOGGER.debug("[EXPERIMENTAL] /rest/produits/factures -> 404")
            return []

    async def get_courbe_de_charge(self, contract_id: str, nb_jours: int = 30) -> list[JsonObject]:
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
        except HttpError as err:
            if err.status != 404:
                raise
            _LOGGER.debug(
                "[EXPERIMENTAL] Courbe de charge non dispo contrat %s " "(compteur non communicant ou endpoint absent)",
                contract_id,
            )
            return []

    async def get_derniere_releve_siamm(self, contract_id: str) -> JsonObject | None:
        try:
            data = await self._get_produits(
                f"contrats/{contract_id}/derniereReleveSIAMM",
                params={"expand": "grandeursPhysiques(modeleGrandeurPhysique)"},
                log_response_errors=False,
            )
            return data if isinstance(data, dict) else None
        except HttpError as err:
            if err.status in (404, 500):
                _LOGGER.debug(
                    "[EXPERIMENTAL] Derniere releve SIAMM non dispo (contrat %s)",
                    contract_id,
                )
                return None
            raise

    async def get_invoice_pdf(self, invoice_id: str) -> bytes:
        """Télécharge le duplicata PDF d'une facture à partir de son identifiant API.

        Le portail officiel utilise ``/factures/{id}/duplicata``. La référence
        lisible de la facture n'est pas acceptée par cette route.
        """
        correlation_id = _new_correlation_id()
        await self._ensure_auth(correlation_id=correlation_id)
        url = f"{PRODUITS_BASE}/factures/{invoice_id}/duplicata"
        start = time.perf_counter()

        async def _download() -> tuple[int, bytes]:
            headers = {
                "Authorization": f"Bearer {self._auth.access_token}",
                "Accept": "application/pdf,application/octet-stream",
            }
            async with self._session.get(url, headers=headers) as resp:
                status = resp.status
                body = await resp.read() if status == 200 else b""
                return status, body

        try:
            status, body = await _download()
            if status == 401:
                # Token expiré : ré-authentifier puis réessayer (comme _request).
                _LOGGER.debug("invoice_pdf_reauth cid=%s id=%s", correlation_id, invoice_id)
                await self._auth.authenticate(correlation_id=correlation_id)
                status, body = await _download()
            _log_http_event(
                phase="invoice_pdf",
                correlation_id=correlation_id,
                method="GET",
                url=url,
                duration_ms=(time.perf_counter() - start) * 1000,
                status=status,
            )
            if status == 403:
                raise WafBlockedError(f"WAF 403 sur telechargement PDF {invoice_id}.")
            if status != 200:
                raise NetworkError(f"Erreur telechargement PDF ({status})")
            if not body.startswith(b"%PDF-"):
                raise NetworkError("La réponse du portail n'est pas un document PDF valide")
            return body
        except (WafBlockedError, AuthenticationError):
            raise
        except (TimeoutError, asyncio.TimeoutError) as err:
            raise NetworkError(f"Timeout telechargement PDF: {err}") from err
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

    async def get_water_quality(self, commune: str | None = None) -> JsonObject:
        """Qualité de l'eau depuis l'Open Data Métropole de Lyon.

        Sans `commune`, retourne la première mesure du jeu de données (commune
        arbitraire du réseau). Avec `commune`, filtre côté client sur le nom.
        """
        maxfeatures = 1000 if commune else 1
        opendata_url = (
            "https://data.grandlyon.com/fr/datapusher/ws/grandlyon"
            f"/eau_eau.eauqualite/json/?maxfeatures={maxfeatures}&start=1"
            "&fields=commune,durete,nitrates,chloreresiduel,turbidite,dateanalyse"
        )
        empty: JsonObject = {
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
            if commune:
                wanted = commune.strip().casefold()
                match = next(
                    (r for r in values if wanted in str(r.get("commune") or "").casefold()),
                    None,
                )
                if match is not None:
                    row = match
                else:
                    _LOGGER.warning(
                        "[OPEN DATA] Commune '%s' introuvable dans les mesures qualite eau — "
                        "premiere mesure du reseau utilisee (voir l'attribut 'commune')",
                        commune,
                    )

            def _safe_float(val: Any) -> float | None:
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
        except (aiohttp.ClientError, TimeoutError, asyncio.TimeoutError) as err:
            _LOGGER.debug("[OPEN DATA] Network error fetching water quality: %s", err)
            return empty
        except (json.JSONDecodeError, ValueError, TypeError, KeyError) as err:
            _LOGGER.debug("[OPEN DATA] Invalid water quality response: %s", err)
            return empty

    @staticmethod
    def format_consumptions(raw_entries: list[JsonObject]) -> list[JsonObject]:
        result = []
        for entry in raw_entries:
            try:
                month_raw = int(entry["mois"])
                # L'API Téléo envoie les mois en base-0 (0=Janvier … 11=Décembre).
                # Ancienne validation 1-12 sautait Janvier (mois=0) et décalait tous
                # les autres d'un rang (Décembre mois=11 → MONTHS_FR[10]="Novembre").
                if not 0 <= month_raw <= 11:
                    continue
                month_idx = month_raw  # déjà base-0, pas de soustraction
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
    def format_daily_consumptions(raw_entries: list[JsonObject], contract_id: str = "inconnu") -> list[JsonObject]:
        result = []
        nb_with_conso = 0
        for entry in raw_entries:
            try:
                conso = EauGrandLyonApi._extract_conso(entry)
                normalized: JsonObject = {
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
    def _extract_index(entry: JsonObject) -> float | None:
        for key in _INDEX_KEYS:
            if key in entry:
                try:
                    value = float(entry[key] or 0)
                except (ValueError, TypeError):
                    continue
                # Filet de sécurité UNIQUEMENT si l'unité n'a pas été déclarée par
                # l'API (_parse_daily_response convertit déjà via `unites.index`
                # quand disponible — voir régression ci-dessous). Une magnitude
                # improbable en m³ (index cumulé > 100 000 m³) est alors supposée
                # être en litres. Ce seuil est peu fiable pour un petit index
                # (compteur récent) : c'est pourquoi la conversion basée sur
                # `unites` est la voie primaire, celle-ci n'est qu'un repli.
                if value > 100000:
                    return round(value / 1000, 3)
                return round(value, 3)
        return None

    @staticmethod
    def _extract_conso(entry: JsonObject) -> float | None:
        for key in ("consommation", "volume", "quantite", "valeur"):
            if key in entry:
                try:
                    return float(entry[key] or 0)
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _parse_daily_response(data: Any) -> list[JsonObject]:
        entries: list[object] = []
        from_postes = False
        unites: JsonObject = {}
        if isinstance(data, dict):
            raw_unites = data.get("unites")
            unites = raw_unites if isinstance(raw_unites, dict) else {}
            if isinstance(data.get("postes"), list):
                from_postes = True
                for poste in data["postes"]:
                    if not isinstance(poste, dict) or not isinstance(poste.get("data"), list):
                        continue
                    entries.extend(poste["data"])
            elif "data" in data and isinstance(data["data"], list):
                entries = data["data"]
            elif "consommationsJournalieres" in data and isinstance(data["consommationsJournalieres"], list):
                entries = data["consommationsJournalieres"]
        elif isinstance(data, list):
            entries = data
        if not from_postes:
            return cast(list[JsonObject], entries)

        conso_unit = (unites.get("consommation") or "").upper()
        # The postes/annee/mois/jour format always uses 0-indexed months (0=January)
        month_offset = 1
        if not conso_unit:
            conso_unit = _infer_unit_from_magnitude(entries)

        # Les champs volumeEstimeFuite (unite "l") et debitMin (unite "L/h") sont
        # renvoyes en litres par l'API. Ils doivent etre convertis en m3 (et m3/h)
        # pour rester coherents avec les cles *_m3 / *_m3h produites en aval —
        # sinon les capteurs fuite/debit affichent des valeurs 1000x trop grandes.
        consommation_en_litres = _is_litre_unit(unites.get("consommation"))
        fuite_en_litres = _is_litre_unit(unites.get("volumeEstimeFuite"))
        debit_en_litres = _is_litre_rate_unit(unites.get("debitMin"))
        # Index compteur (unites.index = "l") : sans cette conversion, un index
        # inférieur à 100 000 L (compteur récent / faible cumul) échappe au filet
        # de sécurité par magnitude de _extract_index et reste affiché en litres
        # sous l'étiquette m³ (ex. compteur à 20,990 m³ affiché "20990.000 m³").
        index_en_litres = _is_litre_unit(unites.get("index"))

        normalized: list[JsonObject] = []
        for entry in entries:
            if not isinstance(entry, dict):
                _LOGGER.debug("Entree journaliere ignoree (format inattendu) : %s", entry)
                continue
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
            if (conso_unit == "L" or consommation_en_litres) and "consommation" in item:
                try:
                    item["consommation"] = float(item["consommation"]) / 1000.0
                except (ValueError, TypeError):
                    pass
            if "volumeEstimeFuite" in item and "volumeFuiteEstime" not in item:
                item["volumeFuiteEstime"] = item.pop("volumeEstimeFuite")
            if fuite_en_litres and item.get("volumeFuiteEstime") is not None:
                try:
                    item["volumeFuiteEstime"] = float(item["volumeFuiteEstime"]) / 1000.0
                except (ValueError, TypeError):
                    pass
            if debit_en_litres and item.get("debitMin") is not None:
                try:
                    item["debitMin"] = float(item["debitMin"]) / 1000.0
                except (ValueError, TypeError):
                    pass
            if index_en_litres:
                for key in _INDEX_KEYS:
                    if item.get(key) is not None:
                        try:
                            item[key] = float(item[key]) / 1000.0
                        except (ValueError, TypeError):
                            pass
                        break
            normalized.append(item)
        return normalized

    @staticmethod
    def format_factures(raw_factures: list[JsonObject]) -> list[JsonObject]:
        result = []
        for facture in raw_factures:
            try:
                statut_raw = facture.get("statutPaiement") or {}
                date_ed = (facture.get("dateEdition") or "")[:10] or None
                date_ex = (facture.get("dateExigibilite") or "")[:10] or None
                result.append(
                    {
                        "id": facture.get("id", ""),
                        "reference": facture.get("reference", ""),
                        "date_edition": date_ed,
                        "date_exigibilite": date_ex,
                        "montant_ht": float(facture.get("montantHT", 0) or 0),
                        "montant_ttc": float(facture.get("montantTTC", 0) or 0),
                        "volume_m3": float(facture.get("volume", 0) or 0),
                        "statut_paiement": statut_raw.get("libelle", ""),
                        "contrat_id": (facture.get("contrat") or {}).get("id", ""),
                        "telechargeable": facture.get("telechargeable") is not False,
                    }
                )
            except (AttributeError, KeyError, ValueError, TypeError):
                _LOGGER.debug("Skipping invoice (unexpected format): %s", facture)
        result.sort(key=lambda item: item.get("date_edition") or "", reverse=True)
        return result

    @staticmethod
    def parse_contract_details(raw: JsonObject) -> JsonObject:
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
        module = point_releve.get("moduleRadio") or {}
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
    def parse_siamm_index(data: JsonObject) -> float | None:
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
