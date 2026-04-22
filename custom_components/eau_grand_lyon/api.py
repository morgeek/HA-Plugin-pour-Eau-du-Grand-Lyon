"""Client API pour Eau du Grand Lyon (authentification PKCE + données contrat).

Deux modes de fonctionnement :
- Mode legacy (défaut) : utilise les anciens endpoints /application/rest/...
  Ces URLs sont stables et fonctionnelles — comportement par défaut de l'intégration.
- Mode expérimental (CONF_EXPERIMENTAL=True) : tente les nouveaux endpoints
  /rest/produits/... et /rest/interfaces/ael/... découverts dans le bundle Angular 2026.
  Inclut un fallback automatique vers legacy si un nouvel endpoint échoue.
  Les deux modes coexistent sans conflit — rien ne casse en cas d'erreur.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://agence.eaudugrandlyon.com"
CLIENT_ID = "kwnOk0B_aqlOI6p_GVxrbf6"
REDIRECT_URI = f"{BASE_URL}/autorisation-callback.html"

# ── URLs d'authentification ───────────────────────────────────────────────────
# Legacy (ancienne API, préfixe /application/) — stable, utilisé par défaut
LOGIN_URL     = f"{BASE_URL}/application/auth/externe/authentification"
AUTHORIZE_URL = f"{BASE_URL}/application/auth/authorize-internet"
TOKEN_URL     = f"{BASE_URL}/application/auth/tokenUtilisateurInternet"

# Nouveaux (sans préfixe /application/ — bundle Angular 2026, 0 occurrence de /application/)
_NEW_LOGIN_URL     = f"{BASE_URL}/auth/externe/authentification"
_NEW_AUTHORIZE_URL = f"{BASE_URL}/auth/authorize-internet"
_NEW_TOKEN_URL     = f"{BASE_URL}/auth/tokenUtilisateurInternet"
_TOKEN_REVOKE_URL  = f"{BASE_URL}/auth/revoke"  # nouveau endpoint de révocation

# ── Bases endpoints données ───────────────────────────────────────────────────
# Legacy : /application/rest/interfaces/ael/
_LEGACY_AEL_BASE = f"{BASE_URL}/application/rest/interfaces/ael"

# Expérimental : deux namespaces distincts
_PRODUITS_BASE       = f"{BASE_URL}/rest/produits"        # données métier (factures, contrats…)
_INTERFACES_AEL_BASE = f"{BASE_URL}/rest/interfaces/ael"  # mêmes données, format "interfaces"

# code_verifier non-standard mais conforme au serveur (PKCE simplifié — 1 chiffre)
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

# Champs demandés lors de la recherche de contrats
_CONTRACTS_SELECT = (
    "id,reference,statutExtrait,dateEffet,dateEcheance,"
    "conditionPaiement(compteClient(solde),mensualise,modePaiement),"
    "servicesSouscrits(statut,usage,calibreCompteur,nombreHabitants),"
    "espaceDeLivraison(reference)"
)
_CONTRACTS_EXPAND = "conditionPaiement(compteClient),servicesSouscrits,espaceDeLivraison"


# ── Exceptions ────────────────────────────────────────────────────────────────

class AuthenticationError(Exception):
    """Identifiants invalides ou flux OAuth2 échoué."""


class WafBlockedError(Exception):
    """Le WAF Apache a bloqué la requête (HTTP 403).

    Causes possibles : trop de requêtes en peu de temps, ou headers Sec-Fetch-*
    dans la requête.
    """


class ApiError(Exception):
    """Erreur générique lors d'un appel API (hors auth et WAF)."""


class NetworkError(Exception):
    """Erreur réseau / timeout lors d'un appel API."""


# ── Helper PKCE ───────────────────────────────────────────────────────────────

