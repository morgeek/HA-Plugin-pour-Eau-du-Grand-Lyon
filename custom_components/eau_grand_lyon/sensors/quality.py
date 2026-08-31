"""Sensors de qualité de l'eau — Open Data Métropole de Lyon."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorStateClass

from .base import _EauGrandLyonGlobalBase, _EauGrandLyonWaterQualityBase

if TYPE_CHECKING:
    from .. import EauGrandLyonConfigEntry
    from ..coordinator import EauGrandLyonCoordinator
    from ..models import WaterQualityData


class EauGrandLyonWaterHardnessSensor(_EauGrandLyonWaterQualityBase):
    """Dureté réelle de l'eau distribuée (°fH) — Open Data Métropole Lyon."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "°fH"
    _attr_translation_key = "water_hardness_live"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: EauGrandLyonConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_water_hardness_live"

    def _quality_value(self, wq: WaterQualityData) -> float | None:
        return wq.get("durete_fh")

    @property
    def native_value(self) -> float | None:
        wq = (self.coordinator.data or {}).get("water_quality", {})
        return self._quality_value(wq)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        wq = (self.coordinator.data or {}).get("water_quality", {})
        base = super().extra_state_attributes
        base["note"] = "Valeur mesurée sur le réseau — peut différer de votre robinet si adoucisseur"
        base["turbidite_ntu"] = wq.get("turbidite_ntu")
        return base


class EauGrandLyonNitratesSensor(_EauGrandLyonWaterQualityBase):
    """Concentration en nitrates dans l'eau distribuée (mg/L) — Open Data."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "mg/L"
    _attr_translation_key = "nitrates"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: EauGrandLyonConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_nitrates"

    def _quality_value(self, wq: WaterQualityData) -> float | None:
        return wq.get("nitrates_mgl")

    @property
    def native_value(self) -> float | None:
        wq = (self.coordinator.data or {}).get("water_quality", {})
        return self._quality_value(wq)

    @property
    def icon(self) -> str:
        val = self.native_value
        if val is None:
            return "mdi:flask-outline"
        if val < 10:
            return "mdi:flask"
        if val < 25:
            return "mdi:flask-empty-outline"
        if val < 50:
            return "mdi:alert-circle-outline"
        return "mdi:alert-circle"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        base = super().extra_state_attributes
        base["seuil_oms_mgl"] = 50
        base["note"] = "Seuil réglementaire européen : 50 mg/L"
        return base


class EauGrandLyonChloreSensor(_EauGrandLyonWaterQualityBase):
    """Chlore résiduel dans l'eau distribuée (mg/L) — Open Data."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "mg/L"
    _attr_translation_key = "chlore"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: EauGrandLyonConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_chlore"

    def _quality_value(self, wq: WaterQualityData) -> float | None:
        return wq.get("chlore_mgl")

    @property
    def native_value(self) -> float | None:
        wq = (self.coordinator.data or {}).get("water_quality", {})
        return self._quality_value(wq)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        base = super().extra_state_attributes
        base["note"] = "Chlore résiduel libre — garantit la potabilité jusqu'au robinet"
        return base


class _EauGrandLyonPfasBase(_EauGrandLyonGlobalBase):
    """Base des mesures PFAS publiques opt-in."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "µg/L"
    _attr_entity_registry_enabled_default = False
    _data_key = ""

    @property
    def available(self) -> bool:
        data = self.coordinator.data or {}
        return bool(
            super().available and data.get("pfas_enabled") and data.get("pfas", {}).get(self._data_key) is not None
        )

    @property
    def native_value(self) -> float | None:
        value = (self.coordinator.data or {}).get("pfas", {}).get(self._data_key)
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        data = (self.coordinator.data or {}).get("pfas", {})
        return {
            "commune": data.get("commune"),
            "nombre_prelevements_12_mois": data.get("samples_12_months"),
            "seuil_reglementaire_ug_l": data.get("threshold_ug_l", 0.1),
            "source": data.get("source", "Site public Eau du Grand Lyon"),
        }


class EauGrandLyonPfasMeanSensor(_EauGrandLyonPfasBase):
    """Valeur moyenne publique de la somme des 20 PFAS."""

    _attr_translation_key = "pfas_mean"
    _attr_suggested_display_precision = 3
    _data_key = "mean_ug_l"

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: EauGrandLyonConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_pfas_mean"


class EauGrandLyonPfasMaximumSensor(_EauGrandLyonPfasBase):
    """Valeur maximale publique de la somme des 20 PFAS."""

    _attr_translation_key = "pfas_maximum"
    _attr_suggested_display_precision = 3
    _data_key = "maximum_ug_l"

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: EauGrandLyonConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_pfas_maximum"
