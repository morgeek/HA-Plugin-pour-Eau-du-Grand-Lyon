"""Client isolé pour l'API publique officielle VigiEau."""

from __future__ import annotations

import json
import logging
import time
import unicodedata
from typing import Any, TypedDict

import aiohttp

_LOGGER = logging.getLogger(__name__)
_GEO_URL = "https://geo.api.gouv.fr/communes"
_VIGIEAU_URL = "https://api.vigieau.gouv.fr/api/zones"
_CACHE_SECONDS = 24 * 60 * 60
_LEVEL_PRIORITY = {
    "normal": 0,
    "vigilance": 1,
    "alerte": 2,
    "alerte_renforcee": 3,
    "crise": 4,
}


class VigieauData(TypedDict):
    """Niveau officiel applicable à l'eau potable d'une commune."""

    commune: str | None
    commune_code: str | None
    decree_end_date: str | None
    decree_start_date: str | None
    decree_url: str | None
    level: str | None
    source: str
    zone_name: str | None


def empty_vigieau_data() -> VigieauData:
    return {
        "commune": None,
        "commune_code": None,
        "decree_end_date": None,
        "decree_start_date": None,
        "decree_url": None,
        "level": None,
        "source": "VigiEau",
        "zone_name": None,
    }


def _normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    return "".join(char for char in text if not unicodedata.combining(char))


class VigieauClient:
    """Résout le code INSEE et interroge VigiEau au maximum une fois par jour."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._cache: dict[str, tuple[float, VigieauData]] = {}

    async def async_get(self, commune: str) -> VigieauData:
        key = _normalized(commune)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < _CACHE_SECONDS:
            return cached[1]

        def remember(result: VigieauData) -> VigieauData:
            self._cache[key] = (now, result)
            return result

        try:
            async with self._session.get(
                _GEO_URL,
                params={
                    "nom": commune,
                    "fields": "nom,code,codesPostaux",
                    "boost": "population",
                    "limit": 10,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    return remember(empty_vigieau_data())
                candidates: Any = json.loads(await response.text())
            if not isinstance(candidates, list):
                return remember(empty_vigieau_data())
            selected = next(
                (
                    item
                    for item in candidates
                    if isinstance(item, dict) and _normalized(item.get("nom")) == key and item.get("code")
                ),
                (candidates[0] if len(candidates) == 1 and isinstance(candidates[0], dict) else None),
            )
            if not selected or not selected.get("code"):
                return remember(empty_vigieau_data())
            async with self._session.get(
                _VIGIEAU_URL,
                params={
                    "commune": selected["code"],
                    "profil": "particulier",
                    "zoneType": "AEP",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    return remember(empty_vigieau_data())
                zones: Any = json.loads(await response.text())
            valid_zones = (
                [
                    zone
                    for zone in zones
                    if isinstance(zone, dict) and str(zone.get("niveauGravite") or "").casefold() in _LEVEL_PRIORITY
                ]
                if isinstance(zones, list)
                else []
            )
            if not valid_zones:
                return remember(empty_vigieau_data())
            zone = max(
                valid_zones,
                key=lambda item: _LEVEL_PRIORITY[str(item["niveauGravite"]).casefold()],
            )
            raw_decree = zone.get("arrete")
            decree: dict[str, Any] = raw_decree if isinstance(raw_decree, dict) else {}
            result: VigieauData = {
                "commune": str(selected.get("nom") or commune),
                "commune_code": str(selected["code"]),
                "decree_end_date": str(decree.get("dateFinValidite") or "")[:10] or None,
                "decree_start_date": str(decree.get("dateDebutValidite") or "")[:10] or None,
                "decree_url": decree.get("cheminFichier"),
                "level": str(zone.get("niveauGravite") or "").casefold() or None,
                "source": "VigiEau",
                "zone_name": zone.get("nom"),
            }
        # Cette source optionnelle ne doit jamais interrompre la mise à jour principale.
        except Exception as err:
            _LOGGER.debug("[VIGIEAU] Source publique indisponible: %s", err)
            result = empty_vigieau_data()
        return remember(result)
