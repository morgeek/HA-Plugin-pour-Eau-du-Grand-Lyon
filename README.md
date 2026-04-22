# Intégration Eau du Grand Lyon pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Ceci est une intégration personnalisée NON OFFICIELLE pour [Home Assistant](https://www.home-assistant.io/) qui fournit des capteurs pour les données de consommation d'eau du service Eau du Grand Lyon.

![alt text](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/blob/main/custom_components/eau_grand_lyon/HA-Eau-Grand-Lyon.png)

## Historique des versions

Voir le [CHANGELOG.md](CHANGELOG.md) pour l'historique complet des changements.

### 🧠 Intelligence Avancée & Écologie
- **Eco-Score (A-G)** : Analyse de performance basée sur le nombre d'habitants et les barèmes nationaux.
- **Empreinte Carbone (CO₂e)** : Calcul de l'impact écologique de votre consommation (kg CO₂e).
- **Prédictions Fin de Mois** : Estimation du volume et du coût final pour le mois en cours.
- **Tendance vs N-1** : Comparaison en pourcentage par rapport à la même période l'année précédente.
- **Eco-Benchmark** : Comparaison de votre usage face à la moyenne régionale lyonnaise.

### 🛡️ Sécurité & Alertes
- **Détection Fuite Temps Réel (Téléo)** : Basé sur les alertes officielles du compteur.
- **Détection Fuite Locale (Pattern)** : Analyse intelligente du flux constant (idéal pour compteurs legacy).
- **Mode Vacances** : Switch de surveillance renforcée (alerte immédiate pour toute consommation > 1L).
- **Suivi Sécheresse (69)** : Sensor dédié aux restrictions préfectorales du Rhône.
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

## Prérequis
- Home Assistant (`2024.1.0` ou ultérieure)
- Un compte valide avec Eau du Grand Lyon (email et mot de passe)

## Installation

### Option 1 : Installation a l'ancienne
1. Téléchargez la dernière version depuis le [dépôt GitHub](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon).
2. Extrayez le contenu du dossier `custom_components/eau_grand_lyon/` dans le répertoire `custom_components/` de votre Home Assistant.
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

### Option 2 : HACS
1. Assurez-vous d'avoir [HACS](https://hacs.xyz/) installé dans votre instance Home Assistant.
2. Allez dans "Intégrations" et recherchez "Eau du Grand Lyon".
3. Cliquez sur "Installer" et redémarrez Home Assistant.
4. Passez à la configuration ci-dessous.

## Configuration
1. Dans Home Assistant, allez dans **Paramètres** > **Appareils et services**.
2. Cliquez sur **Ajouter une intégration** et recherchez "Eau du Grand Lyon".
3. Saisissez votre email et mot de passe du compte Eau du Grand Lyon.
4. Terminez la configuration.

Une fois installée, vous pouvez modifier les options (tarif au m³, intervalle de mise à jour, mode expérimental) en retournant dans **Appareils et services** > **Eau du Grand Lyon** > **Configurer**.

L'intégration récupérera automatiquement les données toutes les **24 heures** par défaut (car les données eau sont généralement mensuelles). Cet intervalle est modifiable dans les options (6h, 12h, 24h, 48h). Et on ne va pas tabasser leur serveur inutilement.

![alt text](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/blob/main/custom_components/eau_grand_lyon/HA-Eau-Grand-Lyon2.png)

## Utilisation
Une fois configuré, les capteurs apparaîtront dans votre tableau de bord Home Assistant. Vous pouvez les utiliser dans des automatisations, des tableaux de bord, ou de toute autre manière que vous utilisez les capteurs dans Home Assistant.

### Notifications Intelligentes

> ⚠️ **Non disponible dans cette version** — prévu pour une version future.

## Dépannage
- **Problèmes d'authentification** : Assurez-vous que votre email et mot de passe sont corrects. L'intégration utilise l'API officielle d'Eau du Grand Lyon.
Merci @painteau pour le fix et @hufon pour le merge.
- **Aucune donnée** : Les données eau sont mises à jour mensuellement. Si aucune donnée n'apparaît, vérifiez le statut de votre contrat.
- **Erreurs** : Vérifiez les journaux Home Assistant pour tout message d'erreur lié à l'intégration.
- **Réparations (Repairs)** : L'intégration utilise la plateforme native de Home Assistant pour signaler les problèmes critiques (ex. Alertes Sécheresse). Consultez l'onglet "Réparations" dans HA.
- **Diagnostics** : En cas de bug, téléchargez l'export de diagnostic depuis la page de l'intégration pour obtenir des logs redactés et anonymisés.

### Erreur `Integration 'eau_grand_lyon' not found`

Si vous voyez dans les logs :

```text
Unable to get manifest for integration eau_grand_lyon: Integration 'eau_grand_lyon' not found.
```

le problème n'est généralement pas l'API Eau du Grand Lyon mais l'installation locale de l'intégration.

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
  translations/
```

### Fonctionnalités à venir
**Multi-utilisateurs**
   - Support pour plusieurs comptes utilisateur

### Contributions
Les contributions sont les bienvenues ! N'hésitez pas à proposer des features

## Licence
Ce projet est sous licence MIT - voir le fichier LICENSE pour plus de détails.

## Avertissement
Cette intégration n'est pas officiellement affiliée à Eau du Grand Lyon ou Grand Lyon Métropole. Utilisez à vos propres risques.
