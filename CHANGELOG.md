# Changelog

Tous les changements notables apportés à cette intégration seront documentés dans ce fichier.

## [3.5.4] - 2026-09-03

### Qualité de l'eau

- Remplacement ciblé de l'ancien jeu Open Data Métropole de Lyon par l'API nationale Hub'Eau `qualite_eau_potable` pour la dureté, les nitrates, le chlore libre et la turbidité.
- La commune est désormais résolue exactement en code INSEE et UDI du Rhône ; une commune absente, inconnue ou ambiguë laisse les mesures indisponibles au lieu d'utiliser une autre commune.
- Les analyses réglementaires sont validées par code SANDRE, unité et date, puis la mesure valide la plus récente est retenue. Les pannes Hub'Eau sont mises en cache brièvement et n'affectent jamais les contrats, consommations, factures, PFAS ou VigiEau.

### Corrections API

- Les factures utilisent désormais les champs réels `statutReglement` et `consommationTotale`, avec conversion litres vers m³ lorsque l'unité le demande, tout en conservant le repli sur l'ancien cache.
- La courbe de charge accepte l'enveloppe confirmée `valeurs` / `unite`, journalise uniquement les noms de clés d'une première entrée inconnue et reste vide si aucun champ de consommation reconnu n'est disponible.
- Les seuils serveur de surconsommation sont informatifs, non bloquants en cas d'échec et ajoutés aux attributs de l'alerte heuristique existante. Les entités serveur associées sont désactivées par défaut.

### Fonctions opt-in

- Ajout d'une aide indicative « Éligibilité dégrèvement fuite (loi Warsmann) », désactivée par défaut et indisponible sans trois périodes homologues exactes.
- Ajout des valeurs PFAS moyenne/maximale et d'une conformité indicative depuis le widget public Eau du Grand Lyon, derrière une option désactivée par défaut et un cache de 24 heures.
- Ajout du niveau réglementaire VigiEau pour l'eau potable, derrière une option désactivée par défaut et un cache de 24 heures. L'heuristique saisonnière historique reste inchangée.

### Données et robustesse

- Extension du cache à 37 mois mensuels et 1 097 jours Téléo afin de permettre, à terme, les comparaisons sur trois années complètes.
- Les sources PFAS et VigiEau sont isolées : toute erreur HTTP, réseau ou de format les rend indisponibles sans interrompre les consommations, contrats ou factures.


## [3.5.3] - 2026-08-30

### Robustesse runtime

- **Prochaine facture facultative** : ajout d'un transport texte dédié qui conserve les protections réseau, authentification, WAF et HTTP sans affaiblir le parsing JSON des autres endpoints. Les chaînes JSON, objets JSON, dates ou datetimes ISO en texte brut sont acceptés ; les réponses vides, 204, 404, HTML ou dates inexploitables donnent désormais `None` sans faire tomber le contrat.
- **Contrat préservé** : une réponse 200 non JSON sur `dateProchaineFacture` ne déclenche plus le backoff global, le mode hors-ligne ou la perte des consommations, index, appareils et statistiques. Les erreurs réseau, authentification, WAF et serveur continuent de remonter.
- **Journalisation hors-ligne** : les retries restent en `DEBUG`, le passage en mode hors-ligne produit un seul avertissement, les cycles suivants restent silencieux et le retour du service produit un seul message d'information.

### Entités et statistiques

- **Prévision de coût** : les capteurs de prédiction mensuelle conservent leur valeur en EUR et leurs `unique_id`, mais n'utilisent plus la combinaison invalide `MONETARY + MEASUREMENT`. Une prévision ponctuelle porte désormais `state_class = None`.
- **Audit automatisé** : tests de non-régression sur les combinaisons `MONETARY`, `WATER`, `MEASUREMENT` et `TOTAL_INCREASING`, sans modification des `statistic_id` publics.
- **Contrats dynamiques** : `sensor` et `binary_sensor` ajoutent les entités d'un contrat découvert après le setup, une seule fois et sans suppression destructive lors d'une disparition temporaire.

### Qualité et documentation

