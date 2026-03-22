# Intégration Eau du Grand Lyon pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Ceci est une intégration personnalisée NON OFFICIELLE pour [Home Assistant](https://www.home-assistant.io/) qui fournit des capteurs pour les données de consommation d'eau du service Eau du Grand Lyon.

## Fonctionnalités
Cette intégration vous permet de surveiller votre utilisation de l'eau et les informations de compte du service des eaux de Grand Lyon. Elle fournit les capteurs suivants :

- **Consommation Actuelle** : Consommation d'eau pour le mois en cours (en m³)
- **Consommation Précédente** : Consommation d'eau pour le mois précédent (en m³)
- **Consommation Annuelle** : Consommation totale d'eau pour l'année en cours (en m³)
- **Solde du Compte** : Solde actuel de votre compte eau (en €)
- **Statut du Contrat** : Statut de votre contrat eau
- **Date d'Échéance** : Prochaine date d'échéance de paiement

### Capteurs de coût
- **Coût Mensuel** : Coût estimé pour le mois en cours (configurable)
- **Coût Annuel** : Coût estimé pour les 12 derniers mois (configurable)
- **Économie vs N-1** : Économie réalisée par rapport à l'année précédente (€)
- **Alerte Fuite Possible** : Détection de surconsommation anormale (binaire)
- Tarif configurable directement depuis l'interface Home Assistant (défaut : 5,20 €/m³, tarif indicatif Grand Lyon 2024 - à adapter selon votre facture)

### Détection des mois manquants
- L'attribut `mois_manquants` sur l'index cumulatif liste les trous dans l'historique (compteur remplacé, données API absentes...)

### Consommations journalières
- L'intégration tente automatiquement 2 endpoints API possibles
- Si votre compteur est compatible Téléo/TIC, les capteurs "7 jours" et "30 jours" deviennent disponibles
- Sinon, ils restent silencieux (aucune erreur)

Elle inclut également un bouton pour déclencher manuellement une mise à jour des données.

### Dashboard Lovelace
- Template complet : `lovelace/dashboard.yaml`
- Template avec notifications : `lovelace/dashboard_notifications.yaml`
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

### Notifications Avancées
- **Pushover/Telegram intégrés** : Notifications push personnalisées avec priorité *(temporairement désactivé)*
- **Alertes vocales Google Home/Alexa** : Annonces vocales pour les situations critiques *(temporairement désactivé)*
- **Alertes intelligentes automatiques** : Détection automatique de fuites, consommation élevée, etc. *(temporairement désactivé)*

⚠️ **Note** : Les fonctionnalités de notifications sont temporairement désactivées en raison d'un problème d'import. Elles seront réactivées dans une future mise à jour.
- **Résumé quotidien** : Rapport automatique de consommation

Pour activer les notifications :
1. Configurez Pushover/Telegram dans `configuration.yaml` (voir `lovelace/notification_config.yaml`)
2. Importez les automatisations depuis `lovelace/smart_notifications.yaml`
3. Configurez les devices TTS pour les alertes vocales

## Prérequis
- Home Assistant (version 2021.3.0 ou ultérieure recommandée)
- Un compte valide avec Eau du Grand Lyon (email et mot de passe)

## Installation

### Option 1 : Installation Manuelle
1. Téléchargez la dernière version depuis le [dépôt GitHub](https://github.com/morgeek/eau_grand_lyon_component).
2. Extrayez le contenu du dossier `custom_components/eau_grand_lyon/` dans le répertoire `custom_components/` de votre Home Assistant.
3. Redémarrez Home Assistant.

### Option 2 : HACS dispo mais non testé
1. Assurez-vous d'avoir [HACS](https://hacs.xyz/) installé dans votre instance Home Assistant.
2. Allez dans "Intégrations" et recherchez "Eau du Grand Lyon".
3. Cliquez sur "Installer" et redémarrez Home Assistant.
4. Passez à la configuration ci-dessous.

## Configuration
1. Dans Home Assistant, allez dans **Paramètres** > **Appareils et services**.
2. Cliquez sur **Ajouter une intégration** et recherchez "Eau du Grand Lyon".
3. Saisissez votre email et mot de passe du compte Eau du Grand Lyon.
4. Terminez la configuration.

L'intégration récupérera automatiquement les données toutes les 6 heures (car les données eau sont généralement mensuelles).

## Utilisation
Une fois configuré, les capteurs apparaîtront dans votre tableau de bord Home Assistant. Vous pouvez les utiliser dans des automatisations, des tableaux de bord, ou de toute autre manière que vous utilisez les capteurs dans Home Assistant.

### Notifications Intelligentes
L'intégration inclut un système complet de notifications intelligentes. Consultez la [documentation détaillée](docs/NOTIFICATIONS.md) pour :
- Configuration des services Pushover/Telegram
- Paramétrage des alertes vocales Google Home/Alexa
- Automatisations prédéfinies pour la détection de fuites
- Personnalisation des seuils d'alerte

## Dépannage
- **Problèmes d'authentification** : Assurez-vous que votre email et mot de passe sont corrects. L'intégration utilise l'API officielle d'Eau du Grand Lyon.
- **Aucune donnée** : Les données eau sont mises à jour mensuellement. Si aucune donnée n'apparaît, vérifiez le statut de votre contrat.
- **Erreurs** : Vérifiez les journaux Home Assistant pour tout message d'erreur lié à l'intégration.

## Roadmap & Suggestions de Features

### Fonctionnalités à venir

**Multi-utilisateurs**
   - Support pour plusieurs comptes utilisateur
   - Partage de données entre membres de la famille

### Contributions
Les contributions sont les bienvenues ! N'hésitez pas à proposer des features

## Licence
Ce projet est sous licence MIT - voir le fichier LICENSE pour plus de détails.

## Avertissement
Cette intégration n'est pas officiellement affiliée à Eau du Grand Lyon ou Grand Lyon Métropole. Utilisez à vos propres risques.</content>
