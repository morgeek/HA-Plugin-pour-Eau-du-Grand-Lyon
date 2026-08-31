"""Constantes pour l'intégration Eau du Grand Lyon."""

DOMAIN = "eau_grand_lyon"

# Prefixes des statistiques externes recorder. Les suffixes font partie de
# l'API publique de l'intégration et ne doivent pas être renommés.
STATISTIC_WATER = "water"
STATISTIC_WATER_DAILY = "water_daily"
STATISTIC_COST = "cost"
STATISTIC_COST_DAILY = "cost_daily"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Options configurables
CONF_UPDATE_INTERVAL_HOURS = "update_interval_hours"
DEFAULT_UPDATE_INTERVAL_HOURS = 24

CONF_MAX_RETRIES = "max_retries"
DEFAULT_MAX_RETRIES = 3

CONF_TARIF_M3 = "tarif_m3"
# Repli historique conservé pour les entrées en mode manuel. Les nouvelles
# entrées utilisent par défaut la dernière facture TTC, ou la grille 2026 si
# aucun couple montant/volume exploitable n'est disponible.
DEFAULT_TARIF_M3 = 5.20

# Source des estimations de coût. Les entrées existantes sont migrées vers le
# mode manuel/dynamique pour préserver leur comportement ; les nouvelles
# entrées utilisent le montant TTC de la dernière facture quand il est fourni.
CONF_TARIFF_MODE = "tariff_mode"
TARIFF_MODE_LATEST_INVOICE = "latest_invoice"
TARIFF_MODE_OFFICIAL_2026 = "official_2026"
TARIFF_MODE_MANUAL = "manual"
TARIFF_MODE_DYNAMIC = "dynamic"
TARIFF_MODES = [
    TARIFF_MODE_LATEST_INVOICE,
    TARIFF_MODE_OFFICIAL_2026,
    TARIFF_MODE_MANUAL,
    TARIFF_MODE_DYNAMIC,
]
DEFAULT_TARIFF_MODE = TARIFF_MODE_LATEST_INVOICE

# Mode expérimental — données Téléo étendues découvertes dans le bundle Angular 2026.
# Les factures sont désormais récupérées dans tous les modes.
# Active : consommationsJournalieres étendues, courbeDeCharge et tentative des
# nouvelles URLs d'authentification (sans /application/).
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

# Commune pour filtrer les mesures Open Data de qualité de l'eau.
# Vide = première mesure du jeu de données (commune arbitraire du réseau).
CONF_WATER_QUALITY_COMMUNE = "water_quality_commune"
DEFAULT_WATER_QUALITY_COMMUNE = ""

# Sources publiques optionnelles, explicitement désactivées par défaut.
CONF_PFAS_ENABLED = "pfas_enabled"
DEFAULT_PFAS_ENABLED = False
CONF_VIGIEAU_ENABLED = "vigieau_enabled"
DEFAULT_VIGIEAU_ENABLED = False

# Tuning runtime comportement
RATE_LIMIT_DELAY_S = 30.0
WAF_RETRY_BASE_DELAY_S = 60.0
NETWORK_RETRY_BASE_DELAY_S = 10.0
RETRY_BACKOFF_MULTIPLIER = 2.0
RETRY_JITTER_RATIO = 0.2
CONF_LEAK_MULTIPLIER = "leak_multiplier"
DEFAULT_LEAK_MULTIPLIER = 2.0
CACHE_MAX_AGE_DAYS = 30

# Part fixe annuelle utilisée uniquement en modes manuel et dynamique.
# Le mode officiel sélectionne automatiquement le tarif selon le calibre.
CONF_SUBSCRIPTION_ANNUAL = "subscription_annual"
DEFAULT_SUBSCRIPTION_ANNUAL = 0.0  # 0 = fonctionnement identique à avant
