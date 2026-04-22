"""Constantes pour l'intégration Eau du Grand Lyon."""

DOMAIN = "eau_grand_lyon"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Options configurables
CONF_UPDATE_INTERVAL_HOURS = "update_interval_hours"
DEFAULT_UPDATE_INTERVAL_HOURS = 24

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

