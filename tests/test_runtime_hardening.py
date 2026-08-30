"""Regression tests for runtime hardening and dynamic contract entities."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.eau_grand_lyon import binary_sensor as binary_sensor_platform
from custom_components.eau_grand_lyon import sensor as sensor_platform
from custom_components.eau_grand_lyon.sensors import consumption, cost, experimental, global_sensors, intelligence
from custom_components.eau_grand_lyon.sensors.intelligence import EauGrandLyonPredictionCostSensor


def _dynamic_platform_entry(data: dict) -> tuple[MagicMock, MagicMock, list]:
    coordinator = MagicMock()
    coordinator.data = data
    listeners = []
    coordinator.async_add_listener.side_effect = lambda listener: listeners.append(listener) or MagicMock()

    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.options = {}
    entry.runtime_data = coordinator
    return entry, coordinator, listeners


def _added_unique_ids(add_entities: MagicMock) -> list[str]:
    return [entity._attr_unique_id for call in add_entities.call_args_list for entity in call.args[0]]


@pytest.mark.asyncio
async def test_sensor_platform_adds_new_contract_once_and_keeps_reappearing_contract_registered():
    data = {
        "contracts": {"A": {"teleo_compatible": False}},
        "global": {"nb_contracts": 1},
        "experimental_mode": False,
    }
    entry, coordinator, listeners = _dynamic_platform_entry(data)
    add_entities = MagicMock()

    await sensor_platform.async_setup_entry(MagicMock(), entry, add_entities)

    initial_ids = _added_unique_ids(add_entities)
    assert any("_A_" in unique_id for unique_id in initial_ids)
    assert not any("_B_" in unique_id for unique_id in initial_ids)
    assert len(listeners) == 1

    coordinator.data = {
        "contracts": {
            "A": {"teleo_compatible": False},
            "B": {"teleo_compatible": True, "derniere_facture": {"montant_ttc": 12.0}},
        },
        "global": {"nb_contracts": 2},
        "experimental_mode": True,
    }
    listeners[0]()

    after_discovery = _added_unique_ids(add_entities)
    assert any("_B_" in unique_id for unique_id in after_discovery)
    assert len(after_discovery) == len(set(after_discovery))
    discovery_call_count = add_entities.call_count

    listeners[0]()
    assert add_entities.call_count == discovery_call_count

    coordinator.data = {
        "contracts": {"A": {"teleo_compatible": False}},
        "global": {"nb_contracts": 1},
        "experimental_mode": False,
    }
    listeners[0]()
    assert add_entities.call_count == discovery_call_count

    coordinator.data = {
        "contracts": {"A": {"teleo_compatible": False}, "B": {"teleo_compatible": True}},
        "global": {"nb_contracts": 2},
        "experimental_mode": False,
    }
    listeners[0]()
    assert add_entities.call_count == discovery_call_count
    assert _added_unique_ids(add_entities) == after_discovery


@pytest.mark.asyncio
async def test_binary_sensor_platform_adds_multiple_new_contracts_without_duplicates():
    data = {"contracts": {"A": {}}}
    entry, coordinator, listeners = _dynamic_platform_entry(data)
    add_entities = MagicMock()

    await binary_sensor_platform.async_setup_entry(MagicMock(), entry, add_entities)

    coordinator.data = {
        "contracts": {
            "A": {},
            "B": {"abonne_alerte_fuite": True},
            "C": {"seuil_surconso_jour_m3": 1.0, "seuil_surconso_mois_m3": 10.0},
        }
    }
    listeners[0]()
    ids_after_discovery = _added_unique_ids(add_entities)

    assert any("_B_" in unique_id for unique_id in ids_after_discovery)
    assert any("_C_" in unique_id for unique_id in ids_after_discovery)
    assert len(ids_after_discovery) == len(set(ids_after_discovery))

    call_count = add_entities.call_count
    listeners[0]()
    assert add_entities.call_count == call_count


def test_prediction_cost_sensor_uses_valid_monetary_semantics_and_preserves_value():
    coordinator = MagicMock()
    coordinator.data = {"contracts": {"REF1": {"prediction_cout_mois": 123.45}}}
    entry = MagicMock(entry_id="entry-1")
    sensor = EauGrandLyonPredictionCostSensor(coordinator, entry, "REF1")

    assert sensor._attr_unique_id == "entry-1_REF1_prediction_cost"
    assert sensor._attr_device_class is SensorDeviceClass.MONETARY
    assert sensor._attr_state_class is None
    assert sensor._attr_native_unit_of_measurement == "EUR"
    assert sensor.native_value == 123.45

    coordinator.data["contracts"]["REF1"]["prediction_cout_mois"] = None
    assert sensor.native_value is None


def test_no_monetary_sensor_declares_measurement_state_class():
    monetary_classes = {}
    for module in (cost, experimental, global_sensors, intelligence):
        for name, value in vars(module).items():
            if isinstance(value, type) and getattr(value, "_attr_device_class", None) is SensorDeviceClass.MONETARY:
                monetary_classes[name] = value

    assert len(monetary_classes) == 12
    for name, entity_class in monetary_classes.items():
        assert getattr(entity_class, "_attr_state_class", None) is not SensorStateClass.MEASUREMENT, name

    assert intelligence.EauGrandLyonPredictionCostSensor._attr_state_class is None
    assert global_sensors.EauGrandLyonGlobalPredictionCostSensor._attr_state_class is None


def test_all_sensor_classes_keep_valid_water_and_cumulative_semantics():
    """Lock the state-class rules that protect Recorder and the Energy dashboard."""
    sensor_classes = {}
    for module in (consumption, cost, experimental, global_sensors, intelligence):
        for name, value in vars(module).items():
            if isinstance(value, type) and name.startswith("EauGrandLyon"):
                sensor_classes[name] = value

    for name, entity_class in sensor_classes.items():
        device_class = getattr(entity_class, "_attr_device_class", None)
        state_class = getattr(entity_class, "_attr_state_class", None)
        assert not (device_class is SensorDeviceClass.WATER and state_class is SensorStateClass.MEASUREMENT), name

    total_increasing = {
        name
        for name, entity_class in sensor_classes.items()
        if getattr(entity_class, "_attr_state_class", None) is SensorStateClass.TOTAL_INCREASING
    }
    assert total_increasing == {
        "EauGrandLyonConsommationSensor",
        "EauGrandLyonEnergyWaterSensor",
        "EauGrandLyonIndexJournalierSensor",
        "EauGrandLyonIndexSensor",
    }

    coordinator = MagicMock(data={"contracts": {"REF1": {}}})
    entry = MagicMock(entry_id="entry-1")
    previous_month = consumption.EauGrandLyonConsommationSensor(coordinator, entry, "REF1", "precedent")
    assert previous_month._attr_device_class is None
    assert previous_month._attr_state_class is SensorStateClass.MEASUREMENT
