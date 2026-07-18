"""Tests de concurrence réels sur la couche d'authentification.

Valide le verrou anti-tempête : lorsqu'un cycle lance plusieurs requêtes en
parallèle et que le token expire, chaque requête reçoit un 401 et appelle
`authenticate()` en même temps. Sans dédoublonnage, N flux OAuth complets
partiraient simultanément contre un WAF agressif. Le premier ré-authentifie,
les suivants réutilisent le token fraîchement obtenu.
"""
import asyncio
from unittest.mock import MagicMock

import pytest

from custom_components.eau_grand_lyon.api.auth import EauGrandLyonAuth


def _make_auth():
    return EauGrandLyonAuth(session=MagicMock(), email="user@example.com", password="secret")


class TestAuthConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_reauth_triggers_single_login(self):
        """Tempête de 401 : un seul vrai login, tous récupèrent le même token frais."""
        auth = _make_auth()
        auth._access_token = "expired-token"  # ce que chaque requête en vol détenait
        logins = 0

        async def fake_login(urls, correlation_id):
            nonlocal logins
            logins += 1
            await asyncio.sleep(0.01)  # simule la latence réseau du flux OAuth
            auth._access_token = f"fresh-token-{logins}"
            return auth._access_token

        auth._authenticate_with_urls = fake_login

        results = await asyncio.gather(*[auth.authenticate() for _ in range(5)])

        assert logins == 1, "un seul flux OAuth devait partir malgré 5 appels concurrents"
        assert set(results) == {"fresh-token-1"}, "tous les appelants réutilisent le token frais"
        assert auth._access_token == "fresh-token-1"

    @pytest.mark.asyncio
    async def test_concurrent_initial_auth_triggers_single_login(self):
        """Premier démarrage : plusieurs appels concurrents sans token → un seul login."""
        auth = _make_auth()
        auth._access_token = None
        logins = 0

        async def fake_login(urls, correlation_id):
            nonlocal logins
            logins += 1
            await asyncio.sleep(0.01)
            auth._access_token = "the-token"
            return auth._access_token

        auth._authenticate_with_urls = fake_login

        results = await asyncio.gather(*[auth.authenticate() for _ in range(4)])

        assert logins == 1
        assert set(results) == {"the-token"}

    @pytest.mark.asyncio
    async def test_sequential_reauth_after_completion_relogins(self):
        """Une ré-auth explicite lancée APRÈS coup (token inchangé) relance bien un login."""
        auth = _make_auth()
        auth._access_token = None
        logins = 0

        async def fake_login(urls, correlation_id):
            nonlocal logins
            logins += 1
            auth._access_token = f"token-{logins}"
            return auth._access_token

        auth._authenticate_with_urls = fake_login

        first = await auth.authenticate()
        # Le token n'a pas changé côté serveur entre-temps → nouveau login légitime.
        second = await auth.authenticate()

        assert logins == 2
        assert first != second