- **Typage strict** : ajout de modèles `TypedDict` normalisés pour les contrats, consommations, factures, alertes, données de facturation et agrégats globaux ; adaptation du client API, du coordinator et des plateformes d'entités afin que l'intégration passe désormais la vérification mypy en mode strict.
- Couverture globale relevée à plus de 95 %, avec un contrôle CI supplémentaire exigeant strictement plus de 95 % pour chaque module Python non vide de l'intégration.
- Documentation du warning normal des custom integrations, de la date de facture réellement fournie, des transitions hors-ligne, des contrats dynamiques et de l'état non conforme des assets Brands locaux.

## [3.5.2] - 2026-08-30

### Compatibilité Home Assistant

- **Reauth/Reconfigure HA 2024.11+** : `async_update_and_abort()` reste le chemin principal sur les versions récentes. Une détection de capacité utilise `async_update_entry()` puis `async_abort()` sur HA 2024.11, qui ne fournit pas encore cette méthode.
- **Un seul reload** : aucun flow ne recharge directement l'intégration ; le listener de `ConfigEntry` reste l'unique responsable du reload, sur les deux chemins.
- **CI réelle** : ajout de smoke tests exécutés avec HA 2024.11/Python 3.12 et HA 2025.12/Python 3.13, en plus de la matrice de tests existante. Les pushes sur `DEV` déclenchent désormais la CI complète.

### Factures

- **Lien navigateur sûr** : un lien `/local/...` est créé uniquement lorsque le PDF résolu est réellement sous le dossier `www` de Home Assistant. Les chemins frères, faux préfixes et traversals `..` ne peuvent plus produire `/local/../...`.
- **Fichiers hors `www`** : le téléchargement par Home Assistant et l'écriture locale restent inchangés, mais la notification indique le chemin filesystem sans publier de faux lien navigateur.

### Migration des appareils

- **Device legacy « Morgeek »** : l'ancien identifiant `(eau_grand_lyon, entry_id)` devient stale dès qu'au moins un device contrat actif existe. Le setup le supprime automatiquement uniquement s'il correspond exactement à l'ancien format et qu'aucune entité, autre ConfigEntry ou device enfant n'en dépend.
- **Migration sûre et idempotente** : tous les devices contrats sont vérifiés avant suppression. Aucun registre d'entités, `entity_id`, `unique_id`, `statistic_id` ni historique Recorder n'est modifié.

### Tests et formatage

- Ajout de tests multi-contrats, protection des entités legacy, idempotence, liens sous/hors `www`, faux sous-répertoire et traversal.
- Le formatage Black couvre désormais aussi `tests/` et le smoke test, sans modification de leur logique.

## [3.5.1] - 2026-08-30

### Corrections

- **Téléchargement de facture** : utilisation de la route actuelle du portail (`/factures/{id}/duplicata`) avec l'identifiant API de la facture, au lieu de l'ancienne route non valide fondée sur sa référence. Les réponses HTTP 200 qui ne sont pas des PDF sont désormais rejetées.
- **Disponibilité du bouton facture** : le bouton ne dépend plus du mode expérimental et indique `indisponible` tant qu'aucune facture munie d'un identifiant téléchargeable n'est fournie.
- **Alertes de fuite ambiguës** : clarification des trois sources (surconsommation mensuelle locale, anomalie locale, estimation fournisseur sur 30 jours) sans changer leurs `unique_id`. Les heuristiques locales passent indisponibles lorsqu'elles ne disposent pas d'assez de données.

### Documentation

- Remplacement des promesses imprécises par une matrice indiquant ce qui est fonctionnel, conditionnel, expérimental, indicatif ou incomplet.
- Documentation des limites du mode vacances, de la qualité de l'eau, du calendrier, des estimations environnementales et du téléchargement PDF.

## [3.5.0] - 2026-08-30

### Facturation

- **Montant réel distinct des estimations** : le capteur `derniere_facture` expose le montant TTC renvoyé par le fournisseur, indépendamment du mode expérimental. Les capteurs historiques conservent leurs `unique_id`, mais leurs noms et attributs indiquent désormais clairement qu'ils sont estimés.
- **Mode dernière facture** : nouveau mode recommandé qui calcule un taux TTC tout compris à partir de `montant TTC ÷ volume facturé`. Le cas de régression anonymisé de 88 m³ reproduit ainsi 328,42 € au lieu de 367,40 €.
- **Grille officielle 2026** : ajout des tranches annuelles d'eau potable, des composantes variables TTC et des parts fixes par calibre de compteur publiées par Eau du Grand Lyon. Ce mode sert aussi de repli si la dernière facture n'a pas de montant ou de volume exploitable.
- **Modes manuel et dynamique** : ils restent disponibles pour les configurations personnalisées. Les entrées existantes sont migrées vers leur comportement antérieur (manuel ou dynamique) et peuvent sélectionner le nouveau mode depuis les options.
- **Transparence** : ajout du mode, de la source, du volume, du taux effectif et de la ventilation variable/fixe dans les attributs des capteurs de coût.

