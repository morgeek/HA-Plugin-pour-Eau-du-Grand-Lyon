"""Sensors de consommation d'eau (mensuelle, journalière, index)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory

from .base import _EauGrandLyonBase, _EauGrandLyonDailyBase


class EauGrandLyonIndexSensor(_EauGrandLyonBase):
    """Index cumulatif (TOTAL_INCREASING) — Tableau de bord Énergie HA."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "m³"
    translation_key = "water_index"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_index_cumulatif"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.get_cumulative_index(self._contract_ref)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        consos = self._contract.get("consommations", [])
        manquants = self._contract.get("mois_manquants", [])
        return {
            "premier_relevé": consos[0]["label"] if consos else None,
            "dernier_relevé": consos[-1]["label"] if consos else None,
            "nb_mois_inclus": len(consos),
            "mois_manquants": manquants,
            "nb_mois_manquants": len(manquants),
            "note": "Somme cumulée — historique injecté dans les statistiques HA.",
        }


class EauGrandLyonIndexJournalierSensor(_EauGrandLyonBase):
    """Dernier index compteur connu depuis les données journalières Téléo (m³).

    Inspiré du fork hufon/HA-Plugin-pour-Eau-du-Grand-Lyon.
    N'est disponible que sur les compteurs communicants Téléo dont les données
    journalières incluent un champ 'index'. L'entité passe unavailable si aucun
    index n'est présent dans les données récupérées.
    """

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "m³"
    translation_key = "index_journalier"
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_index_journalier"

    @property
    def available(self) -> bool:
        if not self.coordinator.data:
            return False
        return self._contract.get("index_journalier_dernier") is not None

    @property
    def native_value(self) -> float | None:
        return self._contract.get("index_journalier_dernier")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "date_index":    c.get("index_journalier_dernier_date"),
            "source_donnee": c.get("daily_source", "Inconnue"),
            "nb_jours":      c.get("daily_nb_entries", 0),
            "note": (
                "Index lu dans les données journalières Téléo. "
                "Unavailable si le compteur ne transmet pas l'index."
            ),
        }


class EauGrandLyonConsommationSensor(_EauGrandLyonBase):
    """Consommation du mois courant ou précédent (m³)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry, contract_ref, period: str):
        super().__init__(coordinator, entry, contract_ref)
        self._period = period
        self.translation_key = f"conso_{period}"
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_conso_{period}"

    @property
    def native_value(self) -> float | None:
        c = self._contract
        return (
            c.get("consommation_mois_courant")
            if self._period == "courant"
            else c.get("consommation_mois_precedent")
        )

    @property
    def icon(self) -> str:
        val = self.native_value
        if val is None or val == 0:
            return "mdi:water-outline"
        if val < 5:  return "mdi:water-minus"
        if val < 15: return "mdi:water"
        return "mdi:water-percent"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        consos = c.get("consommations", [])
        attrs: dict[str, Any] = {}

        if self._period == "courant":
            attrs["période"] = c.get("label_mois_courant", "")

            prev = c.get("consommation_mois_precedent")
            curr = c.get("consommation_mois_courant")
            if prev is not None and curr is not None:
                attrs["variation_vs_mois_precedent_m3"] = round(curr - prev, 1)
                attrs["variation_vs_mois_precedent_pct"] = (
                    round((curr - prev) / prev * 100, 1) if prev != 0 else None
                )

            n1 = c.get("consommation_n1")
            if n1 is not None and curr is not None:
                attrs["consommation_n1_m3"] = n1
                attrs["période_n1"] = c.get("label_n1", "")
                attrs["variation_vs_n1_m3"] = round(curr - n1, 1)
                attrs["variation_vs_n1_pct"] = (
                    round((curr - n1) / n1 * 100, 1) if n1 != 0 else None
                )
        else:
            attrs["période"] = c.get("label_mois_precedent", "")

        # Cap l'historique à 24 mois pour éviter de saturer les attributs (DB bloat)
        consos_capped = consos[-24:] if len(consos) > 24 else consos
        attrs["historique"] = [
            {"période": e["label"], "consommation_m3": e["consommation_m3"]}
            for e in consos_capped
        ]
        attrs["nb_mois_disponibles"] = len(consos)
        return attrs


class EauGrandLyonConsommationAnnuelleSensor(_EauGrandLyonBase):
    """Consommation totale des 12 derniers mois (m³)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    translation_key = "conso_annuelle"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_conso_annuelle"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("consommation_annuelle")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        consos = c.get("consommations", [])
        last_12 = consos[-12:] if len(consos) >= 12 else consos
        tarif = c.get("tarif_m3", 0)
        monthly_chart = [
            {
                "label": e["label"],
                "conso_m3": e["consommation_m3"],
                "cout_eur": round(e["consommation_m3"] * tarif, 2) if tarif else None,
            }
            for e in last_12
        ]
        return {
            "nb_mois_inclus": len(last_12),
            "période_début": last_12[0]["label"] if last_12 else None,
            "période_fin": last_12[-1]["label"] if last_12 else None,
            "monthly_chart_data": monthly_chart,
            "détail_mensuel": [
                {"période": e["label"], "consommation_m3": e["consommation_m3"]}
                for e in last_12
            ],
        }


