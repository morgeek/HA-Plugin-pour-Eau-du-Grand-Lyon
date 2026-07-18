# Changelog

Tous les changements notables apportés à cette intégration seront documentés dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
et cette intégration adhère au [Versionnage Sémantique](https://semver.org/spec/v2.0.0.html).

## [3.3.0] - 2026-07-18

Validation sur données réelles capturées depuis l'espace client : correction d'un bug d'unité et exploitation des seuils d'alerte configurés côté serveur.

### Corrections de Bugs

- **Crash au démarrage sur montée de version du cache** (`coordinator.py`) : `async_setup_entry` levait `NotImplementedError` lorsqu'un fichier `.storage` d'une installation antérieure portait une version différente (ex. historique mensuel v1 → v2), car le `Store` n'avait aucune fonction de migration. **Fix** : `_RebuildableStore` migre en repartant d'un cache vide (les données sont reconstruites depuis l'API), et `_load_persistent_data` intercepte désormais aussi `NotImplementedError` / `ValueError`. Corrige `NotImplementedError` au chargement de `_monthly_history_store`.
- **Unités fuite / débit journaliers non converties** (`api/client.py`, `_parse_daily_response`) : seul le champ `consommation` était divisé par 1000 pour passer des litres aux m³. Les champs `volumeEstimeFuite` (unité API `"l"`) et `debitMin` (unité `"L/h"`) étaient stockés tels quels dans `volume_fuite_estime_m3` et `debit_min_m3h` — soit des valeurs **1000× trop grandes** dès qu'une fuite réelle était détectée (ex. 1500 L affichés comme « 1500 m³ »). **Fix** : conversion ÷1000 de ces deux champs selon leur unité déclarée. Sans impact visible sur un compteur sans fuite (valeurs toujours 0), mais faux pour tout compteur avec fuite estimée.

### Ajouté

- **Seuils d'alerte surconsommation serveur** : nouvelle méthode API `get_alerte_surconsommation()` lisant les endpoints `seuilAlerteSurconsommation/journaliere` et `.../mensuelle` (m³) ainsi que `abonneAlerteFuite`. Ces seuils reflètent la configuration réelle de l'abonné plutôt qu'une heuristique locale.
- **Nouveaux capteurs** (compteurs disposant de ces services) : `Seuil surconsommation (jour)` et `Seuil surconsommation (mois)` (diagnostic, m³).
- **Nouveaux binary_sensors** : `Surconsommation journalière` et `Surconsommation mensuelle` (comparaison de la conso au seuil serveur), et `Abonnement alerte fuite` (statut d'abonnement).

### Interne

- Rétablissement de la configuration pytest `asyncio_mode = auto` (`pytest.ini`) supprimée avec `pyproject.toml` — sans elle 9 tests `async` étaient collectés en échec. Correction du `cache-dependency-path` de la CI.

## [3.2.0] - 2026-06-24

Version issue des premiers retours utilisateurs : correction de 5 bugs, seuil fuite configurable, couverture de tests étendue.

### Corrections de Bugs

- **Décalage systématique des labels mensuels** (`api/client.py`) : l'API Téléo encode les mois en base-0 (0 = Janvier, 11 = Décembre). L'ancienne validation `1 ≤ mois ≤ 12` rejetait Janvier (mois=0) et décalait tous les autres d'un rang (Mai affiché comme Avril, Décembre introuvable → marqué "manquant"). **Fix** : `month_idx = month_raw` sans soustraction, validation corrigée à `0 ≤ mois ≤ 11`.
- **Cache corrompu invalidé** (`coordinator.py`) : bump Store version 1 → 2 pour forcer le recalcul de l'historique mensuel au prochain démarrage (les `mois_index` stockés en v1 étaient tous décalés d'un rang).
- **Perte de précision sur l'index compteur** (`coordinator.py`) : `round(x, 1)` → `round(x, 3)` dans `get_cumulative_index()` — un index brut de 326.014 m³ n'est plus tronqué à 326.0.
- **Faux positif permanent — capteur fuite locale** (`coordinator.py`, `binary_sensor.py`) : la règle `all(v > 0.05 m³ sur 7 jours)` était toujours vraie dans un logement habité. Remplacée par un seuil statistique : alerte uniquement si la consommation du dernier jour dépasse `max(moyenne_7j × 2,5 ; 500 L/j)`. Le capteur est désormais désactivé par défaut (`entity_registry_enabled_default = False`).
- **Impossible de changer la fréquence de mise à jour** (`config_flow.py`) : `vol.In(...)` → `vol.All(vol.Coerce(int), vol.In(...))` — Home Assistant soumet les valeurs de selector sous forme de string.
- **`state_class` incorrect** (`sensors/consumption.py`) : `TOTAL` → `TOTAL_INCREASING` sur `EauGrandLyonConsommationSensor` pour compatibilité avec le dashboard Énergie natif HA.

### Améliorations

- **Seuil fuite configurable** (`binary_sensor.py`, `config_flow.py`, `const.py`) : le multiplicateur de détection de fuite mensuelle (`LEAK_MULTIPLIER`) est désormais exposé dans les options de l'intégration (plage : 1,5× – 10×, défaut : 2×). Utile pour les foyers avec une consommation saisonnière élevée (piscine, arrosage).

### Tests

- 27 nouveaux cas de test couvrant tous les bugs corrigés :
  - `TestFormatConsumptions` (8 tests) — encodage base-0, Janvier inclus, Mai sans décalage, mois=12 rejeté
  - `TestDetectLocalLeak` (7 tests) — spike statistique, seuil plancher 500 L, courbe 24h
  - `TestIntervalSchema` (5 tests) — coercition string→int dans l'options flow
  - `TestConsommationSensor.test_state_class_is_total_increasing`
  - `TestLocalLeakSensor.test_disabled_by_default`
- Mise à jour du test `test_real_index_used_when_present` pour refléter la précision à 3 décimales.
- **245 tests** au vert (vs 218 en v3.1.0).

## [3.1.0] - 2026-06-10

Version issue d'un audit complet du projet : corrections de bugs, durcissement sécurité/vie privée, nettoyage du code mort et simplification de la CI.

### Corrections de Bugs

- **Plantage du capteur Eco-Coach** (`TypeError: '>' not supported between NoneType and int`) : le coordinateur renseigne toujours la clé `tendance_n1_pct`, souvent à `None` (pas de donnée N-1). `c.get("tendance_n1_pct", 0)` renvoyait donc `None` et `trend > 20` plantait à chaque écriture d'état pour les scores C à G. Corrigé (`or 0`) + test de non-régression.
- **Fuite de session aiohttp à chaque tentative de setup échouée** : le coordinateur crée sa propre `ClientSession` ; si le premier rafraîchissement échouait (`ConfigEntryNotReady`, réauthentification), elle n'était jamais fermée — et HA réessaie le setup en boucle. La session est désormais fermée si le setup échoue.
- **Fuite mémoire du cache par cycle** : `_CycleCachedApi` utilisait `@alru_cache(maxsize=None)` sur des méthodes d'instance — le cache, porté par la classe, gardait une référence sur chaque instance (une par cycle) et accumulait les réponses API de tous les cycles. Remplacé par un cache de tasks porté par l'instance (même coalescence des appels concurrents), ce qui supprime aussi la dépendance `async-lru`.
- **Statistiques silencieusement désactivées sur les HA plus anciens** : `StatisticMeanType` était importé dans le même `try` que le reste du recorder ; son absence désactivait toute l'injection de statistiques et le fallback `has_mean` était du code mort. L'import est désormais séparé et le fallback fonctionne (vérifié contre un vrai recorder HA 2025.1).
- **Statistiques jamais injectées pour les références de contrat non numériques** : le recorder n'accepte que `[a-z0-9_]` dans un `statistic_id` ; une référence contenant des majuscules ou des tirets (ex. `REF-123A`) produisait `Invalid statistic_id` et l'injection échouait silencieusement depuis toujours. Les références sont désormais normalisées (`_statistic_ref`) — no-op pour les références purement numériques, donc aucun impact sur les statistiques existantes.
- **Service `download_latest_invoice`** : les erreurs réseau/API (`NetworkError`, `WafBlockedError`, `ApiError`, `AuthenticationError`) levées par le téléchargement du PDF n'étaient pas interceptées et remontaient en exception brute. Elles sont maintenant converties en `HomeAssistantError` lisible.
- **Calendrier** : `async_get_events` ignorait la plage `start_date`/`end_date` demandée (tous les événements étaient toujours renvoyés) ; la propriété `event` n'était renseignée que par effet de bord d'un appel UI. Les événements sont filtrés par plage et le prochain événement est calculé directement depuis les données du coordinateur.
- **Timeout réseau** : aucune des sessions aiohttp n'avait de timeout (défaut aiohttp : 5 minutes par requête). Timeout explicite de 30 s sur la session du coordinateur et celle du config flow.

### Sécurité / Vie privée

- **Diagnostics** : l'export contenait l'email du compte (via `entry.title`) et les références de contrat (clés du dict `contracts`, non couvertes par la redaction). Le titre n'est plus exporté et les contrats sont ré-indexés en `contract_1`, `contract_2`, …
- **Services d'écriture de fichiers** (`export_data`, `download_latest_invoice`) : les chemins fournis sont désormais validés avec `hass.config.is_allowed_path()`. ⚠️ **Action requise** : ajoutez le répertoire cible (ex. `/config/exports`) à `allowlist_external_dirs` dans `configuration.yaml` pour continuer à utiliser ces services.

### Améliorations

- **Option « Commune (qualité de l'eau) »** : les capteurs qualité de l'eau (dureté, nitrates, chlore) utilisaient la première mesure du jeu Open Data — c'est-à-dire une commune arbitraire du réseau. Une nouvelle option permet de filtrer sur votre commune ; sans filtre, le comportement reste inchangé (l'attribut `commune` indique la commune réellement mesurée).
- **Capteur sécheresse assumé comme heuristique** : le niveau « Vigilance » est purement saisonnier (juin–septembre). L'issue de réparation HA correspondante — qui alertait tous les utilisateurs la moitié de l'année — est supprimée ; le capteur reste, avec des attributs `source`/`note` renvoyant vers vigieau.gouv.fr.
- **Devices unifiés** (`device.py`) : même fabricant (« Eau du Grand Lyon ») sur toutes les plateformes (le binary_sensor déclarait « Morgeek »), switch/calendrier/boutons rattachés au device du compteur (plus de second device orphelin), et nom du device suffixé par la référence de contrat en multi-contrats.
- **Unité monétaire unifiée** : `EUR` partout (certains capteurs globaux utilisaient `€`, ce que les statistiques long terme traitent comme une unité différente).
- **Localisation** : le bouton « Forcer la mise à jour » utilise une clé de traduction (le nom était codé en dur en français) ; ajout de `invalid_email` manquant dans `en.json` ; idiome `_attr_translation_key` partout.

### Maintenance interne / CI

- **Code mort supprimé** : `api/methods.py` (jamais importé, et cassé), flux de réparation `ConfirmRepairFlow` inutilisé, stubs de test `async_lru`/`tenacity`/`repairs` obsolètes, hack `locals()` dans la journalisation d'auth, blueprints dupliqués à la racine (`budget_notification.yaml`, `leak_notification.yaml` — les versions à jour sont dans `blueprints/automation/eau_grand_lyon/`).
- **CI simplifiée** : un seul workflow (`tests.yaml`) au lieu de deux quasi-identiques ; matrice Python réduite à 3.12/3.13 (HA ne tourne que sur 3.12+) ; flake8 et black désormais **bloquants** ; suppression de l'upload codecov cassé (le fichier `coverage.xml` n'était jamais généré).
- **Versions cohérentes** : `pyproject.toml` resynchronisé avec `manifest.json` (il était resté à 2.9.5) ; `pytest.ini` supprimé (doublon de `[tool.pytest.ini_options]`) ; `requires-python >= 3.12`.
- **Version minimale de HA relevée à 2024.11.0** dans `hacs.json` : le code requiert la propriété automatique `OptionsFlow.config_entry` (HA 2024.11+) ; la valeur précédente (2024.4.0) ne pouvait pas fonctionner.
- Suite de tests : **222 tests** au vert, avec nouveaux tests de non-régression (Eco-Coach `None`, validation des chemins, diagnostics sans email, normalisation des `statistic_id`).
- **Nouveaux smoke tests « vrai Home Assistant »** (`smoke_tests/`, hors CI) : setup complet de la config entry, création des entités, injection des statistiques dans un vrai recorder, options flow, validation des chemins et unload — exécutés contre HA 2025.1 réel avec seul le HTTP mocké. Voir l'en-tête de `smoke_tests/test_real_ha.py` pour les lancer.

## [3.0.4] - 2026-06-10

### Corrections de Bugs

- **`state_class` invalide pour les capteurs de coût** (`state class 'total_increasing' which is impossible considering device class 'monetary'`) : `EauGrandLyonEnergyCostSensor` et `EauGrandLyonCoutCumuleSensor` combinaient `device_class: monetary` avec `state_class: total_increasing`, interdit par Home Assistant (seuls `None` ou `total` sont autorisés pour `monetary`). Corrigé : `state_class` passe à `TOTAL` (avec `last_reset`, conforme au tableau de bord Énergie). Test de non-régression couvrant tous les capteurs monétaires.
- **`unit_class` manquant pour les statistiques de coût** (déprécié, supprimé en HA 2025.11) : l'appel `async_add_external_statistics` pour les statistiques de coût ne précisait pas `unit_class`. Corrigé : `unit_class` est désormais `None` (une devise n'a pas de convertisseur d'unité ; la valeur `"monetary"` est rejetée comme convertisseur inconnu). Le remplacement `has_mean` → `mean_type` était déjà géré.

## [3.0.3] - 2026-06-09

### Corrections de Bugs

- **Plantage `'NoneType' object can't be awaited`** : `repairs.py` faisait `await` sur `ir.async_create_issue()` et `ir.async_delete_issue()`, qui sont des fonctions **synchrones** (`@callback`) dans Home Assistant et renvoient `None`. Attendre `None` provoquait l'erreur lors de la création/suppression d'une issue (sécheresse, panne prolongée). Corrigé : ces appels ne sont plus `await` (les fonctions `check_drought_issue` / `check_long_outage_issue` restent `async def` pour que le coordinateur puisse les attendre). Le stub de test `issue_registry` est passé de `AsyncMock` à `MagicMock` pour refléter le comportement réel de HA, et des tests de non-régression exercent désormais les deux branches.
- **Notifications d'alerte (`a coroutine was expected, got None`)** : `_handle_alert_notifications` enveloppait `persistent_notification.async_create` / `async_dismiss` dans `hass.async_create_task(...)`, alors que ces fonctions sont synchrones (`@callback`) et renvoient `None` — `async_create_task(None)` échouait dès qu'une alerte était créée ou levée. Corrigé : ces fonctions sont maintenant appelées directement. Stub `persistent_notification` ajouté en test + test de non-régression.

### Maintenance interne

- **Nettoyage du dépôt** : suppression de l'environnement virtuel `.venv/` versionné par erreur (642 fichiers) et des fichiers `__pycache__` / `*.pyc` ; `.gitignore` renforcé ; suppression du fichier mort `mock_ha.py`.
- **Guide `AGENTS.md`** ajouté : invariants du projet, workflow tests/lint/release et pièges connus, pour guider les contributeurs humains et les agents IA.
- Suite de tests portée à **219 tests** ; flake8 + black au vert.

## [3.0.2] - 2026-06-09

### Corrections de Bugs

- **Plantage à chaque rafraîchissement (`TypeError: _get() got an unexpected keyword argument 'params'`)** : la méthode `EauGrandLyonApi._get()` n'acceptait pas d'argument `params`, alors que `get_monthly_consumptions()` l'appelait avec `params=...`. Résultat : chaque cycle de mise à jour échouait et l'intégration apparaissait comme « cassée » (souvent perçu comme un problème d'authentification). Corrigé : `_get()` transmet désormais `params` à `_do_get()` (rétrocompatible). Un test de non-régression reproduit l'erreur exacte sans le correctif.
- **Endpoints API corrigés** : les chemins `produits` et `interfaces/ael` utilisaient `/rest/...` qui renvoyait 404. Ils pointent désormais vers `/application/rest/...` (vérifié contre le serveur en production). Détection des compteurs communicants Téléo/TIC améliorée (gère les champs `{code, libelle}`) ; correction de l'offset de mois.
- **Erreurs de traduction dans les options** (`formatjs MISSING_VALUE`) : le formulaire d'options était affiché sans `description_placeholders`, donc les chaînes `water_hardness` et `subscription_annual` ne pouvaient pas s'afficher. Les variables `hardness_lyon_avg` (30 °fH, moyenne Lyon) et `subscription_example` (~180 €/an) sont maintenant fournies.

### CI / Empaquetage

- **Validation HACS corrigée** : suppression de la clé invalide `category` dans `hacs.json` (`category` est un paramètre de l'action HACS, pas un champ du manifeste HACS). C'était la cause réelle de l'échec persistant de la validation HACS.
- Suite de tests : `async-lru` est désormais simulé (stub) en environnement de test ; la vérification `brands` de HACS est ignorée (installation en dépôt personnalisé).

### Note de version

Les versions 3.0.0 et 3.0.1 n'ont pas été publiées ; 3.0.2 est la première release de la série 3.0.x.

## [2.9.5] - 2026-06-08

### Corrections de Bugs

- **Historique mensuel incomplet (janvier-mars 2026 manquants)** : L'endpoint `/consommationsMensuelles` était appelé sans paramètre, ce qui entraînait le retour seulement des 2-3 derniers mois de données par l'API. Résultat : les mois au-delà de l'historique récent (janvier-mars 2026 dans le cas signalé) ne s'affichaient pas dans HA même si le site web les montrait. Corrigé : la méthode `get_monthly_consumptions()` accepte maintenant un paramètre `nbJours` (par défaut 1095 jours = 36 mois) qui est envoyé à l'API pour récupérer l'historique complet.

## [2.9.4] - 2026-06-08

### Corrections de Bugs

- **Erreur "a coroutine was expected, got None" au setup** : Les fonctions `check_drought_issue()` et `check_long_outage_issue()` dans `repairs.py` étaient synchrones mais appelaient des fonctions asynchrones HA (`ir.async_create_issue` / `ir.async_delete_issue`) sans les attendre. Résultat : des coroutines non-awaited causaient l'erreur de setup. Corrigé : ces fonctions sont maintenant `async def` avec `await` sur les appels async, et tous les appels depuis `coordinator.py` utilisent `await`.

## [2.9.3] - 2026-05-11

### Corrections de Bugs

- **Graphique historique vide** : Le coordinateur fusionnait déjà jusqu'à 36 mois de données mensuelles dans `_monthly_history` (store persistant sur disque), mais `_inject_statistics` n'utilisait que les données fraîches de l'API (`contract.get("consommations", [])` — 12 mois max). Résultat : Janvier, Février, Mars 2026 n'apparaissaient jamais dans le graphique HA malgré leur présence dans l'historique interne. Corrigé : `_inject_statistics` utilise désormais `self._monthly_history.get(ref)` pour les deux passes (eau m³ et coût €), avec fallback sur les données fraîches si l'historique étendu est vide. L'historique complet disponible est injecté dès la première mise à jour après cette correction.
- **Total "13 mois" = 11 m³** : Conséquence directe du bug ci-dessus — la somme visible dans HA ne reflétait que les mois récents. Ce sera corrigé automatiquement au premier cycle de mise à jour.

### Impact Utilisateur

Après mise à jour et **forcer la mise à jour** (bouton `button.eau_du_grand_lyon_forcer_la_mise_a_jour`) :
- Le graphique mensuel se remplit avec tous les mois présents dans le cache local (jusqu'à 36 mois)
- Les statistiques HA (`eau_grand_lyon:water_<ref>` et `eau_grand_lyon:cost_<ref>`) sont réinjectées avec l'historique complet
- Aucune action manuelle supplémentaire n'est nécessaire

### Clarification : Capteurs Annuels (pas un bug)

| Capteur | Valeur | Méthode de calcul |
|---|---|---|
| **Consommation annuelle** | ~109 m³ | 12 derniers mois **glissants** (Juin 2025 → Mai 2026) |
| **Consommation depuis jan.** | ~27 m³ | Somme des mois de l'**année civile 2026** (Jan + Fév + Mar + Avr) |
| **Coût (depuis jan.)** | ~87 € | `consommation_cumulee_annee × tarif` — cohérent avec le site web |

Ces deux capteurs sont intentionnellement différents. Le label "Année en cours" peut prêter à confusion car il représente une année **glissante**, pas l'année civile.

### Aucun breaking change — mise à jour transparente depuis v2.9.2

---

## [2.9.2] - 2026-05-xx

### Corrections de Bugs
- Corrections mineures de stabilité (voir commits)

---

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