### Tests

- Ajout de tests unitaires pour les paliers 2026, les diamètres de compteur, les valeurs non finies, le repli automatique et la facture anonymisée de référence.

## [3.4.6] - 2026-08-30

### Corrections

- **Reconfigure** : le tarif au m³ n'est plus affiché ni ignoré silencieusement ; il est désormais stocké uniquement dans les options, avec migration sans perte des entrées v1/v2.
- **Reauth/Reconfigure Home Assistant 2026.12** : adoption de `_get_reauth_entry()`, `_get_reconfigure_entry()`, `_abort_if_unique_id_mismatch()` et `async_update_and_abort()` ; suppression des reloads explicites et des risques de double reload/race condition.
- **Identité de compte** : l'email normalisé reste l'`unique_id` ; un flow ne peut plus convertir une entrée en un autre compte, notamment un compte déjà configuré.
- **Erreurs API** : ajout d'erreurs HTTP typées ; les erreurs réseau, authentification, WAF, timeout, serveur et JSON invalide remontent désormais au coordinator. Seuls les endpoints explicitement optionnels utilisent un repli borné aux statuts attendus.
- **Sessions HTTP** : remplacement de `CookieJar(unsafe=True)` par le jar sécurisé par défaut et création des sessions dédiées via le helper Home Assistant, sans modification du flux OAuth/PKCE.
- **mypy/CI** : résolution du doublon de modules, analyse effective des 26 fichiers Python et suppression du `continue-on-error` trompeur.

### Tests et qualité

- Couverture portée d'environ 64 % à 77 %, avec renforcement ciblé des flows, du transport API, du coordinator, du cycle setup/unload, des services, du calendrier, des devices, du cache et du mode hors-ligne.
- La déclaration Gold a été retirée : aucun niveau officiel n'est revendiqué tant que `brands` (Bronze), `test-coverage` (Silver) et `dynamic-devices` (Gold) restent en `todo`.
- Aucun `unique_id`, `statistic_id`, nom d'entité ou format de Store persistant existant n'a été modifié.

## [3.4.5] - 2026-08-21

### Ajouts

- **Statistique journalière Téléo** : ajout de `eau_grand_lyon:water_daily_<ref>`, reconstruite par date pour intégrer automatiquement les corrections tardives de l'API.
- **Coût journalier Téléo** : ajout de `eau_grand_lyon:cost_daily_<ref>`, calculé à partir de la consommation journalière et du tarif configuré.
- **Transparence des coûts** : les capteurs de coût réel indiquent explicitement que l'abonnement est inclus ; les statistiques historiques restent limitées au coût variable.

### Corrections de robustesse

- **Cache journalier** : les dates et valeurs invalides sont ignorées au chargement afin de ne pas interrompre un rafraîchissement Home Assistant.
- **Statistiques idempotentes** : les journées dupliquées sont dédoublonnées avant reconstruction des cumuls.
- **Parser Téléo** : les métadonnées comptent uniquement les entrées normalisées et exploitables.
- **Identifiants de statistiques** : les préfixes sont centralisés sans modifier les identifiants publics existants.

## [3.4.2] - 2026-08-11

Quatre correctifs remontés par un retour utilisateur détaillé sur une installation en production, packagés dans une release distincte car mergés dans `main` après la publication du tag `v3.4.1` (qui ne les contenait donc pas).

### Corrections de Bugs

