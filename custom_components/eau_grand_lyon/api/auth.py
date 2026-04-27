"""PKCE OAuth helpers for Eau du Grand Lyon."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import aiohttp

from .endpoints import (
    AUTHORIZE_URL,
    BROWSER_NAV_HEADERS,
    CLIENT_ID,
    CODE_VERIFIER,
    LOGIN_URL,
    NEW_AUTHORIZE_URL,
    NEW_LOGIN_URL,
    NEW_TOKEN_URL,
    REDIRECT_URI,
    TOKEN_REVOKE_URL,
    TOKEN_URL,
)

_LOGGER = logging.getLogger(__name__)


def _new_correlation_id() -> str:
    return uuid.uuid4().hex[:12]


def _log_http_event(
    *,
    phase: str,
    correlation_id: str,
    method: str,
    url: str,
    duration_ms: float,
    status: int | None = None,
    error: Exception | None = None,
) -> None:
    extra = {
        "correlation_id": correlation_id,
        "http_method": method,
        "http_url": url,
        "duration_ms": round(duration_ms, 1),
        "phase": phase,
    }
    if status is not None:
        extra["http_status"] = status
    if error is None:
        _LOGGER.debug(
            "api_http phase=%s cid=%s method=%s status=%s duration_ms=%.1f url=%s",
            phase,
            correlation_id,
            method,
            status,
            duration_ms,
            url,
            extra=extra,
        )
    else:
        extra["error_type"] = type(error).__name__
        _LOGGER.warning(
            "api_http phase=%s cid=%s method=%s status=%s duration_ms=%.1f url=%s error=%s",
            phase,
            correlation_id,
            method,
            status,
            duration_ms,
            url,
            type(error).__name__,
            extra=extra,
        )


class AuthenticationError(Exception):
    """Identifiants invalides ou flux OAuth2 echoue."""


class WafBlockedError(Exception):
    """Le WAF Apache a bloque la requete (HTTP 403)."""


class ApiError(Exception):
    """Erreur generique lors d'un appel API."""


class NetworkError(Exception):
    """Erreur reseau / timeout lors d'un appel API."""


def _compute_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _extract_code_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    code = qs.get("code", [None])[0]
    if not code:
        frag = parse_qs(parsed.fragment)
        code = frag.get("code", [None])[0]
    return code


@dataclass(frozen=True)
class AuthUrls:
    """URLs required for one authentication attempt."""

    login_url: str
    authorize_url: str
    token_url: str


