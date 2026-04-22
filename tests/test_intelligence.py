"""Tests pour les nouvelles fonctionnalités Intelligence et Agrégation."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from custom_components.eau_grand_lyon.coordinator import EauGrandLyonCoordinator
from custom_components.eau_grand_lyon.api import EauGrandLyonApi

@pytest.mark.asyncio
async def test_coordinator_calculates_trend_and_prediction():
    """Vérifie que la tendance N-1 et la prédiction fin de mois sont calculées."""
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {"email": "test@test.com", "password": "pass", "tarif_m3": 3.0}
    entry.options = {}
    
    coordinator = EauGrandLyonCoordinator(hass, entry)
    
    # Mock API responses
    # Contrat 1 : 10m3 ce mois-ci, 8m3 l'an dernier au même mois (Mars)
    # On est le 15 du mois -> prediction devrait être 20m3
    now = datetime(2024, 3, 15)
    with MagicMock() as mock_dt:
        mock_dt.now.return_value = now
        
        raw_contract = {"reference": "REF1", "id": "C1"}
        monthly = [
            {"annee": 2023, "mois": 3, "consommation": 8.0, "libelleMois": "Mars"},
            {"annee": 2024, "mois": 3, "consommation": 10.0, "libelleMois": "Mars"},
        ]
        daily = [{"date": "2024-03-15", "consommation": 0.5}]
        
        coordinator.api.get_contracts = AsyncMock(return_value=[raw_contract])
        coordinator.api.get_alertes = AsyncMock(return_value=[])
        coordinator.api.get_monthly_consumptions = AsyncMock(return_value=monthly)
        coordinator.api.get_daily_consumptions = AsyncMock(return_value=daily)
        coordinator._inject_statistics = AsyncMock()
        
        # On injecte datetime.now pour le test
        import custom_components.eau_grand_lyon.coordinator as coord_mod
        with MagicMock() as mock_datetime:
            mock_datetime.now.return_value = now
            mock_datetime.strptime = datetime.strptime
            # Replace datetime in coordinator module
            coord_mod.datetime = mock_datetime
            
            data = await coordinator._fetch_all_data()
            
            c = data["contracts"]["REF1"]
            # Tendance : ((10 - 8) / 8) * 100 = 25%
            assert c["tendance_n1_pct"] == 25.0
            # Prédiction : (10 / 15) * 31 (Mars) = 20.66... -> 20.7
            assert c["prediction_conso_mois"] == 20.7
            # Coût prédiction : 20.7 * 3.0 = 62.1
            assert c["prediction_cout_mois"] == 62.1

@pytest.mark.asyncio
async def test_coordinator_aggregates_multiple_contracts():
    """Vérifie que les agrégats globaux sont corrects avec plusieurs contrats."""
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {"email": "test@test.com", "password": "pass", "tarif_m3": 2.0}
    entry.options = {}
    coordinator = EauGrandLyonCoordinator(hass, entry)
    
    raw_contracts = [
        {"reference": "REF1", "id": "C1"},
        {"reference": "REF2", "id": "C2"},
    ]
    # C1: 10m3, C2: 5m3 -> Total 15m3
    monthly_c1 = [{"annee": 2024, "mois": 1, "consommation": 10.0}]
    monthly_c2 = [{"annee": 2024, "mois": 1, "consommation": 5.0}]
    
    coordinator.api.get_contracts = AsyncMock(return_value=raw_contracts)
    coordinator.api.get_alertes = AsyncMock(return_value=[])
    coordinator.api.get_monthly_consumptions = AsyncMock(side_effect=[monthly_c1, monthly_c2])
    coordinator.api.get_daily_consumptions = AsyncMock(return_value=[])
    coordinator._inject_statistics = AsyncMock()
    
    data = await coordinator._fetch_all_data()
    
    g = data["global"]
    assert g["total_conso_courant"] == 15.0
    assert g["total_cout_courant_eur"] == 30.0 # (10+5) * 2.0
    assert g["nb_contracts"] == 2
