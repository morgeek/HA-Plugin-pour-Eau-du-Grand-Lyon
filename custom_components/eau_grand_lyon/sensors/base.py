"""Classes de base pour les sensors Eau du Grand Lyon."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from ..coordinator import EauGrandLyonCoordinator
from ..device import account_device_info, contract_device_info
from ..models import ContractData, WaterQualityData

if TYPE_CHECKING:
    from .. import EauGrandLyonConfigEntry


class _EauGrandLyonBase(CoordinatorEntity[EauGrandLyonCoordinator], SensorEntity):
    """Base commune pour tous les sensors Eau du Grand Lyon."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EauGrandLyonCoordinator,
        entry: EauGrandLyonConfigEntry,
        contract_ref: str,
        description: SensorEntityDescription | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._contract_ref = contract_ref
        self._entry = entry
        if description:
            self.entity_description = description
            self._attr_unique_id = f"{entry.entry_id}_{contract_ref}_{description.key}"

    @property
    def _current_year_str(self) -> str:
        return f"{dt_util.now().year}-01-01"

    @property
    def _contract(self) -> ContractData:
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get("contracts", {}).get(self._contract_ref, {})

    @property
    def device_info(self) -> DeviceInfo:
        return contract_device_info(self.coordinator, self._entry, self._contract_ref)


class _EauGrandLyonGlobalBase(CoordinatorEntity[EauGrandLyonCoordinator], SensorEntity):
    """Base commune pour les sensors globaux (alertes, dernière MAJ, santé API)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: EauGrandLyonConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return account_device_info(self.coordinator, self._entry)


class _EauGrandLyonDailyBase(_EauGrandLyonBase):
    """Base pour les sensors journaliers — unavailable si données non dispo."""

    @property
    def available(self) -> bool:
        return super().available and bool(self._contract.get("consommations_journalieres"))


class _EauGrandLyonHourlyBase(_EauGrandLyonBase):
    """Base pour les sensors horaires — unavailable si courbe de charge absente."""

    _attr_entity_registry_enabled_default = False  # Téléo uniquement

    @property
    def available(self) -> bool:
        return super().available and bool(self._contract.get("courbe_de_charge"))


class _EauGrandLyonWaterQualityBase(_EauGrandLyonGlobalBase):
    """Base pour les sensors qualité eau — unavailable si Hub'Eau indisponible."""

    _attr_entity_registry_enabled_default = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        wq = (self.coordinator.data or {}).get("water_quality", {})
        return super().available and self._quality_value(wq) is not None

    def _quality_value(self, wq: WaterQualityData) -> float | None:
        raise NotImplementedError

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        wq = (self.coordinator.data or {}).get("water_quality", {})
        return {
            "commune": wq.get("commune"),
            "code_commune": wq.get("code_commune"),
            "code_reseau": wq.get("code_reseau"),
            "nom_reseau": wq.get("nom_reseau"),
            "date_analyse": wq.get("date_analyse"),
            "source": wq.get("source"),
        }