def _compute_code_challenge(verifier: str) -> str:
    """Calcule le code_challenge PKCE (SHA-256 en base64url)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ══════════════════════════════════════════════════════════════════════════════

class EauGrandLyonApi:
    """Client pour l'API Eau du Grand Lyon avec authentification PKCE OAuth2.

    Paramètres
    ----------
    session      : session aiohttp partagée (CookieJar unsafe=True recommandé)
    email        : identifiant Eau du Grand Lyon
    password     : mot de passe
    experimental : active les nouveaux endpoints /rest/produits/ (défaut: False)
                   Les anciens endpoints restent en fallback si un nouvel échoue.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        experimental: bool = False,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._access_token: str | None = None
        self._experimental = experimental
        # Détermine le jeu d'URLs d'auth à utiliser.
        # En mode expérimental on tente "new" d'abord, puis "legacy" si échec.
        self._auth_mode: str = "new" if experimental else "legacy"
        _LOGGER.debug(
            "EauGrandLyonApi initialisé — mode=%s",
            "expérimental" if experimental else "legacy",
        )

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def experimental(self) -> bool:
        return self._experimental

    # ------------------------------------------------------------------
    # Authentification
    # ------------------------------------------------------------------

    async def authenticate(self) -> str:
        """Effectue l'authentification PKCE complète et retourne l'access token.

        Flux OAuth2 rétro-ingéniéré du bundle Angular :
        1. POST /auth/externe/authentification  {username, password, client_id}
           → 200 + cookie de session HttpOnly
        2. GET  /auth/authorize-internet?code_challenge=...
           → 302 → /autorisation-callback.html?code=...
        3. POST /auth/tokenUtilisateurInternet  {grant_type=authorization_code, …}
           → {"access_token": "…"}

        En mode expérimental, tente les nouvelles URLs (sans /application/) en premier.
        Si elles retournent 404 ou une erreur réseau, bascule sur les URLs legacy.
        Les erreurs d'authentification (401) et WAF (403) ne déclenchent pas le fallback.
        """
        if self._experimental and self._auth_mode == "new":
            try:
                token = await self._authenticate_with_urls(
                    _NEW_LOGIN_URL, _NEW_AUTHORIZE_URL, _NEW_TOKEN_URL
                )
                _LOGGER.debug("Auth OK via nouvelles URLs auth (sans /application/)")
                return token
            except ApiError as err:
                # 404 → URL n'existe pas encore → fallback legacy
                _LOGGER.warning(
                    "[EXPÉRIMENTAL] Nouvelles URLs auth échouées (%s) → fallback legacy", err
                )
                self._auth_mode = "legacy"
            except NetworkError as err:
                _LOGGER.warning(
                    "[EXPÉRIMENTAL] Erreur réseau nouvelles URLs auth (%s) → fallback legacy", err
                )
                self._auth_mode = "legacy"
            # AuthenticationError et WafBlockedError : on ne fallback pas
            # (les credentials sont mauvais ou le WAF bloque → l'utilisateur doit agir)

        token = await self._authenticate_with_urls(LOGIN_URL, AUTHORIZE_URL, TOKEN_URL)
        if self._experimental:
            _LOGGER.debug("Auth OK via URLs legacy (/application/)")
        return token

    async def _authenticate_with_urls(
        self, login_url: str, authorize_url: str, token_url: str
    ) -> str:
        """Exécute le flux OAuth2 PKCE complet avec les URLs fournies."""
        # Étape 1 : Login → cookie de session
        try:
            async with self._session.post(
                login_url,
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
        if login_status == 404:
            raise ApiError(f"URL de login non trouvée (404): {login_url}")
        if login_status not in (200, 204):
            raise ApiError(f"Login échoué ({login_status}): {login_body[:200]}")

        _LOGGER.debug("Login OK (status=%s), récupération du code PKCE…", login_status)

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
                authorize_url,
                params=params,
                headers=BROWSER_NAV_HEADERS,
                allow_redirects=True,
            ) as resp:
                if resp.status == 403:
                    raise WafBlockedError(
                        "Le WAF a bloqué la requête authorize-internet (HTTP 403)."
                    )
                if resp.status == 404:
                    raise ApiError(f"URL authorize non trouvée (404): {authorize_url}")
                final_url = str(resp.url)
                _LOGGER.debug("Authorize final URL: %s", final_url[:200])
        except (WafBlockedError, ApiError):
            raise
        except aiohttp.ClientError as err:
            raise NetworkError(f"Erreur réseau sur /authorize: {err}") from err

        code = self._extract_code_from_url(final_url)
        if not code:
            raise AuthenticationError(
                f"Pas de code d'autorisation dans l'URL de callback: {final_url[:200]}"
            )

        # Étape 3 : échange code → token
        return await self._exchange_code(code, token_url)

    @staticmethod
    def _extract_code_from_url(url: str) -> str | None:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        code = qs.get("code", [None])[0]
        if not code:
            frag = parse_qs(parsed.fragment)
            code = frag.get("code", [None])[0]
        return code

    async def _exchange_code(self, code: str, token_url: str) -> str:
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": CODE_VERIFIER,
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
        }
        try:
            async with self._session.post(
                token_url,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                if resp.status == 403:
                    raise WafBlockedError("Le WAF a bloqué l'échange de token (HTTP 403).")
                if resp.status == 404:
                    raise ApiError(f"URL token non trouvée (404): {token_url}")
                if resp.status != 200:
                    body = await resp.text()
                    raise AuthenticationError(
                        f"Échange de token échoué ({resp.status}): {body[:200]}"
                    )
                result: dict = json.loads(await resp.text())
        except (WafBlockedError, AuthenticationError, ApiError):
            raise
        except aiohttp.ClientError as err:
            raise NetworkError(f"Requête token échouée: {err}") from err

        if "access_token" not in result:
            raise AuthenticationError(f"Pas d'access_token dans la réponse: {result}")

        self._access_token = result["access_token"]
        _LOGGER.debug("Authentification réussie pour %s", self._email)
        return self._access_token

    async def async_revoke_token(self) -> None:
        """Révoque l'access token auprès du serveur (best-effort).

        Appelé lors du déchargement de l'intégration pour éviter les sessions
        orphelines côté serveur. Ne lève jamais d'exception.
        """
        if not self._access_token:
            return
        try:
            async with self._session.post(
                _TOKEN_REVOKE_URL,
                data={"token": self._access_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                _LOGGER.debug(
                    "Révocation token → HTTP %s", resp.status
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Échec révocation token (best-effort, ignoré)")
        finally:
            self._access_token = None

    # ------------------------------------------------------------------
    # Transport HTTP interne
    # ------------------------------------------------------------------

    async def _ensure_auth(self) -> None:
        if not self._access_token:
            await self.authenticate()

    async def _do_get(self, url: str, params: dict | None = None) -> Any:
        """GET authentifié sur URL complète, avec retry sur 401 (token expiré)."""
        await self._ensure_auth()
        headers = {"Authorization": f"Bearer {self._access_token}"}
        try:
            async with self._session.get(url, headers=headers, params=params) as resp:
                if resp.status == 401:
                    _LOGGER.debug("Token expiré, ré-authentification…")
                    await self.authenticate()
                    headers = {"Authorization": f"Bearer {self._access_token}"}
                    async with self._session.get(url, headers=headers, params=params) as resp2:
                        if resp2.status == 403:
                            raise WafBlockedError(f"WAF 403 sur GET {url} (après ré-auth).")
                        resp2.raise_for_status()
                        return json.loads(await resp2.text())
                if resp.status == 403:
                    raise WafBlockedError(f"WAF 403 sur GET {url}.")
                resp.raise_for_status()
                return json.loads(await resp.text())
        except (WafBlockedError, AuthenticationError):
            raise
        except aiohttp.ClientResponseError as err:
            raise ApiError(f"HTTP {err.status} sur GET {url}: {err.message}") from err
        except aiohttp.ClientError as err:
            raise NetworkError(f"Erreur réseau sur GET {url}: {err}") from err

    async def _do_post(self, url: str, body: dict | None = None) -> Any:
        """POST authentifié sur URL complète, avec retry sur 401 (token expiré)."""
        await self._ensure_auth()
        headers = {"Authorization": f"Bearer {self._access_token}"}
        try:
            async with self._session.post(url, json=body or {}, headers=headers) as resp:
                if resp.status == 401:
                    _LOGGER.debug("Token expiré, ré-authentification…")
                    await self.authenticate()
                    headers = {"Authorization": f"Bearer {self._access_token}"}
                    async with self._session.post(url, json=body or {}, headers=headers) as resp2:
                        if resp2.status == 403:
                            raise WafBlockedError(f"WAF 403 sur POST {url} (après ré-auth).")
                        resp2.raise_for_status()
                        return json.loads(await resp2.text())
                if resp.status == 403:
                    raise WafBlockedError(f"WAF 403 sur POST {url}.")
                resp.raise_for_status()
                return json.loads(await resp.text())
        except (WafBlockedError, AuthenticationError):
            raise
        except aiohttp.ClientResponseError as err:
            raise ApiError(f"HTTP {err.status} sur POST {url}: {err.message}") from err
        except aiohttp.ClientError as err:
            raise NetworkError(f"Erreur réseau sur POST {url}: {err}") from err

    # ── Raccourcis legacy (backward compat — conservés intacts) ──────────────

    async def _get(self, path: str) -> Any:
        """GET legacy — path relatif construit sous BASE_URL (avec /application/)."""
        return await self._do_get(f"{BASE_URL}{path}")

    async def _post(self, path: str, body: dict | None = None) -> Any:
        """POST legacy — path relatif construit sous BASE_URL (avec /application/)."""
        return await self._do_post(f"{BASE_URL}{path}", body)

    # ── Raccourcis expérimentaux ─────────────────────────────────────────────

    async def _get_produits(self, sub_path: str, params: dict | None = None) -> Any:
        """GET /rest/produits/{sub_path} [EXPÉRIMENTAL]."""
        url = f"{_PRODUITS_BASE}/{sub_path.lstrip('/')}"
        return await self._do_get(url, params)

    async def _get_interfaces(self, sub_path: str, params: dict | None = None) -> Any:
        """GET /rest/interfaces/ael/{sub_path} [EXPÉRIMENTAL]."""
        url = f"{_INTERFACES_AEL_BASE}/{sub_path.lstrip('/')}"
        return await self._do_get(url, params)

    # ------------------------------------------------------------------
    # API métier — endpoints LEGACY (stables, comportement inchangé)
    # ------------------------------------------------------------------

    async def get_contracts(self) -> list[dict]:
        """Retourne les contrats avec détails complets (solde, service, etc.)."""
        data = await self._post(
            f"/application/rest/interfaces/ael/contrats/rechercher"
            f"?expand={_CONTRACTS_EXPAND}&select={_CONTRACTS_SELECT}"
        )
        if not isinstance(data, (dict, list)):
            _LOGGER.warning(
                "Réponse inattendue pour get_contracts (type=%s)", type(data).__name__
            )
            return []
        contracts = data.get("content", data) if isinstance(data, dict) else data
        return list(contracts) if contracts else []

    async def get_monthly_consumptions(self, contract_id: str) -> list[dict]:
        """Retourne les consommations mensuelles brutes, triées par date (croissant)."""
        data = await self._get(
            f"/application/rest/interfaces/ael/contrats/{contract_id}"
            f"/consommationsMensuelles"
        )
        entries: list[dict] = []
        if not isinstance(data, dict):
            _LOGGER.warning(
                "Réponse inattendue pour consommationsMensuelles (type=%s)",
                type(data).__name__,
            )
            return entries
        for poste in data.get("postes", []):
            entries.extend(poste.get("data", []))
        entries.sort(key=lambda x: (int(x.get("annee", 0)), int(x.get("mois", 0))))
        return entries

    async def get_daily_consumptions(
        self, contract_id: str, nb_jours: int = 90
    ) -> list[dict]:
        """Récupère les consommations journalières (Téléo/TIC uniquement).

        Stratégie selon le mode :
        - Expérimental : tente /rest/produits/contrats/{id}/consommationsJournalieres
          avec params dateDebut/dateFin (format bundle 2026), puis fallback legacy.
        - Legacy : deux patterns d'endpoints observés selon versions de l'API.

        Retourne une liste vide si aucune donnée journalière n'est disponible.
        """
        if self._experimental:
            result = await self._get_daily_new(contract_id, nb_jours)
            if result:
                _LOGGER.debug(
                    "[EXPÉRIMENTAL] Journalier OK pour contrat %s : %d entrées (nouveau endpoint)",
                    contract_id, len(result),
                )
                return result
            _LOGGER.debug(
                "[EXPÉRIMENTAL] Nouveau endpoint journalier indisponible pour contrat %s"
                " — fallback legacy", contract_id,
            )

        return await self._get_daily_legacy(contract_id, nb_jours)

    async def _get_daily_new(self, contract_id: str, nb_jours: int) -> list[dict]:
        """Nouvel endpoint journalier avec dateDebut/dateFin (bundle Angular 2026).

        GET /rest/produits/contrats/{id}/consommationsJournalieres
            ?dateDebut=YYYY-MM-DDTHH:MM:SS.000Z&dateFin=YYYY-MM-DDTHH:MM:SS.000Z

        Champs supplémentaires par rapport au legacy (si compteur compatible) :
          volumeFuiteEstime, debitMin, index
        """
        try:
            date_fin = datetime.now(timezone.utc)
            date_debut = date_fin - timedelta(days=nb_jours)
            params = {
                "dateDebut": date_debut.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "dateFin":   date_fin.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
            data = await self._get_produits(
                f"contrats/{contract_id}/consommationsJournalieres", params
            )
            entries: list[dict] = []
            if isinstance(data, dict) and "postes" in data:
                for poste in data["postes"]:
                    entries.extend(poste.get("data", []))
            elif isinstance(data, list):
                entries = data

            if entries:
                entries.sort(key=lambda x: x.get("date", ""))
            return entries

        except ApiError as err:
            if "404" in str(err):
                _LOGGER.debug(
                    "[EXPÉRIMENTAL] Endpoint journalier /rest/produits/ → 404 (contrat %s)",
                    contract_id,
                )
            else:
                _LOGGER.debug(
                    "[EXPÉRIMENTAL] Erreur endpoint journalier (contrat %s) : %s",
                    contract_id, err,
                )
            return []
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "[EXPÉRIMENTAL] Erreur inattendue endpoint journalier (contrat %s) : %s",
                contract_id, err,
            )
            return []

    async def _get_daily_legacy(self, contract_id: str, nb_jours: int) -> list[dict]:
        """Anciens endpoints journaliers — deux patterns observés selon versions API."""
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
                if isinstance(data, dict) and "postes" in data:
                    for poste in data["postes"]:
                        entries.extend(poste.get("data", []))
                elif isinstance(data, list):
                    entries = data

                if entries:
                    entries.sort(key=lambda x: x.get("date", ""))
                    _LOGGER.debug(
                        "Données journalières legacy OK contrat %s : %d entrées",
                        contract_id, len(entries),
                    )
                    return entries

            except ApiError as err:
                if "404" in str(err):
                    _LOGGER.debug(
                        "Endpoint journalier legacy non disponible (contrat %s) : %s",
                        contract_id,
                        endpoint.split("/")[-1].split("?")[0],
                    )
                else:
                    _LOGGER.debug(
                        "Données journalières legacy non disponibles (contrat %s) : %s",
                        contract_id, err,
                    )
                continue
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug(
                    "Erreur traitement données journalières legacy (contrat %s) : %s",
                    contract_id, err,
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
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Erreur récupération alertes : %s", err)
            return []

    # ------------------------------------------------------------------
    # API métier — endpoints EXPÉRIMENTAUX (/rest/produits/)
    # ------------------------------------------------------------------

    async def get_factures(self) -> list[dict]:
        """[EXPÉRIMENTAL] Retourne les factures depuis /rest/produits/factures.

        Champs disponibles dans chaque facture :
          reference, dateEdition, dateExigibilite, montantHT, montantTTC,
          statutPaiement{libelle}, volume, contrat{id}

        Retourne [] si l'endpoint n'est pas disponible ou en cas d'erreur.
        """
        try:
            data = await self._get_produits("factures")
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("content", [])
            return []
        except ApiError as err:
            if "404" in str(err):
                _LOGGER.debug("[EXPÉRIMENTAL] /rest/produits/factures → 404")
            else:
                _LOGGER.debug("[EXPÉRIMENTAL] Erreur get_factures : %s", err)
            return []
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[EXPÉRIMENTAL] Erreur inattendue get_factures : %s", err)
            return []

    async def get_courbe_de_charge(
        self, contract_id: str, nb_jours: int = 30
    ) -> list[dict]:
        """[EXPÉRIMENTAL] Retourne la courbe de charge (données sub-journalières).

        Disponible uniquement sur les compteurs communicants Téléo.
        Endpoint : GET /rest/interfaces/ael/contrats/{id}/courbeDeCharge
                       ?dateDebut=ISO&dateFin=ISO

        Retourne [] si le compteur ne supporte pas les données horaires.
        """
        try:
            date_fin = datetime.now(timezone.utc)
            date_debut = date_fin - timedelta(days=nb_jours)
            params = {
                "dateDebut": date_debut.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "dateFin":   date_fin.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
            data = await self._get_interfaces(
                f"contrats/{contract_id}/courbeDeCharge", params
            )
            entries: list[dict] = []
            if isinstance(data, dict) and "postes" in data:
                for poste in data["postes"]:
                    entries.extend(poste.get("data", []))
            elif isinstance(data, list):
                entries = data

            if entries:
                entries.sort(key=lambda x: x.get("date", ""))
                _LOGGER.debug(
                    "[EXPÉRIMENTAL] Courbe de charge OK contrat %s : %d points",
                    contract_id, len(entries),
                )
            return entries

        except ApiError as err:
            if "404" in str(err):
                _LOGGER.debug(
                    "[EXPÉRIMENTAL] Courbe de charge non dispo contrat %s"
                    " (compteur non communicant ou endpoint absent)", contract_id,
                )
            else:
                _LOGGER.debug(
                    "[EXPÉRIMENTAL] Erreur get_courbe_de_charge (contrat %s) : %s",
                    contract_id, err,
                )
            return []
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "[EXPÉRIMENTAL] Erreur inattendue get_courbe_de_charge (contrat %s) : %s",
                contract_id, err,
            )
            return []

    async def get_derniere_releve_siamm(self, contract_id: str) -> dict | None:
        """[EXPÉRIMENTAL] Retourne la dernière relève SIAMM du compteur.

        Endpoint : GET /rest/produits/contrats/{id}/derniereReleveSIAMM
                       ?expand=grandeursPhysiques(modeleGrandeurPhysique)

        Retourne None si indisponible.
        """
        try:
            data = await self._get_produits(
                f"contrats/{contract_id}/derniereReleveSIAMM"
                "?expand=grandeursPhysiques(modeleGrandeurPhysique)"
            )
            return data if isinstance(data, dict) else None
        except ApiError as err:
            if "404" in str(err):
                _LOGGER.debug(
                    "[EXPÉRIMENTAL] Dernière relève SIAMM non dispo (contrat %s)", contract_id
                )
            else:
                _LOGGER.debug(
                    "[EXPÉRIMENTAL] Erreur get_derniere_releve_siamm (contrat %s) : %s",
                    contract_id, err,
                )
            return None
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "[EXPÉRIMENTAL] Erreur inattendue get_derniere_releve_siamm"
                " (contrat %s) : %s", contract_id, err,
            )
            return None

    # ------------------------------------------------------------------
    # Helpers de formatage
    # ------------------------------------------------------------------

    async def get_invoice_pdf(self, invoice_ref: str) -> bytes:
        """[EXPÉRIMENTAL] Télécharge le PDF d'une facture."""
        url = f"{BASE_URL}/rest/produits/factures/{invoice_ref}/document"
        async with self._session.get(url, headers=self._headers) as resp:
            if resp.status != 200:
                raise NetworkError(f"Erreur téléchargement PDF ({resp.status})")
            return await resp.read()

    @staticmethod
    def format_consumptions(raw_entries: list[dict]) -> list[dict]:
        """Enrichit les entrées mensuelles brutes avec labels lisibles."""
        result = []
        for e in raw_entries:
            try:
                mois_raw = int(e["mois"])
                if not (1 <= mois_raw <= 12):
                    continue  # Skip invalid month values (e.g. mois=0)
                mois_idx = mois_raw - 1  # API retourne 1-12, on convertit en 0-11
                annee = int(e["annee"])
                result.append({
                    "mois_index":       mois_idx,
                    "mois":             MONTHS_FR[mois_idx],
                    "annee":            annee,
                    "label":            f"{MONTHS_FR[mois_idx]} {annee}",
                    "consommation_m3":  float(e.get("consommation", 0)),
                })
            except (KeyError, ValueError, TypeError):
                _LOGGER.debug("Entrée mensuelle ignorée (format inattendu) : %s", e)
        return result

    @staticmethod
    def format_daily_consumptions(raw_entries: list[dict]) -> list[dict]:
        """Enrichit les entrées journalières brutes.

        Extrait les champs standards (date, consommation) et les champs
        expérimentaux optionnels remontés par les nouveaux compteurs Téléo :
          - volumeFuiteEstime → volume_fuite_estime_m3
          - debitMin          → debit_min_m3h
          - index             → index_m3
        Ces champs sont absents si le compteur ne les supporte pas.
        """
        result = []
        for e in raw_entries:
            try:
                entry: dict = {
                    "date":            e.get("date", ""),
                    "consommation_m3": float(e.get("consommation", 0)),
                }
                # Champs expérimentaux — présents seulement sur compteurs Téléo récents
                for src_key, dst_key in [
                    ("volumeFuiteEstime", "volume_fuite_estime_m3"),
                    ("debitMin",          "debit_min_m3h"),
                    ("index",             "index_m3"),
                ]:
                    val = e.get(src_key)
                    if val is not None:
                        try:
                            entry[dst_key] = float(val)
                        except (ValueError, TypeError):
                            pass
                result.append(entry)
            except (ValueError, TypeError):
                _LOGGER.debug("Entrée journalière ignorée (format inattendu) : %s", e)
        return result

    @staticmethod
    def format_factures(raw_factures: list[dict]) -> list[dict]:
        """[EXPÉRIMENTAL] Normalise les factures brutes depuis /rest/produits/factures.

        Retourne les factures triées par date d'édition décroissante (plus récente en tête).
        """
        result = []
        for f in raw_factures:
            try:
                statut_raw = f.get("statutPaiement") or {}
                date_ed = (f.get("dateEdition") or "")[:10] or None
                date_ex = (f.get("dateExigibilite") or "")[:10] or None
                result.append({
                    "reference":        f.get("reference", ""),
                    "date_edition":     date_ed,
                    "date_exigibilite": date_ex,
                    "montant_ht":       float(f.get("montantHT", 0) or 0),
                    "montant_ttc":      float(f.get("montantTTC", 0) or 0),
                    "volume_m3":        float(f.get("volume", 0) or 0),
                    "statut_paiement":  statut_raw.get("libelle", ""),
                    "contrat_id":       (f.get("contrat") or {}).get("id", ""),
                })
            except (KeyError, ValueError, TypeError):
                _LOGGER.debug("Facture ignorée (format inattendu) : %s", f)
        result.sort(key=lambda x: x.get("date_edition") or "", reverse=True)
        return result

    @staticmethod
    def parse_contract_details(raw: dict) -> dict:
        """Extrait les champs utiles d'un contrat brut (depuis rechercher)."""
        ref    = raw.get("reference", "")
        statut = (raw.get("statutExtrait") or {}).get("libelle", "")

        date_effet_raw    = raw.get("dateEffet") or ""
        date_echeance_raw = raw.get("dateEcheance") or ""
        date_effet    = date_effet_raw[:10]    if date_effet_raw    else None
        date_echeance = date_echeance_raw[:10] if date_echeance_raw else None

        condition   = raw.get("conditionPaiement") or {}
        compte      = condition.get("compteClient") or {}
        solde_obj   = compte.get("solde") or {}
        try:
            solde_eur = float(solde_obj.get("value", 0))
        except (ValueError, TypeError):
            solde_eur = 0.0

        mensualise:   bool = bool(condition.get("mensualise", False))
        mode_paiement = (condition.get("modePaiement") or {}).get("libelle", "")

        services          = raw.get("servicesSouscrits") or []
        calibre_compteur  = ""
        usage             = ""
        nombre_habitants  = ""
        if services:
            svc              = services[0]
            calibre_compteur = (svc.get("calibreCompteur") or {}).get("libelle", "")
            usage            = (svc.get("usage")           or {}).get("libelle", "")
            nb_h             = svc.get("nombreHabitants") or {}
            nombre_habitants = nb_h.get("libelle", "") if nb_h else ""

        eds     = raw.get("espaceDeLivraison") or {}
        ref_pds = eds.get("reference", "")
        
        # Hardware Health (Téléo)
        point_releve = raw.get("pointDeReleve") or {}
        compteur     = point_releve.get("compteur") or {}
        module       = point_releve.get("moduleRadio") or {}
        
        signal_pct = None
        if "niveauSignal" in module:
            try:
                signal_pct = float(module["niveauSignal"])
            except (ValueError, TypeError):
                pass
        
        battery_ok = None
        if "etatPile" in module:
            battery_ok = module["etatPile"] == "OK"

        return {
            "id":               raw.get("id", ""),
            "reference":        ref,
            "statut":           statut,
            "signal_pct":       signal_pct,
            "battery_ok":       battery_ok,
            "date_effet":       date_effet,
            "date_echeance":    date_echeance,
            "solde_eur":        solde_eur,
            "mensualise":       mensualise,
            "mode_paiement":    mode_paiement,
            "calibre_compteur": calibre_compteur,
            "usage":            usage,
            "nombre_habitants": nombre_habitants,
            "reference_pds":    ref_pds,
        }

    @staticmethod
    def parse_siamm_index(data: dict) -> float | None:
        """[EXPÉRIMENTAL] Extrait l'index (m³) de la relève SIAMM brute.

        Parcourt grandeursPhysiques à la recherche du code 'VOLUME'.
        """
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