- **Crash du flux d'options si aucune entité de prix dynamique n'est configurée** (`config_flow.py`) : `vol.Optional(CONF_PRICE_ENTITY, default="")` valide la valeur par défaut même quand le champ est vide — un `EntitySelector` rejette alors une chaîne vide avec `Entity is neither a valid entity ID nor a valid UUID.`, bloquant la sauvegarde des options pour tout utilisateur n'ayant pas configuré d'entité de prix dynamique (la majorité, régression introduite par l'`EntitySelector` de la 3.4.1). **Fix** : le champ n'a plus de `default` invalide ; `description={"suggested_value": ...}` pré-remplit le champ sans déclencher de validation sur le vide.
- **Attribut `nombre_habitants` vide** (`sensors/contract.py`) : l'API ne peuple pas toujours `servicesSouscrits[0].nombreHabitants` selon le type de contrat. **Fix** : repli sur l'option `household_size` déjà collectée pour l'Éco-Score, avec la mention « (valeur configurée) » pour indiquer la provenance.
- **Capteur batterie faussement rassurant** (`binary_sensor.py`) : sans `etatPile` dans la réponse API, `battery_ok` vaut `None`, et `is_on = (battery_ok is False)` affichait silencieusement « pile OK » sans aucune donnée réelle. **Fix** : le capteur passe `unavailable` quand `battery_ok` est absent au lieu d'afficher un état non fondé.
- **Index compteur affiché 1000x trop grand sur les compteurs récents / à faible cumul** (`api/client.py`) : l'API déclare l'unité de l'index (`unites.index = "l"`) mais seul `_extract_index` en tenait compte, via un filet de sécurité par magnitude (conversion L→m³ uniquement si l'index brut dépassait 100 000). Un compteur avec un index physique de 20,990 m³ (donc un index brut API de 20990 L) reste **sous** ce seuil : aucune conversion n'était appliquée, et l'index — donc les capteurs "Index compteur" / "Index journalier" qui alimentent le tableau de bord Énergie — s'affichait `20990.000 m³` au lieu de `20.990 m³`. Les deltas quotidiens calculés par HA en héritaient directement : une consommation réelle de 80 L/jour s'affichait comme **80 m³/jour**. **Fix** : `_parse_daily_response` convertit désormais l'index dès que l'unité déclarée par l'API est "l" (même logique déjà appliquée à `volumeEstimeFuite`/`debitMin`) ; le filet de sécurité par magnitude reste en repli uniquement pour les réponses sans bloc `unites`.

### Renommage

- Le capteur `conso_hier` s'appelle désormais « Dernière conso journalière connue » (au lieu de « Consommation d'hier ») pour éviter la confusion avec le décalage de 2-3 jours possible de la télé-relève Téléo. `entity_id` et `unique_id` inchangés — aucun impact sur les automatisations ou l'historique.

## [3.4.1] - 2026-07-19

Traitement de l'intégralité des axes d'amélioration restants de l'audit et retour au niveau Gold, honnêtement mérité cette fois.

### ⚠️ Changements cassants

Deux catégories peuvent impacter vos **automatisations, templates et cartes existants**.

**1. Valeurs d'état de capteurs (traduction ENUM).** L'état brut renvoyé par `states('sensor.xxx')` de quatre capteurs passe de textes français à des clés en minuscules (l'affichage dans l'interface reste traduit, mais la valeur testée dans les automatisations change). Mettez à jour vos comparaisons :

| Capteur | Avant | Après |
| --- | --- | --- |
| Santé de l'intégration | `OK` / `KO` / `HORS-LIGNE` / `INCONNU` | `ok` / `error` / `offline` / `unknown` |
| Niveau de sécheresse | `Normal` / `Vigilance` / `Crise` | `normal` / `vigilance` / `crise` |
| Compatibilité compteur | `Téléo (Télé-relève)` / `Standard (Relève manuelle)` | `teleo` / `standard` |
| Eco-Score | `A` … `G` / `Inconnu` | `a` … `g` / `unknown` |

Exemple : `{{ states('sensor.xxx') == 'OK' }}` devient `== 'ok'`.

**2. Classes de capteurs (statistiques long terme).** Les capteurs de consommation « mois précédent », « annuelle », « 7 derniers jours », « 30 derniers jours », « veille », « référence annuelle » et « prédiction conso » passent de `state_class: total` à `measurement` et perdent leur `device_class: water` (combinaison invalide). Home Assistant peut afficher un avertissement sur ces entités et réinitialiser leurs statistiques long terme. **Aucune action requise** : la consommation officielle du tableau Énergie provient des statistiques externes (`eau_grand_lyon:water_*`), qui ne sont pas impactées.

### Corrections de Bugs

