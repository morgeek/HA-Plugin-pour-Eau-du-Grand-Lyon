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

## Prérequis

- Home Assistant (version 2021.3.0 ou ultérieure recommandée)
- Un compte valide avec Eau du Grand Lyon (email et mot de passe)

## Installation

### Option 1 : Installation Manuelle

1. Téléchargez la dernière version depuis le [dépôt GitHub](https://github.com/morgeek/eau_grand_lyon_component).
2. Extrayez le contenu du dossier `custom_components/eau_grand_lyon/` dans le répertoire `custom_components/` de votre Home Assistant.
3. Redémarrez Home Assistant.

### Option 2 : HACS dispo dans prochaine version

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

## Dépannage

- **Problèmes d'authentification** : Assurez-vous que votre email et mot de passe sont corrects. L'intégration utilise l'API officielle d'Eau du Grand Lyon.
- **Aucune donnée** : Les données eau sont mises à jour mensuellement. Si aucune donnée n'apparaît, vérifiez le statut de votre contrat.
- **Erreurs** : Vérifiez les journaux Home Assistant pour tout message d'erreur lié à l'intégration.


## Licence

Ce projet est sous licence MIT - voir le fichier LICENSE pour plus de détails.

## Avertissement

Cette intégration n'est pas officiellement affiliée à Eau du Grand Lyon ou Grand Lyon Métropole. Utilisez à vos propres risques.</content>
