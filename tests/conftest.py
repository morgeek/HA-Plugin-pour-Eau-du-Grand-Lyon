"""Fixtures partagées pour les tests Eau du Grand Lyon."""

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub homeassistant package so tests run without a real HA installation
# ---------------------------------------------------------------------------


def _make_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _stub_homeassistant() -> None:
    """Register minimal HA stubs so component imports don't explode."""
    if "homeassistant" in sys.modules:
        return

    # Base package
    ha = _make_module("homeassistant")

    class _HomeAssistantError(Exception):
        """Mock HomeAssistantError (accepte les kwargs de traduction comme le vrai)."""

        def __init__(self, *args, translation_domain=None, translation_key=None, translation_placeholders=None):
            super().__init__(*args)
            self.translation_domain = translation_domain
            self.translation_key = translation_key
            self.translation_placeholders = translation_placeholders

    class _ServiceValidationError(_HomeAssistantError):
        """Mock ServiceValidationError."""

        pass

    _make_module(
        "homeassistant.core",
        HomeAssistant=MagicMock,
        HomeAssistantError=_HomeAssistantError,
        ServiceValidationError=_ServiceValidationError,
        ServiceCall=MagicMock,
    )

    class _ConfigEntryAuthFailed(Exception):
        pass

    _make_module(
        "homeassistant.exceptions",
        ConfigEntryAuthFailed=_ConfigEntryAuthFailed,
        HomeAssistantError=_HomeAssistantError,
        ServiceValidationError=_ServiceValidationError,
    )
    _make_module("homeassistant.const", EntityCategory=MagicMock(), Platform=MagicMock())

    class _ConfigEntry:
        def __class_getitem__(cls, item):
            return cls

    class _ConfigFlow:
        """Stub ConfigFlow that accepts domain= keyword."""

        def __init__(self):
            self._modern_update_calls = []

        def __init_subclass__(cls, domain=None, **kw):
            super().__init_subclass__(**kw)

        def async_update_and_abort(self, entry, *, data_updates, reason):
            """Mirror the inherited modern HA implementation used by the flow."""
            self._modern_update_calls.append((entry, data_updates, reason))
            self.hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, **data_updates},
            )
            return self.async_abort(reason=reason)

    _make_module(
        "homeassistant.config_entries",
        ConfigEntry=_ConfigEntry,
        ConfigFlow=_ConfigFlow,
        OptionsFlow=MagicMock,
    )
    _make_module("homeassistant.helpers")
    _make_module(
        "homeassistant.helpers.config_validation",
        config_entry_only_config_schema=lambda domain: (lambda cfg: cfg),
    )
    _make_module("homeassistant.helpers.typing", ConfigType=MagicMock)
    _make_module("homeassistant.helpers.storage", Store=MagicMock)
    _make_module(
        "homeassistant.helpers.device_registry",
        DeviceInfo=MagicMock,
        async_get=MagicMock(),
    )
    _make_module(
        "homeassistant.helpers.entity_registry",
        async_get=MagicMock(),
        async_entries_for_device=MagicMock(return_value=[]),
    )
    _make_module("homeassistant.helpers.entity_platform", AddEntitiesCallback=MagicMock)

    class _GenericBase:
        def __init__(self, *args, **kwargs):
            # CoordinatorEntity(coordinator) — accepte l'argument pour que les
            # constructeurs réels des entités soient exerçables en test.
            self.coordinator = args[0] if args else None

        def __class_getitem__(cls, item):
            return cls

        @property
        def available(self) -> bool:
            # Mirrors CoordinatorEntity.available — True unless coordinator says otherwise.
            return True

    _make_module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=_GenericBase,
        CoordinatorEntity=_GenericBase,
        UpdateFailed=Exception,
    )

    sensor_mod = _make_module(
        "homeassistant.components.sensor",
        SensorEntity=object,
        SensorEntityDescription=MagicMock,
        SensorDeviceClass=MagicMock(),
        SensorStateClass=MagicMock(),
    )
    _make_module(
        "homeassistant.components.binary_sensor",
        BinarySensorEntity=object,
        BinarySensorDeviceClass=MagicMock(),
    )
    _make_module("homeassistant.components.button", ButtonEntity=object)

    class _SwitchEntity:
        pass

    _make_module("homeassistant.components.switch", SwitchEntity=_SwitchEntity)
    _make_module("homeassistant.components.calendar", CalendarEntity=object, CalendarEvent=MagicMock)
    _make_module("homeassistant.components.recorder")
    _make_module(
        "homeassistant.components.recorder.models",
        StatisticData=MagicMock,
        StatisticMetaData=MagicMock,
    )
    _make_module(
        "homeassistant.components.recorder.statistics",
        async_add_external_statistics=AsyncMock(),
        StatisticMeanType=MagicMock(),
    )
    # persistent_notification.async_create / async_dismiss are sync @callback in HA.
    _make_module(
        "homeassistant.components.persistent_notification",
        async_create=MagicMock(return_value=None),
        async_dismiss=MagicMock(return_value=None),
    )
    _make_module(
        "homeassistant.helpers.issue_registry",
        # Sync @callback functions in real HA — MagicMock (not AsyncMock) so that
        # awaiting them in component code fails in tests, matching production.
        async_create_issue=MagicMock(),
        async_delete_issue=MagicMock(),
        IssueSeverity=MagicMock(),
    )

    class _Selector:
        def __init__(self, config=None):
            self._config = config

        def __call__(self, value):
            return value

    _make_module(
        "homeassistant.helpers.selector",
        EntitySelector=_Selector,
        EntitySelectorConfig=lambda **kw: dict(kw),
        SelectSelector=_Selector,
        SelectSelectorConfig=lambda **kw: dict(kw),
        SelectOptionDict=lambda **kw: dict(kw),
        SelectSelectorMode=types.SimpleNamespace(DROPDOWN="dropdown", LIST="list"),
    )
    _make_module("homeassistant.helpers.aiohttp_client", async_create_clientsession=MagicMock())

    class _RestoreEntity:
        async def async_get_last_state(self):
            return None

    _make_module("homeassistant.helpers.restore_state", RestoreEntity=_RestoreEntity)
    import datetime as _dt

    _dt_util = types.ModuleType("homeassistant.util.dt")
    _dt_util.now = lambda: _dt.datetime.now(_dt.timezone.utc)
    _dt_util.utcnow = lambda: _dt.datetime.now(_dt.timezone.utc)
    sys.modules["homeassistant.util.dt"] = _dt_util
    _make_module("homeassistant.util", dt=_dt_util)
    _make_module("aiohttp")

    # voluptuous stub — only the parts config_flow uses
    class _Range:
        def __init__(self, **kw):
            pass

        def __call__(self, v):
            return v

    class _Length:
        def __init__(self, **kw):
            pass

        def __call__(self, v):
            return v

    class _All:
        def __init__(self, *validators):
            self._v = validators

        def __call__(self, v):
            for fn in self._v:
                v = fn(v)
            return v

    class _In:
        def __init__(self, container):
            self._c = container

        def __call__(self, v):
            if v not in self._c:
                raise ValueError(f"{v!r} not in {self._c}")
            return v

    class _Schema:
        def __init__(self, schema):
            self._schema = schema

        def __call__(self, data):
            return data

    class _Required:
        def __init__(self, key):
            self.key = key

        def __hash__(self):
            return hash(self.key)

        def __eq__(self, other):
            return self.key == other

    class _Optional:
        def __init__(self, key, default=None, **kwargs):
            self.key = key
            self.default = default

        def __hash__(self):
            return hash(self.key)

        def __eq__(self, other):
            return self.key == other

    class _Coerce:
        def __init__(self, typ):
            self._t = typ

        def __call__(self, v):
            return self._t(v)

    class _Invalid(Exception):
        pass

    vol = types.ModuleType("voluptuous")
    vol.Schema = _Schema
    vol.Required = _Required
    vol.Optional = _Optional
    vol.All = _All
    vol.Range = _Range
    vol.Length = _Length
    vol.In = _In
    vol.Coerce = _Coerce
    vol.Invalid = _Invalid
    sys.modules["voluptuous"] = vol


_stub_homeassistant()

# Add component root to path so "from .coordinator import ..." resolves
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_consos():
    """12 months of monthly consumption entries."""
    return [{"annee": 2024, "mois_index": i, "label": f"Mois {i}", "consommation_m3": 10.0 + i} for i in range(12)]


@pytest.fixture
def sample_daily():
    """30 daily consumption entries."""
    import datetime

    base = datetime.date(2024, 3, 1)
    return [
        {
            "date": (base + datetime.timedelta(days=i)).isoformat(),
            "consommation_m3": 0.3 + i * 0.01,
        }
        for i in range(30)
    ]
