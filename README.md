# Intégration Eau du Grand Lyon pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Tests & Validation](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/actions/workflows/tests.yaml/badge.svg?branch=main)](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/actions/workflows/tests.yaml)

Ceci est une intégration personnalisée non officielle pour [Home Assistant](https://www.home-assistant.io/) qui récupère la consommation d'eau, les informations de contrat et les alertes du service Eau du Grand Lyon.

> **À savoir** : l'intégration interroge le portail Eau du Grand Lyon. Elle nécessite un compte client valide et peut être limitée par le pare-feu anti-abus du service.

> **Message Home Assistant normal** : `We found a custom integration eau_grand_lyon which has not been tested by Home Assistant` est affiché pour les intégrations installées dans `custom_components`. Il ne signale pas une panne et ne peut pas être supprimé proprement par l'intégration.

## Démarrage rapide

1. Installez l'intégration avec HACS, ou copiez le dossier `custom_components/eau_grand_lyon/` dans votre configuration Home Assistant.
2. Redémarrez Home Assistant.
3. Allez dans **Paramètres > Appareils et services > Ajouter une intégration**.
4. Recherchez **Eau du Grand Lyon**, puis saisissez votre email et votre mot de passe.
5. Ouvrez **Configurer** pour choisir le mode de calcul des coûts et la fréquence de mise à jour.

Les données apparaissent après la première synchronisation. Celle-ci peut prendre quelques minutes et les données Téléo peuvent être publiées avec un décalage fourni par le distributeur.

## Quel compteur est pris en charge ?

| Compteur | Données disponibles |
| --- | --- |
| **Téléo** | Consommation journalière, index journalier, alertes de fuite, signal et fonctions horaires selon le compte |
| **Standard** | Consommation mensuelle, contrat, factures et indicateurs généraux |

Le capteur **Compatibilité compteur** permet de vérifier le type détecté. Les capteurs incompatibles restent indisponibles ou sont désactivés par défaut.

## État réel des fonctionnalités

Ce tableau distingue les données fournies par Eau du Grand Lyon des calculs effectués localement. La disponibilité peut varier selon le contrat et le type de compteur.

| Fonction | État | Précision importante |
| --- | --- | --- |
| Contrats, consommations mensuelles, historique et cache hors-ligne | Fonctionnel | Données du portail, avec publication souvent mensuelle |
| Consommation et index journaliers | Conditionnel | Uniquement si le compte expose les données Téléo |
| Courbe horaire, signal, pile et estimation de fuite fournisseur | Expérimental/conditionnel | Les capteurs restent indisponibles si l'API ne renvoie pas les champs nécessaires |
| Montant de la dernière facture | Fonctionnel si fourni | Montant TTC réel du portail, distinct des capteurs de coût estimé |
| Téléchargement du PDF | Conditionnel | Utilise l'identifiant interne et la route `duplicata` du portail ; nécessite une facture marquée téléchargeable et un dossier autorisé dans Home Assistant |
| Prédictions, Eco-Score, coaching, CO₂e et calcaire | Indicatif | Formules locales déterministes, pas de modèle d'IA ni de barème officiel garanti |
| Qualité de l'eau | Conditionnel | Configurez la commune ; sinon la première mesure Open Data disponible peut concerner une autre commune |
| PFAS | Expérimental/opt-in | Valeurs publiques du widget Eau du Grand Lyon, au plus une lecture par jour ; entités désactivées par défaut |
| Calendrier | Fonctionnel selon les dates fournies | La prochaine facture n'est publiée comme état que si l'API renvoie une date exploitable ; l'estimation locale à échéance + 180 jours reste séparée dans l'attribut `date_estimée` |
| Mode vacances | Incomplet | Le seuil est calculé et journalisé, mais aucune entité d'alerte ni notification dédiée n'est actuellement exposée |
| Sécheresse | Indicatif + officiel opt-in | L'heuristique calendaire est conservée ; VigiEau peut fournir séparément le niveau officiel AEP de la commune |
| Aide Warsmann | Indicatif | Compare une période aux trois périodes homologues précédentes ; indisponible sans historique complet et désactivée par défaut |

### Alertes de consommation et de fuite

Trois capteurs différents existent ; ils ne représentent pas la même information :

| Nom affiché | Source | Comportement |
| --- | --- | --- |
| **Alerte surconsommation mensuelle (heuristique)** | Calcul local | Compare le mois courant au mois précédent avec le multiplicateur configuré ; ce n'est pas une preuve de fuite |
| **Alerte anomalie locale (heuristique)** | Calcul local, désactivé par défaut | Recherche un flux horaire continu sur au moins 24 points ou un pic sur au moins 7 jours de données ; indisponible sans cet historique |
| **Alerte fuite fournisseur (estimation 30 j)** | Champ `volumeFuiteEstime` du portail, désactivé par défaut | Disponible en mode expérimental uniquement si le fournisseur renvoie ce champ ; ce n'est pas une détection temps réel |

L'ancienne présentation « Alerte Fuite possible » et « Alerte Fuite (Pattern local) » donnait l'impression d'un doublon. Les `unique_id` sont conservés pour ne pas casser les automatisations, mais les noms affichés ont été clarifiés.

Les seuils journalier et mensuel configurés dans l'espace fournisseur sont exposés comme attributs informatifs de l'alerte mensuelle locale. Ils ne remplacent pas son multiplicateur et ne modifient pas son état ON/OFF.

### PFAS, VigiEau et aide Warsmann

- **PFAS** : après activation explicite, l'intégration résout la commune configurée via l'autocomplétion publique puis lit la [page Qualité de mon eau](https://www.eaudugrandlyon.com/mon-eau/eau-chez-moi/qualite-de-mon-eau/). Les valeurs moyenne/maximale et le nombre de prélèvements sont mis en cache 24 h. Une valeur maximale inférieure ou égale à 0,1 µg/L donne l'indication « conforme » ; si le HTML change, les entités deviennent indisponibles.
- **VigiEau** : après activation explicite, la commune est résolue en code INSEE puis l'[API officielle VigiEau](https://api.vigieau.gouv.fr/swagger/) est interrogée pour le profil `particulier` et l'eau potable (`AEP`). Le capteur officiel complète l'heuristique saisonnière sans la remplacer.
- **Warsmann** : le capteur désactivé par défaut applique le seuil du double de la moyenne sur trois périodes homologues, conformément à [l'article L2224-12-4 du CGCT](https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000041410387). Il reste une aide : il ne vérifie ni la nature de la fuite, ni la réparation, ni la notification du fournisseur. Le délai légal actuel est d'un mois après l'information, et aucun compte à rebours automatique n'est créé.

### Estimations locales indicatives

- La prédiction de fin de mois est une extrapolation linéaire de la consommation connue au dernier jour publié.
- L'Eco-Score utilise des seuils internes par personne ; il ne constitue pas un classement officiel.
- Le coaching est un ensemble de conseils déterministes selon le score, la tendance et l'heuristique de fuite ; il ne fait pas appel à une IA.
- Le CO₂e applique un facteur fixe de 0,52 kg CO₂e/m³ et le calcaire dépend de la dureté configurée. Ces résultats sont des ordres de grandeur.
- La moyenne sur 7 jours, la tendance N-1 et les prédictions exigent un historique suffisant.

### Services et utilitaires

- **Export CSV** : service `eau_grand_lyon.export_data` pour sauvegarder l'historique en local.
- **Téléchargement facture PDF** : service `eau_grand_lyon.download_latest_invoice` pour récupérer un duplicata disponible sur le portail.
- **Réparations Home Assistant** : signalement d'une panne API prolongée de plus de sept jours.
- **Santé Téléo** : signal et pile uniquement lorsque le portail fournit réellement ces données.

Le répertoire de destination des exports et factures doit être autorisé dans `configuration.yaml` :

```yaml
homeassistant:
  allowlist_external_dirs:
    - /config/exports
    - /config/www/eau_grand_lyon
```

Redémarrez Home Assistant après avoir modifié cette liste.

### Mode hors-ligne

Si l'API Eau du Grand Lyon est indisponible (coupure réseau, maintenance, blocage WAF), l'intégration bascule automatiquement en **mode hors-ligne** :
- Les capteurs restent disponibles et affichent les dernières données connues
- Le capteur **Statut API** affiche `Hors-ligne` (état brut `offline`) avec l'horodatage du début de la panne
- Le cache est persistant sur disque — il survit à un redémarrage de Home Assistant
- Dès que l'API répond à nouveau, les données sont rafraîchies et le mode hors-ligne se désactive automatiquement

Les tentatives intermédiaires restent au niveau `DEBUG`. Une panne persistante produit un seul avertissement lors du passage en mode hors-ligne, puis un seul message d'information au retour du service ; les cycles identiques suivants ne répètent pas le même avertissement.

### Contrats ajoutés après l'installation

Les plateformes `sensor` et `binary_sensor` surveillent les contrats découverts à chaque mise à jour. Un nouveau contrat et ses entités sont ajoutés sans recharger l'intégration et sans recréer les entités déjà présentes. Si un contrat disparaît temporairement, aucune entité, statistique Recorder ou donnée historique n'est supprimée automatiquement ; sa réapparition ne crée pas de doublon.

### Mode Expérimental (données étendues)
Une option **Mode expérimental** (désactivée par défaut) active la récupération de données supplémentaires, lorsque votre compteur et votre compte les exposent :
- **Courbe de charge horaire** (compteurs Téléo) et **volumes de fuite estimés**.
- Ces données proviennent d'endpoints additionnels de l'API. Si elles ne sont pas disponibles pour votre compteur, les capteurs correspondants restent simplement indisponibles, sans impacter le reste de l'intégration.

Le montant TTC de la dernière facture est une donnée principale et ne dépend plus du mode expérimental.

**Activation** :
1. Allez dans Paramètres > Appareils et services.
2. Recherchez l'intégration Eau du Grand Lyon.
3. Cliquez sur **Configurer** (ou **Options** selon votre version de HA).
4. Cochez la case **Mode expérimental**.

Si votre compteur est compatible, les capteurs supplémentaires apparaîtront automatiquement (pensez à vérifier s'ils sont désactivés par défaut dans l'interface des entités).

## Réglages recommandés

- **Fréquence de mise à jour** : 24 heures. Utilisez 48 heures si le portail bloque temporairement les requêtes.
- **Mode de calcul des coûts** : utilisez « Dernière facture » pour une estimation calibrée sur le montant TTC réellement facturé. En l'absence d'une facture avec volume exploitable, l'intégration bascule sur la grille officielle 2026.
- **Tarif manuel et part fixe** : utilisés uniquement dans les modes manuel et dynamique.
- **Nombre d'habitants** : utilisé pour l'Éco-Score et les conseils personnalisés.
- **Mode expérimental** : laissez-le désactivé tant que vous n'avez pas besoin des données étendues Téléo.
- **PFAS / VigiEau** : configurez d'abord une commune exacte, puis activez uniquement la source souhaitée. Chaque source est limitée à une interrogation par 24 heures.

## Mise à jour des données

L'intégration récupère vos données de consommation selon un intervalle configurable :

- **Intervalle par défaut** : 24 heures (pour éviter les blocages WAF)
- **Intervalle configurable** : 6h, 12h, 24h, 48h — accessible via Paramètres > Appareils et services > Options
- **Mise à jour manuelle** : Service `update_now` pour forcer un rafraîchissement immédiat
- **Cache persistant** : En cas d'indisponibilité API, les dernières données connues restent affichées localement
- **Retry automatique** : les délais augmentent exponentiellement et incluent un léger jitter de ±20 %. Avec les trois tentatives par défaut (tentative initiale comprise), une panne réseau/API utilise environ 10 puis 20 secondes entre les tentatives, tandis qu'un blocage WAF utilise environ 60 puis 120 secondes. Ces durées sont indicatives en raison du jitter.

Les services `eau_grand_lyon.update_now` et `eau_grand_lyon.clear_cache` permettent respectivement de forcer une synchronisation et de repartir d'un cache vide.

### Gestion du blocage WAF

L'API officielle utilise un pare-feu web (WAF) qui peut bloquer les requêtes trop fréquentes. Si vous recevez l'erreur "Requête bloquée par le pare-feu", deux solutions :
1. **Augmentez l'intervalle** : Passez à 48 heures au lieu de 24h
2. **Attendez quelques minutes** : L'intégration réessaye automatiquement après un délai exponentiel

### Intégration Energy Dashboard

#### Statistiques injectées automatiquement
Les statistic IDs externes suivants sont injectés automatiquement par le coordinateur :

| Statistic ID | Unit | Period | Usage |
|---|---|---|---|
| `eau_grand_lyon:water_<ref>` | m³ | Monthly | Historique consommation jusqu'à 36 mois, Energy Dashboard |
| `eau_grand_lyon:water_daily_<ref>` | m³ | Daily | Historique journalier reconstruit, corrections tardives incluses |
| `eau_grand_lyon:cost_<ref>` | EUR | Monthly | Historique coûts jusqu'à 36 mois (si tarif configuré) |
| `eau_grand_lyon:cost_daily_<ref>` | EUR | Daily | Coût variable journalier Téléo (si tarif configuré) |

*`<ref>` = votre numéro de contrat (ex: AB1234567890)*

> **Note sur les capteurs annuels** : Le capteur "Consommation annuelle" affiche les **12 derniers mois glissants** (pas l'année civile). Pour suivre la consommation depuis le 1er janvier, utilisez le capteur "Consommation depuis janvier" (`consommation_cumulee_annee`) ou le capteur de coût cumulé.

> **Migration du tableau Énergie** : après la mise à jour, sélectionnez une fois `eau_grand_lyon:water_daily_<ref>` comme statistique historique de la source d'eau. L'ancienne statistique mensuelle reste intacte; cette migration est donc réversible et n'entrepose pas les anciennes valeurs erronées dans la nouvelle série.

> **Abonnement** : les statistiques `cost_<ref>` et `cost_daily_<ref>` contiennent uniquement le coût variable (`consommation × tarif_m3`). L'abonnement annuel configuré est intégré aux capteurs `cout_reel_mois` et `cout_reel_annuel`, mais pas aux statistiques historiques, afin de ne pas dupliquer une charge fixe à chaque journée.

Configuration :
1. **Vérifier que le capteur de coût est activé** : `sensor.eau_du_grand_lyon_energie_cout`
2. **Choisir le mode de calcul des coûts** dans Paramètres > Options
3. **Ajouter une source d'eau** au tableau de bord Énergie :
   - Téléo : `sensor.eau_du_grand_lyon_index_journalier_energy` (quotidien, haute précision)
   - Standard : `sensor.eau_du_grand_lyon_index_compteur` (mensuel)
4. **Ajouter le coût** pour cette source : `sensor.eau_du_grand_lyon_energie_cout`
5. **Coûts** : `sensor.eau_du_grand_lyon_energie_cout` (auto-calculé si tarif configuré)
6. **Statistiques** : Utilisez les statistic IDs ci-dessus pour les cartes statistiques.

### Comprendre les coûts

- **Dernière facture** : le capteur `derniere_facture` expose le montant TTC réel renvoyé par le fournisseur. Il ne s'agit jamais d'une estimation.
- **Automatique depuis la dernière facture** (recommandé) : le taux TTC effectif est `montant TTC ÷ volume facturé`, ce qui intègre les parts eau, assainissement, redevances et part fixe telles qu'elles ont réellement été facturées.
- **Grille officielle 2026** : applique les tranches annuelles de l'eau potable, les composantes variables et la part fixe correspondant au calibre du compteur. La grille provient du [tarif général Eau du Grand Lyon 2026](https://www.eaudugrandlyon.com/wp-content/uploads/2026/04/Tarif-general-2026.pdf).
- **Manuel** : applique le tarif au m³ et la part fixe saisis dans les options.
- **Dynamique** : applique la valeur d'une entité Home Assistant et la part fixe manuelle.

Les noms historiques et les `unique_id` des capteurs sont conservés, mais les capteurs `cout_mois`, `cout_annuel`, `cout_reel_mois` et `cout_reel_annuel` sont explicitement présentés comme des estimations. Leurs attributs indiquent le mode, la source du tarif, le volume, le taux effectif et la décomposition variable/fixe.

Les statistiques `cost_<ref>` et `cost_daily_<ref>` restent des approximations variables destinées au tableau Énergie. La part fixe n'y est pas ajoutée afin de ne pas la compter plusieurs fois dans l'historique.

#### Dépannage rapide
- ⚠️ Capteurs grisés ? → Paramètres > Appareils et services > Eau du Grand Lyon > Activer
- 📊 Statistiques vides ou graphique incomplet ? → Forcer une mise à jour avec le bouton dédié, puis attendre quelques secondes
- 🔍 Statistic ID inconnu ? → Vérifiez les statistiques dans **Outils de développement > Statistiques** ou utilisez la recherche de statistiques dans l'interface.

## Appareils supportés

L'intégration fonctionne avec deux types de compteurs :

| Type | Nom | Disponibilité des données |
|------|-----|---------------------------|
| **Téléo** (communicant) | Compteur communicant Eau du Grand Lyon | Consommation journalière ; courbe horaire, estimation de fuite et signal seulement si l'API les expose |
| **Standard** | Compteur traditionnel avec relevé manuel | Consommation mensuelle uniquement |

### Comment savoir quel compteur j'ai ?

- Un capteur **Compatibilité compteur** (désactivé par défaut) indique `Téléo` ou `Standard`
- Allez dans Paramètres > Appareils et services > Eau du Grand Lyon > Entités
- Cherchez "Compatibilité compteur" — activez-la si elle est masquée

## Limitations connues

- **Mise à jour mensuelle** : Les données de consommation sont généralement mises à jour une fois par mois par le service. La vue quotidienne n'est disponible que pour les compteurs Téléo.
- **Blocage WAF** : L'API officielle peut bloquer les requêtes trop fréquentes. Consultez la section "Mise à jour des données" pour plus de détails.
- **Données historiques API** : L'API Eau du Grand Lyon ne retourne qu'une fenêtre historique limitée. L'intégration accumule jusqu'à **37 mois** mensuels et **1 097 jours** Téléo en cache local persistant. L'aide Warsmann reste indisponible tant que les trois périodes homologues exactes ne sont pas toutes présentes.
- **Compteurs Standard** : Les détails horaires et alertes temps réel ne sont disponibles que sur compteurs Téléo.
- **Mode hors-ligne** : En cas d'indisponibilité prolongée (>7 jours), une alerte apparaît dans les réparations HA.
- **Alertes locales** : elles détectent une surconsommation ou une anomalie statistique, pas une fuite certaine. Le capteur local est indisponible sans au moins 24 points horaires ou 7 jours de données.
- **Mode vacances** : son résultat n'est pas encore exposé sous forme de capteur ou de notification ; le switch seul ne constitue donc pas une alarme opérationnelle.
- **Qualité de l'eau** : renseignez la commune dans les options pour éviter qu'une mesure Open Data d'une autre commune soit affichée.
- **PFAS et VigiEau** : ces sources publiques optionnelles peuvent changer ou être indisponibles ; leur échec n'affecte jamais le rafraîchissement principal. PFAS dépend du rendu HTML public, VigiEau d'une résolution fiable de la commune.
- **Indicateurs environnementaux** : Eco-Score, coaching, CO₂e, calcaire et sécheresse sont des calculs locaux indicatifs.

## Dépannage

### L'intégration affiche « Hors-ligne »

**Cause** : L'API Eau du Grand Lyon est indisponible ou inaccessible.

**Solutions** :
1. Vérifiez votre connexion réseau et que le serveur https://agence.eaudugrandlyon.com est accessible
2. Attendez quelques minutes — l'intégration réessaye automatiquement
3. Utilisez le service **Effacer le cache** (Paramètres > Appareils et services) pour réinitialiser l'état
4. Consultez les logs dans **Paramètres > Système > Journaux**.

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

### L'index compteur ou la consommation journalière affiche une valeur anormale

**Cause** : l'API peut fournir un index en litres alors que l'entité attend des m³. L'intégration convertit les unités déclarées par l'API et utilise un repli par magnitude lorsque l'unité est absente.

**Solutions** :
1. Vérifiez les unités et les valeurs brutes renvoyées par l'API dans les attributs du capteur.
2. Les statistiques long terme déjà enregistrées peuvent être corrigées dans `Outils de développement > Statistiques`.
3. Si nécessaire, utilisez le service **Effacer le cache** puis **Forcer la mise à jour** pour reconstruire l'historique depuis l'API.

### Certains capteurs sont manquants

**Cause** : Certains capteurs techniques sont désactivés par défaut.

**Solutions** :
1. Allez dans Paramètres > Appareils et services > Eau du Grand Lyon > Entités
2. Cherchez les capteurs que vous souhaitez voir (ex. "Fuite estimée", "Heure de pic", "Éco-Score")
3. Cliquez sur le capteur puis sur l'icône engrenage → Activez le capteur

### Pourquoi deux ou trois alertes de fuite apparaissent-elles ?

Elles ne proviennent pas de la même source. **Alerte surconsommation mensuelle** compare deux mois, **Alerte anomalie locale** analyse les points journaliers ou horaires, et **Alerte fuite fournisseur** reprend un volume estimé sur 30 jours lorsque le portail le fournit. Les deux dernières sont désactivées par défaut. Consultez leurs attributs pour connaître la méthode utilisée et évitez de traiter une heuristique comme une fuite confirmée.

Après la mise à jour, Home Assistant peut conserver l'ancien nom personnalisé d'une entité. Ouvrez ses paramètres et rétablissez le nom par défaut si le nouveau libellé n'apparaît pas.

### Le téléchargement de facture ne fonctionne pas

La version 3.5.3 utilise la route actuelle du portail (`/factures/{id}/duplicata`) et l'identifiant interne de la facture, au lieu de sa référence lisible. Le bouton est indisponible si aucun document n'est annoncé comme téléchargeable. Un lien `/local/...` est ajouté uniquement lorsque le fichier se trouve réellement sous `/config/www` ; ailleurs, la notification indique seulement le chemin de sauvegarde local.

Vérifiez ensuite :

1. qu'une facture apparaît bien dans les données du contrat ;
2. que `/config/www/eau_grand_lyon` figure dans `allowlist_external_dirs` ;
3. que Home Assistant a été redémarré après cette modification ;
4. que le PDF est encore téléchargeable directement depuis votre espace client.

La route est alignée sur l'application web officielle actuelle, mais sa disponibilité reste dépendante du compte et peut changer côté fournisseur.

## Prérequis
- Home Assistant (`2024.11.0` ou ultérieure)
- Un compte valide avec Eau du Grand Lyon (email et mot de passe)

## Installation

> [!CAUTION]
> **IMPORTANT** : Avant d'installer cette intégration ou toute autre extension personnalisée, effectuez toujours une **sauvegarde complète** de votre configuration Home Assistant. L'auteur ne peut être tenu responsable en cas de perte de données ou d'instabilité de votre instance.

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

Une fois installée, vous pouvez modifier les options (mode de calcul des coûts, tarif manuel, intervalle de mise à jour, mode expérimental) en retournant dans **Appareils et services** > **Eau du Grand Lyon** > **Configurer**.

L'intégration récupérera automatiquement les données toutes les **24 heures** par défaut (car les données eau sont généralement mensuelles). Cet intervalle est modifiable dans les options (6h, 12h, 24h, 48h). Et on ne va pas tabasser leur serveur inutilement.

### Options disponibles

| Option | Utilisation | Valeur conseillée |
| --- | --- | --- |
| Fréquence de mise à jour | Intervalle entre deux synchronisations | 24 heures |
| Mode de calcul des coûts | Choisit la source de l'estimation | Dernière facture |
| Tarif au m³ | Repli du mode manuel | Tarif TTC personnalisé |
| Entité de prix dynamique | Source du mode dynamique | Facultatif |
| Part fixe annuelle | Utilisée en modes manuel et dynamique | Montant TTC personnalisé, ou `0` |
| Nombre d'habitants | Éco-Score et conseils personnalisés | Nombre réel du foyer |
| Dureté de l'eau | Estimation du calcaire | Valeur de votre commune ou de votre facture |
| Commune qualité de l'eau | Filtre les données Open Data | Facultatif |
| Nombre de tentatives API | Nombre d'essais avant le mode hors-ligne | Valeur par défaut |
| Mode expérimental | Courbe horaire et données Téléo étendues | Désactivé au départ |

L'entité de prix dynamique est facultative. Si elle est indisponible, l'intégration utilise le tarif fixe configuré.

### Délais de disponibilité des données

- Les consommations mensuelles suivent généralement le calendrier de publication du fournisseur.
- Les données Téléo peuvent arriver avec un décalage de plusieurs jours. Le capteur « dernier jour connu » n'est donc pas nécessairement la veille civile.
- Une correction publiée tardivement remplace automatiquement la journée concernée et recalcule les cumuls suivants.
- Une réponse vide ou une panne temporaire ne supprime pas les dernières données valides : l'intégration utilise son cache et indique son état dans le capteur de santé.

## Utilisation
Une fois configuré, les capteurs apparaîtront dans votre tableau de bord Home Assistant. Vous pouvez les utiliser dans des automatisations, des tableaux de bord, ou de toute autre manière que vous utilisez les capteurs dans Home Assistant.

### Services disponibles

| Service | Fonction |
| --- | --- |
| `eau_grand_lyon.update_now` | Force une synchronisation immédiate |
| `eau_grand_lyon.clear_cache` | Supprime le cache local et réinitialise l'historique reconstruit |
| `eau_grand_lyon.export_data` | Exporte les consommations en CSV |
| `eau_grand_lyon.download_latest_invoice` | Télécharge le dernier duplicata PDF que le portail marque comme disponible |

Les services d'export et de téléchargement nécessitent que leur dossier de destination figure dans `allowlist_external_dirs`. N'utilisez que des chemins locaux explicitement autorisés dans votre configuration Home Assistant.

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

### Blueprints inclus

Quatre Blueprints d'automatisation sont fournis dans [`blueprints/automation/eau_grand_lyon/`](blueprints/automation/eau_grand_lyon/) :

- [Alerte budget](blueprints/automation/eau_grand_lyon/alerte_budget.yaml) : notifie lorsqu'un capteur de coût franchit un seuil configurable.
- [Alerte coupure](blueprints/automation/eau_grand_lyon/alerte_coupure.yaml) : notifie lorsqu'une interruption de service est active ou prévue dans les 48 heures et peut lancer des actions de préparation.
- [Alerte fuite/surconsommation](blueprints/automation/eau_grand_lyon/alerte_fuite.yaml) : surveille l'un des `binary_sensor` d'anomalie, de surconsommation ou de fuite fournis par l'intégration.
- [Alerte sécheresse](blueprints/automation/eau_grand_lyon/alerte_secheresse.yaml) : signale le passage de l'heuristique saisonnière au niveau `vigilance`. Cet indicateur ne remplace pas les arrêtés préfectoraux ni [VigiEau](https://vigieau.gouv.fr/).

Ces Blueprints sont inclus dans ce dépôt, mais ne sont pas annoncés comme publiés sur Blueprint Exchange. Pour satisfaire la règle officielle `docs-examples` lors d'une future soumission Home Assistant Core, un ensemble limité devra être publié dans le dépôt documentaire Home Assistant ou sur Blueprint Exchange, puis lié depuis la page officielle de l'intégration.

### Alerte de surconsommation mensuelle

Créez une automation qui vous avertit lorsque l'heuristique mensuelle se déclenche. Remplacez l'`entity_id` par celui de votre installation :

```yaml
alias: Alerte surconsommation d'eau
trigger:
  - platform: state
    entity_id: binary_sensor.eau_grand_lyon_alerte_surconsommation_mensuelle_heuristique
    to: 'on'
action:
  - service: persistent_notification.create
    data:
      title: "⚠️ Surconsommation d'eau détectée"
      message: "L'heuristique mensuelle s'est déclenchée. Vérifiez les consommations avant de conclure à une fuite."
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
  
  - type: entities
    entities:
      - entity: sensor.eau_grand_lyon_conso_7j
      - entity: sensor.eau_grand_lyon_cout_mois
      - entity: sensor.eau_grand_lyon_eco_score
      - entity: binary_sensor.eau_grand_lyon_alerte_surconsommation_mensuelle_heuristique
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

### Formulations prédictives

Créez un template pour afficher une estimation personnalisée :

```jinja2
{% set consumption = states('sensor.eau_grand_lyon_conso_courant_m3') | float(0) %}
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

### Plusieurs comptes

Une même instance Home Assistant peut configurer plusieurs comptes Eau du Grand Lyon sous forme de Config Entries séparées, à condition que chaque compte utilise une adresse email distincte. « Multi-utilisateurs » ne désigne donc pas une fonctionnalité future séparée et aucune gestion de profils ou de droits entre utilisateurs Home Assistant n'est promise.

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