- **Régression agrégats multi-contrats** (`coordinator.py`) : le bloc de mise à jour de `global_data` (conso / coût / prédiction totaux) était devenu du code mort après le `raise` introduit en 3.4.0 → les capteurs globaux affichaient 0. **Fix** : agrégation réintégrée dans la boucle des contrats.
- **Garde d'identité en ré-auth / reconfiguration** (`config_flow.py`) : un changement d'email laissait l'`unique_id` sur l'ancien compte, cassant la détection de doublon. **Fix** : `async_set_unique_id` + mise à jour de l'`unique_id` de l'entrée.
- **`state_class` incohérents** (`sensors/`) : conso 7j/30j/annuelle, référence annuelle, veille, prédictions et compteur d'alertes passent de `TOTAL` à `MEASUREMENT` (valeurs glissantes/statiques, sans device_class WATER incompatible).
- **Alerte tartre permanente** (`coordinator.py`) : basée sur l'index absolu du compteur (cumul depuis la pose), l'alerte était quasi toujours active. **Fix** : calcul borné sur les 12 derniers mois.
- **`get_invoice_pdf`** (`api/client.py`) : ré-authentifie sur 401 (token expiré), distingue le 403 WAF, gère les timeouts.
- **`max_retries` non borné** (`coordinator.py`) : une option à 0 donnait `range(0)` → aucune tentative. **Fix** : `max(1, ...)` + try/except.
- **Tâches réseau orphelines** (`coordinator.py`) : les tâches en vol sont annulées sur les chemins d'erreur (fin des warnings « Task exception was never retrieved » et des requêtes fantômes).
- **Fuseau horaire** : `date.today()` → `dt_util.now()` (`calendar.py`, `binary_sensor.py`).

### Qualité — retour au Gold

- **`action-setup`** : services enregistrés dans `async_setup` (et non `async_setup_entry`).
- **`exception-translations`** : exceptions de service reliées à des `translation_key` (`export_failed`, `download_failed`, `invalid_path`, `path_not_allowed`, `no_invoices`).
- **`entity-translations`** : états traduits via `device_class` ENUM pour santé, sécheresse, compatibilité compteur et éco-score (+ sections `state` FR/EN).
- **`stale-devices`** : `async_remove_config_entry_device` permet de supprimer un compteur dont le contrat a disparu ; l'historique mensuel des contrats disparus est purgé.
- **`brands`** : marqué `exempt` (dépôt custom, icônes via `brand/` local — soumission au store par défaut non requise).
- **`quality_scale` : Silver → Gold** (`manifest.json` + `quality_scale.yaml`).

### Polish

- Imports canoniques : `HomeAssistantError` / `ServiceValidationError` depuis `homeassistant.exceptions`.
- Options : `CONF_PRICE_ENTITY` en `EntitySelector` (sensor / input_number) ; libellés d'intervalle traduisibles via un `SelectSelector`.

### Tests & CI

- **Couverture** : `pytest-cov` avec seuil `--cov-fail-under=60` (couverture actuelle ~63 %).
- **mypy** : configuration `mypy.ini` + job CI (non bloquant ; `strict-typing` Platinum reste à durcir).
- **Smoke tests** : job CI `workflow_dispatch` (exécution manuelle contre un vrai Home Assistant).
- **Nouveaux tests** : migration d'entrée v1→v2, happy-path de `async_step_user`, suppression d'appareils obsolètes, ré-authentification du téléchargement de facture, `translation_key` des exceptions, ancrage des statistiques.

## [3.4.0] - 2026-07-19

Audit de robustesse : correction de la chaîne de gestion d'erreurs (qui court-circuitait le mode hors-ligne), de deux URLs invalides, et fiabilisation des statistiques long terme. Quality Scale ajusté de Gold à Silver pour refléter la réalité.

### Corrections de Bugs

