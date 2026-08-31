# Préparation de la contribution Home Assistant Brands

## Statut

La règle `brands` reste volontairement `todo` dans `quality_scale.yaml`. Aucune publication dans le dépôt officiel `home-assistant/brands` n'est actuellement prouvée, et les fichiers locaux ne satisfont pas encore les dimensions requises.

Audit des fichiers présents dans `custom_components/eau_grand_lyon/brand/` :

| Fichier | Dimensions actuelles | Conformité |
| --- | ---: | --- |
| `icon.png` | 220 × 68 px | Non : une icône doit être carrée en 256 × 256 px |
| `logo.png` | 220 × 68 px | Non : le côté le plus court doit mesurer entre 128 et 256 px |

Les deux fichiers sont des PNG RGBA transparents, au ratio horizontal 3,24:1, sans bordure opaque ajoutée et avec le contenu recadré jusqu'aux bords. Ils sont strictement identiques et contiennent le même logo horizontal. La signature blanche « DU GRAND LYON » manque de contraste sur fond clair. Il ne faut ni étirer ce visuel pour fabriquer une icône carrée, ni produire artificiellement une variante claire : une source officielle haute définition ou une déclinaison d'icône autorisée est nécessaire.

## Assets à préparer

- `icon.png` : PNG carré 256 × 256, recadré, transparent si possible.
- `icon@2x.png` : PNG carré 512 × 512, recommandé pour les écrans haute densité.
- `logo.png` : PNG horizontal respectant les proportions du logo, avec un côté court compris entre 128 et 256 px.
- `logo@2x.png` : même logo en haute densité, avec un côté court compris entre 256 et 512 px.
- variantes `dark_*` uniquement si le visuel normal n'est pas lisible sur fond sombre.

Les droits d'utilisation de la marque et la provenance des fichiers doivent être vérifiés avant toute soumission. L'intégration étant non officielle, les visuels ne doivent pas laisser croire à une intégration Home Assistant officielle.

## Deux destinations distinctes

Pour l'intégration personnalisée actuelle, Home Assistant 2026.3 et versions
ultérieures peuvent lire le dossier local `custom_components/eau_grand_lyon/brand/`.
Ce mécanisme améliore uniquement l'affichage local et ne rend pas les fichiers
actuels conformes : leurs dimensions restent insuffisantes.

Pour une publication dans le dépôt `home-assistant/brands` :

- tant que le projet reste une intégration personnalisée, la destination est
  `custom_integrations/eau_grand_lyon/` ;
- après acceptation dans Home Assistant Core, la destination de la marque Core
  est `core_integrations/eau_grand_lyon/`.

## Chemin de contribution

1. Obtenir les assets conformes et autorisés, puis les optimiser sans perte.
2. Forker `https://github.com/home-assistant/brands` et créer une branche dédiée.
3. Choisir le chemin adapté au statut réel du projet parmi les deux chemins ci-dessus ; le dossier doit correspondre exactement au domaine du `manifest.json`.
4. Exécuter les validations du dépôt Brands et ouvrir une pull request vers sa branche `master` en remplissant sa checklist.
5. Attendre l'acceptation et la publication effectives avant de passer `brands` à `done`.

Ne passer la règle `brands` à `done` qu'après présence vérifiée d'assets conformes
dans le chemin officiel correspondant. La compatibilité minimale 2024.11 reste
inchangée.
