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


# ── Helpers détection format données journalières ─────────────────────────────

def _detect_month_offset(entries: list[dict]) -> int:
    """Détecte si le champ 'mois' est 0-indexed (JS) ou 1-indexed (Python/ISO).

    Stratégie (inspirée du fork hufon) :
    - On examine jusqu'à 30 entrées.
    - On compte les entrées avec mois == 0 (impossible en 1-indexed → forcément 0-indexed)
      et les entrées avec mois == 12 (impossible en 0-indexed → forcément 1-indexed).
    - Si score_0indexed > score_1indexed → offset = 1 (on ajoute 1 pour obtenir 1-12).
    - Sinon offset = 0 (mois déjà 1-indexed).

    Retourne 1 (0-indexed) ou 0 (1-indexed, pas de correction nécessaire).
    """
    score_0indexed = 0  # preuves que mois est 0-indexed
    score_1indexed = 0  # preuves que mois est 1-indexed

    sample = entries[:30]
    for e in sample:
        m = e.get("mois")
        if m is None:
            continue
        try:
            m_int = int(m)
        except (ValueError, TypeError):
            continue
        if m_int == 0:
            score_0indexed += 3   # mois=0 ne peut exister qu'en 0-indexed
        elif m_int == 12:
            score_1indexed += 3   # mois=12 ne peut exister qu'en 1-indexed
        elif 1 <= m_int <= 11:
            # Ambigu — ne change pas les scores
            pass

    if score_0indexed > score_1indexed:
        return 1   # 0-indexed → ajouter 1
    return 0       # 1-indexed (ou ambigu → on ne touche pas)


