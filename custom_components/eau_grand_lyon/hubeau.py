"""Public Hub'Eau client for regulatory drinking-water quality data."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import math
import time
import unicodedata
from typing import TypedDict, cast

import aiohttp

from .models import WaterQualityData

HUBEAU_BASE_URL = "https://hubeau.eaufrance.fr/api/v1/qualite_eau_potable"
HUBEAU_COMMUNES_UDI_URL = f"{HUBEAU_BASE_URL}/communes_udi"
HUBEAU_RESULTATS_DIS_URL = f"{HUBEAU_BASE_URL}/resultats_dis"
HUBEAU_SOURCE = "Hub'Eau / Ministère chargé de la Santé"

# SANDRE 1345: Titre hydrotimétrique (dureté totale), unité 28 (°f).
HUBEAU_PARAM_HARDNESS = "1345"
# SANDRE 1340: Nitrates (en NO3), unité 162 (mg/L).
HUBEAU_PARAM_NITRATES = "1340"
# SANDRE 1398: Chlore libre, unité 165 (mg(Cl2)/L).
HUBEAU_PARAM_CHLORINE = "1398"
# SANDRE 1295: Turbidité néphélométrique NFU, unité 232 (NFU).
# The historical public key remains ``turbidite_ntu`` for compatibility.
HUBEAU_PARAM_TURBIDITY = "1295"

SUCCESS_CACHE_SECONDS = 24 * 60 * 60
FAILURE_CACHE_SECONDS = 15 * 60
REQUEST_TIMEOUT_SECONDS = 10
RESULT_WINDOW_DAYS = 730
RESULT_PAGE_SIZE = 20

_RESULT_FIELDS = ",".join(
    (
        "code_commune",
        "nom_commune",
        "code_prelevement",
        "date_prelevement",
        "code_parametre",
        "libelle_parametre",
        "resultat_numerique",
        "code_unite",
        "libelle_unite",
        "code_installation_amont",
        "nom_installation_amont",
        "reseaux",
    )
)

_LOGGER = logging.getLogger(__name__)


class HubeauUdi(TypedDict):
    """Normalized distribution network linked to a municipality."""

    code: str
    name: str | None


class HubeauCommune(TypedDict):
    """Unambiguous municipality resolution returned by communes_udi."""

    code: str
    name: str
    networks: list[HubeauUdi]


@dataclass(frozen=True, slots=True)
class _ParameterSpec:
    key: str
    unit_code: str
    unit_labels: frozenset[str]


@dataclass(frozen=True, slots=True)
class _Measurement:
    value: float
    sampled_at: datetime
    row: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    data: WaterQualityData
    expires_at: float


_PARAMETERS: dict[str, _ParameterSpec] = {
    HUBEAU_PARAM_HARDNESS: _ParameterSpec("durete_fh", "28", frozenset({"°f", "degre francais"})),
    HUBEAU_PARAM_NITRATES: _ParameterSpec("nitrates_mgl", "162", frozenset({"mg/l"})),
    HUBEAU_PARAM_CHLORINE: _ParameterSpec("chlore_mgl", "165", frozenset({"mg(cl2)/l"})),
    HUBEAU_PARAM_TURBIDITY: _ParameterSpec("turbidite_ntu", "232", frozenset({"nfu"})),
}


class _HubeauResponseError(Exception):
    """Internal marker for a temporary HTTP or payload failure."""


def empty_water_quality() -> WaterQualityData:
    """Return the stable public schema with unavailable measurements."""
    return {
        "durete_fh": None,
        "nitrates_mgl": None,
        "chlore_mgl": None,
        "turbidite_ntu": None,
        "commune": None,
        "date_analyse": None,
        "source": HUBEAU_SOURCE,
        "unite_turbidite": None,
        "code_commune": None,
        "code_reseau": None,
        "nom_reseau": None,
    }


def _normalized_name(value: str) -> str:
    """Normalize a municipality name without turning partial matches into exact ones."""
    decomposed = unicodedata.normalize("NFKD", value.strip().casefold())
    ascii_name = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(ascii_name.replace("-", " ").split())


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _parse_datetime(value: object) -> datetime | None:
    raw = _text(value)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _valid_unit(row: Mapping[str, object], spec: _ParameterSpec) -> bool:
    code = _text(row.get("code_unite"))
    if code is not None:
        return code == spec.unit_code
    label = _text(row.get("libelle_unite"))
    return label is not None and _normalized_name(label) in spec.unit_labels


def _latest_measurement(
    rows: list[Mapping[str, object]],
    *,
    commune_code: str,
    parameter_code: str,
) -> _Measurement | None:
    """Select the latest valid row; stable IDs break same-timestamp ties."""
    spec = _PARAMETERS[parameter_code]
    candidates: list[tuple[tuple[datetime, str, str], _Measurement]] = []
    for row in rows:
        if _text(row.get("code_commune")) != commune_code:
            continue
        if _text(row.get("code_parametre")) != parameter_code:
            continue
        sampled_at = _parse_datetime(row.get("date_prelevement"))
        value = _numeric(row.get("resultat_numerique"))
        if sampled_at is None or value is None or not _valid_unit(row, spec):
            continue
        tie_break = (
            sampled_at,
            _text(row.get("code_prelevement")) or "",
            _text(row.get("code_installation_amont")) or "",
        )
        candidates.append((tie_break, _Measurement(value, sampled_at, row)))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


class HubeauWaterQualityClient:
    """Fetch and normalize public drinking-water analyses from Hub'Eau."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._cache: dict[str, _CacheEntry] = {}

    async def async_get_water_quality(self, commune: str | None) -> WaterQualityData:
        """Return quality data for one exact municipality, never an arbitrary row."""
        if commune is None or not commune.strip():
            return empty_water_quality()

        cache_key = _normalized_name(commune)
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached is not None and cached.expires_at > now:
            return cast(WaterQualityData, dict(cached.data))

        ttl = SUCCESS_CACHE_SECONDS
        try:
            resolved = await self._resolve_commune(commune)
            if resolved is None:
                result = empty_water_quality()
            else:
                result = await self._fetch_measurements(resolved)
        except (
            _HubeauResponseError,
            aiohttp.ClientError,
            asyncio.TimeoutError,
            TimeoutError,
        ) as err:
            _LOGGER.debug("Hub'Eau water-quality request failed: %s", err)
            result = empty_water_quality()
            ttl = FAILURE_CACHE_SECONDS

        self._cache[cache_key] = _CacheEntry(result, now + ttl)
        return cast(WaterQualityData, dict(result))

    async def _request_rows(self, url: str, params: Mapping[str, str]) -> list[Mapping[str, object]]:
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
        async with self._session.get(
            url,
            params=params,
            headers={"Accept": "application/json"},
            timeout=timeout,
        ) as response:
            if response.status not in (200, 206):
                raise _HubeauResponseError(f"HTTP {response.status}")
            body = await response.text()
        try:
            payload = cast(object, json.loads(body))
        except (json.JSONDecodeError, TypeError, ValueError) as err:
            raise _HubeauResponseError("invalid JSON") from err
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise _HubeauResponseError("invalid data payload")
        rows: list[Mapping[str, object]] = []
        for item in payload["data"]:
            if isinstance(item, dict):
                rows.append(cast(dict[str, object], item))
        return rows

    async def _resolve_commune(self, commune: str) -> HubeauCommune | None:
        # Hub'Eau tokenizes hyphenated names as broad OR searches. Replacing
        # separators with spaces keeps searches such as SAINT-PRIEST bounded
        # enough for the exact-name check below to find the current-year row.
        search_name = " ".join(commune.strip().replace("-", " ").split())
        rows = await self._request_rows(
            HUBEAU_COMMUNES_UDI_URL,
            {
                "nom_commune": search_name,
                "fields": "code_commune,nom_commune,code_reseau,nom_reseau,annee",
                "size": "100",
                "sort": "desc",
            },
        )
        wanted = _normalized_name(commune)
        exact = [
            row
            for row in rows
            if (_text(row.get("code_commune")) or "").startswith("69")
            and (name := _text(row.get("nom_commune"))) is not None
            and _normalized_name(name) == wanted
        ]
        commune_codes = {_text(row.get("code_commune")) for row in exact}
        commune_codes.discard(None)
        if len(commune_codes) != 1:
            _LOGGER.debug("Hub'Eau municipality is unknown or ambiguous: %s", commune)
            return None

        code = cast(str, next(iter(commune_codes)))
        code_rows = [row for row in exact if _text(row.get("code_commune")) == code]
        years = [int(year) for row in code_rows if (year := _text(row.get("annee"))) and year.isdigit()]
        if years:
            latest_year = max(years)
            code_rows = [row for row in code_rows if _text(row.get("annee")) == str(latest_year)]

        networks_by_code: dict[str, HubeauUdi] = {}
        for row in code_rows:
            network_code = _text(row.get("code_reseau"))
            if network_code is not None:
                networks_by_code[network_code] = {
                    "code": network_code,
                    "name": _text(row.get("nom_reseau")),
                }
        if not networks_by_code:
            return None
        resolved_name = _text(code_rows[0].get("nom_commune")) or commune.strip()
        return {
            "code": code,
            "name": resolved_name,
            "networks": [networks_by_code[key] for key in sorted(networks_by_code)],
        }

    async def _fetch_measurements(self, commune: HubeauCommune) -> WaterQualityData:
        date_min = (datetime.now(timezone.utc) - timedelta(days=RESULT_WINDOW_DAYS)).date().isoformat()
        network_codes = ",".join(network["code"] for network in commune["networks"])

        async def _for_parameter(parameter_code: str) -> tuple[str, list[Mapping[str, object]]]:
            rows = await self._request_rows(
                HUBEAU_RESULTATS_DIS_URL,
                {
                    "code_commune": commune["code"],
                    "code_reseau": network_codes,
                    "code_parametre": parameter_code,
                    "date_min_prelevement": date_min,
                    "fields": _RESULT_FIELDS,
                    "size": str(RESULT_PAGE_SIZE),
                    "sort": "desc",
                },
            )
            return parameter_code, rows

        responses = await asyncio.gather(*(_for_parameter(code) for code in _PARAMETERS))
        selected: dict[str, _Measurement] = {}
        for parameter_code, rows in responses:
            measurement = _latest_measurement(
                rows,
                commune_code=commune["code"],
                parameter_code=parameter_code,
            )
            if measurement is not None:
                selected[parameter_code] = measurement

        result = empty_water_quality()
        result["commune"] = commune["name"]
        result["code_commune"] = commune["code"]
        if measurement := selected.get(HUBEAU_PARAM_HARDNESS):
            result["durete_fh"] = measurement.value
        if measurement := selected.get(HUBEAU_PARAM_NITRATES):
            result["nitrates_mgl"] = measurement.value
        if measurement := selected.get(HUBEAU_PARAM_CHLORINE):
            result["chlore_mgl"] = measurement.value
        if measurement := selected.get(HUBEAU_PARAM_TURBIDITY):
            result["turbidite_ntu"] = measurement.value
            result["unite_turbidite"] = "NFU"

        if not selected:
            return result

        newest_code, newest = max(
            selected.items(),
            key=lambda item: (item[1].sampled_at, item[0]),
        )
        del newest_code
        result["date_analyse"] = newest.sampled_at.date().isoformat()
        network = self._network_for_row(newest.row, commune["networks"])
        if network is not None:
            result["code_reseau"] = network["code"]
            result["nom_reseau"] = network["name"]
        return result

    @staticmethod
    def _network_for_row(row: Mapping[str, object], networks: list[HubeauUdi]) -> HubeauUdi | None:
        """Return network metadata only when the selected row identifies it uniquely."""
        by_code = {network["code"]: network for network in networks}
        upstream = _text(row.get("code_installation_amont"))
        if upstream in by_code:
            return by_code[upstream]

        raw_networks = row.get("reseaux")
        if not isinstance(raw_networks, list):
            return None
        matching_codes: set[str] = set()
        for raw_network in raw_networks:
            if not isinstance(raw_network, dict):
                continue
            network_code = _text(raw_network.get("code"))
            if network_code in by_code:
                matching_codes.add(network_code)
        if len(matching_codes) != 1:
            return None
        return by_code[next(iter(matching_codes))]
