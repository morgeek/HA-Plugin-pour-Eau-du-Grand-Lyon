# Préparation de la contribution Home Assistant Brands

## Statut

La règle `brands` reste volontairement `todo` dans `quality_scale.yaml`. Aucune publication dans le dépôt officiel `home-assistant/brands` n'est actuellement prouvée, et les fichiers locaux ne satisfont pas encore les dimensions requises.

Audit des fichiers présents dans `custom_components/eau_grand_lyon/brand/` :

| Fichier | Dimensions actuelles | Conformité |
| --- | ---: | --- |
| `icon.png` | 220 × 68 px | Non : une icône doit être carrée en 256 × 256 px |
| `logo.png` | 220 × 68 px | Non : le côté le plus court doit mesurer entre 128 et 256 px |

Les deux fichiers contiennent actuellement le même logo horizontal. Il ne faut pas étirer ce visuel pour fabriquer une icône carrée : une source officielle haute définition ou une déclinaison d'icône autorisée est nécessaire.

## Assets à préparer

- `icon.png` : PNG carré 256 × 256, recadré, transparent si possible.
- `icon@2x.png` : PNG carré 512 × 512, recommandé pour les écrans haute densité.
- `logo.png` : PNG horizontal respectant les proportions du logo, avec un côté court compris entre 128 et 256 px.
- `logo@2x.png` : même logo en haute densité, avec un côté court compris entre 256 et 512 px.
- variantes `dark_*` uniquement si le visuel normal n'est pas lisible sur fond sombre.

Les droits d'utilisation de la marque et la provenance des fichiers doivent être vérifiés avant toute soumission. L'intégration étant non officielle, les visuels ne doivent pas laisser croire à une intégration Home Assistant officielle.

## Chemin de contribution

1. Obtenir les assets conformes et autorisés, puis les optimiser sans perte.
2. Forker `https://github.com/home-assistant/brands` et créer une branche dédiée.
3. Ajouter les fichiers sous `custom_integrations/eau_grand_lyon/` ; le dossier doit correspondre exactement au domaine du `manifest.json`.
4. Exécuter les validations du dépôt Brands et ouvrir une pull request vers sa branche `master` en remplissant sa checklist.
5. Attendre l'acceptation et la publication effectives avant de passer `brands` à `done`.

Depuis Home Assistant 2026.3, les intégrations personnalisées peuvent également embarquer leurs images dans leur propre dossier `brand/`. Cela améliore l'affichage local sur ces versions récentes, mais ne change ni la compatibilité minimale 2024.11 de ce projet, ni le statut honnête de la contribution externe demandée ici.
