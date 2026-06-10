"""Sensors liés au contrat et au compte client."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass

from .base import _EauGrandLyonBase


class EauGrandLyonStatutSensor(_EauGrandLyonBase):
    """Statut du contrat (actif, résilié, etc.)."""

    _attr_translation_key = "statut"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_statut"

    @property
    def native_value(self) -> str | None:
        return self._contract.get("statut")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._contract
        return {
            "référence": c.get("reference", ""),
            "date_effet": c.get("date_effet"),
            "date_fin": c.get("date_echeance"),
            "usage": c.get("usage", ""),
            "calibre_compteur_mm": c.get("calibre_compteur", ""),
            "nombre_habitants": c.get("nombre_habitants", ""),
            "référence_pds": c.get("reference_pds", ""),
        }


class EauGrandLyonDateEcheanceSensor(_EauGrandLyonBase):
    """Date d'échéance (fin) du contrat."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_translation_key = "date_echeance"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_date_echeance"

    @property
    def native_value(self) -> date | None:
        raw = self._contract.get("date_echeance")
        if raw:
            try:
                return date.fromisoformat(raw)
            except ValueError:
                return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"date_début": self._contract.get("date_effet")}


class EauGrandLyonProchaineFactureSensor(_EauGrandLyonBase):
    """Date de la prochaine facture — issue de l'API /dateProchaineFacture."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_translation_key = "prochaine_facture"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_prochaine_facture"

    @property
    def native_value(self) -> date | None:
        raw = self._contract.get("next_bill_date")
        if raw:
            try:
                return date.fromisoformat(raw)
            except ValueError:
                return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "source": "API /dateProchaineFacture" if self._contract.get("next_bill_date") else "estimation",
        }


class EauGrandLyonProchaineReleveSensor(_EauGrandLyonBase):
    """Date du prochain relevé compteur — issue de /pointDeService."""

    _attr_device_class = SensorDeviceClass.DATE
    _attr_translation_key = "prochaine_releve"

    def __init__(self, coordinator, entry, contract_ref):
        super().__init__(coordinator, entry, contract_ref)
        self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_prochaine_releve"

    @property
    def native_value(self) -> date | None:
        raw = self._contract.get("date_prochaine_releve")
        if raw:
            try:
                return date.fromisoformat(raw)
            except ValueError:
                return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "mode_releve": self._contract.get("pds_mode_releve"),
            "communicabilite_amm": self._contract.get("pds_communicabilite_amm"),
        }
