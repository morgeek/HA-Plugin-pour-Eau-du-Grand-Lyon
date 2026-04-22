# Intégration Eau du Grand Lyon pour Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Ceci est une intégration personnalisée NON OFFICIELLE pour [Home Assistant](https://www.home-assistant.io/) qui fournit des capteurs pour les données de consommation d'eau du service Eau du Grand Lyon.

![alt text](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/blob/main/custom_components/eau_grand_lyon/HA-Eau-Grand-Lyon.png)

## Historique des versions

Voir le [CHANGELOG.md](CHANGELOG.md) pour l'historique complet des changements.

## Fonctionnalités
Cette intégration vous permet de surveiller votre utilisation de l'eau et les informations de compte du service des eaux de Grand Lyon. Elle fournit les capteurs suivants :

- **Consommation Actuelle** : Consommation d'eau pour le mois en cours (en m³)
- **Consommation Précédente** : Consommation d'eau pour le mois précédent (en m³)
- **Consommation Annuelle** : Consommation totale d'eau pour l'année en cours (en m³)
- **Solde du Compte** : Solde actuel de votre compte eau (en €)
- **Statut du Contrat** : Statut de votre contrat eau
- **Date d'Échéance** : Prochaine date d'échéance de paiement
- **Dernière facture** : Montant de la dernière facture émise (expérimental)

### Capteurs de coût
- **Coût Mensuel** : Coût estimé pour le mois en cours (configurable)
- **Coût Annuel** : Coût estimé pour les 12 derniers mois (configurable)
- **Économie vs N-1** : Économie réalisée par rapport à l'année précédente (€)
- **Alerte Fuite Possible** : Détection de surconsommation anormale (binaire)
- Tarif configurable directement depuis l'interface Home Assistant (défaut : 5,20 €/m³, tarif indicatif Grand Lyon 2024 - à adapter selon votre facture)

### Détection des mois manquants
- L'attribut `mois_manquants` sur l'index cumulatif liste les trous dans l'historique (compteur remplacé, données API absentes...)

### Consommations journalières
- L'intégration tente automatiquement 2 endpoints API possibles si un jour cela est disponible...
- Si compteur est compatible Téléo/TIC, les capteurs "7 jours" et "30 jours" deviennent disponibles.
- **En mode expérimental**, des données supplémentaires comme le **Volume de fuite estimé**, le **Débit minimal** et l'**Index réel** sont récupérées pour les compteurs récents.
- Sinon, ils restent silencieux (aucune erreur).

Inclut également un bouton pour déclencher manuellement une mise à jour des données.

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

### Notifications Avancées

> ⚠️ **Non disponible dans cette version** — les notifications Pushover/Telegram et automatisations intelligentes ne sont pas encore implémentées. 

## Prérequis
- Home Assistant (version 2021.3.0 ou ultérieure recommandée)
- Un compte valide avec Eau du Grand Lyon (email et mot de passe)

## Installation

### Option 1 : Installation a l'ancienne
1. Téléchargez la dernière version depuis le [dépôt GitHub](https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon).
2. Extrayez le contenu du dossier `custom_components/eau_grand_lyon/` dans le répertoire `custom_components/` de votre Home Assistant.
3. Redémarrez Home Assistant.

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

### Fonctionnalités à venir
**Multi-utilisateurs**
   - Support pour plusieurs comptes utilisateur

### Contributions
Les contributions sont les bienvenues ! N'hésitez pas à proposer des features

## Licence
Ce projet est sous licence MIT - voir le fichier LICENSE pour plus de détails.

## Avertissement
Cette intégration n'est pas officiellement affiliée à Eau du Grand Lyon ou Grand Lyon Métropole. Utilisez à vos propres risques.
