"""Fixtures des tests d'intégration sur un vrai Home Assistant.

Contrairement à `tests/`, aucun module Home Assistant n'est simulé ici : seules
les réponses réseau du portail Eau du Grand Lyon et des sources publiques sont
remplacées par des données fixes. Ces tests nécessitent
`pytest-homeassistant-custom-component` et se lancent avec `pytest tests_ha`.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eau_grand_lyon.api.client import EauGrandLyonApi
from custom_components.eau_grand_lyon.const import (
    CONF_EMAIL,
    CONF_EXPERIMENTAL,
    CONF_PASSWORD,
    CONF_PFAS_ENABLED,
    CONF_VIGIEAU_ENABLED,
    CONF_WATER_QUALITY_COMMUNE,
    DOMAIN,
)
from custom_components.eau_grand_lyon.hubeau import empty_water_quality
from custom_components.eau_grand_lyon.pfas import empty_pfas_data
from custom_components.eau_grand_lyon.vigieau import empty_vigieau_data

# Date figée des tests : 12 octobre 2026, 12 h à Lyon.
NOW = "2026-10-12 10:00:00+00:00"
CONTRACT_REF = "AB1234567890"

RAW_CONTRACT: dict[str, Any] = {
    "id": "C1",
    "reference": CONTRACT_REF,
    "statutExtrait": {"libelle": "Actif"},
    "dateEffet": "2020-01-01T00:00:00",
    "dateEcheance": "2027-01-01T00:00:00",
    "conditionPaiement": {
        "compteClient": {"solde": {"value": 0}},
        "mensualise": False,
        "modePaiement": {"libelle": "Prélèvement"},
    },
    "servicesSouscrits": [
        {
            "calibreCompteur": {"libelle": "15"},
            "usage": {"libelle": "Domestique"},
            "nombreHabitants": {"libelle": "2 personnes"},
        }
    ],
    "espaceDeLivraison": {"reference": "PDS1"},
    "pointDeReleve": {"moduleRadio": {"niveauSignal": 80, "etatPile": "OK"}},
}

# Treize relevés mensuels (mois base 0) jusqu'à septembre 2026 inclus.
RAW_MONTHLY: list[dict[str, Any]] = [{"annee": 2025, "mois": m, "consommation": 7.0} for m in range(8, 12)] + [
    {"annee": 2026, "mois": m, "consommation": 6.0} for m in range(0, 9)
]


def raw_daily() -> list[dict[str, Any]]:
    """Relevés Téléo du 1er au 12 octobre ; le 12 n'a pas encore d'index publié."""
    days: list[dict[str, Any]] = [
        {"date": f"2026-10-{day:02d}", "consommation": 0.2, "index": round(1000 + 0.2 * day, 3)} for day in range(1, 12)
    ]
    days.append({"date": "2026-10-12", "consommation": 0.05, "index": None})
    return days


def daily_response(raw: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    entries = EauGrandLyonApi.format_daily_consumptions(raw if raw is not None else raw_daily(), "C1")
    return {"entries": entries, "source": "test", "nb_entries": len(entries), "last_date": entries[-1]["date"]}


RAW_INVOICES: list[dict[str, Any]] = [
    {
        "id": "F1",
        "reference": "FAC1",
        "dateEdition": "2026-09-15",
        "montantTTC": 120.5,
        "montantHT": 100.0,
        "consommationTotale": {"value": 30, "unit": "m3"},
        "contrat": {"id": "C1"},
        "telechargeable": True,
    }
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    """Autorise le chargement de custom_components/eau_grand_lyon."""
    yield


@pytest.fixture
def mock_api() -> Generator[dict[str, AsyncMock]]:
    """Remplace les appels réseau ; les parseurs et le coordinator restent réels."""
    water_quality = {**empty_water_quality(), "commune": "Lyon", "durete_fh": 30.0, "nitrates_mgl": 10.0}
    pfas = {**empty_pfas_data(), "mean_ug_l": 0.01, "maximum_ug_l": 0.02, "conform": True}
    vigieau = {
        **empty_vigieau_data(),
        "commune": "Lyon",
        "commune_code": "69123",
        "level": "crise",
        "decree_end_date": "2026-10-31",
        "decree_url": "https://example.invalid/arrete.pdf",
    }
    mocks: dict[str, AsyncMock] = {
        "get_contracts": AsyncMock(return_value=[RAW_CONTRACT]),
        "get_alertes": AsyncMock(return_value=[]),
        "get_factures": AsyncMock(return_value=RAW_INVOICES),
        "get_interventions": AsyncMock(return_value=[]),
        "get_monthly_consumptions": AsyncMock(return_value=RAW_MONTHLY),
        "get_daily_consumptions": AsyncMock(side_effect=lambda *args, **kwargs: daily_response()),
        "get_date_prochaine_facture": AsyncMock(return_value="2027-03-15"),
        "get_point_de_service_etendu": AsyncMock(
            return_value={"date_prochaine_releve": "2027-01-10", "conso_annuelle_ref_m3": 75.0}
        ),
        "get_alerte_surconsommation": AsyncMock(
            return_value={"seuil_surconso_jour_m3": 1.0, "seuil_surconso_mois_m3": 20.0, "abonne_alerte_fuite": True}
        ),
        "get_courbe_de_charge": AsyncMock(
            return_value=[
                {"date": f"2026-10-11T{h:02d}:00:00", "valeur": 0.01 if 7 <= h <= 22 else 0} for h in range(24)
            ]
        ),
        "get_derniere_releve_siamm": AsyncMock(return_value=None),
        "async_revoke_token": AsyncMock(return_value=None),
    }
    with (
        patch.multiple(EauGrandLyonApi, **mocks),
        patch(
            "custom_components.eau_grand_lyon.hubeau.HubeauWaterQualityClient.async_get_water_quality",
            AsyncMock(return_value=water_quality),
        ),
        patch("custom_components.eau_grand_lyon.pfas.PfasClient.async_get", AsyncMock(return_value=pfas)),
        patch("custom_components.eau_grand_lyon.vigieau.VigieauClient.async_get", AsyncMock(return_value=vigieau)),
        patch("custom_components.eau_grand_lyon.coordinator.RATE_LIMIT_DELAY_S", 0.0),
    ):
        yield mocks


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Entrée telle que créée par le flux de configuration (toutes sources activées)."""
    return MockConfigEntry(
        domain=DOMAIN,
        version=4,
        unique_id="test@example.com",
        title="Eau du Grand Lyon (test@example.com)",
        data={CONF_EMAIL: "test@example.com", CONF_PASSWORD: "secret"},
        options={
            CONF_EXPERIMENTAL: True,
            CONF_WATER_QUALITY_COMMUNE: "Lyon",
            CONF_PFAS_ENABLED: True,
            CONF_VIGIEAU_ENABLED: True,
        },
    )
