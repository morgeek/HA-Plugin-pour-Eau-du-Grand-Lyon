# Intégration Eau du Grand Lyon pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Tests & Validation](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/actions/workflows/tests.yaml/badge.svg?branch=main)](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/actions/workflows/tests.yaml)

Ceci est une intégration personnalisée NON OFFICIELLE pour [Home Assistant](https://www.home-assistant.io/) qui fournit des capteurs pour les données de consommation d'eau du service Eau du Grand Lyon.

![alt text](https://raw.githubusercontent.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/main/docs/screenshots/HA-Eau-Grand-Lyon.png)

![alt text](https://raw.githubusercontent.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/main/docs/screenshots/HA-Eau-Grand-Lyon2.png)

![alt text](https://raw.githubusercontent.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/main/docs/screenshots/HA-Eau-Grand-Lyon3.png)

![alt text](https://raw.githubusercontent.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/main/docs/screenshots/HA-Eau-Grand-Lyon4.png)

## Historique des versions

Voir le [CHANGELOG.md](CHANGELOG.md) pour l'historique complet des changements.

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
- **Qualité de l'Eau Open Data** : Dureté, Nitrates et Chlore en temps réel via les données de la Métropole de Lyon, avec alertes sur les seuils sanitaires.
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
- **Suivi Sécheresse & Repairs** : Gestion native des niveaux de vigilance sécheresse du Rhône avec intégration dans la plateforme Repairs de HA.
- **Icônes Dynamiques** : Les capteurs (ex: Nitrates, Fuites) changent d'icône selon la sévérité des données.
- **Courbe de Charge Horaire** : Support expérimental des données de consommation heure par heure pour les compteurs Téléo récents.
- **Consommation d'Hier** : Nouveau capteur dédié affichant la consommation du dernier jour connu en **Litres**.
- **Index Journalier Robuste** : Amélioration du parsing de l'index journalier avec support de 9 synonymes de clés API (inspiré du travail de @hufon).
- **Repairs HA** : Intégration des alertes sécheresse critiques directement dans le tableau de bord "Réparations" de Home Assistant.

### 🛠️ Services Pro & Utilitaires
- **Export CSV** : Service `export_data` pour sauvegarder tout votre historique en local.
- **Téléchargement Facture PDF** : Service `download_latest_invoice` pour récupérer votre facture officielle.
- **Santé Hardware** : Diagnostic du niveau de signal et de la pile du module Téléo.
- **Calendrier des Échéances** : Entité calendrier avec dates de paiement et factures prévues.
- **Blueprints d'Automation** : Modèles prêts à l'emploi pour les alertes fuite et budget.

### Mode hors-ligne
Si l'API Eau du Grand Lyon est indisponible (coupure réseau, maintenance, blocage WAF), l'intégration bascule automatiquement en **mode hors-ligne** :
- Les sensors restent disponibles et affichent les dernières données connues
- Le sensor **Statut API** passe à `HORS-LIGNE` avec l'horodatage du début de la panne
- Le cache est persistant sur disque — il survit à un redémarrage de Home Assistant
- Dès que l'API répond à nouveau, les données sont rafraîchies et le mode hors-ligne se désactive automatiquement

### Mode Expérimental (API 2026)
Cette version inclut un nouveau mode basé sur les endpoints découverts dans le bundle Angular 2026 du site officiel :
- **Nouvelles Données** : Accès aux factures détaillées, à la courbe de charge (données sub-journalières pour Téléo) et aux volumes de fuite nocturnes.
- **Modernisation** : Utilise les dernières routes API sans le préfixe `/application/`, offrant potentiellement une meilleure stabilité future.
- **Sécurité & Fallback** : Si un nouvel endpoint échoue ou retourne une erreur 404, l'intégration bascule automatiquement sur l'API stable (legacy). Rien ne casse.
- **Activation** : Désactivé par défaut. Peut être activé dans les options de l'intégration (**Configurer**).
Allez dans Paramètres > Appareils et services.
Recherchez l'intégration Eau du Grand Lyon.
Cliquez sur le bouton Configurer (ou Options selon votre version de HA).
Cochez la case Mode expérimental (API 2026)

Si votre compteur est compatible et que les nouveaux endpoints répondent, les nouveaux capteurs apparaîtront automatiquement (pensez à vérifier s'ils sont désactivés par défaut dans l'interface des entités).

En cas d'erreur avec la nouvelle API, l'intégration repassera automatiquement sur l'ancienne version pour assurer la continuité des données.

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
- Template complet : `lovelace/dashboard.yaml`
- Template avec notifications : `lovelace/dashboard_notifications.yaml`*(temporairement désactivé)*
- Graphique historique sur 24 mois, comparaison N-1, coûts, alerte conditionnelle
- Boutons de test pour les notifications Pushover/Telegram/vocales
- Vue journalière si les données sont disponibles

### Intégration Energy Dashboard
- **Sensors optimisés** : Sensors dédiés avec `state_class: total_increasing` pour de meilleures statistiques
- **Coûts énergétiques automatiques** : Calcul automatique des coûts basé sur le tarif configuré
- **Stats par période** : Statistiques automatiques générées par HA pour tous les sensors
- **Configuration** : Template de configuration dans `lovelace/energy_config.yaml`

Pour activer l'intégration Energy :
1. Activez les sensors "Consommation eau (Énergie)" et "Coûts eau (Énergie)" dans les entités
2. Ajoutez la configuration dans `configuration.yaml` ou via l'interface Énergie
3. Les statistiques se généreront automatiquement

### Notifications Avancées & Blueprints
L'intégration inclut désormais des **Blueprints** (modèles d'automatisation) pour configurer en un clic :
- **Alerte Fuite Actionnable** : Notification sur mobile avec boutons "Rafraîchir" et "Voir Dashboard".
- **Alerte Budget** : Notification si la prédiction de fin de mois dépasse un seuil choisi.
- **Alerte Sécheresse** : Notification automatique dès que le département du Rhône change de niveau de restriction.

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
- **Données historiques** : Seules les 12 derniers mois de données mensuelles sont disponibles par l'API.
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
  api.py
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
