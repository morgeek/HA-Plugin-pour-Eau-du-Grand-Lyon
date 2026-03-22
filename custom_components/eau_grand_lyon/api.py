"""Client API pour Eau du Grand Lyon (authentification PKCE + données contrat)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://agence.eaudugrandlyon.com"
CLIENT_ID = "kwnOk0B_aqlOI6p_GVxrbf6"
REDIRECT_URI = f"{BASE_URL}/autorisation-callback.html"
LOGIN_URL = f"{BASE_URL}/application/auth/externe/authentification"
AUTHORIZE_URL = f"{BASE_URL}/application/auth/authorize-internet"
TOKEN_URL = f"{BASE_URL}/application/auth/tokenUtilisateurInternet"

# code_verifier non-standard mais conforme au serveur (PKCE simplifié)
CODE_VERIFIER = "5"

MONTHS_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]

# Headers minimalistes — PAS de Sec-Fetch-* : le WAF retourne 403 si présents
BROWSER_NAV_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Champs demandés lors du rechercher de contrats — couvre toutes les données utiles
_CONTRACTS_SELECT = (
    "id,reference,statutExtrait,dateEffet,dateEcheance,"
    "conditionPaiement(compteClient(solde),mensualise,modePaiement),"
    "servicesSouscrits(statut,usage,calibreCompteur,nombreHabitants),"
    "espaceDeLivraison(reference)"
)
_CONTRACTS_EXPAND = "conditionPaiement(compteClient),servicesSouscrits,espaceDeLivraison"

# Retry parameters
_RETRY_DELAYS = (5.0, 30.0, 90.0)  # délais en secondes entre les tentatives


class AuthenticationError(Exception):
    """Erreur d'authentification (identifiants invalides ou flux OAuth échoué)."""


class WafBlockedError(Exception):
    """Le WAF Apache a bloqué la requête (HTTP 403).

    Causes possibles : trop de requêtes en peu de temps, ou présence de
    headers Sec-Fetch-* dans la requête.
    """


class ApiError(Exception):
    """Erreur générique lors d'un appel API (hors auth et WAF)."""


class NetworkError(Exception):
    """Erreur réseau / timeout lors d'un appel API."""


