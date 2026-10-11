"""Extraction des interruptions de service depuis les alertes Eau du Grand Lyon."""

from __future__ import annotations

from typing import Any

from .models import OutageData

_OUTAGE_KEYWORDS = ("TRAVAUX", "COUPURE", "INTERRUPT", "MAINTENANCE")


def parse_outage_alertes(alertes: list[dict[str, Any]]) -> list[OutageData]:
    """Extrait les interruptions de service (travaux, coupures) depuis la liste d'alertes.

    Filtre les alertes de type travaux/coupure et les normalise pour le calendrier
    et le binary_sensor. Retourne une liste triée par date de début (la plus proche en tête).
    """
    interruptions: list[OutageData] = []

    for alerte in alertes:
        try:
            info = alerte.get("infosAlarme") or alerte
            modele = alerte.get("modeleAction") or {}
            type_alerte = ((info.get("type") or {}).get("libelle", "") or str(info.get("typeCode", ""))).upper()
            libelle_modele = str(modele.get("libelle", "")).upper()

            if not any(k in (type_alerte + " " + libelle_modele) for k in _OUTAGE_KEYWORDS):
                continue

            date_debut_raw = info.get("dateDebut") or alerte.get("dateDebut") or ""
            date_fin_raw = info.get("dateFin") or alerte.get("dateFin") or ""

            interruptions.append(
                {
                    "titre": info.get("libelle") or modele.get("libelle") or "Interruption service eau",
                    "date_debut": date_debut_raw[:10] if date_debut_raw else None,
                    "date_fin": date_fin_raw[:10] if date_fin_raw else None,
                    "type": type_alerte or "TRAVAUX",
                    "description": info.get("description") or alerte.get("description") or "",
                    "reference": str(alerte.get("id") or ""),
                }
            )
        except Exception:  # noqa: BLE001
            continue

    interruptions.sort(key=lambda x: x.get("date_debut") or "9999-99-99")
    return interruptions
