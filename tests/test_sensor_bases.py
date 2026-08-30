"""Behavior tests for shared sensor base classes."""

from unittest.mock import MagicMock

import pytest

from custom_components.eau_grand_lyon.sensors.base import _EauGrandLyonBase, _EauGrandLyonWaterQualityBase


def test_contract_base_supports_description_empty_data_year_and_device_info():
    coordinator = MagicMock(data=None)
    entry = MagicMock(entry_id="entry-1")
    description = MagicMock(key="described")
    entity = _EauGrandLyonBase(coordinator, entry, "REF1", description)

    assert entity._attr_unique_id == "entry-1_REF1_described"
    assert entity._contract == {}
    assert entity._current_year_str.endswith("-01-01")
    assert entity.device_info is not None


def test_abstract_water_quality_value_is_explicitly_unimplemented():
    entity = _EauGrandLyonWaterQualityBase(MagicMock(data={}), MagicMock(entry_id="entry-1"))
    with pytest.raises(NotImplementedError):
        entity._quality_value({})
