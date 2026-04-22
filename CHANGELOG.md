# Changelog

Tous les changements notables apportés à cette intégration seront documentés dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
et cette intégration adhère au [Versionnage Sémantique](https://semver.org/spec/v2.0.0.html).

## [2.3.0] - 2026-04-22

### Ajouté
- **Intelligence & Écologie** : Eco-Score (A-G), Empreinte Carbone (kg CO2e) et Benchmarking lyonnais.
- **Hardware Health** : Sensors de signal radio et état de pile pour les modules Téléo.
- **Service PDF** : Téléchargement automatisé de la dernière facture officielle.
- **Suivi Sécheresse** : Intégration des niveaux de restriction du Rhône (69) et alertes via Repairs platform.
- **Mode Vacances** : Switch de surveillance renforcée avec alertes de consommation non autorisée.
- **Calendrier Pro** : Entité calendrier pour le suivi des facturations et paiements.
- **Export de Données CSV** : Nouveau service `export_data` pour l'historique complet.
- **Blueprints d'Automation** : Modèles d'alertes fuite (actionnables) et budget inclus.
- **Détection Fuite Locale** : Analyse de pattern intelligente pour les compteurs non-Téléo.
- **Index haute précision** : Alinement parfait avec le compteur physique via les données journalières.
- **Traductions** : Support complet FR/EN.
- **Robustesse** : Ajout d'un handler de migration de config (`async_migrate_entry`) pour les futures versions.
- **Optimisation** : Import différé des diagnostics pour éviter les avertissements de "blocking call" au démarrage.

### Optimisé
- **Appels API parallèles** : `asyncio.gather` pour les consommations mensuelles + journalières (2x plus rapide par contrat).
- **Injection statistiques** : n'injecte dans le recorder que lorsque de nouveaux mois sont détectés.
- **Attributs allégés** : détails journaliers limités à 14 jours dans les attributs pour réduire la taille en BDD.
- **Révocation token** : le token est révoqué côté serveur au déchargement de l'intégration.
- **Nettoyage services** : les services sont désenregistrés quand la dernière entry est supprimée.

### Modifié
- `strings.json` synchronisé avec `fr.json`/`en.json` (champ `price_entity` ajouté).
- `hacs.json` : ajout du tag `country: FR` pour la découvrabilité HACS.
- Version bumped de 2.2.5 à 2.3.0.

## [2.2.5beta] - 2026-04-22

### Ajouté
- **Mode expérimental (API 2026)** : support des nouveaux endpoints découverts dans le bundle Angular 2026.
- Nouveaux sensors : **Dernière facture** et **Fuite estimée 30 jours** (compteurs Téléo compatibles).
- Templates Lovelace mis à jour avec des cartes conditionnelles pour les fonctions expérimentales.
- Support de la courbe de charge (données sub-journalières) via API 2026.

### Modifié
- Documentation (README) mise à jour avec les informations sur l'API 2026.

## [2.2.4] - 2026-03-22

### Ajouté
- **Mode hors-ligne** : si l'API est indisponible après les retries, les sensors restent disponibles avec les dernières données connues (cache local persistant)
- Le sensor "Statut API" affiche `HORS-LIGNE` en mode cache, avec les attributs `offline_since` et `note`
- Le cache est sauvegardé sur disque — survit à un redémarrage de Home Assistant

### Corrigé
- Bug : variable `now` utilisée avant d'être définie dans `_async_update_data`

## [2.2.3] - 2026-03-22

### Corrigé
- Imports manquants dans `config_flow.py` (`logging`, `aiohttp`, `Any`) — crash au chargement
- Remplacement de `.json(content_type=None)` déprécié par `json.loads()` — compatibilité aiohttp 4.x
- Sécurisation des conversions de type dans `format_consumptions`, `format_daily_consumptions`, `parse_contract_details`
- Rate limiting basé sur `time.monotonic()` au lieu de `datetime.now()` — insensible aux changements d'heure
- Validation du type de réponse API dans `get_contracts` et `get_monthly_consumptions`
- Protection des accès directs aux champs dans `_inject_statistics`
- Version alignée dans `manifest.json`

### Modifié
- Déduplication du `device_info` des sensors globaux via classe de base `_EauGrandLyonGlobalBase`
- Déduplication du calcul `last_reset` via propriété `_current_year_str`

## [2.2.1] - 2024-12-15

### Ajouté
- Validation plus stricte des configurations au démarrage (format email, longueur mot de passe)
- Gestion d'erreurs plus spécifique dans l'API et le coordinateur
- Amélioration des logs pour le débogage

### Modifié
- Remplacement des `except Exception` génériques par des exceptions plus spécifiques
- Amélioration de la validation des données d'entrée

### Corrigé
- Gestion plus robuste des erreurs de parsing JSON et réseau

## [2.2.0] - 2024-11-XX

### Ajouté
- Support des consommations journalières (si disponible)
- Détection des mois manquants dans l'historique
- Intégration Energy Dashboard avec sensors optimisés
- Templates Lovelace complets

### Modifié
- Amélioration de la gestion des erreurs réseau avec retry
- Optimisation des appels API

## [2.1.0] - 2024-10-XX

### Ajouté
- Notifications d'alertes persistantes
- Bouton de mise à jour manuelle
- Support des coûts configurables

### Modifié
- Refactorisation de l'architecture (coordinateur + API séparés)

## [2.0.0] - 2024-09-XX

### Ajouté
- Authentification PKCE complète
- Support multi-contrats
- Sensors pour solde, statut contrat, échéance

### Modifié
- Changement majeur de l'API d'authentification

## [1.0.0] - 2024-08-XX

### Ajouté
- Intégration initiale avec sensors de consommation
- Authentification basique
- Support d'un seul contrat