class EauGrandLyonAuth:
    """OAuth2 PKCE authenticator bound to a client session."""

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
        self._experimental = experimental
        self._auth_mode = "new" if experimental else "legacy"
        self._access_token: str | None = None

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @access_token.setter
    def access_token(self, value: str | None) -> None:
        self._access_token = value

    async def authenticate(self, correlation_id: str | None = None) -> str:
        correlation_id = correlation_id or _new_correlation_id()
        _LOGGER.debug("auth_start cid=%s mode=%s", correlation_id, self._auth_mode)
        if self._experimental and self._auth_mode == "new":
            try:
                token = await self._authenticate_with_urls(
                    AuthUrls(NEW_LOGIN_URL, NEW_AUTHORIZE_URL, NEW_TOKEN_URL),
                    correlation_id,
                )
                _LOGGER.debug("auth_success cid=%s mode=new", correlation_id)
                return token
            except ApiError as err:
                _LOGGER.warning(
                    "[EXPERIMENTAL] auth_fallback cid=%s nouvelles URLs auth echouees (%s) -> fallback legacy",
                    correlation_id,
                    err,
                )
                self._auth_mode = "legacy"
            except NetworkError as err:
                _LOGGER.warning(
                    "[EXPERIMENTAL] auth_fallback cid=%s erreur reseau nouvelles URLs auth (%s) -> fallback legacy",
                    correlation_id,
                    err,
                )
                self._auth_mode = "legacy"

        token = await self._authenticate_with_urls(
            AuthUrls(LOGIN_URL, AUTHORIZE_URL, TOKEN_URL),
            correlation_id,
        )
        if self._experimental:
            _LOGGER.debug("auth_success cid=%s mode=legacy", correlation_id)
        return token

    async def _authenticate_with_urls(self, urls: AuthUrls, correlation_id: str) -> str:
        start = time.perf_counter()
        try:
            async with self._session.post(
                urls.login_url,
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
            _log_http_event(
                phase="auth_login",
                correlation_id=correlation_id,
                method="POST",
                url=urls.login_url,
                duration_ms=(time.perf_counter() - start) * 1000,
                status=login_status,
            )
        except aiohttp.ClientError as err:
            _log_http_event(
                phase="auth_login",
                correlation_id=correlation_id,
                method="POST",
                url=urls.login_url,
                duration_ms=(time.perf_counter() - start) * 1000,
                error=err,
            )
            raise NetworkError(f"Impossible de joindre le serveur: {err}") from err

        if login_status == 401:
            raise AuthenticationError(
                "Identifiants incorrects. Verifiez votre email et mot de passe."
            )
        if login_status == 403:
            raise WafBlockedError(
                "Le WAF a bloque la requete de login (HTTP 403). "
                "Attendez quelques minutes avant de reessayer."
            )
        if login_status == 404:
            raise ApiError(f"URL de login non trouvee (404): {urls.login_url}")
        if login_status not in (200, 204):
            raise ApiError(f"Login echoue ({login_status}): {login_body[:200]}")

        code_challenge = _compute_code_challenge(CODE_VERIFIER)
        params = {
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "client_id": CLIENT_ID,
        }
        start = time.perf_counter()
        try:
            async with self._session.get(
                urls.authorize_url,
                params=params,
                headers=BROWSER_NAV_HEADERS,
                allow_redirects=True,
            ) as resp:
                status = resp.status
                if resp.status == 403:
                    raise WafBlockedError(
                        "Le WAF a bloque la requete authorize-internet (HTTP 403)."
                    )
                if resp.status == 404:
                    raise ApiError(
                        f"URL authorize non trouvee (404): {urls.authorize_url}"
                    )
                final_url = str(resp.url)
            _log_http_event(
                phase="auth_authorize",
                correlation_id=correlation_id,
                method="GET",
                url=urls.authorize_url,
                duration_ms=(time.perf_counter() - start) * 1000,
                status=status,
            )
        except (WafBlockedError, ApiError):
            _log_http_event(
                phase="auth_authorize",
                correlation_id=correlation_id,
                method="GET",
                url=urls.authorize_url,
                duration_ms=(time.perf_counter() - start) * 1000,
                error=None,
                status=403 if "403" in str(locals().get("resp", "")) else None,
            )
            raise
        except aiohttp.ClientError as err:
            _log_http_event(
                phase="auth_authorize",
                correlation_id=correlation_id,
                method="GET",
                url=urls.authorize_url,
                duration_ms=(time.perf_counter() - start) * 1000,
                error=err,
            )
            raise NetworkError(f"Erreur reseau sur /authorize: {err}") from err

        code = _extract_code_from_url(final_url)
        if not code:
            raise AuthenticationError(
                f"Pas de code d'autorisation dans l'URL de callback: {final_url[:200]}"
            )

        return await self._exchange_code(code, urls.token_url, correlation_id)

    async def _exchange_code(self, code: str, token_url: str, correlation_id: str) -> str:
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": CODE_VERIFIER,
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
        }
        start = time.perf_counter()
        try:
            async with self._session.post(
                token_url,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                status = resp.status
                if resp.status == 403:
                    raise WafBlockedError("Le WAF a bloque l'echange de token (HTTP 403).")
                if resp.status == 404:
                    raise ApiError(f"URL token non trouvee (404): {token_url}")
                if resp.status != 200:
                    body = await resp.text()
                    raise AuthenticationError(
                        f"Echange de token echoue ({resp.status}): {body[:200]}"
                    )
                result: dict = json.loads(await resp.text())
            _log_http_event(
                phase="auth_token",
                correlation_id=correlation_id,
                method="POST",
                url=token_url,
                duration_ms=(time.perf_counter() - start) * 1000,
                status=status,
            )
        except (WafBlockedError, AuthenticationError, ApiError):
            _log_http_event(
                phase="auth_token",
                correlation_id=correlation_id,
                method="POST",
                url=token_url,
                duration_ms=(time.perf_counter() - start) * 1000,
                error=None,
                status=locals().get("status"),
            )
            raise
        except aiohttp.ClientError as err:
            _log_http_event(
                phase="auth_token",
                correlation_id=correlation_id,
                method="POST",
                url=token_url,
                duration_ms=(time.perf_counter() - start) * 1000,
                error=err,
            )
            raise NetworkError(f"Requete token echouee: {err}") from err

        if "access_token" not in result:
            raise AuthenticationError(f"Pas d'access_token dans la reponse: {result}")

        self._access_token = result["access_token"]
        _LOGGER.debug("Authentification reussie cid=%s pour %s", correlation_id, self._email)
        return self._access_token

    async def revoke_token(self, correlation_id: str | None = None) -> None:
        if not self._access_token:
            return
        correlation_id = correlation_id or _new_correlation_id()
        start = time.perf_counter()
        try:
            async with self._session.post(
                TOKEN_REVOKE_URL,
                data={"token": self._access_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                _log_http_event(
                    phase="auth_revoke",
                    correlation_id=correlation_id,
                    method="POST",
                    url=TOKEN_REVOKE_URL,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    status=resp.status,
                )
        except Exception as err:
            _log_http_event(
                phase="auth_revoke",
                correlation_id=correlation_id,
                method="POST",
                url=TOKEN_REVOKE_URL,
                duration_ms=(time.perf_counter() - start) * 1000,
                error=err,
            )
            _LOGGER.debug("Echec revocation token (best-effort, ignore)")
        finally:
            self._access_token = None