- **Timeouts non gérés** (`api/client.py`, `api/auth.py`) : `aiohttp.ClientTimeout` lève `asyncio.TimeoutError`, qui n'est pas un `aiohttp.ClientError` — il échappait aux blocs de gestion et remontait en `UpdateFailed` sec, **sans retry ni bascule sur le cache hors-ligne**, alors que le timeout est le mode d'échec réseau le plus courant. **Fix** : converti en `NetworkError` dans `_request` et les trois blocs d'authentification.
- **Erreurs serveur / réponses malformées** (`api/client.py`, `coordinator.py`) : un HTTP 5xx (`ApiError`) ou un corps non-JSON (page WAF/maintenance renvoyée en 200) tombait aussi dans le `except` générique → échec immédiat, cache ignoré. **Fix** : nouveau parseur `_parse_json` (corps non-JSON → `ApiError`) et gestion de `ApiError` dans la boucle de retry ; une erreur inattendue sert désormais le cache si disponible.
- **Ré-authentification concurrente** (`api/auth.py`) : à l'expiration du token en milieu de cycle, chaque requête en vol déclenchait son propre flux OAuth complet — rafale de logins contre le WAF. **Fix** : `asyncio.Lock` + réutilisation du token fraîchement obtenu par les appels concurrents.
- **Un contrat en échec faisait tomber tout le compte** (`coordinator.py`) : `asyncio.gather` sans `return_exceptions`. **Fix** : les contrats sont isolés ; l'erreur n'est propagée que si *tous* échouent (pour ne pas écraser le cache avec des données vides).
- **URL de téléchargement de facture invalide** (`api/client.py`) : `get_invoice_pdf` utilisait `/rest/produits/...` (404). **Fix** : passage par `/application/rest/produits/...`.
- **URL de révocation de token invalide** (`api/endpoints.py`) : `TOKEN_REVOKE_URL` pointait sur `/auth/revoke` (404). **Fix** : `/application/auth/revoke`.
- **Placeholder de traduction manquant** (`strings.json`, `translations/*`) : l'erreur `waf_blocked` contenait `{recommended_interval}` jamais fourni → `formatjs MISSING_VALUE` au premier blocage WAF dans un formulaire. **Fix** : valeur (24h) inlinée, plus de placeholder.
- **Mode vacances non restauré au redémarrage** (`switch.py`) : le switch réaffichait « on » mais `coordinator.vacation_mode` restait `False` — surveillance silencieusement inactive. **Fix** : resynchronisation dans `async_added_to_hass`.
- **Multiplicateur de fuite ignoré** (`coordinator.py`, `binary_sensor.py`) : la détection journalière utilisait un `2,5` codé en dur au lieu de l'option `CONF_LEAK_MULTIPLIER`, et l'attribut d'info affichait la valeur par défaut au lieu de la valeur configurée. **Fix** : lecture unifiée de l'option configurée.

### Statistiques long terme

- **Deltas négatifs sur fenêtre glissante** (`coordinator.py`) : le cumul repartait de 0 à chaque injection ; quand un mois quittait la fenêtre de 36 mois, les sommes ré-injectées devenaient inférieures à celles déjà dans le recorder → pics négatifs dans le tableau Énergie. **Fix** : le cumul s'ancre sur la dernière somme connue du recorder (`get_last_statistics`, best-effort avec repli sur l'ancien comportement).
- **Mois courant figé** : la garde « n'injecter que si le nombre de mois change » empêchait le rafraîchissement de la conso du mois en cours (révisée chaque jour par l'API). **Fix** : garde retirée, injection à chaque cycle.
- **`state_class` / `device_class` corrigés** (`sensors/consumption.py`, `sensors/alerts.py`) : « mois précédent » passe en `MEASUREMENT` (au lieu de `TOTAL_INCREASING`, qui lisait chaque baisse mensuelle comme un reset de compteur et gonflait les statistiques) ; les capteurs de seuil perdent le `device_class` WATER (incompatible avec `MEASUREMENT`).

### Qualité

- **Quality Scale : Gold → Silver** (`manifest.json`, `quality_scale.yaml`) pour refléter la réalité : `action-setup`, `brands`, `exception-translations`, `entity-translations` (états), `stale-devices` passés en `todo` avec justification honnête.
- **Suite de tests** : tests factices remplacés par de vrais tests (`test_concurrency.py` teste maintenant le verrou d'authentification ; `benchmarks.py` supprimé ; tautologies remplacées par des tests réels de `check_long_outage_issue`). Couverture ajoutée pour l'ancrage des statistiques, la gestion `ApiError`/timeout et les `state_class` par période.

### Dépôt

- Le dépôt GitHub ne contient désormais que les fichiers nécessaires à HACS / Home Assistant (intégration, blueprints, cartes Lovelace, docs). L'outillage de développement (tests, CI, pré-commit) est conservé en local mais retiré du suivi Git.

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
