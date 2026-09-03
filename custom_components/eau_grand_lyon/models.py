"""Typed normalized data models for Eau du Grand Lyon."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, TypedDict

from .pfas import PfasData
from .vigieau import VigieauData

if TYPE_CHECKING:
    from .warsmann import WarsmannAssessment


class MonthlyConsumption(TypedDict, total=False):
    """Normalized monthly consumption returned by the API adapter."""

    annee: int
    consommation_m3: float
    label: str
    mois: int
    mois_index: int


class DailyConsumption(TypedDict, total=False):
    """Normalized daily consumption returned by the API adapter."""

    consommation_m3: float
    date: str
    index_m3: float
    volume_fuite_estime_m3: float


class InvoiceData(TypedDict, total=False):
    """Normalized invoice metadata."""

    contrat_id: str
    date: str
    id: str
    montant_ttc: float
    reference: str
    telechargeable: bool
    volume_m3: float


class WaterQualityData(TypedDict, total=False):
    """Normalized public water-quality sample."""

    chlore_mgl: float | None
    code_commune: str | None
    code_reseau: str | None
    commune: str | None
    date_analyse: str | None
    durete_fh: float | None
    nitrates_mgl: float | None
    nom_reseau: str | None
    source: str
    turbidite_ntu: float | None
    unite_turbidite: str | None


class OutageData(TypedDict, total=False):
    """Normalized planned outage."""

    contrat_ref: str
    date_debut: str | None
    date_fin: str | None
    description: str
    presence_requise: bool
    reference: str
    titre: str
    type: str


class AlertData(TypedDict, total=False):
    """Normalized provider alert."""

    date_debut: str
    date_fin: str
    description: str
    libelle: str
    modele: dict[str, object]
    titre: str
    type: str


class CostBreakdown(TypedDict, total=False):
    """Serializable details of one cost estimate."""

    effective_rate_eur_m3: float | None
    fixed_eur: float
    source: str
    total_eur: float
    variable_eur: float
    volume_m3: float


class BillingData(TypedDict, total=False):
    """Transparent normalized billing calculation."""

    billing_mode: str
    cost_breakdown_annual: CostBreakdown
    cost_breakdown_monthly: CostBreakdown
    cout_annuel_eur: float | None
    cout_mois_courant_eur: float | None
    cout_reel_annuel: float
    cout_reel_mois: float | None
    estimation: bool
    latest_invoice_effective_rate_eur_m3: float | None
    latest_invoice_ttc: float | None
    latest_invoice_volume_m3: float | None
    subscription_annual: float
    tarif_m3: float
    tariff_source: str


class ContractData(BillingData, total=False):
    """Normalized data for one water contract."""

    abonne_alerte_fuite: bool | None
    adresse: str
    battery_ok: bool | None
    calibre_compteur: str
    co2_footprint_kg: float | None
    conso_annuelle_ref_m3: float | None
    conso_moyenne_7j_litres: float | None
    consommation_7j: float | None
    consommation_30j: float | None
    consommation_annuelle: float
    consommation_annuelle_n1: float | None
    consommation_cumulee_annee: float
    consommation_derniere_heure_m3: float | None
    consommation_mois_courant: float | None
    consommation_mois_precedent: float | None
    consommation_n1: float | None
    consommations: list[MonthlyConsumption]
    consommations_journalieres: list[DailyConsumption]
    courbe_de_charge: list[dict[str, object]]
    daily_last_date: str | None
    daily_nb_entries: int
    daily_source: str
    date_echeance: str
    date_effet: str
    date_prochaine_releve: str | None
    debit_moyen_m3h: float | None
    derniere_conso_jour_m3: float | None
    derniere_facture: InvoiceData | None
    eco_score_grade: str
    eco_score_m3_pers: float | None
    estimated_next_bill_date: str | None
    factures: list[InvoiceData]
    fuite_estime_30j_m3: float | None
    hardness_fh: float
    heure_pic: str | None
    id: str
    index_journalier_dernier: float | None
    index_journalier_dernier_date: str | None
    label_mois_courant: str | None
    label_mois_precedent: str | None
    label_n1: str | None
    limescale_alert: bool
    limescale_g: float
    local_leak_pattern: bool
    mode_paiement: str
    mois_manquants: list[str]
    mensualise: bool
    nb_habitants: int
    next_bill_date: str | None
    next_payment_date: str | None
    nombre_habitants: str
    pds_communicabilite_amm: object
    pds_mode_releve: object
    prediction_conso_mois: float | None
    prediction_cout_mois: float | None
    real_index: float | None
    reference: str
    reference_pds: str
    seuil_surconso_jour_m3: float | None
    seuil_surconso_mois_m3: float | None
    signal_pct: float | None
    solde_eur: float
    statut: str
    surconso_jour_depassee: bool
    surconso_mois_depassee: bool
    teleo_compatible: bool
    tendance_n1_pct: float | None
    usage: str
    warsmann_assessment: WarsmannAssessment | None


class GlobalData(TypedDict, total=False):
    """Normalized cross-contract aggregates."""

    nb_contracts: int
    total_conso_courant: float
    total_consommation_annuelle: float
    total_cout_courant_eur: float
    total_prediction_cout_eur: float


EauGrandLyonData = TypedDict(
    "EauGrandLyonData",
    {
        "api_mode": str,
        "cache_age_days": int | None,
        "consecutive_failures": int,
        "contracts": dict[str, ContractData],
        "drought_level": str,
        "experimental_mode": bool,
        "global": GlobalData,
        "interruptions": list[OutageData],
        "interventions_planifiees": list[OutageData],
        "last_error": str | None,
        "last_error_type": str | None,
        "last_failure_reason": str | None,
        "last_failure_time": datetime | None,
        "last_update_success_time": datetime | None,
        "nb_alertes": int,
        "offline_mode": bool,
        "offline_since": datetime | None,
        "pfas": PfasData,
        "pfas_enabled": bool,
        "prochaine_coupure": OutageData | None,
        "vacation_alert": bool,
        "vigieau": VigieauData,
        "vigieau_enabled": bool,
        "water_quality": WaterQualityData,
    },
    total=False,
)
