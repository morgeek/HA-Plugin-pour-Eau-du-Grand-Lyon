"""Tests for pure coordinator helper functions."""
import pytest
from unittest.mock import MagicMock

from custom_components.eau_grand_lyon.api.client import EauGrandLyonApi
from custom_components.eau_grand_lyon.coordinator import (
    EauGrandLyonCoordinator,
    _find_missing_months,
    _parse_nb_habitants,
    _parse_outage_alertes,
)


class TestParseNbHabitants:
    def test_empty_string_returns_1(self):
        assert _parse_nb_habitants("") == 1

    def test_none_like_falsy_returns_1(self):
        assert _parse_nb_habitants(None) == 1  # type: ignore[arg-type]

    def test_extracts_digit_from_phrase(self):
        assert _parse_nb_habitants("4 personnes") == 4

    def test_single_digit_string(self):
        assert _parse_nb_habitants("3") == 3

    def test_no_digit_returns_1(self):
        assert _parse_nb_habitants("plusieurs personnes") == 1

    def test_leading_digit_wins(self):
        assert _parse_nb_habitants("2 adultes et 1 enfant") == 2


class TestFindMissingMonths:
    def test_empty_list_returns_empty(self):
        assert _find_missing_months([]) == []

    def test_single_entry_returns_empty(self):
        assert _find_missing_months([{"annee": 2024, "mois_index": 0, "label": "Jan"}]) == []

    def test_contiguous_months_returns_empty(self, sample_consos):
        assert _find_missing_months(sample_consos) == []

    def test_gap_in_middle_detected(self):
        consos = [
            {"annee": 2024, "mois_index": 0, "label": "Jan", "consommation_m3": 10},
            {"annee": 2024, "mois_index": 2, "label": "Mar", "consommation_m3": 12},
        ]
        missing = _find_missing_months(consos)
        assert len(missing) == 1
        assert "2024" in missing[0]

    def test_year_boundary_gap(self):
        consos = [
            {"annee": 2023, "mois_index": 11, "label": "Dec", "consommation_m3": 10},
            {"annee": 2024, "mois_index":  1, "label": "Feb", "consommation_m3": 12},
        ]
        missing = _find_missing_months(consos)
        assert len(missing) == 1


class TestParseOutageAlertes:
    def test_empty_list_returns_empty(self):
        assert _parse_outage_alertes([]) == []

    def test_travaux_alert_included(self):
        alerte = {
            "id": "42",
            "infosAlarme": {
                "type": {"libelle": "Travaux"},
                "libelle": "Coupure rue X",
                "dateDebut": "2024-06-01T08:00:00",
                "dateFin": "2024-06-01T18:00:00",
                "description": "Travaux réseau",
            },
            "modeleAction": {"libelle": ""},
        }
        result = _parse_outage_alertes([alerte])
        assert len(result) == 1
        assert result[0]["date_debut"] == "2024-06-01"
        assert result[0]["date_fin"] == "2024-06-01"
        assert result[0]["reference"] == "42"

    def test_non_outage_type_excluded(self):
        alerte = {
            "id": "1",
            "infosAlarme": {
                "type": {"libelle": "Facture"},
                "libelle": "Nouvelle facture disponible",
                "dateDebut": "2024-06-01",
            },
            "modeleAction": {"libelle": ""},
        }
        assert _parse_outage_alertes([alerte]) == []

    def test_sorted_by_date_ascending(self):
        def _make(id_, date, keyword):
            return {
                "id": id_,
                "infosAlarme": {
                    "type": {"libelle": keyword},
                    "dateDebut": date,
                },
                "modeleAction": {"libelle": ""},
            }

        alerts = [
            _make("b", "2024-07-15", "COUPURE"),
            _make("a", "2024-06-01", "TRAVAUX"),
        ]
        result = _parse_outage_alertes(alerts)
        assert result[0]["reference"] == "a"
        assert result[1]["reference"] == "b"

    def test_malformed_entry_skipped(self):
        alerts = [{"bad": "data"}, {
            "id": "ok",
            "infosAlarme": {"type": {"libelle": "COUPURE"}, "dateDebut": "2024-01-01"},
            "modeleAction": {"libelle": ""},
        }]
        result = _parse_outage_alertes(alerts)
        assert len(result) == 1


