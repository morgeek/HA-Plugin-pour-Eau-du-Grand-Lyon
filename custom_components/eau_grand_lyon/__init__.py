"""Intégration Home Assistant pour Eau du Grand Lyon."""
from __future__ import annotations

import csv
import logging
import os

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, HomeAssistantError, ServiceValidationError
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import EauGrandLyonCoordinator

_LOGGER = logging.getLogger(__name__)

EauGrandLyonConfigEntry = ConfigEntry[EauGrandLyonCoordinator]

# This integration only supports config entries, no YAML configuration
CONFIG_SCHEMA = vol.Schema(
    {vol.Optional(DOMAIN): vol.Schema({})},
    extra=vol.ALLOW_EXTRA,
)

PLATFORMS: list[Platform] = [

    Platform.SENSOR, 
    Platform.BINARY_SENSOR, 
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.CALENDAR,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Initialise l'intégration Eau du Grand Lyon."""
    hass.data.setdefault(DOMAIN, {})
    return True


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


async def async_setup_entry(hass: HomeAssistant, entry: EauGrandLyonConfigEntry) -> bool:
    """Initialise l'intégration depuis une config entry."""
    coordinator = EauGrandLyonCoordinator(hass, entry)
    await coordinator.async_initialize()

    # Récupération initiale des données (bloquant jusqu'au premier succès)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Enregistrement des services (une seule fois pour toutes les instances)
    _async_setup_services(hass)

    # Rechargement automatique si les options changent (intervalle de mise à jour)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


def _async_setup_services(hass: HomeAssistant) -> None:
    """Enregistre les services de l'intégration."""
    if hass.services.has_service(DOMAIN, "clear_cache"):
        return

    async def async_handle_clear_cache(_):
        _LOGGER.info("Service clear_cache appelé — réinitialisation de tous les caches")
        try:
            for entry in hass.config_entries.async_entries(DOMAIN):
                if hasattr(entry, "runtime_data"):
                    await entry.runtime_data.async_clear_cache()
        except Exception as err:
            raise HomeAssistantError(f"Failed to clear cache: {err}") from err

    async def async_handle_update_now(_):
        _LOGGER.info("Service update_now appelé — rafraîchissement immédiat")
        try:
            for entry in hass.config_entries.async_entries(DOMAIN):
                if hasattr(entry, "runtime_data"):
                    await entry.runtime_data.async_refresh()
        except Exception as err:
            raise HomeAssistantError(f"Failed to update: {err}") from err

    async def async_handle_export_data(call):
        """Exporte les données vers un fichier CSV."""
        export_path = call.data.get("path", "/config/exports/eau_grand_lyon_history.csv")
        if not export_path or not isinstance(export_path, str):
            raise ServiceValidationError("path must be a non-empty string")

        _LOGGER.info("Service export_data appelé — export vers %s", export_path)

        def _do_export():
            """Opération de fichier bloquante effectuée dans l'executor."""
            os.makedirs(os.path.dirname(export_path), exist_ok=True)
            with open(export_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                # Header
                writer.writerow(["Contrat", "Type", "Date/Label", "Valeur (m3)", "Détails"])

                for entry in hass.config_entries.async_entries(DOMAIN):
                    if not hasattr(entry, "runtime_data"):
                        continue
                    coord = entry.runtime_data
                    if not coord.data:
                        continue
                    for ref, contract in coord.data.get("contracts", {}).items():
                        # Mensuel
                        for c_entry in contract.get("consommations", []):
                            writer.writerow([
                                ref, "MENSUEL", c_entry.get("label"),
                                c_entry.get("consommation_m3"),
                                f"Année {c_entry.get('annee')}"
                            ])
                        # Journalier
                        for c_entry in contract.get("consommations_journalieres", []):
                            writer.writerow([
                                ref, "JOURNALIER", c_entry.get("date"),
                                c_entry.get("consommation_m3"),
                                f"Index {c_entry.get('index_m3')}"
                            ])

        try:
            await hass.async_add_executor_job(_do_export)
            _LOGGER.info("Export réussi : %s", export_path)
        except PermissionError as err:
            raise HomeAssistantError(f"Permission denied writing to {export_path}") from err
        except OSError as err:
            raise HomeAssistantError(f"Failed to export data: {err}") from err

    async def async_handle_download_invoice(call):
        """Télécharge la dernière facture PDF.

        Si contract_reference est spécifié, télécharge depuis ce contrat.
        Sinon, télécharge du premier contrat avec des factures.
        """
        target_path = call.data.get("path", "/config/www/eau_grand_lyon/latest_invoice.pdf")
        contract_ref_filter = call.data.get("contract_reference")

        if not target_path or not isinstance(target_path, str):
            raise ServiceValidationError("path must be a non-empty string")

        _LOGGER.info(
            "Service download_latest_invoice appelé — cible: %s%s",
            target_path,
            f" — contrat: {contract_ref_filter}" if contract_ref_filter else "",
        )

        for entry in hass.config_entries.async_entries(DOMAIN):
            if not hasattr(entry, "runtime_data"):
                continue
            coord = entry.runtime_data
            if not coord.data:
                continue
            for contract_ref, contract in coord.data.get("contracts", {}).items():
                # Si un contrat est spécifié, ne traiter que celui-ci
                if contract_ref_filter and contract_ref != contract_ref_filter:
                    continue
                factures = contract.get("factures", [])
                if factures:
                    latest = factures[0]
                    ref = latest["reference"]
                    try:
                        pdf_data = await coord.api.get_invoice_pdf(ref)

                        def _save_pdf():
                            os.makedirs(os.path.dirname(target_path), exist_ok=True)
                            with open(target_path, "wb") as f:
                                f.write(pdf_data)

                        await hass.async_add_executor_job(_save_pdf)
                        _LOGGER.info("Facture %s (contrat %s) téléchargée avec succès", ref, contract_ref)

                        # Derive the /local/ URL from the saved path so the user
                        # can download the file directly to their device.
                        www_root = hass.config.path("www")
                        try:
                            rel = os.path.relpath(target_path, www_root)
                            download_url = f"/local/{rel}"
                        except ValueError:
                            download_url = None

                        if download_url:
                            await hass.services.async_call(
                                "persistent_notification",
                                "create",
                                {
                                    "title": "📄 Facture Eau du Grand Lyon",
                                    "message": (
                                        f"Facture du contrat {contract_ref} téléchargée. "
                                        f"[Télécharger le PDF]({download_url})"
                                    ),
                                    "notification_id": f"eau_grand_lyon_invoice_{contract_ref}",
                                },
                            )
                        return
                    except PermissionError as err:
                        raise HomeAssistantError(f"Permission denied writing to {target_path}") from err
                    except (OSError, IOError) as err:
                        raise HomeAssistantError(f"Failed to save invoice: {err}") from err
                    except Exception as err:
                        raise HomeAssistantError(f"Failed to download invoice: {err}") from err

        if contract_ref_filter:
            raise HomeAssistantError(f"No invoices found for contract {contract_ref_filter}")
        raise HomeAssistantError("No invoices found")

    hass.services.async_register(DOMAIN, "clear_cache", async_handle_clear_cache)
    hass.services.async_register(DOMAIN, "update_now",  async_handle_update_now)
    hass.services.async_register(DOMAIN, "export_data", async_handle_export_data)
    hass.services.async_register(DOMAIN, "download_latest_invoice", async_handle_download_invoice)


async def async_unload_entry(hass: HomeAssistant, entry: EauGrandLyonConfigEntry) -> bool:
    """Décharge une config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_close()

    # Nettoyage des services si plus aucune entry active
    if not hass.config_entries.async_entries(DOMAIN):
        for service_name in ("clear_cache", "update_now", "export_data", "download_latest_invoice"):
            if hass.services.has_service(DOMAIN, service_name):
                hass.services.async_remove(DOMAIN, service_name)

    return unload_ok


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recharge l'intégration quand les options changent."""
    _LOGGER.debug(
        "Options modifiées pour %s, rechargement de l'intégration", entry.title
    )
    await hass.config_entries.async_reload(entry.entry_id)

