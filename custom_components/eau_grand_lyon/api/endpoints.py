"""Endpoint and request constants for Eau du Grand Lyon."""
from __future__ import annotations

BASE_URL = "https://agence.eaudugrandlyon.com"
CLIENT_ID = "kwnOk0B_aqlOI6p_GVxrbf6"
REDIRECT_URI = f"{BASE_URL}/autorisation-callback.html"

LOGIN_URL = f"{BASE_URL}/application/auth/externe/authentification"
AUTHORIZE_URL = f"{BASE_URL}/application/auth/authorize-internet"
TOKEN_URL = f"{BASE_URL}/application/auth/tokenUtilisateurInternet"

NEW_LOGIN_URL = f"{BASE_URL}/auth/externe/authentification"
NEW_AUTHORIZE_URL = f"{BASE_URL}/auth/authorize-internet"
NEW_TOKEN_URL = f"{BASE_URL}/auth/tokenUtilisateurInternet"
TOKEN_REVOKE_URL = f"{BASE_URL}/auth/revoke"

PRODUITS_BASE = f"{BASE_URL}/rest/produits"
INTERFACES_AEL_BASE = f"{BASE_URL}/rest/interfaces/ael"

CODE_VERIFIER = "5"

MONTHS_FR = [
    "Janvier",
    "Fevrier",
    "Mars",
    "Avril",
    "Mai",
    "Juin",
    "Juillet",
    "Aout",
    "Septembre",
    "Octobre",
    "Novembre",
    "Decembre",
]

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

CONTRACTS_SELECT = (
    "id,reference,statutExtrait,dateEffet,dateEcheance,"
    "conditionPaiement(compteClient(solde),mensualise,modePaiement),"
    "servicesSouscrits(statut,usage,calibreCompteur,nombreHabitants),"
    "espaceDeLivraison(reference)"
)
CONTRACTS_EXPAND = "conditionPaiement(compteClient),servicesSouscrits,espaceDeLivraison"
