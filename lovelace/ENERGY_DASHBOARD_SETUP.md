# Configuration complète du tableau de bord Énergie HA avec Eau du Grand Lyon

## 🎯 Objectif

Ajouter le suivi de la consommation d'eau **ET de son coût** au tableau de bord Énergie natif de Home Assistant.

---

## ✅ Prérequis

1. **Intégration Eau du Grand Lyon** installée et configurée (v2.9.0+)
2. **Tarif configuré** dans les options de l'intégration (€/m³)
3. **Données disponibles** depuis votre compte Eau du Grand Lyon

---

## 🚀 Configuration pas à pas

### ÉTAPE 1 — Vérifier que le capteur de coût est activé

Le capteur de coût doit être **activé par défaut depuis la v2.9.0**, mais vérifiez :

1. Allez à : **Paramètres** → **Appareils et services** → **Eau du Grand Lyon**
2. Cherchez l'entité `sensor.eau_du_grand_lyon_cout_energie`
3. Si elle est **inactive** (grisée), cliquez dessus et sélectionnez **Activer l'entité**

**Astuce :** L'entity_id peut varier selon votre configuration. Cherchez "Énergie" ou "energie" dans la liste.

---

### ÉTAPE 2 — Configurer le tarif (si pas encore fait)

Le coût ne s'affichera que si vous avez configuré le tarif :

1. Allez à : **Paramètres** → **Appareils et services** → **Eau du Grand Lyon** → **Options**
2. Recherchez le champ **"Tarif €/m³"**
3. Entrez votre tarif (exemple : `5.20` pour 5,20€/m³)
4. Cliquez sur **Enregistrer**

**Remarque :** Ce tarif est utilisé pour **estimer** le coût basé sur votre consommation. Il doit correspondre à votre tarif réel pour une estimation précise.

---

### ÉTAPE 3 — Ajouter la source d'eau au tableau de bord Énergie

1. Allez à : **Paramètres** → **Tableaux de bord** → **Énergie**
2. Cherchez la section **Eau** (ou cliquez sur **Ajouter une source**)
3. Cliquez sur **Ajouter une source**
4. Choisissez la source selon votre type de compteur :

   **Pour les compteurs Téléo (communicants) :**
   - Sélectionnez : `sensor.eau_du_grand_lyon_index_journalier_teleo`
   - ✓ Vous aurez des données mises à jour **chaque jour**

   **Pour les compteurs Standard (relevé manuel) :**
   - Sélectionnez : `sensor.eau_du_grand_lyon_index_compteur`
   - ✓ Vous aurez un historique **mensuel**

5. Cliquez sur **Enregistrer**

---

### ÉTAPE 4 — Ajouter le coût à la source d'eau

Cette étape vous permet de voir les **coûts estimés** dans le tableau de bord :

