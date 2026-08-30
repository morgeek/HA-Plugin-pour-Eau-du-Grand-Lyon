"""Sensors du mode expérimental : facture, fuite estimée, courbe de charge."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from .base import _EauGrandLyonBase, _EauGrandLyonHourlyBase


class EauGrandLyonDerniereFactureSensor(_EauGrandLyonBase):
    """Montant TTC réel de la dernière facture renvoyée par le fournisseur."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "EUR"
    _attr_translation_key = "derniere_facture"
    _attr_suggested_display_precision = 2
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_derniere_facture"

    @property
    def available(self) -> bool:
        return super().available and self._contract.get("derniere_facture") is not None

    @property
    def native_value(self) -> float | None:
        facture = self._contract.get("derniere_facture")
        if not facture:
            return None
        return facture.get("montant_ttc")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        facture = self._contract.get("derniere_facture") or {}
        factures = self._contract.get("factures", [])
        return {
            "référence": facture.get("reference", ""),
            "date_édition": facture.get("date_edition"),
            "date_exigibilité": facture.get("date_exigibilite"),
            "montant_ht_eur": facture.get("montant_ht"),
            "montant_ttc_eur": facture.get("montant_ttc"),
            "volume_m3": facture.get("volume_m3"),
            "statut_paiement": facture.get("statut_paiement", ""),
            "nb_factures_total": len(factures),
            "estimation": False,
            "historique_factures": [
                {
                    "référence": f.get("reference"),
                    "date_édition": f.get("date_edition"),
                    "montant_ttc_eur": f.get("montant_ttc"),
                    "statut_paiement": f.get("statut_paiement"),
                }
                for f in factures[:12]  # 12 dernières factures max en attribut
            ],
            "source": "API Eau du Grand Lyon — montant TTC facturé",
        }


class EauGrandLyonFuiteEstimeeSensor(_EauGrandLyonBase):
    """[EXPÉRIMENTAL] Volume de fuite estimé sur les 30 derniers jours (m³).

    Ce champ (volumeFuiteEstime) est remonté par le nouvel endpoint
    /rest/produits/contrats/{id}/consommationsJournalieres, uniquement sur
    les compteurs Téléo récents qui calculent la fuite nocturne.

    Une valeur > 0 peut indiquer une fuite sur le circuit intérieur.
    Le binary_sensor "Alerte fuite possible" reste basé sur la surconsommation
    mensuelle (méthode legacy) — ce sensor est complémentaire.
    """

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    _attr_translation_key = "fuite_estimee"
    _attr_suggested_display_precision = 3
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_fuite_estimee"

    @property
    def available(self) -> bool:
        return super().available and self._contract.get("fuite_estime_30j_m3") is not None

    @property
    def native_value(self) -> float | None:
        return self._contract.get("fuite_estime_30j_m3")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        daily = self._contract.get("consommations_journalieres", [])
        recent_30 = daily[-30:]
        all_fuite = [e for e in recent_30 if "volume_fuite_estime_m3" in e]
        # Attributs limités aux 14 derniers jours pour limiter le volume en BDD
        detail = [
            {
                "date": e["date"],
                "volume_fuite_estime_m3": e.get("volume_fuite_estime_m3", 0),
            }
            for e in all_fuite[-14:]
        ]
        return {
            "nb_jours_avec_donnée": len(all_fuite),
            "détail_journalier": detail,
            "note": (
                "Volume de fuite nocturne estimé par le compteur Téléo. "
                "Non nul = possible fuite sur circuit intérieur."
            ),
            "source": "expérimental — volumeFuiteEstime dans /rest/produits/contrats/{id}/consommationsJournalieres",
        }


class EauGrandLyonHourlyConsoSensor(_EauGrandLyonHourlyBase):
    """Consommation de la dernière heure (m³) — courbe de charge Téléo."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "m³"
    _attr_translation_key = "hourly_conso"
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_hourly_conso"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("consommation_derniere_heure_m3")


class EauGrandLyonPeakHourSensor(_EauGrandLyonHourlyBase):
    """Heure de pic de consommation sur les derniers 7 jours (HH:MM)."""

    _attr_translation_key = "peak_hour"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_peak_hour"

    @property
    def native_value(self) -> str | None:
        return self._contract.get("heure_pic")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"note": "Calculé sur les 7 derniers jours de courbe de charge"}


class EauGrandLyonAvgFlowSensor(_EauGrandLyonHourlyBase):
    """Débit moyen (m³/h) calculé sur les plages actives de la courbe de charge."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "m³/h"
    _attr_translation_key = "avg_flow"
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_avg_flow"

    @property
    def native_value(self) -> float | None:
        return self._contract.get("debit_moyen_m3h")