# ── format_consumptions (bug base-0 mois) ─────────────────────────────────────

class TestFormatConsumptions:
    """Couvre le bug de décalage des labels mensuels (API Téléo base-0)."""

    def _entry(self, mois, annee="2025", consommation="10.0"):
        return {"mois": str(mois), "annee": annee, "consommation": consommation}

    def test_janvier_base0_inclus(self):
        """mois=0 (Janvier) doit être accepté — était rejeté avant le fix."""
        result = EauGrandLyonApi.format_consumptions([self._entry(0)])
        assert len(result) == 1
        assert result[0]["mois_index"] == 0

    def test_decembre_base0_inclus(self):
        """mois=11 (Décembre) doit être accepté avec mois_index=11."""
        result = EauGrandLyonApi.format_consumptions([self._entry(11)])
        assert len(result) == 1
        assert result[0]["mois_index"] == 11

    def test_mois_12_exclu(self):
        """mois=12 est hors plage — doit être ignoré."""
        assert EauGrandLyonApi.format_consumptions([self._entry(12)]) == []

    def test_mois_negatif_exclu(self):
        """mois=-1 est hors plage — doit être ignoré."""
        assert EauGrandLyonApi.format_consumptions([self._entry(-1)]) == []

    def test_pas_de_decalage_mai(self):
        """Mai (mois=4) → mois_index=4, pas 3 (ancien bug de soustraction -1)."""
        result = EauGrandLyonApi.format_consumptions([self._entry(4)])
        assert len(result) == 1
        assert result[0]["mois_index"] == 4

    def test_label_inclut_annee(self):
        result = EauGrandLyonApi.format_consumptions([self._entry(6, annee="2024")])
        assert "2024" in result[0]["label"]

    def test_consommation_m3_parsee(self):
        result = EauGrandLyonApi.format_consumptions([self._entry(3, consommation="8.5")])
        assert result[0]["consommation_m3"] == 8.5

    def test_liste_vide(self):
        assert EauGrandLyonApi.format_consumptions([]) == []


# ── _detect_local_leak (algorithme statistique) ───────────────────────────────

class TestDetectLocalLeak:
    """Couvre le fix du faux positif permanent sur le capteur fuite locale."""

    def _call(self, courbe, daily):
        coord = MagicMock(spec=EauGrandLyonCoordinator)
        return EauGrandLyonCoordinator._detect_local_leak(coord, courbe, daily, "TEST_REF")

    def _make_daily(self, values):
        return [{"consommation_m3": v, "date": f"2025-01-{i+1:02d}"} for i, v in enumerate(values)]

    def test_aucune_donnee_retourne_false(self):
        assert self._call([], []) is False

    def test_spike_declenche_alerte(self):
        """Dernier jour >> 2.5× la moyenne → fuite détectée."""
        daily = self._make_daily([0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 2.0])
        assert self._call([], daily) is True

    def test_conso_stable_pas_alerte(self):
        """Consommation stable → pas de fuite."""
        daily = self._make_daily([0.2] * 7)
        assert self._call([], daily) is False

    def test_moins_de_7_jours_pas_alerte(self):
        """Moins de 7 jours → insuffisant pour décider."""
        daily = self._make_daily([5.0] * 6)
        assert self._call([], daily) is False

    def test_seuil_plancher_500l(self):
        """Spike relatif mais sous le plancher 0.5 m³ → pas d'alerte."""
        # moyenne=0.05, seuil=max(0.125, 0.5)=0.5 ; last=0.4 < 0.5
        daily = self._make_daily([0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.4])
        assert self._call([], daily) is False

    def test_courbe_24h_flux_constant_alerte(self):
        """Courbe intra-journalière : flux non-nul 24h+ → fuite probable."""
        courbe = [{"valeur": 0.01} for _ in range(24)]
        assert self._call(courbe, []) is True

    def test_courbe_24h_avec_zero_pas_alerte(self):
        """Un seul zéro dans la courbe suffit à invalider l'alerte."""
        courbe = [{"valeur": 0.01} for _ in range(23)] + [{"valeur": 0}]
        assert self._call(courbe, []) is False
