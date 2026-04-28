# Changelog

Tous les changements notables apportés à cette intégration seront documentés dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
et cette intégration adhère au [Versionnage Sémantique](https://semver.org/spec/v2.0.0.html).

## [2.9.0] - 2026-04-28

### Corrections de Bugs

- **AttributeError au démarrage** : Crash critique corrigé — `_current_year_str` référencée dans `extra_state_attributes` de `EauGrandLyonEnergyWaterSensor` et `EauGrandLyonEnergyCostSensor` mais jamais définie. Ajoutée dans la classe de base `_EauGrandLyonBase` (retourne `"YYYY-01-01"` pour le champ `last_reset` du tableau de bord Énergie HA).
- **Sécheresse jamais déclenchée** : `check_drought_issue()` vérifiait les niveaux `["Alerte", "Alerte Renforcée", "Crise"]`, mais `_get_drought_level()` ne retourne que `"Vigilance"` ou `"Normal"`. Résultat : aucune issue de sécheresse n'était jamais créée dans HA Repairs. Corrigé pour créer une issue quand niveau == `"Vigilance"`.
- **Coût cumulé = None quand conso = 0** : Le capteur "Coût cumulé" retournait `None` au lieu de `0.0€` quand la consommation était 0. Logique corrigée : `0 m³ × tarif = 0€` (valide), pas `unavailable`.
- **timedelta(hours=48)** : Clarté : changé en `timedelta(days=2)` pour une intention plus explicite.
- **"Économie potentielle" toujours indisponible** : La formule exigeait 24 mois d'historique, mais l'API ne retourne que 12 mois — le capteur retournait donc `None` pour tous les utilisateurs. Deux niveaux de correction :
  1. Fallback immédiat : si l'historique 24 mois n'est pas disponible, le capteur extrapole depuis la comparaison mois courant vs mois N-1 (`(conso_N-1 - conso_courant) × 12 × tarif`). L'attribut `methode` indique `"annuelle"` ou `"extrapolation_mensuelle"` pour être transparent.
  2. Solution durable : voir section "Historique mensuel" ci-dessous.
- **"Index journalier" priorité incorrecte** : `get_cumulative_index()` ignorait `index_journalier_dernier` (disponible sans mode expérimental) et tombait directement en fallback sur la somme des mois. Ordre de priorité corrigé : index SIAMM expérimental → index journalier Téléo → somme mensuelle.
- **Icônes manquantes** : Les capteurs `solde`, `conso_hier` et `last_update` n'avaient pas d'icône dans `icons.json`. Ajout de `mdi:bank-check`, `mdi:calendar-today` et `mdi:clock-check-outline`. Suppression du doublon `derniere_facture`.

### Nouvelles Fonctionnalités

#### Visualisation & Tableaux de Bord
- **Statistiques de coût injectées** : Nouvelle statistic ID `eau_grand_lyon:cost_<ref>` (EUR par mois) injectée automatiquement dans la base de données HA si un tarif est configuré. Permet au tableau de bord Énergie de HA de suivre l'historique de facturation sur 24+ mois, contre 12 mois maximum via l'API.
- **Dashboard Énergie Complet** : Fichier `lovelace/energy_dashboard_preset.yaml` — tableau de bord prêt à paster avec 10 sections : résumé jour (4 mini-cards), historique 24 mois (statistiques), graphique mensuel combiné consommation+coût, détail consommation, coûts et facturation, intelligence & coaching, Téléo (si disponible), qualité de l'eau, alertes & santé, calendrier des échéances.
- **Exemples ApexCharts** : Fichier `lovelace/monthly_chart_cards.yaml` avec 6 exemples prêts à l'emploi utilisant `custom:apexcharts-card` pour visualiser les attributs `monthly_chart_data` : bar chart consommation 12 mois, combo chart consommation + coût, cost bar chart, statistics graph eau (24 mois), statistics graph coût (24 mois), graphique détaillé mensuel.
- **Guide Configuration Énergie** : Refonte complète de `lovelace/energy_config.yaml` — documentation détaillée des sources d'eau par type de compteur (Téléo vs Standard), statistic IDs injectés, troubleshooting avec FAQ, liens vers les presets.
- **Graphiques Lovelace natifs** : Les capteurs annuels (`conso_annuelle`, `cout_annuel`) exposent désormais un attribut `monthly_chart_data` structuré : liste de 12 mois avec `{label, conso_m3, cout_eur}`. Permet aux cartes Lovelace custom de tracer directement sans dépendre des statistiques HA.

#### Services & APIs
- **Téléchargement facture sur l'appareil client** : Après le téléchargement du PDF sur le serveur HA, une notification persistante est envoyée avec un lien cliquable `[Télécharger le PDF](/local/eau_grand_lyon/latest_invoice.pdf)`. Cliquer sur le lien depuis l'app HA ou le navigateur déclenche le téléchargement directement sur l'appareil (téléphone, tablette, PC). Le lien est calculé dynamiquement depuis le chemin de sauvegarde ; si le fichier est sauvegardé hors de `/config/www/`, la notification est omise.
- **Téléchargement facture multi-contrats** : Le service `download_latest_invoice` accepte désormais un paramètre optionnel `contract_reference` pour cibler un contrat spécifique. Sans paramètre, télécharge du premier contrat avec factures (comportement antérieur). Notification inclut le numéro de contrat pour clarté. Paramètre documenté dans `services.yaml`.
- **Historique journalier flexible** : La méthode API `_get_daily_new` utilise désormais le paramètre `nb_jours` au lieu de hardcoder 2 ans. Permet aux appelants de configurer la plage (90 jours par défaut). Améliore la flexibilité pour les futures fonctionnalités.

#### Qualité du Code
- **Exception handling spécifique** : Remplacement des `except Exception:` génériques par des exceptions spécifiques dans `api/methods.py` (`fetch_invoices`, `fetch_load_curves`, `fetch_leak_estimates`) : capture uniquement `KeyError`, `TypeError`, `ValueError` pour une meilleure clarity et maintenabilité.
- **Manifest.json** : Ajout du champ `homeassistant: "2024.4.0"` pour clarifier la dépendance de version minimale Home Assistant (Gold requirement).
- **services.yaml** : Documentation complète du paramètre `contract_reference` dans le service `download_latest_invoice`.

### Historique Mensuel Cumulatif (36 mois)

L'API Eau du Grand Lyon ne retourne que 12 mois d'historique — insuffisant pour comparer deux années complètes. Le coordinateur accumule désormais l'historique mensuel contrat par contrat dans un store dédié persistant sur disque (`_monthly_history_store`) :

- **Merge intelligent** : à chaque mise à jour, les nouveaux mois de l'API sont fusionnés avec l'historique stocké. Les données fraîches priment sur les données stockées pour le même mois (dédup par `(annee, mois_index)`). Maximum 36 mois conservés.
- **N-1 annuel réel** : `conso_annuelle_n1` utilise désormais les 36 mois fusionnés — après 12 mois d'utilisation de l'intégration, le capteur "Économie potentielle" affichera une comparaison annuelle exacte au lieu d'une extrapolation.
- **Persistance** : l'historique survit aux redémarrages HA et aux mises à jour de l'intégration. La commande "Effacer le cache" réinitialise aussi cet historique.

### Qualité & Fiabilité

- **TypedDict Schema** : Remplacement du commentaire de 68 lignes dans `coordinator.py` par des définitions `TypedDict` (`ContractData`, `CoordinatorData`) — 50+ champs typés statiquement, détection des fautes de frappe à la compilation, zéro impact runtime.
- **Précision des capteurs** : Ajout de `_attr_suggested_display_precision = 2` sur les capteurs financiers pour un affichage cohérent (€).
- **Déduplication `strings.json`** : Suppression du bloc `services` en double (30 lignes) — une seule source de vérité pour les traducteurs.

### Tests & Couverture

- **213 tests** (vs 113 en v2.8.0) — +100 nouveaux tests couvrant :
  - Plateformes complètes : `binary_sensor`, `button`, `switch`, `calendar`
  - Chemins d'erreur API, config flow et global sensors
  - Benchmarks de performance : latence, débit, accès aux structures de données
  - Tests de stress concurrents : 10x et 100x appels simultanés, cohérence des données, isolation des erreurs partielles
  - `_merge_monthly_history` : override, accumulation 24 mois, tri chronologique, plafonnement

### Outillage Développeur

- **Pre-commit hooks** (`.pre-commit-config.yaml`) : `black`, `isort`, `flake8`, validation YAML/JSON, détection de clés privées — qualité garantie avant chaque commit.
- **GitHub Actions CI/CD** (`.github/workflows/test.yml`) : Tests automatisés sur Python 3.9, 3.10, 3.11 et 3.12 à chaque push et pull request, avec rapport de couverture via Codecov.
- **api/methods.py** : Fonctions utilitaires extraites de `api/client.py` (`fetch_contracts`, `fetch_monthly_consumptions`, `fetch_invoices`, `fetch_load_curves`, `fetch_leak_estimates`) — fondation pour la future modularisation du client API.

### Aucun breaking change — mise à jour transparente depuis v2.8.0

---

## [2.8.0] - 2026-04-27

### Certification Gold ⭐ Home Assistant

L'intégration atteint le **niveau Gold** de la [Qualité Scale Home Assistant](https://developers.home-assistant.io/docs/core/integration-quality-scale/).

### Nouvelles Fonctionnalités Gold

#### Flux de Configuration Améliorés
- **Réauthentification** (`async_step_reauth`) : Lorsque vos identifiants expirent, vous pouvez les mettre à jour sans supprimer l'intégration
- **Reconfiguration** (`async_step_reconfigure`) : Modifiez email, mot de passe et tarif après la configuration initiale
- **Gestion d'Erreurs** : Les 4 services lèvent maintenant `HomeAssistantError` / `ServiceValidationError` pour un meilleur suivi des erreurs

#### Interface Utilisateur
- **Icons Traduites** : Nouveau fichier `icons.json` — les icônes sont désormais gérées par traduction, pas en Python
- **Exceptions Traduites** : Messages d'erreur en français et anglais pour les services et les flux

#### Entités Catégorisées
- **Sensors Diagnostiques** : Les capteurs techniques (tendance, prédictions, alertes, santé) sont maintenant marqués `DIAGNOSTIC` et désactivés par défaut
- **Sélecteur Parallèle** : `PARALLEL_UPDATES = 0` sur tous les platforms pour conformité avec le coordinateur

#### Documentation Complète
- **Mise à jour des données** : Explique l'intervalle, la gestion du WAF et le cache persistant
- **Appareils supportés** : Tableau Téléo vs Standard avec comparaison des capacités
- **Limitations connues** : Clarité sur les données mensuelles, le WAF, et les 12 mois historiques
- **Dépannage détaillé** : Solutions pour les erreurs courantes (HORS-LIGNE, identifiants, WAF)
- **Exemples pratiques** : Alertes fuites, budgets, dashboards, exports et formules Jinja

### Qualité & Tests
- 113 tests pytest couvrant tous les capteurs critiques
- Validation hassfest complète (manifest, sélecteurs, traductions)
- Intégration CI/CD (GitHub Actions — pytest, hassfest, HACS)

## [2.7.0] - 2026-04-27

### Refonte Architecturale
- **Modularisation des Sensors** : `sensor.py` (1800 lignes) découpé en 9 modules spécialisés dans `sensors/`
  - `sensors/consumption.py` — index, journalier, mensuel, annuel, moyennes
  - `sensors/cost.py` — coûts estimés, réels, énergie, solde
  - `sensors/contract.py` — statut contrat, échéances, relevé
  - `sensors/intelligence.py` — Eco-Coach, Eco-Score, CO₂, tendances, prédictions
  - `sensors/global_sensors.py` — agrégats multi-contrats, santé API, sécheresse
  - `sensors/experimental.py` — API 2026 (factures, fuite, courbe de charge)
  - `sensors/quality.py` — données Open Data (dureté, nitrates, chlore)
  - `sensors/base.py` — classes de base et mixins partagés

### Tests
- **Suite de Tests Complète** : 35 tests pytest couvrant les composants critiques
  - Tests de validation du flux de configuration (email, schéma)
  - Tests des fonctions utilitaires du coordinateur (parsing mois, détection pannes)
  - Tests de la logique métier (cache index, agrégats journaliers)
  - Système de stubs HA compatible Python 3.9+

### Conformité HA
- **Audit Complet** : Vérification exhaustive de la conformité Home Assistant
- Fix `CoordinatorEntity` : `switch.py` et `calendar.py` n'héritaient pas correctement de `CoordinatorEntity` — les entités ne s'abonnaient pas aux mises à jour du coordinateur
- Fix `CalendarEvent` : tous les événements utilisent maintenant des objets `date` (pas `datetime`) pour être conformes aux événements "journée entière" HA
- Fix `services.yaml` et `strings.json` : ajout des clés `selector` manquantes pour les champs de services (requis pour l'UI Outils de développement HA)
- Fix `repairs.py` : fonctions renommées en sync (suppression du préfixe `async_` erroné)
- Vérification : 100 clés de traduction, parfaitement synchronisées entre `strings.json`, `fr.json` et `en.json`

### Corrections de Bugs
- **Bouton Facture** : correction d'un bug critique où `entry.options.get("experimental_api")` utilisait une clé hardcodée au lieu de la constante `CONF_EXPERIMENTAL` — le bouton n'était jamais créé
- **Imports Morts** : suppression des imports inutilisés (`asyncio`, `Any`, constantes orphelines)
- **Constante Morte** : suppression de `_LEGACY_AEL_BASE` jamais référencée dans `api.py`
- **Dépendance Fantôme** : suppression de `tenacity>=8.2.0` dans `manifest.json` (jamais utilisé)
- **Dossier `api/`** : suppression du dossier abandonné qui masquait le module `api.py` (shadowing Python)

### Nettoyage
- Screenshots (257 Ko) déplacés de `custom_components/` vers `docs/screenshots/` — réduit le poids des installations HACS de 34%
- Suppression des fichiers `.DS_Store` macOS du dépôt
- README mis à jour : arborescence des fichiers, prérequis HA (`2024.4.0`), liens GitHub corrigés
- Version : `2.6.0` → `2.7.0`

## [2.6.0] - 2026-04-26

### Ajouté
- **Téléchargement Facture PDF** : Nouveau service `download_latest_invoice` avec normalisation robuste des données API pour retrouver le bon document même en cas de structure variable.
- **Bouton Facture** : Entité bouton dédiée dans l'interface pour déclencher le téléchargement en un clic.
- **Calendrier Enrichi** : Ajout des interventions terrain planifiées et des interruptions de service réseau (travaux/coupures) dans le calendrier HA.
- **Mode Vacances (Switch)** : Activation persistante de la surveillance renforcée avec alerte immédiate sur toute consommation détectée.

### Amélioré
- **Normalisation API** : Gestion des structures de réponse variables (multi-clés, multi-postes) pour les factures et consommations journalières.
- **Lovelace** : Mise à jour des templates `dashboard.yaml` et `energy_config.yaml`.

## [2.5.0] - 2026-04-26
(Merci @hufon) pour le code !

### Ajouté
- **Hardening API 2026** : Refonte massive du parsing des données journalières pour supporter les variations de clés de l'API (`volume`, `quantite`, `valeur`, `consommation`) et les structures multi-postes.
- **Consommation Moyenne (L/jour)** : Nouveau capteur calculant la moyenne glissante sur 7 jours, affichée en Litres pour une meilleure lisibilité.
- **Bouton de Facturation** : Ajout d'un bouton physique dans l'interface pour déclencher le téléchargement de la dernière facture PDF (mode expérimental).
- **Qualité de l'Eau (Open Data)** : Intégration automatisée avec le portail Open Data de la Métropole de Lyon (Dureté, Nitrates, Chlore, Turbidité).
- **Capteur de Compatibilité** : Détection automatique du type de compteur (Téléo vs Standard) pour clarifier la disponibilité des données journalières.
- **Calendrier Hardened** : Amélioration de la robustesse du calendrier face aux formats de dates exotiques et intégration des interruptions de service.
- **Suivi Sécheresse & Repairs** : Gestion native des niveaux de vigilance sécheresse du Rhône avec intégration dans la plateforme Repairs de HA.
- **Icônes Dynamiques** : Les capteurs (ex: Nitrates, Fuites) changent d'icône selon la sévérité des données.
- **Courbe de Charge Horaire** : Support expérimental des données de consommation heure par heure pour les compteurs Téléo récents.
- **Consommation d'Hier** : Nouveau capteur en Litres pour un suivi quotidien simplifié.
- **Index Journalier Robuste** : Refonte du parsing de l'index avec support de 9 synonymes de clés et détection automatique des unités (L vs m³).

### Corrigé
- **Bug Économie Annuelle** : Correction de la formule de calcul du capteur d'économie qui comparait un mois à une année entière. Désormais, la comparaison se fait sur 12 mois vs 12 mois.
- **Fallback 30 jours** : Si l'historique journalier de 90 jours échoue, l'intégration tente automatiquement un fallback sur 30 jours pour éviter de perdre les données.

### Optimisé
- **Vérification de Non-Régression** : Tests de parsing automatisés intégrés pour garantir la stabilité face aux changements côté serveur (gestion des mois indexés à 0, conversion L/m³ et normalisation de l'index).
- **Performance Globale** : Consolidation du Rate Limiting et parallélisation des appels API pour une mise à jour plus rapide et discrète.
- **Nettoyage Code** : Suppression des doublons et des fonctions legacy orphelines dans le coordinateur.

## [2.4.0] - 2026-04-25

### Ajouté
- **Conformité HA 2026** : Modernisation complète de l'intégration pour répondre aux standards Home Assistant les plus récents.
- **Support Multilingue** : Ajout de clés de traduction (`translation_key`) pour tous les capteurs via `strings.json`, permettant une internationalisation native.

### Optimisé
- **Gestion d'État** : Migration vers `entry.runtime_data` (introduit dans HA 2024.4), remplaçant l'ancienne méthode `hass.data[DOMAIN]`, garantissant une meilleure isolation et sécurité.
- **Architecture** : Découpage massif de la logique de récupération des données (`_fetch_all_data`) en sous-méthodes modulaires pour une meilleure lisibilité et robustesse.
- **Statistiques** : Mise à jour de l'API d'injection (`StatisticMeanType`) pour assurer la compatibilité avec HA 2025.x et 2026.x.
- **HACS Boot** : Alignement strict des versions `homeassistant` entre `hacs.json` et `manifest.json` pour garantir une validation sans erreur par HACS 2.0+.

### Corrigé
- **Service Facture** : Résolution d'un bug critique (crash) lors du téléchargement du PDF causé par une référence manquante (`self._headers`).
- **Compatibilité Python** : Correction de syntaxes non-rétrocompatibles (ex: `type`) pour assurer le fonctionnement sur Python 3.9+.

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