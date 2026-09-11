"""Client isolé pour les données PFAS du site public Eau du Grand Lyon."""

from __future__ import annotations

import json
import logging
import time
from html.parser import HTMLParser
from typing import Any, TypedDict

import aiohttp

_LOGGER = logging.getLogger(__name__)

_AUTOCOMPLETE_URL = "https://www.eaudugrandlyon.com/wp-admin/admin-ajax.php"
_QUALITY_PAGE_URL = "https://www.eaudugrandlyon.com/mon-eau/eau-chez-moi/qualite-de-mon-eau/"
_CACHE_SECONDS = 24 * 60 * 60


class PfasData(TypedDict):
    """Données PFAS publiques normalisées."""

    commune: str | None
    conform: bool | None
    maximum_ug_l: float | None
    mean_ug_l: float | None
    samples_12_months: int | None
    source: str
    threshold_ug_l: float


def empty_pfas_data() -> PfasData:
    return {
        "commune": None,
        "conform": None,
        "maximum_ug_l": None,
        "mean_ug_l": None,
        "samples_12_months": None,
        "source": "Site public Eau du Grand Lyon",
        "threshold_ug_l": 0.1,
    }


class _QualityValueParser(HTMLParser):
    """Extrait les couples valeur/libellé des cartes qualité rendues côté serveur."""

    def __init__(self) -> None:
        super().__init__()
        self.pairs: list[tuple[str, str]] = []
        self._depth = 0
        self._capture: str | None = None
        self._value: list[str] = []
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = dict(attrs).get("class", "") or ""
        if tag == "div" and "qualiteAnalyse__text" in classes.split():
            self._depth = 1
            self._value = []
            self._label = []
            return
        if self._depth:
            if tag == "div":
                self._depth += 1
            elif tag in {"b", "p"}:
                self._capture = tag

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if tag in {"b", "p"}:
            self._capture = None
        if tag == "div":
            self._depth -= 1
            if self._depth == 0:
                self.pairs.append((" ".join(self._value).strip(), " ".join(self._label).strip()))

    def handle_data(self, data: str) -> None:
        if self._capture == "b":
            self._value.append(data.strip())
        elif self._capture == "p":
            self._label.append(data.strip())


def parse_pfas_html(html: str, commune: str) -> PfasData:
    """Parse le HTML confirmé sans dépendance tierce et sans supposer son ordre."""
    parser = _QualityValueParser()
    parser.feed(html)
    values = {label.casefold(): value for value, label in parser.pairs if value and label}

    def _number(label_fragment: str) -> float | None:
        raw = next((value for label, value in values.items() if label_fragment in label), None)
        if raw is None:
            return None
        try:
            return float(raw.replace("\u202f", "").replace(" ", "").replace(",", "."))
        except ValueError:
            return None

    mean = _number("valeur moyenne des pfas")
    maximum = _number("valeur max des pfas")
    samples_raw = _number("nombre de prélèvements sur les 12 derniers mois")
    if mean is None or maximum is None:
        return empty_pfas_data()
    return {
        "commune": commune,
        "conform": maximum <= 0.1,
        "maximum_ug_l": maximum,
        "mean_ug_l": mean,
        "samples_12_months": int(samples_raw) if samples_raw is not None else None,
        "source": "Site public Eau du Grand Lyon",
        "threshold_ug_l": 0.1,
    }


class PfasClient:
    """Résout une commune puis lit au maximum une fois par jour la page publique."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._cache: dict[str, tuple[float, PfasData]] = {}

    async def async_get(self, commune: str) -> PfasData:
        key = commune.strip().casefold()
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < _CACHE_SECONDS:
            return cached[1]

        def remember(result: PfasData) -> PfasData:
            self._cache[key] = (now, result)
            return result

        try:
            async with self._session.get(
                _AUTOCOMPLETE_URL,
                params={"action": "nc_autocomplete_communes", "query": commune},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    return remember(empty_pfas_data())
                payload: Any = json.loads(await response.text())
            candidates = payload.get("data", []) if isinstance(payload, dict) and payload.get("success") else []
            selected = next(
                (
                    item
                    for item in candidates
                    if isinstance(item, dict) and str(item.get("name") or "").strip().casefold() == key
                ),
                (candidates[0] if len(candidates) == 1 and isinstance(candidates[0], dict) else None),
            )
            if not selected or not selected.get("name") or not selected.get("code_postal"):
                return remember(empty_pfas_data())
            async with self._session.get(
                _QUALITY_PAGE_URL,
                params={
                    "ville": selected["name"],
                    "code_postal": selected["code_postal"],
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    return remember(empty_pfas_data())
                result = parse_pfas_html(await response.text(), str(selected["name"]))
        # Cette source optionnelle ne doit jamais interrompre la mise à jour principale.
        except Exception as err:
            _LOGGER.debug("[PFAS] Source publique indisponible: %s", err)
            result = empty_pfas_data()
        return remember(result)
