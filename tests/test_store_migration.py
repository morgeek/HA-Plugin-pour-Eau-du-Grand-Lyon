"""Régression : le cache persistant ne doit pas planter le setup sur montée de version.

Avant le fix, `Store(hass, 2, ...)` sans fonction de migration levait
NotImplementedError au chargement d'un fichier `.storage` en version 1
(installations antérieures) — crash de `async_setup_entry`.

`_RebuildableStore` migre en repartant d'un cache vide (reconstruit depuis l'API).
"""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.eau_grand_lyon.coordinator import _RebuildableStore


async def test_migrate_resets_to_empty_dict():
    # Appel de la coroutine non liée avec un faux `self` (seul `self.key` est utilisé),
    # car le Store est stubbé (MagicMock) et non instanciable dans l'environnement de test.
    migrate = _RebuildableStore.__dict__["_async_migrate_func"]
    fake_self = SimpleNamespace(key="eau_grand_lyon_test_monthly_history")
    result = await migrate(fake_self, 1, 0, {"REF1": [{"mois_index": 0}]})
    assert result == {}
