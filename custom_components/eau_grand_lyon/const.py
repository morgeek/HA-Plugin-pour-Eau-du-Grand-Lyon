"""Constantes pour l'intégration Eau du Grand Lyon."""

DOMAIN = "eau_grand_lyon"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Options configurables
CONF_UPDATE_INTERVAL_HOURS = "update_interval_hours"
DEFAULT_UPDATE_INTERVAL_HOURS = 24

CONF_MAX_RETRIES = "max_retries"
DEFAULT_MAX_RETRIES = 3

CONF_TARIF_M3 = "tarif_m3"
# Tarif indicatif Eau du Grand Lyon — TTC, tout inclus (eau + assainissement + taxes)
# Valeur 2024 : 5,20 €/m³ — à vérifier et mettre à jour selon votre facture annuelle
# Modifiable directement depuis les options de l'intégration dans HA
DEFAULT_TARIF_M3 = 5.20

# Mode expérimental — nouveaux endpoints découverts dans le bundle Angular 2026
# Active : /rest/produits/factures, /rest/produits/contrats/{id}/consommationsJournalieres
#          (avec dateDebut/dateFin), /rest/interfaces/ael/contrats/{id}/courbeDeCharge,
#          et la tentative des nouvelles URLs d'authentification (sans /application/).
# Les anciens endpoints restent en fallback automatique — rien ne casse.
CONF_EXPERIMENTAL = "experimental_api"
DEFAULT_EXPERIMENTAL = False

# Entité de prix dynamique (optionnel)
CONF_PRICE_ENTITY = "price_entity"

# Intelligence & Coaching
CONF_HOUSEHOLD_SIZE = "household_size"
DEFAULT_HOUSEHOLD_SIZE = 2

CONF_WATER_HARDNESS = "water_hardness"
DEFAULT_WATER_HARDNESS = 30.0  # °fH (Moyenne Lyon)

# Tuning runtime comportement
RATE_LIMIT_DELAY_S = 30.0
WAF_RETRY_BASE_DELAY_S = 60.0
NETWORK_RETRY_BASE_DELAY_S = 10.0
RETRY_BACKOFF_MULTIPLIER = 2.0
RETRY_JITTER_RATIO = 0.2
LEAK_MULTIPLIER = 2
CACHE_MAX_AGE_DAYS = 30

# Abonnement annuel fixe (hors consommation) pour calcul du coût réel
# Comprend : part fixe abonnement eau + assainissement (hors consommation)
# Valeur indicative Grand Lyon 2024 : ~180€/an — à ajuster selon votre facture
CONF_SUBSCRIPTION_ANNUAL = "subscription_annual"
DEFAULT_SUBSCRIPTION_ANNUAL = 0.0  # 0 = fonctionnement identique à avant
