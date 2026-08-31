# Préparation d'une soumission Home Assistant Core

Ce document décrit une trajectoire Bronze-first. Il ne prétend pas que
l'intégration est déjà acceptée dans Core et ne remplace pas la revue des
mainteneurs Home Assistant.

## Étape 1 — dossier Bronze autonome

- Rebaser le composant sur la version stable de Home Assistant ciblée.
- Conserver le domaine `eau_grand_lyon`, le flux de configuration, les
  `unique_id`, les identifiants de devices et de statistiques existants.
- Extraire dans une bibliothèque PyPI séparée et maintenue le client réseau si
  la revue Core l'exige, avec API asynchrone et session injectée.
- Porter les tests de configuration, authentification, setup, unload et erreurs
  réseau dans l'arbre de tests Core.
- Fournir une documentation `home-assistant.io` au niveau Bronze et une marque
  conforme sous `core_integrations/eau_grand_lyon/`.
- Ajouter le domaine à `.strict-typing` dans Home Assistant Core.

## Étape 2 — pull request Core minimale

La première pull request doit viser un périmètre facile à examiner avec une seule
plateforme principale, `sensor` : identité du contrat et consommation essentielle,
plus config flow, disponibilité, réauthentification, diagnostics, tests et
documentation minimale. Factures, calendrier, boutons, switch, binary sensors et
entités expérimentales viennent dans des pull requests suivantes. Ce découpage
upstream ne modifie ni ne retire les entités déjà exposées par la version HACS.

Joindre à la pull request : preuve de couverture, résultat hassfest, justification
du polling, politique de journalisation, provenance de la marque et lien vers la
documentation. Ne pas déclarer un niveau supérieur à Bronze avant validation des
règles correspondantes dans le dépôt Core.

## Étape 3 — progression Silver, Gold, Platinum

- Silver : confirmer les erreurs traduites, l'unload et la couverture dans
  l'environnement Core.
- Gold : publier une sélection réduite de Blueprints, documenter les cas d'usage
  et valider les devices dynamiques et obsolètes.
- Platinum : maintenir le typage strict, le client entièrement asynchrone et
  l'injection de la websession sur chaque version stable ciblée.

## Garde-fous de migration

- Aucun changement de `domain`, `entry_id`, `unique_id`, identifiant de device ou
  `statistic_id` lors du passage HACS vers Core.
- Aucun service existant supprimé sans dépréciation documentée.
- Aucun nettoyage automatique de l'historique utilisateur.
- Tester explicitement la coexistence et la migration depuis l'installation
  personnalisée avant toute publication Core.
