"""Cohérence entre les entités déclarées dans le code et leurs traductions."""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
from pathlib import Path

import custom_components.eau_grand_lyon.sensors as sensors_pkg

_ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "eau_grand_lyon"
_TRANSLATION_FILES = ("strings.json", "translations/fr.json", "translations/en.json")


def _enum_sensor_classes() -> list[type]:
    classes: dict[str, type] = {}
    for module_info in pkgutil.iter_modules(sensors_pkg.__path__, f"{sensors_pkg.__name__}."):
        module = importlib.import_module(module_info.name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            options = cls.__dict__.get("_attr_options")
            if isinstance(options, list) and cls.__dict__.get("_attr_translation_key"):
                classes[f"{cls.__module__}.{cls.__qualname__}"] = cls
    return list(classes.values())


def test_enum_sensors_are_discovered() -> None:
    names = {cls.__name__ for cls in _enum_sensor_classes()}
    assert "EauGrandLyonVigieauSensor" in names
    assert "EauGrandLyonDroughtSensor" in names


def test_every_enum_state_is_translated() -> None:
    """Régression : les niveaux VigiEau (`alerte_renforcee`…) s'affichaient en valeur brute."""
    for name in _TRANSLATION_FILES:
        entity_sensors = json.loads((_ROOT / name).read_text(encoding="utf-8"))["entity"]["sensor"]
        for cls in _enum_sensor_classes():
            key = cls.__dict__["_attr_translation_key"]
            states = entity_sensors.get(key, {}).get("state", {})
            missing = [option for option in cls.__dict__["_attr_options"] if not states.get(option)]
            assert not missing, f"{name}: états non traduits pour {key!r}: {missing}"
