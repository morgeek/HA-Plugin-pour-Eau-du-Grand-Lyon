"""Classes de base pour les sensors Eau du Grand Lyon."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from ..coordinator import EauGrandLyonCoordinator

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
    def _contract(self) -> dict:
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get("contracts", {}).get(self._contract_ref, {})

    @property
    def device_info(self) -> DeviceInfo:
        calibre = self._contract.get("calibre_compteur", "")
        usage = self._contract.get("usage", "")
        model_parts = [p for p in [calibre and f"DN{calibre}", usage] if p]
        numero_compteur = (
            self._contract.get("reference_pds")
            or self._contract.get("reference", self._contract_ref)
        )
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_{self._contract_ref}")},
            name="Eau du Grand Lyon",
            manufacturer="Morgeek",
            model=", ".join(model_parts) or "Compteur eau",
            serial_number=numero_compteur,
            configuration_url="https://agence.eaudugrandlyon.com",
        )


class _EauGrandLyonGlobalBase(CoordinatorEntity[EauGrandLyonCoordinator], SensorEntity):
    """Base commune pour les sensors globaux (alertes, dernière MAJ, santé API)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EauGrandLyonCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        contracts = (self.coordinator.data or {}).get("contracts", {})
        first_ref = next(iter(contracts), None)
        if first_ref:
            return DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry.entry_id}_{first_ref}")},
            )
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Eau du Grand Lyon",
            manufacturer="Morgeek",
        )


class _EauGrandLyonDailyBase(_EauGrandLyonBase):
    """Base pour les sensors journaliers — unavailable si données non dispo."""

    @property
    def available(self) -> bool:
        return (
            super().available
            and bool(self._contract.get("consommations_journalieres"))
        )


class _EauGrandLyonHourlyBase(_EauGrandLyonBase):
    """Base pour les sensors horaires — unavailable si courbe de charge absente."""

    _attr_entity_registry_enabled_default = False  # Téléo uniquement

    @property
    def available(self) -> bool:
        return (
            super().available
            and bool(self._contract.get("courbe_de_charge"))
        )


class _EauGrandLyonWaterQualityBase(_EauGrandLyonGlobalBase):
    """Base pour les sensors qualité eau — unavailable si Open Data indisponible."""

    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        wq = (self.coordinator.data or {}).get("water_quality", {})
        return super().available and self._quality_value(wq) is not None

    def _quality_value(self, wq: dict) -> Any:
        raise NotImplementedError

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        wq = (self.coordinator.data or {}).get("water_quality", {})
        return {
            "commune":      wq.get("commune"),
            "date_analyse": wq.get("date_analyse"),
            "source":       wq.get("source"),
        }
