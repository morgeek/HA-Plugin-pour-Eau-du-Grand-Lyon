"""Régression : conversion litres -> m³ des champs journaliers.

Vérifie que `consommation`, `index`, `volumeEstimeFuite` et `debitMin` sont
correctement convertis depuis les litres (unités renvoyées par l'API réelle
Eau du Grand Lyon : consommation/index = "l", debitMin = "L/h") vers m³.

Ces valeurs proviennent d'une capture réelle de l'API (compteur Téléo).
"""

from __future__ import annotations

from custom_components.eau_grand_lyon.api.client import EauGrandLyonApi as A


def _daily_response() -> dict:
    return {
        "unites": {"consommation": "l", "index": "l", "debitMin": "L/h", "volumeEstimeFuite": "l"},
        "postes": [
            {
                "libelle": "toutes heures",
                "data": [
                    {
                        "annee": 2026,
                        "mois": 6,  # 0-indexé -> juillet
                        "jour": 15,
                        "consommation": 408,
                        "index": 1091581,
                        "debitMin": 250,
                        "volumeEstimeFuite": 1500,
                    }
                ],
            }
        ],
    }


def test_consommation_and_index_converted_and_date_built():
    parsed = A._parse_daily_response(_daily_response())
    assert len(parsed) == 1
    entry = parsed[0]
    assert entry["consommation"] == 408 / 1000.0
    assert entry["date"] == "2026-07-15"
    assert "volumeFuiteEstime" in entry and "volumeEstimeFuite" not in entry


def test_leak_volume_and_min_flow_divided_by_1000():
    """Le bug : volumeEstimeFuite (l) et debitMin (L/h) n'étaient pas convertis."""
    entry = A._parse_daily_response(_daily_response())[0]
    assert entry["volumeFuiteEstime"] == 1.5  # 1500 L -> 1.5 m³ (pas 1500)
    assert entry["debitMin"] == 0.25  # 250 L/h -> 0.25 m³/h (pas 250)


def test_format_daily_exposes_correct_m3_fields():
    parsed = A._parse_daily_response(_daily_response())
    row = A.format_daily_consumptions(parsed, "test")[0]
    assert row["consommation_m3"] == 0.408
    assert row["index_m3"] == 1091.581
    assert row["volume_fuite_estime_m3"] == 1.5
    assert row["debit_min_m3h"] == 0.25
    assert row["date"] == "2026-07-15"


def test_small_index_below_magnitude_heuristic_still_converted():
    """Régression (retour utilisateur) : compteur récent, index physique 20,990 m³.

    L'API renvoie l'index brut en litres (20990) avec `unites.index = "l"`. Le
    filet de sécurité par magnitude de _extract_index (seuil 100 000) ne se
    déclenche PAS pour cette valeur — sans conversion via `unites.index` dans
    _parse_daily_response, l'index restait affiché "20990.000 m³" au lieu de
    "20.990 m³", gonflant artificiellement la consommation journalière calculée.
    """
    resp = {
        "unites": {"consommation": "l", "index": "l"},
        "postes": [
            {
                "data": [
                    {"annee": 2026, "mois": 6, "jour": 15, "consommation": 300, "index": 20990},
                ]
            }
        ],
    }
    parsed = A._parse_daily_response(resp)
    row = A.format_daily_consumptions(parsed, "test")[0]
    assert row["index_m3"] == 20.990


def test_no_conversion_when_units_absent():
    """Sans bloc `unites`, l'inférence par magnitude gère la conso mais on ne
    touche pas aux champs fuite/débit (comportement conservateur)."""
    resp = {
        "postes": [
            {
                "data": [
                    {"annee": 2026, "mois": 0, "jour": 1, "consommation": 5, "volumeEstimeFuite": 3},
                ]
            }
        ]
    }
    entry = A._parse_daily_response(resp)[0]
    # petite magnitude -> considérée m³, pas de division
    assert entry["consommation"] == 5
    assert entry["volumeFuiteEstime"] == 3


def test_litre_unit_aliases_are_converted():
    resp = {
        "unites": {"consommation": "litres", "index": "litre", "debitMin": "litres / h"},
        "postes": [{"data": [{"annee": 2026, "mois": 0, "jour": 1,
                                "consommation": 500, "index": 20000, "debitMin": 250}]}],
    }
    row = A.format_daily_consumptions(A._parse_daily_response(resp), "test")[0]
    assert row["consommation_m3"] == 0.5
    assert row["index_m3"] == 20.0
    assert row["debit_min_m3h"] == 0.25


def test_malformed_daily_entries_are_ignored():
    resp = {"postes": [{"data": [None, "invalid", {"annee": 2026, "mois": 0, "jour": 1,
                                      "consommation": 0.5}]}]}
    parsed = A._parse_daily_response(resp)
    assert len(parsed) == 1
    assert A.format_daily_consumptions(parsed, "test")[0]["consommation_m3"] == 0.5