1. Retournez au tableau de bord **Énergie**
2. Cliquez sur la boîte **EAU** (votre source d'eau)
3. Un panneau devrait s'ouvrir avec les détails
4. Cherchez le bouton **"Ajouter le coût de cette source"**
5. Sélectionnez : `sensor.eau_du_grand_lyon_cout_energie`
6. Cliquez sur **Enregistrer**

> **Remarque :** Si le bouton n'apparaît pas, vérifiez que l'entité `energie_cout` est **activée** (ÉTAPE 1).

---

## 📊 Résultat attendu

Après ces 4 étapes, votre tableau de bord Énergie devrait afficher :

- 📈 **Graphique de consommation** (m³ par mois)
- 💶 **Graphique de coût estimé** (€ par mois)
- 📊 **Statistiques cumulées** (consommation totale, coût total)

---

## ❓ FAQ / Troubleshooting

### "Le coût affiche 0 EUR ou 'Pas de données'"

**Solution :**
1. Vérifiez que le **tarif est configuré** (voir ÉTAPE 2)
2. Vérifiez que vous avez au moins **une données de consommation**
3. Attendez **24h** après la configuration pour que les données s'accumulent
4. **Redémarrez Home Assistant** si le problème persiste

### "Le bouton 'Ajouter le coût' n'apparaît pas"

**Solution :**
1. Vérifiez que `sensor.eau_du_grand_lyon_cout_energie` est **activé**
   - Paramètres → Appareils et services → Eau du Grand Lyon
   - Cherchez l'entité et cliquez pour l'activer si grisée
2. Attendez quelques secondes que HA recharge la page
3. Retournez au tableau de bord Énergie

### "Je ne vois pas la source d'eau dans le tableau de bord"

**Solution :**
1. Vérifiez que l'entity_id est correct :
   - Paramètres → Appareils et services → Eau du Grand Lyon
   - Cliquez sur le capteur pour voir son `entity_id` complet
2. Essayez de supprimer la source et de la re-ajouter
3. **Redémarrez Home Assistant**

### "L'entity_id du compteur n'apparaît pas dans la liste"

**Possible causes :**
- L'entité est **inactive** → allez l'activer (ÉTAPE 1)
- L'entité n'existe pas pour votre type de compteur (Téléo vs Standard)
- L'intégration n'a pas pu récupérer les données → attendez la prochaine sync (24h par défaut)

---

## 🔄 Types de compteurs et sources recommandées

| Type | Entity ID | Mise à jour | Précision |
|------|-----------|-------------|-----------|
| **Téléo** (communicant) | `sensor.eau_du_grand_lyon_index_journalier_teleo` | Quotidienne | Maximale |
| **Standard** (manuel) | `sensor.eau_du_grand_lyon_index_compteur` | Mensuelle | Basique |

---

## 📌 Capteurs utiles au tableau Énergie

| Capteur | État par défaut | Rôle |
|---------|-----------------|------|
| « Coût (Énergie) » | **ACTIVÉ** | Coût cumulé pour le tableau de bord Énergie |
| « Dernière conso journalière connue » | **ACTIVÉ** | Dernière journée publiée (2-3 jours de latence Téléo possibles) |
| « Consommation (7 derniers jours) » | **ACTIVÉ** | Somme des 7 derniers relevés journaliers (m³) |
| « Consommation (30 derniers jours) » | **ACTIVÉ** | Somme des 30 derniers relevés journaliers (m³) |
| « Consommation moyenne (7j) » | **ACTIVÉ** | Moyenne journalière sur 7 jours (L/jour) |

---

## 📚 Ressources complémentaires

- **Lovelace Cards** — Exemples de cartes personnalisées : `lovelace/monthly_chart_cards.yaml`
- **Energy Dashboard Preset** — Tableau de bord complet prêt à importer : `lovelace/energy_dashboard_preset.yaml`
- **Dashboard natif** — Sans carte HACS : `lovelace/dashboard.yaml`
- **Automatisations** — Rafraîchissement planifié et alertes : `lovelace/automation_refresh.yaml`

---

## 💡 Astuce avancée : Utiliser les statistiques injectées

Quatre statistiques externes sont **auto-injectées** dans la base de données du
recorder (`<REF>` = référence du contrat, visible dans Outils de développement >
Statistiques en recherchant « eau_grand_lyon ») :

1. **`eau_grand_lyon:water_<REF>`** — Consommation mensuelle (m³, jusqu'à 37 mois)
2. **`eau_grand_lyon:water_daily_<REF>`** — Consommation journalière cumulative (m³, compteurs Téléo)
3. **`eau_grand_lyon:cost_<REF>`** — Coût estimé mensuel (EUR, si un tarif est disponible)
4. **`eau_grand_lyon:cost_daily_<REF>`** — Coût estimé journalier (EUR, Téléo, si un tarif est disponible)

Les coûts ne contiennent que la part variable (consommation × tarif) : la part
fixe n'est pas répartie dans l'historique.

La statistique journalière est reconstruite et triée à chaque rafraîchissement sur
l'historique accumulé localement (jusqu'à 3 ans). Une correction tardive d'une
journée met donc aussi à jour les cumuls des journées suivantes, sans doublon.

Dans une carte `statistics-graph`, utilisez l'identifiant tel quel :

```yaml
type: statistics-graph
entities:
  - entity: eau_grand_lyon:cost_AB1234567890
period: month
stat_types:
  - change
```

### Migration recommandée du tableau Énergie

Dans la source d'eau existante, sélectionnez une seule fois
**`eau_grand_lyon:water_daily_<REF>`** comme statistique historique. Ne supprimez
pas l'ancienne statistique `water_<REF>` : elle reste disponible comme historique
mensuel et la migration peut être annulée en resélectionnant l'ancienne source.

Ces statistiques permettent de créer des graphiques avancés avec des cartes `statistics-graph` ou `custom:apexcharts-card`.

---

## 🆘 Besoin d'aide ?

Si vous avez des problèmes :

1. Consultez les **logs** de Home Assistant :
   - Paramètres → Système → Journaux
   - Redémarrez et cherchez "eau_grand_lyon"

2. Ouvrez une **issue GitHub** :
   - https://github.com/morgeek/HA-Plugin-pour-Eau-du-Grand-Lyon/issues

3. Vérifiez votre **configuration** :
   - Paramètres → Appareils et services → Eau du Grand Lyon
