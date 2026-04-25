"""Configuration pytest — stub les modules Home Assistant non installés."""
import sys
import enum
from unittest.mock import MagicMock, AsyncMock


def _make_ha_stubs() -> None:
    """Injecte de faux modules homeassistant dans sys.modules avant tout import."""
    mods = [
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.device_registry",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.storage",
        "homeassistant.helpers.update_coordinator",
        "homeassistant.helpers.issue_registry",
        "homeassistant.components",
        "homeassistant.components.sensor",
        "homeassistant.components.binary_sensor",
        "homeassistant.components.button",
        "homeassistant.components.switch",
        "homeassistant.components.calendar",
        "homeassistant.components.recorder",
        "homeassistant.components.recorder.models",
        "homeassistant.components.recorder.statistics",
        "homeassistant.components.persistent_notification",
        "homeassistant.components.repairs",
        "homeassistant.util",
        "homeassistant.util.dt",
        "homeassistant.helpers.typing",
    ]
    for mod in mods:
        sys.modules[mod] = MagicMock()

    # ── homeassistant.const ───────────────────────────────────────────────────
    class Platform(str, enum.Enum):
        SENSOR        = "sensor"
        BINARY_SENSOR = "binary_sensor"
        BUTTON        = "button"
        SWITCH        = "switch"
        CALENDAR      = "calendar"

    class EntityCategory(str, enum.Enum):
        CONFIG     = "config"
        DIAGNOSTIC = "diagnostic"

    const_mod = sys.modules["homeassistant.const"]
    const_mod.Platform       = Platform
    const_mod.EntityCategory = EntityCategory

    # ── DataUpdateCoordinator / UpdateFailed ──────────────────────────────────
    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator:
        def __init__(self, hass, logger, name, update_interval):
            self.hass   = hass
            self.data   = None
            self.logger = logger

        async def async_request_refresh(self):
            pass

        def __class_getitem__(cls, item):
            return cls  # support DataUpdateCoordinator[T]

    class CoordinatorEntity:
        def __init__(self, coordinator, *args, **kwargs):
            self.coordinator = coordinator

        @property
        def available(self):
            return self.coordinator.data is not None

        def __class_getitem__(cls, item):
            return cls  # support CoordinatorEntity[T]

    upc = sys.modules["homeassistant.helpers.update_coordinator"]
    upc.UpdateFailed          = UpdateFailed
    upc.DataUpdateCoordinator = DataUpdateCoordinator
    upc.CoordinatorEntity     = CoordinatorEntity

    # ── Enums HA ──────────────────────────────────────────────────────────────
    class SensorStateClass(str, enum.Enum):
        MEASUREMENT      = "measurement"
        TOTAL            = "total"
        TOTAL_INCREASING = "total_increasing"

    class SensorDeviceClass(str, enum.Enum):
        WATER       = "water"
        MONETARY    = "monetary"
        TIMESTAMP   = "timestamp"
        DATE        = "date"
        VOLUME      = "volume"
        WEIGHT      = "weight"
        TEMPERATURE = "temperature"
        PRESSURE    = "pressure"
        ENERGY      = "energy"
        POWER       = "power"
        DISTANCE    = "distance"
        SPEED       = "speed"
        DURATION    = "duration"

    class BinarySensorDeviceClass(str, enum.Enum):
        PROBLEM  = "problem"
        MOISTURE = "moisture"
        BATTERY  = "battery"

    class SwitchDeviceClass(str, enum.Enum):
        SWITCH  = "switch"
        OUTLET  = "outlet"

    # ── Entity base classes stub (vraies classes, pas MagicMock) ─────────────
    # MagicMock comme base casse super().__init__() dans les sensors.
    class _StubEntity:
        """Base stub pour toutes les entités HA."""
        _attr_has_entity_name              = False
        _attr_entity_registry_enabled_default = True
        _attr_unique_id                    = None
        _attr_name                         = None
        _attr_icon                         = None
        _attr_device_class                 = None
        _attr_state_class                  = None
        _attr_native_unit_of_measurement   = None
        _attr_suggested_display_precision  = None
        _attr_entity_category              = None

        def __init__(self, *args, **kwargs):
            pass

    class SensorEntity(_StubEntity):
        pass

    class BinarySensorEntity(_StubEntity):
        pass

    class ButtonEntity(_StubEntity):
        pass

    class SwitchEntity(_StubEntity):
        pass

    class CalendarEntity(_StubEntity):
        pass

    class CalendarEvent:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    sensor_mod = sys.modules["homeassistant.components.sensor"]
    sensor_mod.SensorStateClass  = SensorStateClass
    sensor_mod.SensorDeviceClass = SensorDeviceClass
    sensor_mod.SensorEntity      = SensorEntity

    bs_mod = sys.modules["homeassistant.components.binary_sensor"]
    bs_mod.BinarySensorDeviceClass = BinarySensorDeviceClass
    bs_mod.BinarySensorEntity      = BinarySensorEntity

    btn_mod = sys.modules["homeassistant.components.button"]
    btn_mod.ButtonEntity = ButtonEntity

    sw_mod = sys.modules["homeassistant.components.switch"]
    sw_mod.SwitchEntity      = SwitchEntity
    sw_mod.SwitchDeviceClass = SwitchDeviceClass

    cal_mod = sys.modules["homeassistant.components.calendar"]
    cal_mod.CalendarEntity = CalendarEntity
    cal_mod.CalendarEvent  = CalendarEvent

    # ── DeviceInfo ────────────────────────────────────────────────────────────
    class DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    sys.modules["homeassistant.helpers.device_registry"].DeviceInfo = DeviceInfo

    # ── Store stub ────────────────────────────────────────────────────────────
    class Store:
        def __init__(self, hass, version, key):
            self._data = None

        async def async_load(self):
            return self._data

        async def async_save(self, data):
            self._data = data

    sys.modules["homeassistant.helpers.storage"].Store = Store


_make_ha_stubs()
