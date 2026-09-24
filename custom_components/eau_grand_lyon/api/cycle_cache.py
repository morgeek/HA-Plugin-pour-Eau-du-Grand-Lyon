"""Façade de l'API mise en cache pour la durée d'un cycle de mise à jour."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from ..models import OutageData
from .client import EauGrandLyonApi


class CycleCachedApi:
    """Per-update-cycle cached facade around EauGrandLyonApi.

    Le cache (un dict de tasks) vit dans l'instance et meurt avec elle à la fin
    du cycle. Un décorateur de cache au niveau classe (ex. alru_cache) garderait
    une référence sur chaque instance et accumulerait les réponses API de tous
    les cycles précédents. Les appels concurrents sur la même clé partagent la
    même task (un seul appel API par clé et par cycle).
    """

    def __init__(self, api: EauGrandLyonApi) -> None:
        self._api = api
        self._tasks: dict[tuple[object, ...], asyncio.Task[Any]] = {}

    def _cached(self, method: str, *args: object, **kwargs: object) -> asyncio.Task[Any]:
        key = (method, args, tuple(sorted(kwargs.items())))
        if key not in self._tasks:
            self._tasks[key] = asyncio.ensure_future(getattr(self._api, method)(*args, **kwargs))
        return self._tasks[key]

    async def aclose(self) -> None:
        """Annule les tasks encore en vol à la fin du cycle (chemins d'erreur).

        Évite les requêtes fantômes et les avertissements « Task exception was
        never retrieved » quand le cycle se termine sur une exception.
        """
        pending = [t for t in self._tasks.values() if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def get_contracts(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._cached("get_contracts"))

    async def get_alertes(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._cached("get_alertes"))

    async def get_interventions(self) -> list[OutageData]:
        return cast(list[OutageData], await self._cached("get_interventions"))

    async def get_factures(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self._cached("get_factures"))

    async def get_monthly_consumptions(self, contract_id: str) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            await self._cached("get_monthly_consumptions", contract_id),
        )

    async def get_daily_consumptions(self, contract_id: str, nb_jours: int = 90) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._cached("get_daily_consumptions", contract_id, nb_jours=nb_jours),
        )

    async def get_alerte_surconsommation(self, contract_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._cached("get_alerte_surconsommation", contract_id),
        )

    async def get_date_prochaine_facture(self, contract_id: str) -> str | None:
        return cast(str | None, await self._cached("get_date_prochaine_facture", contract_id))

    async def get_point_de_service_etendu(self, contract_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await self._cached("get_point_de_service_etendu", contract_id),
        )

    async def get_courbe_de_charge(self, contract_id: str, nb_jours: int = 7) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            await self._cached("get_courbe_de_charge", contract_id, nb_jours=nb_jours),
        )

    async def get_derniere_releve_siamm(self, contract_id: str) -> dict[str, Any] | None:
        return cast(
            dict[str, Any] | None,
            await self._cached("get_derniere_releve_siamm", contract_id),
        )