def _infer_unit_from_magnitude(entries: list[dict]) -> str:
    """Infère l'unité (L ou M3) depuis la magnitude des valeurs de consommation.

    Si l'API ne déclare pas l'unité explicitement :
    - On calcule la médiane des valeurs non-nulles de consommation.
    - Si la médiane est > 50 → probablement en Litres (1 pers ≈ 100-200 L/j).
    - Sinon → probablement déjà en m³.

    Retourne "L", "M3" ou "" (si impossible de déterminer).
    """
    values: list[float] = []
    for e in entries[:50]:
        v = e.get("consommation")
        if v is None:
            continue
        try:
            fv = float(v)
            if fv > 0:
                values.append(fv)
        except (ValueError, TypeError):
            continue

    if not values:
        return ""
    values.sort()
    median = values[len(values) // 2]
    return "L" if median > 50 else "M3"


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

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        """Exécute une requête authentifiée avec retry automatique sur 401."""
        await self._ensure_auth()
        headers = {"Authorization": f"Bearer {self._access_token}"}
        
        try:
            async with self._session.request(method, url, headers=headers, **kwargs) as resp:
                if resp.status == 401:
                    _LOGGER.debug("Token expiré, ré-authentification…")
                    await self.authenticate()
                    headers = {"Authorization": f"Bearer {self._access_token}"}
                    async with self._session.request(method, url, headers=headers, **kwargs) as resp2:
                        if resp2.status == 403:
                            raise WafBlockedError(f"WAF 403 sur {method} {url} (après ré-auth).")
                        resp2.raise_for_status()
                        return json.loads(await resp2.text())
                if resp.status == 403:
                    raise WafBlockedError(f"WAF 403 sur {method} {url}.")
                resp.raise_for_status()
                return json.loads(await resp.text())
        except (WafBlockedError, AuthenticationError):
            raise
        except aiohttp.ClientResponseError as err:
            raise ApiError(f"HTTP {err.status} sur {method} {url}: {err.message}") from err
        except aiohttp.ClientError as err:
            raise NetworkError(f"Erreur réseau sur {method} {url}: {err}") from err

    async def _do_get(self, url: str, params: dict | None = None) -> Any:
        """GET authentifié sur URL complète, avec retry sur 401 (token expiré)."""
        return await self._request("GET", url, params=params)

    async def _do_post(self, url: str, body: dict | None = None) -> Any:
        """POST authentifié sur URL complète, avec retry sur 401 (token expiré)."""
        return await self._request("POST", url, json=body or {})

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
    ) -> dict[str, Any]:
        """Récupère les consommations journalières avec fallback et métadonnées.

        Stratégie :
        1. Tente 90 jours (ou nb_jours passé).
        2. Si échec ou 0 entrée, tente 30 jours (fallback automatique).
        3. Tente mode expérimental puis legacy.

        Retourne un dict :
        {
            "entries":    list[dict],  # entrées formatées
            "source":     str,         # source des données
            "nb_entries": int,         # nombre d'entrées
            "last_date":  str | None,  # date de la dernière entrée
        }
        """
        result = await self._fetch_daily_raw(contract_id, nb_jours)
        
        # Fallback 30 jours si 90 jours ne donne rien
        if not result["entries"] and nb_jours > 30:
            _LOGGER.debug(
                "Zéro donnée journalière pour %s sur %d jours, tentative sur 30 jours...",
                contract_id, nb_jours
            )
            result = await self._fetch_daily_raw(contract_id, 30)
            
        return result

    async def _fetch_daily_raw(self, contract_id: str, nb_jours: int) -> dict[str, Any]:
        """Implémentation interne de la récupération journalière.

        Stratégie (indépendante du mode expérimental) :
        1. Tente toujours le nouvel endpoint /rest/produits/…/consommationsJournalieres
           → confirmé HTTP 200 en production (browser inspection 2026-04-26).
        2. Si le nouvel endpoint échoue (404, erreur), fallback sur les anciens endpoints legacy.

        Le mode expérimental ne change pas la logique journalière — il est conservé pour
        d'autres fonctionnalités (factures, courbe de charge, etc.).
        """
        entries: list[dict] = []
        source = "Aucune"

        # Étape 1 : Nouvel endpoint (toujours tenté — /rest/produits/ sans /application/)
        entries = await self._get_daily_new(contract_id, nb_jours)
        if entries:
            source = "Produits (2026)"

        # Étape 2 : Fallback legacy si le nouvel endpoint n'a rien retourné
        if not entries:
            entries, source = await self._get_daily_legacy(contract_id, nb_jours)

        last_date = entries[-1].get("date") if entries else None

        return {
            "entries":    self.format_daily_consumptions(entries, contract_id),
            "source":     source,
            "nb_entries": len(entries),
            "last_date":  last_date,
        }

    async def _get_daily_new(self, contract_id: str, nb_jours: int) -> list[dict]:
        """Endpoint /rest/produits/…/consommationsJournalieres (confirmé HTTP 200 en prod).

        La page Angular envoie systématiquement une plage de 2 ans. On fait de même
        pour maximiser les chances d'obtenir des données, puis on filtre côté client
        pour ne garder que les nb_jours derniers jours si l'appelant le souhaite.

        Réponse attendue : {"postes": [{"data": [{annee, mois(0-idx), jour, consommation, …}]}],
                            "unites": {"consommation": "L", "index": "m3"}}
        """
        try:
            date_fin = datetime.now(timezone.utc)
            # Plage 2 ans — conforme à l'appel observé dans le browser (2026-04-26)
            date_debut = date_fin.replace(year=date_fin.year - 2)
            params = {
                "dateDebut": date_debut.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "dateFin":   date_fin.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
            data = await self._get_produits(
                f"contrats/{contract_id}/consommationsJournalieres", params
            )
            entries = self._parse_daily_response(data)

            if entries:
                entries.sort(key=lambda x: x.get("date", ""))
                _LOGGER.debug(
                    "Données journalières /rest/produits/ OK contrat %s : %d entrées",
                    contract_id, len(entries),
                )
            return entries

        except ApiError as err:
            if "404" in str(err):
                _LOGGER.debug(
                    "Endpoint /rest/produits/…/consommationsJournalieres → 404 (contrat %s)",
                    contract_id,
                )
            else:
                _LOGGER.debug(
                    "Erreur endpoint journalier /rest/produits/ (contrat %s) : %s",
                    contract_id, err,
                )
            return []
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "Erreur inattendue endpoint journalier /rest/produits/ (contrat %s) : %s",
                contract_id, err,
            )
            return []

    async def _get_daily_legacy(
        self, contract_id: str, nb_jours: int
    ) -> tuple[list[dict], str]:
        """Anciens endpoints journaliers avec identification de la source."""
        endpoints = [
            (
                f"/application/rest/interfaces/ael/contrats/{contract_id}"
                f"/consommationsJournalieres?nbJours={nb_jours}",
                "Legacy (Standard)",
            ),
            (
                f"/application/rest/interfaces/ael/contrats/{contract_id}"
                f"/consommationsDailyPeriode?nbJours={nb_jours}",
                "Legacy (Période)",
            ),
        ]

        for url, source_name in endpoints:
            try:
                data = await self._get(url)
                entries = self._parse_daily_response(data)

                if entries:
                    entries.sort(key=lambda x: x.get("date", ""))
                    _LOGGER.debug(
                        "Données journalières %s OK contrat %s : %d entrées",
                        source_name, contract_id, len(entries),
                    )
                    return entries, source_name

            except ApiError as err:
                _LOGGER.debug(
                    "Endpoint journalier %s non disponible pour %s : %s",
                    source_name, contract_id, err,
                )
                continue
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug(
                    "Erreur sur %s (contrat %s) : %s", source_name, contract_id, err
                )
                continue

        return [], "Aucune"

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

    async def get_date_prochaine_facture(self, contract_id: str) -> str | None:
        """Retourne la date de la prochaine facture (ISO YYYY-MM-DD) ou None.

        Endpoint confirmé HTTP 200 en production (browser inspection 2026-04-26) :
          GET /rest/produits/contrats/{id}/dateProchaineFacture

        Retourne None si indisponible ou si l'endpoint échoue.
        """
        try:
            data = await self._do_get(
                f"{BASE_URL}/application/rest/produits/contrats"
                f"/{contract_id}/dateProchaineFacture"
            )
            # La réponse peut être une chaîne ISO, un dict {"date": "..."} ou {"value": "..."}
            if isinstance(data, str):
                return data[:10] if len(data) >= 10 else None
            if isinstance(data, dict):
                raw = data.get("date") or data.get("value") or data.get("dateProchaineFacture")
                return str(raw)[:10] if raw else None
            return None
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Erreur get_date_prochaine_facture (contrat %s) : %s", contract_id, err)
            return None

    async def get_point_de_service_etendu(self, contract_id: str) -> dict:
        """Retourne les données étendues du point de service.

        Endpoint confirmé HTTP 200 en production (browser inspection 2026-04-26).
        Champs clés retournés :
          - communicabiliteAMM  : bool — compteur Téléo communicant
          - modeReleve          : str  — "AMM" ou "RELEVE_TERRAIN"
          - dateProchaineReleveReelle : ISO — date du prochain relevé compteur
          - consommationAnnuelleReference : float — conso de référence (m³/an)
          - niveauDeTension / typeTension : type de raccordement
          - nbCadransCompteur  : int — nombre de cadrans

        Retourne {} si indisponible.
        """
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
                f"{BASE_URL}/application/rest/produits/contrats"
                f"/{contract_id}/pointDeService",
                params={"select": select, "expand": expand},
            )
            if not isinstance(data, dict):
                return {}

            # Extraire consommationAnnuelleReference depuis la période active la plus récente
            conso_ref = None
            for periode in data.get("periodesActiviteProfil", []):
                v = periode.get("consommationAnnuelleReference")
                if v is not None:
                    try:
                        conso_ref = float(v)
                    except (ValueError, TypeError):
                        pass

            return {
                "communicabilite_amm":    data.get("communicabiliteAMM"),
                "mode_releve":            data.get("modeReleve"),
                "date_prochaine_releve":  (data.get("dateProchaineReleveReelle") or "")[:10] or None,
                "niveau_tension":         data.get("niveauDeTension"),
                "type_tension":           data.get("typeTension"),
                "nb_cadrans":             data.get("nbCadransCompteur"),
                "conso_annuelle_ref_m3":  conso_ref,
                "reference_pds":          data.get("reference"),
            }
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "Erreur get_point_de_service_etendu (contrat %s) : %s", contract_id, err
            )
            return {}

    async def get_interventions(self) -> list[dict]:
        """Retourne les interventions terrain planifiées (releveur, technicien…).

        Endpoint confirmé HTTP 200 en production (browser inspection 2026-04-26).
        Filtre : interventions planifiées (modePlanification=7),
                 à domicile (modeRealisation=1),
                 présence client nécessaire,
                 statuts : planifiée (4), en cours (9) ou demandée (0).

        Retourne une liste de dicts normalisés avec :
          - reference        : str
          - type             : str (libellé du sous-type)
          - statut           : str (libellé du statut)
          - date_debut       : str YYYY-MM-DD
          - date_fin         : str YYYY-MM-DD
          - presence_requise : bool
          - contrat_ref      : str
        """
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
            raw_list = []
            if isinstance(data, list):
                raw_list = data
            elif isinstance(data, dict):
                raw_list = data.get("content", data.get("_embedded", {}).get("interventions", []))

            result = []
            for item in raw_list:
                try:
                    svc = item.get("serviceSouscrit") or {}
                    contrat = svc.get("contrat") or {}
                    sous_type = item.get("sousType") or {}
                    statut_raw = item.get("statut")

                    date_debut = (item.get("dateDebutPrevue") or "")[:10] or None
                    date_fin   = (item.get("dateFinPrevue")   or date_debut or "")[:10] or None

                    result.append({
                        "reference":        item.get("reference", ""),
                        "type":             sous_type.get("libelle", "") if isinstance(sous_type, dict) else str(sous_type),
                        "statut":           str(statut_raw) if statut_raw is not None else "",
                        "date_debut":       date_debut,
                        "date_fin":         date_fin,
                        "presence_requise": bool(item.get("presenceDuClientNecessaire", False)),
                        "contrat_ref":      contrat.get("reference", ""),
                    })
                except (KeyError, TypeError, AttributeError):
                    continue

            _LOGGER.debug("Interventions planifiées : %d trouvées", len(result))
            return result

        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Erreur get_interventions : %s", err)
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
            entries = self._parse_daily_response(data)

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
        await self._ensure_auth()
        url = f"{BASE_URL}/rest/produits/factures/{invoice_ref}/document"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        try:
            async with self._session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    raise NetworkError(f"Erreur téléchargement PDF ({resp.status})")
                return await resp.read()
        except aiohttp.ClientError as err:
            raise NetworkError(f"Erreur réseau lors du téléchargement PDF: {err}") from err

    async def get_water_quality(self) -> dict:
        """Récupère la qualité de l'eau depuis l'Open Data de la Métropole de Lyon.

        Source : data.grandlyon.com (sans authentification).
        Retourne un dict avec les clés : durete_fh, nitrates_mgl, chlore_mgl,
        turbidite_ntu, commune, date_analyse. Chaque valeur est None si indisponible.

        Ce service est best-effort : en cas d'échec, retourne un dict de None sans planter.
        """
        _OPENDATA_URL = (
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
            "source": "Open Data Métropole de Lyon",
        }
        try:
            async with self._session.get(
                _OPENDATA_URL,
                headers={"Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("[OPEN DATA] Qualité eau → HTTP %s", resp.status)
                    return empty
                data = json.loads(await resp.text())

            values = data.get("values", [])
            if not values:
                _LOGGER.debug("[OPEN DATA] Qualité eau → réponse vide")
                return empty

            row = values[0]

            def _safe_float(val: object) -> float | None:
                try:
                    return float(val) if val is not None else None
                except (ValueError, TypeError):
                    return None

            return {
                "durete_fh":     _safe_float(row.get("durete")),
                "nitrates_mgl":  _safe_float(row.get("nitrates")),
                "chlore_mgl":    _safe_float(row.get("chloreresiduel")),
                "turbidite_ntu": _safe_float(row.get("turbidite")),
                "commune":       row.get("commune"),
                "date_analyse":  (row.get("dateanalyse") or "")[:10] or None,
                "source":        "Open Data Métropole de Lyon",
            }
        except aiohttp.ClientError as err:
            _LOGGER.debug("[OPEN DATA] Erreur réseau qualité eau : %s", err)
            return empty
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[OPEN DATA] Erreur inattendue qualité eau : %s", err)
            return empty


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
    def format_daily_consumptions(raw_entries: list[dict], contract_id: str = "inconnu") -> list[dict]:
        """Enrichit les entrées journalières brutes avec parsing multi-clés.

        Vérifie successivement les clés: consommation, volume, quantite, valeur.
        Log un WARNING si aucune donnée de consommation n'est trouvée.
        """
        result = []
        nb_with_conso = 0
        for e in raw_entries:
            try:
                conso = EauGrandLyonApi._extract_conso(e)
                entry: dict = {
                    "date":            e.get("date", ""),
                    "consommation_m3": conso if conso is not None else 0.0,
                }
                if conso is not None:
                    nb_with_conso += 1

                # Champs expérimentaux — présents seulement sur compteurs Téléo récents
                has_exp = False
                for src_key, dst_key in [
                    ("volumeFuiteEstime", "volume_fuite_estime_m3"),
                    ("debitMin",          "debit_min_m3h"),
                ]:
                    val = e.get(src_key)
                    if val is not None:
                        try:
                            entry[dst_key] = float(val)
                            has_exp = True
                        except (ValueError, TypeError):
                            pass
                
                # Extraction de l'index avec synonymes (hufon robust pattern)
                idx_val = EauGrandLyonApi._extract_index(e)
                if idx_val is not None:
                    entry["index_m3"] = idx_val
                    has_exp = True

                if conso is not None or has_exp:
                    result.append(entry)
            except (ValueError, TypeError):
                _LOGGER.debug("Entrée journalière ignorée (format inattendu) : %s", e)
        
        if raw_entries and nb_with_conso == 0:
            _LOGGER.warning(
                "Le parsing des volumes journaliers pour le contrat %s a échoué : "
                "aucune clé reconnue (consommation, volume, quantite, valeur) "
                "dans les %d entrées reçues. Les compteurs d'eau ne seront pas mis à jour.", 
                contract_id, len(raw_entries)
            )
        elif not raw_entries:
            _LOGGER.warning(
                "Aucune donnée journalière reçue de l'API pour le contrat %s "
                "(le compteur n'est probablement pas compatible Téléo/TIC).", 
                contract_id
            )

        return result

    @staticmethod
    def _extract_index(entry: dict) -> float | None:
        """Extrait l'index cumulé via une large liste de synonymes (Robust Index Parsing).
        
        Clés supportées (inspiré du fork hufon) :
        - index, indexCompteur, index_compteur
        - releve, releveCompteur, volumeCompteur
        - volume_cumule, consommationCumulee, consommation_cumulee
        """
        for key in (
            "index", "indexCompteur", "index_compteur",
            "releve", "releveCompteur", "volumeCompteur",
            "volume_cumule", "consommationCumulee", "consommation_cumulee"
        ):
            if key in entry:
                try:
                    val = float(entry[key] or 0)
                    # Guess Litres vs m3 : si la valeur brute est > 100000 
                    # sur un index journalier, c'est probablement des Litres.
                    if val > 100000:
                        return round(val / 1000, 3)
                    return round(val, 3)
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _extract_conso(entry: dict) -> float | None:
        """Extrait la valeur de consommation via plusieurs clés possibles."""
        for key in ("consommation", "volume", "quantite", "valeur"):
            if key in entry:
                try:
                    return float(entry[key] or 0)
                except (ValueError, TypeError):
                    continue
        return None

    @staticmethod
    def _parse_daily_response(data: Any) -> list[dict]:
        """Parse les différentes structures de réponse possibles pour le journalier.

        Gère deux formats principaux :

        Format « postes » (nouveau endpoint /rest/produits/…/consommationsJournalieres) :
          {
            "postes": [{"data": [{"annee": 2024, "mois": 3, "jour": 15,
                                  "consommation": 120, "index": …, "estime": false,
                                  "volumeEstimeFuite": 0}]}],
            "unites": {"consommation": "L", "index": "m3"}
          }
          ⚠️  "mois" est 0-indexed (style JavaScript : 0=janvier … 11=décembre).
          ⚠️  "consommation" peut être en Litres — converti en m³ si unites.consommation == "L".

        Format « liste plate » (anciens endpoints legacy) :
          [{"date": "2024-04-15", "consommation": 0.120, …}]
          ou {"data": […]} / {"consommationsJournalieres": […]}
          Dans ce cas "mois" est 1-indexed et la valeur est déjà en m³.
        """
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

        # ── Normalisation du format « postes » ────────────────────────────────
        conso_unit = (unites.get("consommation") or "").upper()  # "L" ou "M3" ou ""

        # ── Auto-détection de l'encodage des mois (0-indexed vs 1-indexed) ────
        # Inspiré du fork hufon : on calcule un score sur un échantillon d'entrées.
        # Si plus de la moitié des mois sont 0-indexed (0-11), on applique +1.
        # Si les mois sont déjà 1-indexed (1-12), on ne touche pas.
        month_offset = _detect_month_offset(entries)

        # ── Auto-inférence d'unité par magnitude si unité non déclarée ────────
        # Si l'API ne précise pas l'unité mais que les valeurs médianes sont > 100,
        # ce sont probablement des Litres (1 personne/jour ≈ 100-200 L).
        if not conso_unit:
            conso_unit = _infer_unit_from_magnitude(entries)

        normalized: list[dict] = []
        for e in entries:
            entry = dict(e)

            # 1. Construire le champ "date" manquant
            if "date" not in entry and "annee" in entry and "mois" in entry:
                try:
                    annee = int(entry["annee"])
                    mois_1based = int(entry["mois"]) + month_offset
                    # Borner 1-12 pour éviter les dates invalides
                    mois_1based = max(1, min(12, mois_1based))
                    jour = int(entry.get("jour") or 1)
                    entry["date"] = f"{annee}-{mois_1based:02d}-{jour:02d}"
                except (ValueError, TypeError):
                    pass

            # 2. Convertir Litres → m³
            if conso_unit == "L" and "consommation" in entry:
                try:
                    entry["consommation"] = float(entry["consommation"]) / 1000.0
                except (ValueError, TypeError):
                    pass

            # 3. Harmoniser le nom du champ de fuite estimée
            #    API retourne "volumeEstimeFuite", format_daily_consumptions attend "volumeFuiteEstime"
            if "volumeEstimeFuite" in entry and "volumeFuiteEstime" not in entry:
                entry["volumeFuiteEstime"] = entry.pop("volumeEstimeFuite")

            normalized.append(entry)

        return normalized

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
            "teleo_compatible": bool(module),
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
