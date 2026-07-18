# Intégration Eau du Grand Lyon pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Tests & Validation](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/actions/workflows/tests.yaml/badge.svg?branch=main)](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/actions/workflows/tests.yaml)
[![Quality Scale - Silver](https://img.shields.io/badge/Quality%20Scale-Silver-9E9E9E)](https://developers.home-assistant.io/docs/core/integration-quality-scale/)

Ceci est une intégration personnalisée NON OFFICIELLE pour [Home Assistant](https://www.home-assistant.io/) qui fournit des capteurs pour les données de consommation d'eau du service Eau du Grand Lyon.

> 🥈 **Quality Scale : Silver** — Intégration robuste au quotidien : gestion d'erreurs et mode hors-ligne, flux de configuration / options / ré-authentification, traductions FR/EN, documentation détaillée et large couverture de tests. Plusieurs critères Gold restent en cours (voir [`quality_scale.yaml`](custom_components/eau_grand_lyon/quality_scale.yaml)) : traduction des états d'entités, `exception-translations`, nettoyage des appareils obsolètes et enregistrement des services via `async_setup`.

![alt text](https://raw.githubusercontent.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/main/docs/screenshots/HA-Eau-Grand-Lyon.png)

![alt text](https://raw.githubusercontent.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/main/docs/screenshots/HA-Eau-Grand-Lyon2.png)

![alt text](https://raw.githubusercontent.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/main/docs/screenshots/HA-Eau-Grand-Lyon3.png)

![alt text](https://raw.githubusercontent.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/main/docs/screenshots/HA-Eau-Grand-Lyon4.png)

## Historique des versions

Voir le [CHANGELOG.md](CHANGELOG.md) pour l'historique complet des changements.

### 🛡️ Robustesse réseau & statistiques — Audit (v3.4.0)

- **Timeouts et erreurs serveur gérés** : un timeout ou une erreur HTTP 5xx / réponse malformée déclenche désormais le retry puis le mode hors-ligne (cache) au lieu de faire tomber toutes les entités.
- **Ré-authentification sérialisée** : lors d'un cycle, une expiration de token ne déclenche plus qu'un seul flux OAuth au lieu d'une rafale contre le pare-feu (WAF).
- **Un contrat en erreur n'impacte plus les autres** du même compte.
- **URLs corrigées** : téléchargement de facture et révocation de token passent enfin par le préfixe `/application/...` (les anciennes routes renvoyaient 404).
- **Statistiques long terme fiabilisées** : le cumul s'ancre sur la dernière valeur du recorder (plus de pics négatifs quand la fenêtre glisse) et la consommation du mois courant est rafraîchie à chaque cycle.
- **Corrections capteurs** : mode vacances restauré au redémarrage, multiplicateur de fuite configurable pris en compte partout, `state_class` / `device_class` corrigés (mois précédent, seuils).
- **Config flow** : l'erreur WAF ne provoque plus de message cassé (placeholder manquant).
- **Qualité affichée honnête** : Quality Scale ramené de Gold à **Silver** pour refléter la réalité.

### 🐛 Retours utilisateurs — Labels, Précision, Fuite (v3.2.0)

- **Labels mensuels corrigés** : l'API Téléo envoie les mois en base-0 (0 = Janvier) — le décalage d'un rang est corrigé, Janvier n'est plus "manquant".
- **Précision index** : `round(x, 1)` → `round(x, 3)` — 326.014 m³ n'est plus affiché comme 326.0.
- **Fuite locale** : seuil statistique (2,5× la moyenne 7j) remplace la règle qui déclenchait en permanence ; capteur désactivé par défaut.
- **Fréquence de mise à jour** : la modification via les options HA ne renvoie plus d'erreur de validation.
- **Seuil fuite configurable** : multiplicateur réglable de 1,5× à 10× dans les options de l'intégration.
- **245 tests** au vert.

### 🩹 Stabilité & Endpoints (v3.0.x)

- **Endpoints API corrigés** : les routes de données utilisent désormais le préfixe `/application/rest/...` (les anciennes routes `/rest/...` renvoyaient 404, vérifié en production). Authentification et récupération des données fiabilisées.
- **Correctifs de plantage** : résolution de plusieurs erreurs au rafraîchissement et lors des notifications/alertes — `TypeError: _get() ... 'params'`, `'NoneType' object can't be awaited`, `a coroutine was expected, got None` (appel correct des fonctions synchrones `@callback` de Home Assistant).
- **Options** : correction de l'affichage des libellés de configuration (dureté de l'eau, abonnement annuel) qui provoquaient une erreur de traduction.
- **Détection Téléo/TIC** améliorée (gère les nouveaux formats de champs de l'API).
- **Qualité & packaging** : 220 tests automatisés ; validations HACS et hassfest au vert ; nettoyage du dépôt (suppression du `.venv` versionné) et ajout d'un guide `AGENTS.md` pour les contributeurs et agents IA.

### 🐛 Correctif Graphique Historique (v2.9.3)

- **Graphique mensuel vide** : Le coordinateur stockait jusqu'à 36 mois d'historique en local, mais l'injection dans les statistiques HA n'utilisait que les 12 mois retournés par l'API à chaque cycle. Résultat : Janvier, Février, Mars 2026 n'apparaissaient pas dans les graphiques HA. **Corrigé** — l'historique complet est désormais injecté à chaque mise à jour.
- Après mise à jour : utilisez le bouton **Forcer la mise à jour** pour déclencher l'injection immédiate.

### 🔧 Corrections & Nouvelles Fonctionnalités (v2.9.0)

#### Corrections Critiques
- **Correction crash démarrage** : `AttributeError` sur `_current_year_str` dans les capteurs Energy — corrigé dans la classe de base
- **"Économie potentielle" restaurée** : Fallback immédiat par extrapolation mensuelle, puis calcul exact après 12 mois d'accumulation d'historique
- **Historique mensuel 36 mois** : Le coordinateur accumule l'historique contrat par contrat sur disque — le calcul N-1 annuel devient exact après 1 an d'utilisation
- **Sécheresse jamais déclenchée** : Corrections du niveau détecté dans `repairs.py` (désormais niveau == "Vigilance")
- **Coût cumulé = 0€ au lieu de unavailable** : Correction du capteur "Coût cumulé" (0 m³ → 0.0€ valide)
- **Index journalier priorité** : Correctif pour utiliser réellement `index_journalier_dernier` avant la fallback sur somme mensuelle
- **nb_jours parameter utilisé** : `_get_daily_new` utilise désormais le paramètre au lieu de hardcoder 2 ans

#### Nouvelles Fonctionnalités
- **Statistiques de coût injectées** : Nouvel ID statistic `eau_grand_lyon:cost_<ref>` (EUR/mois) injecté automatiquement si tarif configuré — permet au tableau de bord Énergie HA de suivre l'historique de facturation sur 24+ mois
- **Graphiques Lovelace natifs** : Fichier `lovelace/monthly_chart_cards.yaml` avec 6 exemples prêts à l'emploi utilisant `custom:apexcharts-card` pour visualiser les données `monthly_chart_data` (consommation/coût mensuels, graphiques combinés)
- **Dashboard Énergie complet** : `lovelace/energy_dashboard_preset.yaml` — tableau de bord prêt à paster avec 10 sections (résumé, historique 24 mois, coûts, intelligence, Téléo, qualité eau, alertes, calendrier)
- **Guide Configuration Énergie** : `lovelace/energy_config.yaml` enrichi avec documentation complète des sources d'eau, statistic IDs, troubleshooting
- **Téléchargement facture multi-contrats** : Service `download_latest_invoice` accepte maintenant paramètre optionnel `contract_reference` pour cibler un contrat spécifique
- **Icônes manquantes** : `solde`, `conso_hier`, `last_update` ajoutées dans `icons.json`

#### Qualité & Maintenabilité
- **213 tests** (vs 113 en v2.8.0) — +100 nouveaux tests couvrant toutes les plateformes et chemins d'erreur
- **Exception handling** : Remplacement des `except Exception` génériques par des exceptions spécifiques (`KeyError`, `TypeError`, `ValueError`) dans `api/methods.py`
- **Documentation des statistic IDs** : Clarification des IDs injectés pour la traçabilité et l'intégration Energy Dashboard
- **Type hints améliorés** — ~80% de couverture sur les méthodes critiques
- **CI/CD GitHub Actions** : Tests automatisés sur Python 3.9–3.12 à chaque push et pull request
- **Pre-commit hooks** : `black`, `isort`, `flake8`, validation YAML/JSON, détection de clés privées
- **Manifest.json** : Ajout du champ `homeassistant: "2024.4.0"` pour clarifier les dépendances
- **Aucun dead code** — code audit effectué, zéro imports inutilisés
- **Aucun breaking change** — upgrade transparent depuis v2.8.0

### ⭐ Certification Gold Home Assistant (v2.8.0)
- **Quality Scale Gold** : Intégration certifiée conforme aux critères Gold de Home Assistant
- **Flux Configuration Avancés** : Réauthentification automatique + reconfiguration des identifiants sans suppression
- **Gestion d'Erreurs Pro** : Services qui lèvent `HomeAssistantError` / `ServiceValidationError` pour une meilleure traçabilité
- **Icons & Exceptions Traduites** : `icons.json` + traductions multilingues des messages d'erreur
- **Entités Catégorisées** : Capteurs diagnostiques (tendance, prédictions, alertes) masqués par défaut, `PARALLEL_UPDATES = 0`
- **Documentation Gold** : 6 nouvelles sections — mise à jour données, appareils supportés, limitations, dépannage, cas d'usage, exemples
- **Tests Complets** : 113 tests pytest + validation CI/CD (GitHub Actions)
- **Aucun breaking change** — upgrade transparent depuis v2.7.0

### 🏗️ Refonte Architecturale & Audit HA (v2.7.0)
- **Architecture Modulaire** : `sensor.py` (1800 lignes) découpé en 9 modules spécialisés dans `sensors/` pour une meilleure maintenabilité
- **Suite de Tests Complète** : 35 tests pytest — flux de config, coordinateur, logique métier
- **Audit HA Complet** : Corrections de cycle de vie des entités (`CoordinatorEntity`), types calendrier (`date` objects), clés de services (`selector`)
- **Corrections Critiques** : Bug bouton facture (clé hardcodée), `switch.py`/`calendar.py` (`super().__init__()`), fonctions `async_` erronées dans `repairs.py`
- **Nettoyage** : Imports morts, dépendance `tenacity` fantôme, dossier `api/` abandonné, screenshots (257 Ko) déplacés vers `docs/`
- **Aucun breaking change** — migration transparente depuis v2.6.0

### 📦 Téléchargement Facture & Calendrier Enrichi (v2.6.0)
- **Service `download_latest_invoice`** : Téléchargement PDF de la dernière facture avec normalisation robuste des réponses API
- **Bouton Facture** : Entité bouton dans l'interface HA pour déclencher le téléchargement en un clic
- **Calendrier Enrichi** : Interventions terrain planifiées et interruptions réseau (travaux/coupures) intégrées
- **Mode Vacances (Switch)** : Surveillance renforcée persistante avec alerte sur toute consommation

### 🚀 Hardening & Features Pack (v2.5.0)
- **Hardening API 2026** : Parsing ultra-robuste des volumes journaliers (support multi-clés et structures API variées).
- **Consommation Moyenne (L/j)** : Nouveau capteur glissant en **Litres** pour une vision plus concrète du quotidien.
- **Capteur de Compatibilité** : Détection automatique Téléo vs Standard pour clarifier la disponibilité des données.
- **Bouton Facture Direct** : Téléchargez votre dernière facture PDF en un clic depuis l'interface HA.
- **Qualité de l'Eau Open Data** : Dureté, Nitrates et Chlore via les données de la Métropole de Lyon, avec alertes sur les seuils sanitaires. Renseignez votre commune dans les options pour filtrer les mesures (sinon, première mesure disponible du réseau — voir l'attribut `commune`).
- **Consommation d'Hier** : Suivez votre volume consommé la veille directement en Litres.
- **Index Journalier (Energy)** : Nouveau capteur d'index cumulé haute précision, idéal pour le panneau Énergie de HA.
- **Courbe de Charge Horaire** : Visualisez votre consommation heure par heure (compteurs Téléo compatibles).
- **Stabilité Totale** : Mise en place de tests de non-régression et correction du bug de calcul de l'économie vs N-1.
- **Correction Bug Économie** : Correction de la formule de calcul du capteur d'économie qui comparait un mois à une année entière (désormais : 12 mois vs 12 mois).
- **Fallback 30 jours** : Si l'historique journalier de 90 jours échoue, l'intégration tente automatiquement un fallback sur 30 jours pour éviter de perdre les données.

### 🚀 Modernisation HA 2026 (v2.4.0)
- **Pleine Conformité HA 2026** : Alignement total avec les standards de développement Home Assistant 2026.
- **Internationalisation Native** : Support complet des `translation_key` pour une interface multilingue fluide.
- **Architecture Haute Performance** : Migration vers `entry.runtime_data` et optimisation des statistiques à long terme (`StatisticMeanType`).
- **Prêt pour HACS 2.0** : Validation rigoureuse des métadonnées pour une installation sans accroc.

### 🧠 Intelligence Avancée & Coaching "Platinum"
- **Eco-Coach (IA) 💎** : Sensor de conseil personnalisé qui analyse vos habitudes pour vous aider à réduire votre consommation quotidiennement.
- **Eco-Score (A-G)** : Note de performance environnementale basée sur le nombre d'habitants et les barèmes nationaux.
- **Entartrage Virtuel** : Estimation exclusive de l'accumulation de calcaire (en grammes) basée sur la dureté de l'eau configurée.
- **Empreinte Carbone (CO₂e)** : Calcul automatique de l'impact écologique de votre consommation d'eau (kg CO₂e).
- **Prédictions Fin de Mois** : Algorithmes prédictifs pour estimer le volume et le coût final de votre facture.
- **Consommation Moyenne (L/jour) 💧** : Affiche votre consommation moyenne glissante sur 7 jours en **Litres**. Idéal pour comparer avec les moyennes nationales (env. 150L/pers/jour).
- **Tendance vs N-1** : Comparaison intelligente avec la même période de l'année précédente (Annuelle vs Annuelle).

### 🛡️ Sécurité & Alertes
- **Détection Fuite Temps Réel (Téléo)** : Basé sur les alertes officielles du compteur.
- **Détection Fuite Locale (Pattern)** : Analyse intelligente du flux constant (idéal pour compteurs legacy).
- **Mode Vacances** : Switch de surveillance renforcée (alerte immédiate pour toute consommation > 1L).
- **Indicateur Sécheresse (saisonnier)** : Capteur indicatif basé sur une heuristique saisonnière (juin–septembre = Vigilance). Il ne reflète pas les arrêtés préfectoraux réels — consultez [vigieau.gouv.fr](https://vigieau.gouv.fr) pour les restrictions en vigueur.
- **Icônes Dynamiques** : Les capteurs (ex: Nitrates, Fuites) changent d'icône selon la sévérité des données.
- **Courbe de Charge Horaire** : Support expérimental des données de consommation heure par heure pour les compteurs Téléo récents.
- **Consommation d'Hier** : Nouveau capteur dédié affichant la consommation du dernier jour connu en **Litres**.
- **Index Journalier Robuste** : Amélioration du parsing de l'index journalier avec support de 9 synonymes de clés API (inspiré du travail de @hufon).
- **Repairs HA** : Alerte dans le tableau de bord "Réparations" de Home Assistant en cas de panne API prolongée (> 7 jours).

### 🛠️ Services Pro & Utilitaires
- **Export CSV** : Service `export_data` pour sauvegarder tout votre historique en local.
- **Téléchargement Facture PDF** : Service `download_latest_invoice` pour récupérer votre facture officielle.
  > ⚠️ Depuis la 3.1.0, le répertoire de destination de ces deux services doit être autorisé dans `configuration.yaml` :
  > ```yaml
  > homeassistant:
  >   allowlist_external_dirs:
  >     - /config/exports
  >     - /config/www/eau_grand_lyon
  > ```
- **Santé Hardware** : Diagnostic du niveau de signal et de la pile du module Téléo.
- **Calendrier des Échéances** : Entité calendrier avec dates de paiement et factures prévues.
- **Blueprints d'Automation** : Modèles prêts à l'emploi pour les alertes fuite et budget.

### Mode hors-ligne
Si l'API Eau du Grand Lyon est indisponible (coupure réseau, maintenance, blocage WAF), l'intégration bascule automatiquement en **mode hors-ligne** :
- Les sensors restent disponibles et affichent les dernières données connues
- Le sensor **Statut API** passe à `HORS-LIGNE` avec l'horodatage du début de la panne
- Le cache est persistant sur disque — il survit à un redémarrage de Home Assistant
- Dès que l'API répond à nouveau, les données sont rafraîchies et le mode hors-ligne se désactive automatiquement

### Mode Expérimental (données étendues)
Une option **Mode expérimental** (désactivée par défaut) active la récupération de données supplémentaires, lorsque votre compteur et votre compte les exposent :
- **Factures détaillées**, **courbe de charge horaire** (compteurs Téléo) et **volumes de fuite estimés**.
- Ces données proviennent d'endpoints additionnels de l'API. Si elles ne sont pas disponibles pour votre compteur, les capteurs correspondants restent simplement indisponibles, sans impacter le reste de l'intégration.

**Activation** :
1. Allez dans Paramètres > Appareils et services.
2. Recherchez l'intégration Eau du Grand Lyon.
3. Cliquez sur **Configurer** (ou **Options** selon votre version de HA).
4. Cochez la case **Mode expérimental**.

Si votre compteur est compatible, les capteurs supplémentaires apparaîtront automatiquement (pensez à vérifier s'ils sont désactivés par défaut dans l'interface des entités).

> **Note (v3.0.x)** : l'authentification et la récupération des données utilisent les routes officielles `/application/...`, vérifiées en production. L'ancien basculement automatique vers des routes alternatives (sans préfixe `/application/`) a été retiré : ces routes n'existent plus côté serveur (404).

## Mise à jour des données

L'intégration récupère vos données de consommation selon un intervalle configurable :

- **Intervalle par défaut** : 24 heures (pour éviter les blocages WAF)
- **Intervalle configurable** : 6h, 12h, 24h, 48h — accessible via Paramètres > Appareils et services > Options
- **Mise à jour manuelle** : Service `update_now` pour forcer un rafraîchissement immédiat
- **Cache persistant** : En cas d'indisponibilité API, les dernières données connues restent affichées localement
- **Retry automatique** : En cas d'erreur réseau ou blocage WAF, l'intégration réessaie après un délai croissant (1 min, 5 min)

### Gestion du blocage WAF

L'API officielle utilise un pare-feu web (WAF) qui peut bloquer les requêtes trop fréquentes. Si vous recevez l'erreur "Requête bloquée par le pare-feu", deux solutions :
1. **Augmentez l'intervalle** : Passez à 48 heures au lieu de 24h
2. **Attendez quelques minutes** : L'intégration réessaye automatiquement après un délai exponentiel

### Dashboard Lovelace

#### Templates Prêts à l'Emploi (v2.9.0+)
- **`lovelace/energy_dashboard_preset.yaml`** — Dashboard complet prêt à paster (10 sections : résumé, 24 mois historique, coûts, intelligence, Téléo, qualité, alertes, calendrier)
- **`lovelace/monthly_chart_cards.yaml`** — 6 exemples de cartes ApexCharts pour visualiser `monthly_chart_data` :
  - Bar chart consommation mensuelle
  - Combo chart consommation + coût
  - Bar chart coût mensuel
  - Statistics graph 24 mois (sans HACS)
  - Statistics graph coût (avec statistic ID)
  - Graphique détaillé mensuel
- **`lovelace/dashboard.yaml`** — Dashboard "Synthèse" avec graphiques et statistiques (v2.8.0+)
- **`lovelace/dashboard_notifications.yaml`** — Template avec notifications avancées *(optionnel)*

#### Installation Rapide
```
1. Ouvrir lovelace/energy_dashboard_preset.yaml
2. Copier tout le contenu YAML
3. HA : Paramètres > Tableaux de bord > Créer > Importer à partir du YAML
4. Adapter les entity_id si différents (voir votre intégration)
5. Valider — le dashboard s'affiche immédiatement
```

### Intégration Energy Dashboard (v2.9.0+)

#### Statistiques Injectées Automatiquement
Depuis v2.9.0, deux statistic IDs externes sont injectés automatiquement par le coordinateur :

| Statistic ID | Unit | Period | Usage |
|---|---|---|---|
| `eau_grand_lyon:water_<ref>` | m³ | Monthly | Historique consommation jusqu'à 36 mois, Energy Dashboard |
| `eau_grand_lyon:cost_<ref>` | EUR | Monthly | Historique coûts jusqu'à 36 mois (si tarif configuré) |

*`<ref>` = votre numéro de contrat (ex: AB1234567890)*

> **Note sur les capteurs annuels** : Le capteur "Consommation annuelle" affiche les **12 derniers mois glissants** (pas l'année civile). Pour suivre la consommation depuis le 1er janvier, utilisez le capteur "Consommation depuis janvier" (`consommation_cumulee_annee`) ou le capteur de coût cumulé.

#### Configuration Pas à Pas
Pour configurer le tableau de bord Énergie avec coûts, consultez le **[guide complet](lovelace/ENERGY_DASHBOARD_SETUP.md)**.

En résumé :
1. **Vérifier que le capteur de coût est activé** : `sensor.eau_du_grand_lyon_energie_cout`
2. **Configurer le tarif €/m³** dans Paramètres > Options
3. **Ajouter une source d'eau** au tableau de bord Énergie :
   - Téléo : `sensor.eau_du_grand_lyon_index_journalier_energy` (quotidien, haute précision)
   - Standard : `sensor.eau_du_grand_lyon_index_compteur` (mensuel)
4. **Ajouter le coût** pour cette source : `sensor.eau_du_grand_lyon_energie_cout`
2. **Coûts** : `sensor.eau_du_grand_lyon_energie_cout` (auto-calculé si tarif configuré)
3. **Statistiques** : Utilisez les statistic IDs ci-dessus pour les cartes `statistics-graph` (voir exemples dans `monthly_chart_cards.yaml`)

#### Troubleshooting
- ⚠️ Capteurs grisés ? → Paramètres > Appareils et services > Eau du Grand Lyon > Activer
- 📊 Statistiques vides ou graphique incomplet ? → Forcer une mise à jour avec le bouton dédié, puis attendre quelques secondes
- 🔍 Statistic ID inconnu ? → Vérifier `YOURHA/api/statistic_metadata` ou utiliser l'UI directement

Pour plus de détails : voir `lovelace/energy_config.yaml`

### Notifications Avancées & Blueprints
L'intégration inclut désormais des **Blueprints** (modèles d'automatisation) pour configurer en un clic :
- **Alerte Fuite Actionnable** : Notification sur mobile avec boutons "Rafraîchir" et "Voir Dashboard".
- **Alerte Budget** : Notification si la prédiction de fin de mois dépasse un seuil choisi.
- **Alerte Sécheresse** : Notification quand l'indicateur saisonnier de l'intégration change de niveau (heuristique — voir vigieau.gouv.fr pour les restrictions réelles).

## Appareils supportés

L'intégration fonctionne avec deux types de compteurs :

| Type | Nom | Disponibilité des données |
|------|-----|---------------------------|
| **Téléo** (smart) | Compteur communicant Eau du Grand Lyon | Consommation journalière, courbe horaire, alertes temps réel, signal radio |
| **Standard** | Compteur traditionnel avec relevé manuel | Consommation mensuelle uniquement |

### Comment savoir quel compteur j'ai ?

- Un capteur **Compatibilité compteur** (désactivé par défaut) indique `Téléo` ou `Standard`
- Allez dans Paramètres > Appareils et services > Eau du Grand Lyon > Entités
- Cherchez "Compatibilité compteur" — activez-la si elle est masquée

## Limitations connues

- **Mise à jour mensuelle** : Les données de consommation sont généralement mises à jour une fois par mois par le service. La vue quotidienne n'est disponible que pour les compteurs Téléo.
- **Blocage WAF** : L'API officielle peut bloquer les requêtes trop fréquentes. Consultez la section "Mise à jour des données" pour plus de détails.
- **Données historiques API** : L'API Eau du Grand Lyon ne retourne que les 12 derniers mois. L'intégration accumule cependant jusqu'à **36 mois** en cache local persistant — le graphique se remplit progressivement au fil du temps.
- **Compteurs Standard** : Les détails horaires et alertes temps réel ne sont disponibles que sur compteurs Téléo.
- **Mode hors-ligne** : En cas d'indisponibilité prolongée (>7 jours), une alerte apparaît dans les réparations HA.

## Dépannage

### L'intégration affiche "HORS-LIGNE"

**Cause** : L'API Eau du Grand Lyon est indisponible ou inaccessible.

**Solutions** :
1. Vérifiez votre connexion réseau et que le serveur https://agence.eaudugrandlyon.com est accessible
2. Attendez quelques minutes — l'intégration réessaye automatiquement
3. Utilisez le service **Effacer le cache** (Paramètres > Appareils et services) pour réinitialiser l'état
4. Consultez les logs Home Assistant pour plus de détails : `Settings > System > Logs`

### Erreur "Identifiants incorrects"

**Cause** : Votre email ou mot de passe est invalide ou a changé.

**Solutions** :
1. Vérifiez que votre email et mot de passe sont corrects sur https://agence.eaudugrandlyon.com
2. Réinitialisez votre mot de passe sur le site si nécessaire
3. Allez dans Paramètres > Appareils et services > Eau du Grand Lyon
4. Cliquez sur le bouton Reconfigurer et entrez vos identifiants à jour

### Erreur "Requête bloquée par le pare-feu web"

**Cause** : L'API officielle utilise un pare-feu web (WAF) qui bloque les requêtes trop fréquentes.

**Solutions** :
1. Augmentez l'intervalle de mise à jour : Paramètres > Appareils et services > Eau du Grand Lyon > Options > Fréquence de mise à jour (passez à 48h)
2. Attendez quelques minutes avant de réessayer — l'intégration réessaye automatiquement avec un délai exponentiel
3. Si le problème persiste, attendez 1-2 heures avant de configurer l'intégration

### Certains capteurs sont manquants

**Cause** : Certains capteurs techniques sont désactivés par défaut.

**Solutions** :
1. Allez dans Paramètres > Appareils et services > Eau du Grand Lyon > Entités
2. Cherchez les capteurs que vous souhaitez voir (ex. "Fuite estimée", "Heure de pic", "Éco-Score")
3. Cliquez sur le capteur puis sur l'icône engrenage → Activez le capteur

## Prérequis
- Home Assistant (`2024.4.0` ou ultérieure)
- Un compte valide avec Eau du Grand Lyon (email et mot de passe)

## Installation

> [!CAUTION]
> **IMPORTANT** : Avant d'installer cette intégration ou toute autre extension personnalisée, effectuez toujours une **sauvegarde complète (Backup)** de votre configuration Home Assistant. L'auteur ne peut être tenu responsable en cas de perte de données ou d'instabilité de votre instance.

### Option 1 : Installation à l'ancienne
1. Téléchargez la dernière version depuis le [dépôt GitHub](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon).
2. Extrayez **l'intégralité** du dossier `custom_components/eau_grand_lyon/` (y compris le sous-dossier `sensors/`) dans le répertoire `custom_components/` de votre Home Assistant.
3. Redémarrez Home Assistant.

Arborescence attendue après copie manuelle :

```text
/config/custom_components/eau_grand_lyon/manifest.json
/config/custom_components/eau_grand_lyon/__init__.py
/config/custom_components/eau_grand_lyon/config_flow.py
...
```

Ne copiez pas le dépôt complet dans `/config/custom_components/` sinon vous obtiendrez un chemin invalide du type :

```text
/config/custom_components/eau_grand_lyon_component/custom_components/eau_grand_lyon/
```

Dans ce cas, Home Assistant ne trouvera pas l'intégration et affichera `Non chargé`.

### Option 2 : HACS (Recommandé)
1. Assurez-vous d'avoir [HACS](https://hacs.xyz/) installé dans votre instance Home Assistant.
2. Allez dans **Intégrations** HACS et recherchez "Eau du Grand Lyon".
3. Cliquez sur **Installer** et redémarrez Home Assistant.
4. Passez à la configuration ci-dessous.

> **Note** : Si l'intégration n'est pas encore dans HACS, utilisez l'Option 1 ou ajoutez le dépôt personnalisé manuellement dans les paramètres HACS.

## Configuration
1. Dans Home Assistant, allez dans **Paramètres** > **Appareils et services**.
2. Cliquez sur **Ajouter une intégration** et recherchez "Eau du Grand Lyon".
3. Saisissez votre email et mot de passe du compte Eau du Grand Lyon.
4. Terminez la configuration.

Une fois installée, vous pouvez modifier les options (tarif au m³, intervalle de mise à jour, mode expérimental) en retournant dans **Appareils et services** > **Eau du Grand Lyon** > **Configurer**.

L'intégration récupérera automatiquement les données toutes les **24 heures** par défaut (car les données eau sont généralement mensuelles). Cet intervalle est modifiable dans les options (6h, 12h, 24h, 48h). Et on ne va pas tabasser leur serveur inutilement.

## Utilisation
Une fois configuré, les capteurs apparaîtront dans votre tableau de bord Home Assistant. Vous pouvez les utiliser dans des automatisations, des tableaux de bord, ou de toute autre manière que vous utilisez les capteurs dans Home Assistant.

### Notifications Intelligentes

> ⚠️ **Non disponible dans cette version** — prévu pour une version future.


Checklist de réparation :

1. Vérifiez que ce fichier existe bien :
   `/config/custom_components/eau_grand_lyon/manifest.json`
2. Vérifiez que le dossier s'appelle exactement `eau_grand_lyon`
3. Si vous utilisez HACS, désinstallez puis réinstallez l'intégration, puis redémarrez Home Assistant
4. Si le dossier est absent mais que la carte d'intégration existe encore dans Home Assistant, supprimez l'entrée d'intégration bloquée puis réinstallez
5. Faites un redémarrage complet de Home Assistant après réinstallation

En cas de doute, la structure valide est :

```text
/config/custom_components/eau_grand_lyon/
  manifest.json
  __init__.py
  config_flow.py
  coordinator.py
  sensor.py
  binary_sensor.py
  button.py
  calendar.py
  switch.py
  repairs.py
  diagnostics.py
  const.py
  strings.json
  services.yaml
  api/
    __init__.py
    client.py
    auth.py
    endpoints.py
    methods.py
  brand/
    icon.png
    logo.png
  sensors/
    __init__.py
    base.py
    consumption.py
    contract.py
    cost.py
    experimental.py
    global_sensors.py
    intelligence.py
    quality.py
  translations/
    fr.json
    en.json
```

## Cas d'usage & Exemples

### Alerte fuite en temps réel

Créez une automation qui vous envoie une notification si une fuite est détectée :

```yaml
alias: Alerte Fuite Eau
trigger:
  - platform: state
    entity_id: binary_sensor.eau_grand_lyon_alerte_fuite_possible
    to: 'on'
action:
  - service: persistent_notification.create
    data:
      title: "⚠️ Fuite d'eau détectée !"
      message: "Consommation actuelle : {{ state_attr('sensor.eau_grand_lyon_conso_courant_m3', 'consommation') }} m³"
```

### Notification budget dépassé

Recevez une alerte si votre facture prévisionnelle dépasse un seuil :

```yaml
alias: Alerte Budget Eau
trigger:
  - platform: numeric_state
    entity_id: sensor.eau_grand_lyon_prediction_cout_mois
    above: 50  # Alert if monthly prediction exceeds €50
action:
  - service: notify.mobile_app_smartphone
    data:
      title: "💰 Budget eau dépassé"
      message: "Estimation coût du mois : {{ states('sensor.eau_grand_lyon_prediction_cout_mois') }}€"
```

### Dashboard personnalisé

Exemple de carte Lovelace pour afficher votre consommation :

```yaml
type: vertical-stack
cards:
  - type: gauge
    entity: sensor.eau_grand_lyon_conso_courant_m3
    min: 0
    max: 100
    unit: m³
    title: Consommation mois courant
  
  - type: history-stats
    entity: sensor.eau_grand_lyon_conso_7j
    state: 'on'
    period: day
    title: Consommation 7 jours

  - type: entities
    entities:
      - entity: sensor.eau_grand_lyon_cout_mois
      - entity: sensor.eau_grand_lyon_eco_score
      - entity: binary_sensor.eau_grand_lyon_alerte_fuite_possible
```

### Export de données mensuel

Programmez un export automatique de vos données chaque 1er du mois :

```yaml
alias: Export données eau mensuel
trigger:
  - platform: time
    at: "09:00:00"
condition:
  - condition: template
    value_template: "{{ now().day == 1 }}"
action:
  - service: eau_grand_lyon.export_data
    data:
      path: /config/www/eau_export_{{ now().strftime('%Y-%m') }}.csv
```

### Fomulations prédictives

Créez un template pour afficher une estimation personnalisée :

```jinja2
{% set consumption = states('sensor.eau_grand_lyon_conso_courant_m3') | float(0) %}
{% set tarif = 5.20 %}
{% if consumption < 50 %}
  💚 Très économe ({{ consumption }} m³)
{% elif consumption < 100 %}
  🟢 Bon ({{ consumption }} m³)
{% elif consumption < 150 %}
  🟡 À optimiser ({{ consumption }} m³)
{% else %}
  🔴 À réduire ({{ consumption }} m³)
{% endif %}
```

### Fonctionnalités à venir
**Multi-utilisateurs**
   - Support pour plusieurs comptes utilisateur

### Contributions
Les contributions sont les bienvenues ! N'hésitez pas à proposer des features

## Licence
Ce projet est sous licence MIT - voir le fichier LICENSE pour plus de détails.

## Clause de non-responsabilité

Cette intégration est fournie "telle quelle", sans garantie d'aucune sorte, expresse ou implicite. Bien que tout soit mis en œuvre pour assurer la stabilité et la sécurité du plugin, son utilisation reste sous votre entière responsabilité. 

L'auteur ne peut être tenu responsable :
- Des dommages directs ou indirects causés à votre instance Home Assistant.
- De toute perte de données.
- De tout blocage de compte ou changement de politique d'accès de la part du service Eau du Grand Lyon.

Cette intégration n'est en aucun cas officiellement affiliée, approuvée ou maintenue par Eau du Grand Lyon ou la Métropole de Lyon.
