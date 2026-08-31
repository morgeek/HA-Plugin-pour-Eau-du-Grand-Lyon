# Préparation des exemples officiels

La règle Quality Scale `docs-examples` reste volontairement `todo` tant qu'un
ensemble limité de Blueprints n'est pas publié en amont et lié depuis la page
officielle de l'intégration.

## Ensemble proposé

1. `alerte_fuite.yaml` : cas d'usage prioritaire, directement actionnable.
2. `alerte_coupure.yaml` : information opérationnelle sur une interruption.
3. `alerte_budget.yaml` : exemple optionnel si la revue accepte un troisième cas.

`alerte_secheresse.yaml` reste dans ce dépôt pour les utilisateurs HACS, mais ne
fait pas partie de la proposition initiale afin de garder la sélection officielle
courte et centrée sur les données les plus fiables.

## Publication

- Valider les Blueprints dans une installation Home Assistant supportée.
- Publier la sélection dans `home-assistant.io/source/blueprints/integrations/`
  ou sur le Blueprint Exchange, selon le canal retenu par les mainteneurs.
- Ajouter les liens publics à la future page officielle Eau du Grand Lyon.
- Vérifier que chaque lien publié fonctionne avant de marquer `docs-examples`
  `done` dans `quality_scale.yaml`.

Aucune URL de publication n'est préremplie ici : elle ne doit être ajoutée
qu'après publication effective.