def _compute_code_challenge(verifier: str) -> str:
    """Calcule le code_challenge PKCE (SHA-256 en base64url)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class EauGrandLyonApi:
    """Client pour l'API Eau du Grand Lyon avec authentification PKCE OAuth2."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._access_token: str | None = None

    @property
    def access_token(self) -> str | None:
        return self._access_token

    # ------------------------------------------------------------------
    # Authentification
    # ------------------------------------------------------------------

    async def authenticate(self) -> str:
        """Effectue l'authentification complète et retourne l'access token.

        Flux (rétro-ingénierie du bundle Angular) :
        1. POST /auth/externe/authentification  {username, password, client_id}
           → 200 + cookie de session HttpOnly
        2. GET  /auth/authorize-internet?code_challenge=...
           → 302 → /autorisation-callback.html?code=...
        3. POST /auth/tokenUtilisateurInternet  {grant_type=authorization_code, ...}
           → {"access_token": "..."}
        """
        # Étape 1 : Login → cookie de session
        try:
            async with self._session.post(
                LOGIN_URL,
                data={
                    "username": self._email,
                    "password": self._password,
                    "client_id": CLIENT_ID,
                },
                headers={
                    **BROWSER_NAV_HEADERS,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            ) as resp:
                login_body = await resp.text()
                login_status = resp.status
        except aiohttp.ClientError as err:
            raise NetworkError(f"Impossible de joindre le serveur: {err}") from err

        if login_status == 401:
            raise AuthenticationError(
                "Identifiants incorrects. Vérifiez votre email et mot de passe."
            )
        if login_status == 403:
            raise WafBlockedError(
                "Le WAF a bloqué la requête de login (HTTP 403). "
                "Attendez quelques minutes avant de réessayer."
            )
        if login_status not in (200, 204):
            raise ApiError(
                f"Login échoué ({login_status}): {login_body[:200]}"
            )

        _LOGGER.debug("Login OK (status=%s), récupération du code PKCE...", login_status)

        # Étape 2 : code d'autorisation
        code_challenge = _compute_code_challenge(CODE_VERIFIER)
        params = {
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "client_id": CLIENT_ID,
        }
        try:
            async with self._session.get(
                AUTHORIZE_URL,
                params=params,
                headers=BROWSER_NAV_HEADERS,
                allow_redirects=True,
            ) as resp:
                if resp.status == 403:
                    raise WafBlockedError(
                        "Le WAF a bloqué la requête authorize-internet (HTTP 403)."
                    )
                final_url = str(resp.url)
        except WafBlockedError:
            raise
        except aiohttp.ClientError as err:
            raise NetworkError(f"Erreur réseau sur /authorize-internet: {err}") from err

        code = self._extract_code_from_url(final_url)
        if not code:
            raise AuthenticationError(
                f"Pas de code d'autorisation dans l'URL de callback: {final_url[:200]}"
            )

        # Étape 3 : échange code → token
        return await self._exchange_code(code)

    @staticmethod
    def _extract_code_from_url(url: str) -> str | None:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        code = qs.get("code", [None])[0]
        if not code:
            frag = parse_qs(parsed.fragment)
            code = frag.get("code", [None])[0]
        return code

    async def _exchange_code(self, code: str) -> str:
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": CODE_VERIFIER,
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
        }
        try:
            async with self._session.post(
                TOKEN_URL,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                if resp.status == 403:
                    raise WafBlockedError(
                        "Le WAF a bloqué l'échange de token (HTTP 403)."
                    )
                if resp.status != 200:
                    body = await resp.text()
                    raise AuthenticationError(
                        f"Échange de token échoué ({resp.status}): {body[:200]}"
                    )
                result: dict = await resp.json(content_type=None)
        except (WafBlockedError, AuthenticationError):
            raise
        except aiohttp.ClientError as err:
            raise NetworkError(f"Requête token échouée: {err}") from err

        if "access_token" not in result:
            raise AuthenticationError(f"Pas d'access_token dans la réponse: {result}")

        self._access_token = result["access_token"]
        _LOGGER.debug("Authentification réussie pour %s", self._email)
        return self._access_token

    # ------------------------------------------------------------------
    # Appels API internes
    # ------------------------------------------------------------------

    async def _ensure_auth(self) -> None:
        if not self._access_token:
            await self.authenticate()

    async def _get(self, path: str) -> Any:
        """GET authentifié avec retry sur 401 (token expiré)."""
        await self._ensure_auth()
        url = f"{BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        try:
            async with self._session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    _LOGGER.debug("Token expiré, ré-authentification...")
                    await self.authenticate()
                    headers = {"Authorization": f"Bearer {self._access_token}"}
                    async with self._session.get(url, headers=headers) as resp2:
                        if resp2.status == 403:
                            raise WafBlockedError(
                                f"WAF 403 sur GET {path} (après ré-auth)."
                            )
                        resp2.raise_for_status()
                        return await resp2.json(content_type=None)
                if resp.status == 403:
                    raise WafBlockedError(f"WAF 403 sur GET {path}.")
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except (WafBlockedError, AuthenticationError):
            raise
        except aiohttp.ClientResponseError as err:
            raise ApiError(f"HTTP {err.status} sur GET {path}: {err.message}") from err
        except aiohttp.ClientError as err:
            raise NetworkError(f"Erreur réseau sur GET {path}: {err}") from err

    async def _post(self, path: str, body: dict | None = None) -> Any:
        """POST authentifié avec retry sur 401 (token expiré)."""
        await self._ensure_auth()
        url = f"{BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        try:
            async with self._session.post(url, json=body or {}, headers=headers) as resp:
                if resp.status == 401:
                    _LOGGER.debug("Token expiré, ré-authentification...")
                    await self.authenticate()
                    headers = {"Authorization": f"Bearer {self._access_token}"}
                    async with self._session.post(url, json=body or {}, headers=headers) as resp2:
                        if resp2.status == 403:
                            raise WafBlockedError(
                                f"WAF 403 sur POST {path} (après ré-auth)."
                            )
                        resp2.raise_for_status()
                        return await resp2.json(content_type=None)
                if resp.status == 403:
                    raise WafBlockedError(f"WAF 403 sur POST {path}.")
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except (WafBlockedError, AuthenticationError):
            raise
        except aiohttp.ClientResponseError as err:
            raise ApiError(f"HTTP {err.status} sur POST {path}: {err.message}") from err
        except aiohttp.ClientError as err:
            raise NetworkError(f"Erreur réseau sur POST {path}: {err}") from err

    # ------------------------------------------------------------------
    # API métier
    # ------------------------------------------------------------------

    async def get_contracts(self) -> list[dict]:
        """Retourne les contrats avec détails complets (solde, service, etc.)."""
        data = await self._post(
            f"/application/rest/interfaces/ael/contrats/rechercher"
            f"?expand={_CONTRACTS_EXPAND}&select={_CONTRACTS_SELECT}"
        )
        contracts = data.get("content", data) if isinstance(data, dict) else data
        return list(contracts) if contracts else []

    async def get_monthly_consumptions(self, contract_id: str) -> list[dict]:
        """Retourne les consommations mensuelles brutes, triées par date (croissant)."""
        data = await self._get(
            f"/application/rest/interfaces/ael/contrats/{contract_id}"
            f"/consommationsMensuelles"
        )
        entries: list[dict] = []
        for poste in data.get("postes", []):
            entries.extend(poste.get("data", []))
        entries.sort(key=lambda x: (int(x["annee"]), int(x["mois"])))
        return entries

    async def get_daily_consumptions(
        self, contract_id: str, nb_jours: int = 90
    ) -> list[dict]:
        """Tente de récupérer les consommations journalières (données Téléo/TIC).

        Certains compteurs communicants remontent des données quotidiennes.
        Retourne une liste vide si l'endpoint n'est pas disponible ou si le
        compteur ne supporte pas les relevés journaliers.

        Format attendu de chaque entrée :
            {"date": "YYYY-MM-DD", "consommation": <float>, ...}
        """
        # Deux patterns d'endpoint observés selon les versions de l'API
        endpoints = [
            (
                f"/application/rest/interfaces/ael/contrats/{contract_id}"
                f"/consommationsJournalieres?nbJours={nb_jours}"
            ),
            (
                f"/application/rest/interfaces/ael/contrats/{contract_id}"
                f"/consommationsDailyPeriode?nbJours={nb_jours}"
            ),
        ]

        for endpoint in endpoints:
            try:
                data = await self._get(endpoint)
                entries: list[dict] = []
                # Format postes (identique aux données mensuelles)
                if isinstance(data, dict) and "postes" in data:
                    for poste in data.get("postes", []):
                        entries.extend(poste.get("data", []))
                # Format tableau direct
                elif isinstance(data, list):
                    entries = data

                if entries:
                    entries.sort(key=lambda x: x.get("date", ""))
                    _LOGGER.debug(
                        "Données journalières disponibles pour contrat %s : %d entrées",
                        contract_id, len(entries),
                    )
                    return entries

            except ApiError as err:
                # 404 = endpoint inexistant → pas de données journalières
                if "404" in str(err):
                    _LOGGER.debug(
                        "Endpoint journalier non disponible pour contrat %s (%s)",
                        contract_id, endpoint.split("/")[-1].split("?")[0],
                    )
                else:
                    _LOGGER.debug(
                        "Données journalières non disponibles pour contrat %s : %s",
                        contract_id, err,
                    )
                continue
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Données journalières non disponibles pour contrat %s",
                    contract_id,
                )
                continue

        return []

    async def get_alertes(self) -> list[dict]:
        """Retourne la liste des alertes actives (tous contrats)."""
        try:
            data = await self._get(
                "/application/rest/interfaces/ael/contrats/alertes"
                "?expand=infosAlarme,modeleAction,objetMaitre"
            )
            return data if isinstance(data, list) else []
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Impossible de récupérer les alertes, retourne []")
            return []

    # ------------------------------------------------------------------
    # Helpers de formatage
    # ------------------------------------------------------------------

    @staticmethod
    def format_consumptions(raw_entries: list[dict]) -> list[dict]:
        """Enrichit les entrées mensuelles brutes avec labels lisibles."""
        result = []
        for e in raw_entries:
            mois_raw = int(e["mois"])
            if not (1 <= mois_raw <= 12):
                continue  # Skip invalid month values from API (e.g. mois=0)
            mois_idx = mois_raw - 1  # API returns 1-12, convert to 0-11 for MONTHS_FR
            annee = int(e["annee"])
            result.append({
                "mois_index": mois_idx,
                "mois": MONTHS_FR[mois_idx],
                "annee": annee,
                "label": f"{MONTHS_FR[mois_idx]} {annee}",
                "consommation_m3": float(e["consommation"]),
            })
        return result

    @staticmethod
    def format_daily_consumptions(raw_entries: list[dict]) -> list[dict]:
        """Enrichit les entrées journalières brutes (si disponibles)."""
        result = []
        for e in raw_entries:
            date_str = e.get("date", "")
            conso = e.get("consommation", 0)
            result.append({
                "date": date_str,
                "consommation_m3": float(conso),
            })
        return result

    @staticmethod
    def parse_contract_details(raw: dict) -> dict:
        """Extrait les champs utiles d'un contrat brut (depuis rechercher)."""
        ref = raw.get("reference", "")
        statut = (raw.get("statutExtrait") or {}).get("libelle", "")

        date_effet_raw = raw.get("dateEffet") or ""
        date_echeance_raw = raw.get("dateEcheance") or ""
        date_effet = date_effet_raw[:10] if date_effet_raw else None
        date_echeance = date_echeance_raw[:10] if date_echeance_raw else None

        condition = raw.get("conditionPaiement") or {}
        compte = condition.get("compteClient") or {}
        solde_obj = compte.get("solde") or {}
        solde_eur = float(solde_obj.get("value", 0))

        mensualise: bool = bool(condition.get("mensualise", False))
        mode_paiement = (condition.get("modePaiement") or {}).get("libelle", "")

        services = raw.get("servicesSouscrits") or []
        calibre_compteur = ""
        usage = ""
        nombre_habitants = ""
        if services:
            svc = services[0]
            calibre_compteur = (svc.get("calibreCompteur") or {}).get("libelle", "")
            usage = (svc.get("usage") or {}).get("libelle", "")
            nb_h = svc.get("nombreHabitants") or {}
            nombre_habitants = nb_h.get("libelle", "") if nb_h else ""

        eds = raw.get("espaceDeLivraison") or {}
        ref_pds = eds.get("reference", "")

        return {
            "id": raw.get("id", ""),
            "reference": ref,
            "statut": statut,
            "date_effet": date_effet,
            "date_echeance": date_echeance,
            "solde_eur": solde_eur,
            "mensualise": mensualise,
            "mode_paiement": mode_paiement,
            "calibre_compteur": calibre_compteur,
            "usage": usage,
            "nombre_habitants": nombre_habitants,
            "reference_pds": ref_pds,
        }
