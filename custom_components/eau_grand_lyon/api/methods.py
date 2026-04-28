"""Helper methods extracted from api/client.py for better organization.

Keeps api/client.py focused on HTTP orchestration while data-fetching logic
is modularized for clarity.
"""
from __future__ import annotations

from typing import Any


async def fetch_contracts(
    api_client,
    contract_ids: list[str] | None = None,
) -> list[dict]:
    """Fetch all contracts or specific contract IDs.

    Returns list of contract dicts with metadata.
    """
    data = await api_client._get("pointsServiceAndCompteurs")
    contracts = data.get("listeCompteurs", [])
    if contract_ids:
        contracts = [c for c in contracts if c.get("pds_reference") in contract_ids]
    return contracts


async def fetch_monthly_consumptions(
    api_client,
    contract_id: str,
) -> dict[str, Any]:
    """Fetch monthly consumption history for a contract.

    Returns dict with 'consommations' list and metadata.
    """
    params = {"idPdl": contract_id, "listeIndexGEd": []}
    data = await api_client._get_interfaces("historiqueConso", params)
    return data or {}


async def fetch_daily_consumptions(
    api_client,
    contract_id: str,
    nb_jours: int = 400,
) -> dict[str, Any]:
    """Fetch daily consumption data (if available).

    Returns dict with daily consumption list or empty dict if unavailable.
    """
    raw = await api_client._fetch_daily_raw(contract_id, nb_jours)
    if not raw:
        return {}
    return {"consommations_journalieres": await api_client._get_daily_new(contract_id, nb_jours)}


async def fetch_invoices(
    api_client,
    contract_id: str,
) -> list[dict]:
    """Fetch invoices for a contract (experimental API only).

    Returns list of invoice dicts with dates and references.
    """
    if not api_client.experimental:
        return []
    try:
        data = await api_client._get_produits(f"factures/{contract_id}")
        return data.get("factures", []) if data else []
    except (KeyError, TypeError, ValueError):
        return []


async def fetch_load_curves(
    api_client,
    contract_id: str,
) -> dict[str, Any]:
    """Fetch hourly load curves (experimental API, Téléo only).

    Returns dict with hourly consumption data or empty dict if unavailable.
    """
    if not api_client.experimental:
        return {}
    try:
        data = await api_client._get_produits(f"courbesDeCharge/{contract_id}")
        return {"courbe_de_charge": data.get("courbes", [])} if data else {}
    except (KeyError, TypeError, ValueError):
        return {}


async def fetch_leak_estimates(
    api_client,
    contract_id: str,
) -> dict[str, Any]:
    """Fetch estimated leak volumes (experimental API only).

    Returns dict with 30-day leak estimate.
    """
    if not api_client.experimental:
        return {}
    try:
        data = await api_client._get_produits(f"fuites/{contract_id}")
        if data and "fuite_estime_30j_m3" in data:
            return {"fuite_estime_30j_m3": data["fuite_estime_30j_m3"]}
    except (KeyError, TypeError, ValueError):
        pass
    return {}
