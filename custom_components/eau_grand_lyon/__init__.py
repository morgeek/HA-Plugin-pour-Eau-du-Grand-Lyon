"""Intégration Home Assistant pour Eau du Grand Lyon."""
from __future__ import annotations

import logging
import csv
import os
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import EauGrandLyonCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR, 
    Platform.BINARY_SENSOR, 
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.CALENDAR,
]


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migre une config entry vers une nouvelle version."""
    _LOGGER.debug("Migration de la config entry de la version %s", config_entry.version)

    if config_entry.version == 1:
        # Migration v1 -> v2 (placeholder pour future logique)
        new_data = {**config_entry.data}
        new_options = {**config_entry.options}
        
        # On force la version à 2
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, options=new_options, version=2
        )

    _LOGGER.info("Migration vers la version %s réussie", config_entry.version)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialise l'intégration depuis une config entry."""
    coordinator = EauGrandLyonCoordinator(hass, entry)
    await coordinator.async_initialize()

    # Récupération initiale des données (bloquant jusqu'au premier succès)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Enregistrement des services (une seule fois pour toutes les instances)
    if not hass.services.has_service(DOMAIN, "clear_cache"):
        async def async_handle_clear_cache(_):
            _LOGGER.info("Service clear_cache appelé — réinitialisation de tous les caches")
            for coord in hass.data.get(DOMAIN, {}).values():
                await coord.async_clear_cache()
        
        async def async_handle_update_now(_):
            _LOGGER.info("Service update_now appelé — rafraîchissement immédiat")
            for coord in hass.data.get(DOMAIN, {}).values():
                await coord.async_refresh()

        async def async_handle_export_data(call):
            """Exporte les données vers un fichier CSV."""
            export_path = call.data.get("path", "/config/exports/eau_grand_lyon_history.csv")
            _LOGGER.info("Service export_data appelé — export vers %s", export_path)
            
            try:
                os.makedirs(os.path.dirname(export_path), exist_ok=True)
                with open(export_path, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    # Header
                    writer.writerow(["Contrat", "Type", "Date/Label", "Valeur (m3)", "Détails"])
                    
                    for coord in hass.data.get(DOMAIN, {}).values():
                        if not coord.data: continue
                        for ref, contract in coord.data.get("contracts", {}).items():
                            # Mensuel
                            for entry in contract.get("consommations", []):
                                writer.writerow([
                                    ref, "MENSUEL", entry.get("label"), 
                                    entry.get("consommation_m3"), 
                                    f"Année {entry.get('annee')}"
                                ])
                            # Journalier
                            for entry in contract.get("consommations_journalieres", []):
                                writer.writerow([
                                    ref, "JOURNALIER", entry.get("date"), 
                                    entry.get("consommation_m3"), 
                                    f"Index {entry.get('index_m3')}"
                                ])
                _LOGGER.info("Export réussi : %s", export_path)
            except Exception as err:
                _LOGGER.error("Erreur lors de l'export CSV : %s", err)

        async def async_handle_download_invoice(call):
            """Télécharge la dernière facture PDF."""
            target_path = call.data.get("path", "/config/www/eau_grand_lyon/latest_invoice.pdf")
            _LOGGER.info("Service download_latest_invoice appelé — cible: %s", target_path)
            
            for coord in hass.data.get(DOMAIN, {}).values():
                if not coord.data: continue
                # On prend la première facture du premier contrat trouvé
                for contract in coord.data.get("contracts", {}).values():
                    factures = contract.get("factures", [])
                    if factures:
                        latest = factures[0]
                        ref = latest["reference"]
                        try:
                            pdf_data = await coord.api.get_invoice_pdf(ref)
                            os.makedirs(os.path.dirname(target_path), exist_ok=True)
                            with open(target_path, "wb") as f:
                                f.write(pdf_data)
                            _LOGGER.info("Facture %s téléchargée avec succès", ref)
                            return # On s'arrête à la première trouvée
                        except Exception as err:
                            _LOGGER.error("Erreur téléchargement facture : %s", err)

        hass.services.async_register(DOMAIN, "clear_cache", async_handle_clear_cache)
        hass.services.async_register(DOMAIN, "update_now",  async_handle_update_now)
        hass.services.async_register(DOMAIN, "export_data", async_handle_export_data)
        hass.services.async_register(DOMAIN, "download_latest_invoice", async_handle_download_invoice)

    # Rechargement automatique si les options changent (intervalle de mise à jour)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge une config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: EauGrandLyonCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()

    # Nettoyage des services si plus aucune entry active
    if not hass.data.get(DOMAIN):
        for service_name in ("clear_cache", "update_now", "export_data", "download_latest_invoice"):
            if hass.services.has_service(DOMAIN, service_name):
                hass.services.async_remove(DOMAIN, service_name)
        hass.data.pop(DOMAIN, None)

    return unload_ok


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recharge l'intégration quand les options changent.

    Appelé automatiquement par HA lorsque l'utilisateur modifie les options
    (ex. intervalle de mise à jour). Le rechargement recrée le coordinateur
    avec le nouvel intervalle.
    """
    _LOGGER.debug(
        "Options modifiées pour %s, rechargement de l'intégration", entry.title
    )
    await hass.config_entries.async_reload(entry.entry_id)
