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
2. Cherchez l'entité `sensor.eau_du_grand_lyon_energie_cout`
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
   - Sélectionnez : `sensor.eau_du_grand_lyon_index_journalier_energy`
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
5. Sélectionnez : `sensor.eau_du_grand_lyon_energie_cout`
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
1. Vérifiez que `sensor.eau_du_grand_lyon_energie_cout` est **activé**
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
| **Téléo** (communicant) | `sensor.eau_du_grand_lyon_index_journalier_energy` | Quotidienne | Maximale |
| **Standard** (manuel) | `sensor.eau_du_grand_lyon_index_compteur` | Mensuelle | Basique |

---

## 📌 Statut des capteurs depuis v2.9.0

| Capteur | État par défaut | Rôle |
|---------|-----------------|------|
| `energie_cout` | **ACTIVÉ** | Coût cumulé pour le tableau de bord Énergie |
| `conso_hier` | **ACTIVÉ** | Consommation de la veille |
| `conso_7j` | **ACTIVÉ** | Moyenne 7 jours |
| `conso_30j` | **ACTIVÉ** | Moyenne 30 jours |
| `conso_moyenne_7j` | **ACTIVÉ** | Moyenne journalière 7j (L/jour) |

---

## 📚 Ressources complémentaires

- **Lovelace Cards** — Exemples de cartes personnalisées : `lovelace/monthly_chart_cards.yaml`
- **Energy Dashboard Preset** — Tableau de bord complet prêt à importer : `lovelace/energy_dashboard_preset.yaml`
- **Configuration Energy** — Documentation complète : `lovelace/energy_config.yaml`

---

## 💡 Astuce avancée : Utiliser les statistiques injectées

Depuis v2.9.0, deux statistiques sont **auto-injectées** dans la base de données du recorder :

1. **`eau_grand_lyon:water_<REF>`** — Consommation mensuelle (m³)
2. **`eau_grand_lyon:cost_<REF>`** — Coût estimé mensuel (EUR)

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
