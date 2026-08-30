# Intégration Eau du Grand Lyon pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Tests & Validation](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/actions/workflows/tests.yaml/badge.svg?branch=main)](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/actions/workflows/tests.yaml)

Ceci est une intégration personnalisée non officielle pour [Home Assistant](https://www.home-assistant.io/) qui récupère la consommation d'eau, les informations de contrat et les alertes du service Eau du Grand Lyon.

> **À savoir** : l'intégration interroge le portail Eau du Grand Lyon. Elle nécessite un compte client valide et peut être limitée par le pare-feu anti-abus du service.

## Démarrage rapide

1. Installez l'intégration avec HACS, ou copiez le dossier `custom_components/eau_grand_lyon/` dans votre configuration Home Assistant.
2. Redémarrez Home Assistant.
3. Allez dans **Paramètres > Appareils et services > Ajouter une intégration**.
4. Recherchez **Eau du Grand Lyon**, puis saisissez votre email et votre mot de passe.
5. Ouvrez **Configurer** pour régler le tarif au m³ et la fréquence de mise à jour.

Les données apparaissent après la première synchronisation. Celle-ci peut prendre quelques minutes et les données Téléo peuvent être publiées avec un décalage fourni par le distributeur.

## Quel compteur est pris en charge ?

| Compteur | Données disponibles |
| --- | --- |
| **Téléo** | Consommation journalière, index journalier, alertes de fuite, signal et fonctions horaires selon le compte |
| **Standard** | Consommation mensuelle, contrat, factures et indicateurs généraux |

Le capteur **Compatibilité compteur** permet de vérifier le type détecté. Les capteurs incompatibles restent indisponibles ou sont désactivés par défaut.

## Fonctionnalités

### 🧠 Intelligence avancée & coaching
- **Eco-Coach (IA) 💎** : capteur de conseil personnalisé qui analyse vos habitudes pour vous aider à réduire votre consommation quotidiennement.
- **Eco-Score (A-G)** : Note de performance environnementale basée sur le nombre d'habitants et les barèmes nationaux.
- **Entartrage Virtuel** : Estimation exclusive de l'accumulation de calcaire (en grammes) basée sur la dureté de l'eau configurée.
- **Empreinte Carbone (CO₂e)** : Calcul automatique de l'impact écologique de votre consommation d'eau (kg CO₂e).
- **Prédictions Fin de Mois** : Algorithmes prédictifs pour estimer le volume et le coût final de votre facture.
- **Consommation Moyenne (L/jour) 💧** : Affiche votre consommation moyenne glissante sur 7 jours en **Litres**. Idéal pour comparer avec les moyennes nationales (env. 150L/pers/jour).
- **Tendance vs N-1** : Comparaison intelligente avec la même période de l'année précédente (Annuelle vs Annuelle).

### 🛡️ Sécurité & Alertes
- **Détection Fuite Temps Réel (Téléo)** : Basé sur les alertes officielles du compteur.
- **Détection Fuite Locale (Pattern)** : analyse intelligente d'un débit constant, utile pour les compteurs standard.
- **Mode Vacances** : Switch de surveillance renforcée (alerte immédiate pour toute consommation > 1L).
- **Indicateur Sécheresse (saisonnier)** : Capteur indicatif basé sur une heuristique saisonnière (juin–septembre = Vigilance). Il ne reflète pas les arrêtés préfectoraux réels — consultez [vigieau.gouv.fr](https://vigieau.gouv.fr) pour les restrictions en vigueur.
- **Icônes Dynamiques** : Les capteurs (ex: Nitrates, Fuites) changent d'icône selon la sévérité des données.
- **Courbe de Charge Horaire** : Support expérimental des données de consommation heure par heure pour les compteurs Téléo récents.
- **Consommation journalière** : Capteur dédié affichant la consommation du dernier jour connu en **Litres**.
- **Index Journalier Robuste** : Amélioration du parsing de l'index journalier avec support de 9 synonymes de clés API (inspiré du travail de @hufon).
- **Repairs HA** : Alerte dans le tableau de bord "Réparations" de Home Assistant en cas de panne API prolongée (> 7 jours).

### 🛠️ Services Pro & Utilitaires
- **Export CSV** : service `eau_grand_lyon.export_data` pour sauvegarder votre historique en local.
- **Téléchargement facture PDF** : service `eau_grand_lyon.download_latest_invoice` pour récupérer votre facture officielle.
  > ⚠️ Le répertoire de destination de ces services doit être autorisé dans `configuration.yaml` :
  > ```yaml
  > homeassistant:
  >   allowlist_external_dirs:
  >     - /config/exports
  >     - /config/www/eau_grand_lyon
  > ```
- **Santé Hardware** : Diagnostic du niveau de signal et de la pile du module Téléo.
- **Calendrier des Échéances** : Entité calendrier avec dates de paiement et factures prévues.
- **Blueprints d'automatisation** : modèles prêts à l'emploi pour les alertes fuite et budget.

### Mode hors-ligne
Si l'API Eau du Grand Lyon est indisponible (coupure réseau, maintenance, blocage WAF), l'intégration bascule automatiquement en **mode hors-ligne** :
- Les capteurs restent disponibles et affichent les dernières données connues
- Le capteur **Statut API** affiche `Hors-ligne` (état brut `offline`) avec l'horodatage du début de la panne
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

## Réglages recommandés

- **Fréquence de mise à jour** : 24 heures. Utilisez 48 heures si le portail bloque temporairement les requêtes.
- **Tarif au m³** : indiquez le tarif total visible sur votre facture, incluant l'eau, l'assainissement et les taxes.
- **Abonnement annuel** : renseignez uniquement la part fixe annuelle de votre facture. Laissez `0` si vous ne souhaitez pas l'intégrer aux capteurs de coût réel.
- **Nombre d'habitants** : utilisé pour l'Éco-Score et les conseils personnalisés.
- **Mode expérimental** : laissez-le désactivé tant que vous n'avez pas besoin des données étendues Téléo.

## Mise à jour des données

L'intégration récupère vos données de consommation selon un intervalle configurable :

- **Intervalle par défaut** : 24 heures (pour éviter les blocages WAF)
- **Intervalle configurable** : 6h, 12h, 24h, 48h — accessible via Paramètres > Appareils et services > Options
- **Mise à jour manuelle** : Service `update_now` pour forcer un rafraîchissement immédiat
- **Cache persistant** : En cas d'indisponibilité API, les dernières données connues restent affichées localement
- **Retry automatique** : En cas d'erreur réseau ou blocage WAF, l'intégration réessaie après un délai croissant (1 min, 5 min)

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
2. **Configurer le tarif €/m³** dans Paramètres > Options
3. **Ajouter une source d'eau** au tableau de bord Énergie :
   - Téléo : `sensor.eau_du_grand_lyon_index_journalier_energy` (quotidien, haute précision)
   - Standard : `sensor.eau_du_grand_lyon_index_compteur` (mensuel)
4. **Ajouter le coût** pour cette source : `sensor.eau_du_grand_lyon_energie_cout`
5. **Coûts** : `sensor.eau_du_grand_lyon_energie_cout` (auto-calculé si tarif configuré)
6. **Statistiques** : Utilisez les statistic IDs ci-dessus pour les cartes statistiques.

### Comprendre les coûts

- `cost_<ref>` et `cost_daily_<ref>` correspondent uniquement au coût variable : consommation × tarif au m³.
- `cout_reel_mois` inclut la part variable du mois et un douzième de l'abonnement annuel.
- `cout_reel_annuel` inclut la consommation des douze derniers mois et l'abonnement annuel complet.

L'abonnement n'est pas ajouté aux statistiques journalières ou mensuelles, afin de ne pas le compter plusieurs fois dans l'historique.

#### Dépannage rapide
- ⚠️ Capteurs grisés ? → Paramètres > Appareils et services > Eau du Grand Lyon > Activer
- 📊 Statistiques vides ou graphique incomplet ? → Forcer une mise à jour avec le bouton dédié, puis attendre quelques secondes
- 🔍 Statistic ID inconnu ? → Vérifiez les statistiques dans **Outils de développement > Statistiques** ou utilisez la recherche de statistiques dans l'interface.

## Appareils supportés

L'intégration fonctionne avec deux types de compteurs :

| Type | Nom | Disponibilité des données |
|------|-----|---------------------------|
| **Téléo** (communicant) | Compteur communicant Eau du Grand Lyon | Consommation journalière, courbe horaire, alertes temps réel, signal radio |
| **Standard** | Compteur traditionnel avec relevé manuel | Consommation mensuelle uniquement |

### Comment savoir quel compteur j'ai ?

- Un capteur **Compatibilité compteur** (désactivé par défaut) indique `Téléo` ou `Standard`
- Allez dans Paramètres > Appareils et services > Eau du Grand Lyon > Entités
- Cherchez "Compatibilité compteur" — activez-la si elle est masquée

## Limitations connues

- **Mise à jour mensuelle** : Les données de consommation sont généralement mises à jour une fois par mois par le service. La vue quotidienne n'est disponible que pour les compteurs Téléo.
- **Blocage WAF** : L'API officielle peut bloquer les requêtes trop fréquentes. Consultez la section "Mise à jour des données" pour plus de détails.
- **Données historiques API** : L'API Eau du Grand Lyon ne retourne qu'une fenêtre historique limitée. L'intégration accumule cependant jusqu'à **36 mois** en cache local persistant.
- **Compteurs Standard** : Les détails horaires et alertes temps réel ne sont disponibles que sur compteurs Téléo.
- **Mode hors-ligne** : En cas d'indisponibilité prolongée (>7 jours), une alerte apparaît dans les réparations HA.

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

Une fois installée, vous pouvez modifier les options (tarif au m³, intervalle de mise à jour, mode expérimental) en retournant dans **Appareils et services** > **Eau du Grand Lyon** > **Configurer**.

L'intégration récupérera automatiquement les données toutes les **24 heures** par défaut (car les données eau sont généralement mensuelles). Cet intervalle est modifiable dans les options (6h, 12h, 24h, 48h). Et on ne va pas tabasser leur serveur inutilement.

### Options disponibles

| Option | Utilisation | Valeur conseillée |
| --- | --- | --- |
| Fréquence de mise à jour | Intervalle entre deux synchronisations | 24 heures |
| Tarif au m³ | Calcul des coûts variables | Tarif total indiqué sur votre facture |
| Entité de prix dynamique | Remplace le tarif fixe par une entité Home Assistant | Facultatif |
| Abonnement annuel | Part fixe utilisée par les coûts réels | Montant annuel de la facture, ou `0` |
| Nombre d'habitants | Éco-Score et conseils personnalisés | Nombre réel du foyer |
| Dureté de l'eau | Estimation du calcaire | Valeur de votre commune ou de votre facture |
| Commune qualité de l'eau | Filtre les données Open Data | Facultatif |
| Nombre de tentatives API | Nombre d'essais avant le mode hors-ligne | Valeur par défaut |
| Mode expérimental | Factures détaillées, courbe horaire et données Téléo étendues | Désactivé au départ |

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
| `eau_grand_lyon.download_latest_invoice` | Télécharge la dernière facture PDF |

Les services d'export nécessitent que leur dossier de destination figure dans `allowlist_external_dirs`. N'utilisez que des chemins locaux explicitement autorisés dans votre configuration Home Assistant.

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

### Formulations prédictives

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