class EauGrandLyonYesterdaySensor(_EauGrandLyonDailyBase):
    """Consommation de la veille (dernier jour disponible) en Litres."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "L"
    translation_key = "conso_hier"
    _attr_suggested_display_precision = 0
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_conso_hier"

    @property
    def native_value(self) -> float | None:
        daily = self._contract.get("consommations_journalieres", [])
        if not daily:
            return None
        last_val_m3 = daily[-1].get("consommation_m3")
        if last_val_m3 is None:
            return None
        return round(last_val_m3 * 1000, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        daily = self._contract.get("consommations_journalieres", [])
        last_date = daily[-1].get("date") if daily else None
        return {
            "date_relevé": last_date,
            "unité": "Litres",
            "note": "Donnée de la veille (ou dernier jour connu par l'API)",
        }


class EauGrandLyonConso7JSensor(_EauGrandLyonDailyBase):
    """Consommation sur les 7 derniers jours (compteur Téléo/TIC uniquement)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    translation_key = "conso_7j"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_conso_7j"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("consommation_7j")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        daily = self._contract.get("consommations_journalieres", [])
        return {
            "source": self._contract.get("daily_source"),
            "nb_entrées_total": self._contract.get("daily_nb_entries"),
            "dernière_date_api": self._contract.get("daily_last_date"),
            "derniers_jours": [
                {"date": e["date"], "consommation_m3": e["consommation_m3"]}
                for e in daily[-7:]
            ],
        }


class EauGrandLyonConso30JSensor(_EauGrandLyonDailyBase):
    """Consommation sur les 30 derniers jours (compteur Téléo/TIC uniquement)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    translation_key = "conso_30j"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_conso_30j"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("consommation_30j")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        daily = self._contract.get("consommations_journalieres", [])
        # Attributs limités aux 14 derniers jours pour limiter le volume en BDD
        recent_14 = daily[-14:]
        return {
            "source": self._contract.get("daily_source"),
            "nb_entrées_total": self._contract.get("daily_nb_entries"),
            "dernière_date_api": self._contract.get("daily_last_date"),
            "nb_jours_inclus": min(len(daily), 30),
            "derniers_jours": [
                {"date": e["date"], "consommation_m3": e["consommation_m3"]}
                for e in recent_14
            ],
        }


class EauGrandLyonConsoMoyenne7JSensor(_EauGrandLyonDailyBase):
    """Consommation moyenne journalière sur 7 jours (L/jour)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "L"
    translation_key = "conso_moyenne_7j"
    _attr_suggested_display_precision = 0
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_conso_moyenne_7j"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("conso_moyenne_7j_litres")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "période": "7 derniers jours",
            "unité": "Litres par jour",
        }


class EauGrandLyonCompatibilitySensor(_EauGrandLyonBase):
    """Indique si le compteur est compatible avec la télé-relève (Téléo)."""

    translation_key = "compatibilite_compteur"
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_compatibility"

    @property
    def native_value(self) -> str:
        if self._contract.get("teleo_compatible"):
            return "Téléo (Télé-relève)"
        return "Standard (Relève manuelle)"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "nb_entrées_journalières": self._contract.get("daily_nb_entries", 0),
            "signal_pct": self._contract.get("signal_pct"),
            "pile_ok": self._contract.get("battery_ok"),
        }


class EauGrandLyonConsoAnnuelleRefSensor(_EauGrandLyonBase):
    """Consommation annuelle de référence du profil contrat (m³/an)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    translation_key = "conso_annuelle_ref"
    _attr_suggested_display_precision = 0
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_conso_annuelle_ref"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("conso_annuelle_ref_m3")
