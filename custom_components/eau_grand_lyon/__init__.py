"""Home Assistant integration for Eau du Grand Lyon."""

from __future__ import annotations

import csv
import logging
import os
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    HomeAssistantError,
    ServiceCall,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import ApiError, AuthenticationError, NetworkError, WafBlockedError
from .const import DOMAIN
from .coordinator import EauGrandLyonCoordinator

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    EauGrandLyonConfigEntry = ConfigEntry[EauGrandLyonCoordinator]
else:
    EauGrandLyonConfigEntry = ConfigEntry

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.CALENDAR,
]

SERVICE_NAMES = ("clear_cache", "update_now", "export_data", "download_latest_invoice")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration (no YAML)."""
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry to a newer version."""
    _LOGGER.debug("Migrating config entry from version %s", entry.version)
    if entry.version == 1:
        hass.config_entries.async_update_entry(entry, version=2)
        return True
    _LOGGER.error("Cannot migrate config entry from unknown version %s", entry.version)
    return False


async def async_setup_entry(hass: HomeAssistant, entry: EauGrandLyonConfigEntry) -> bool:
    """Set up an integration instance from a config entry."""
    coordinator = EauGrandLyonCoordinator(hass, entry)
    try:
        await coordinator.async_initialize()
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        # Le coordinator possède sa propre ClientSession ; sans fermeture ici,
        # chaque tentative de setup échouée (ConfigEntryNotReady, reauth) en fuit une.
        await coordinator.async_close()
        raise

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_setup_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True


def _iter_coordinators(hass: HomeAssistant):
    """Yield active coordinators across all config entries."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        coord = getattr(entry, "runtime_data", None)
        if coord is not None:
            yield coord


def _validate_write_path(hass: HomeAssistant, path: str) -> None:
    """Refuse les chemins vides ou hors des répertoires autorisés."""
    if not isinstance(path, str) or not path.strip():
        raise ServiceValidationError("path must be a non-empty string")
    if not hass.config.is_allowed_path(path):
        raise ServiceValidationError(
            f"Path '{path}' is not allowed. Add its directory to " "'allowlist_external_dirs' in configuration.yaml."
        )


def _async_setup_services(hass: HomeAssistant) -> None:
    """Register integration-wide services (idempotent)."""
    if hass.services.has_service(DOMAIN, "clear_cache"):
        return

    async def async_handle_clear_cache(call: ServiceCall) -> None:
        for coord in _iter_coordinators(hass):
            await coord.async_clear_cache()

    async def async_handle_update_now(call: ServiceCall) -> None:
        for coord in _iter_coordinators(hass):
            await coord.async_refresh()

    async def async_handle_export_data(call: ServiceCall) -> None:
        export_path = call.data.get("path", "/config/exports/eau_grand_lyon_history.csv")
        _validate_write_path(hass, export_path)

        coordinators = list(_iter_coordinators(hass))

        def _do_export() -> None:
            os.makedirs(os.path.dirname(export_path), exist_ok=True)
            with open(export_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["Contrat", "Type", "Date/Label", "Valeur (m3)", "Détails"])
                for coord in coordinators:
                    if not coord.data:
                        continue
                    for ref, contract in coord.data.get("contracts", {}).items():
                        for c_entry in contract.get("consommations", []):
                            writer.writerow(
                                [
                                    ref,
                                    "MENSUEL",
                                    c_entry.get("label"),
                                    c_entry.get("consommation_m3"),
                                    f"Année {c_entry.get('annee')}",
                                ]
                            )
                        for c_entry in contract.get("consommations_journalieres", []):
                            writer.writerow(
                                [
                                    ref,
                                    "JOURNALIER",
                                    c_entry.get("date"),
                                    c_entry.get("consommation_m3"),
                                    f"Index {c_entry.get('index_m3')}",
                                ]
                            )

        try:
            await hass.async_add_executor_job(_do_export)
        except PermissionError as err:
            raise HomeAssistantError(f"Permission denied writing to {export_path}") from err
        except OSError as err:
            raise HomeAssistantError(f"Failed to export data: {err}") from err

    async def async_handle_download_invoice(call: ServiceCall) -> None:
        target_path = call.data.get("path", "/config/www/eau_grand_lyon/latest_invoice.pdf")
        contract_ref_filter = call.data.get("contract_reference")
        _validate_write_path(hass, target_path)

        for coord in _iter_coordinators(hass):
            if not coord.data:
                continue
            for contract_ref, contract in coord.data.get("contracts", {}).items():
                if contract_ref_filter and contract_ref != contract_ref_filter:
                    continue
                factures = contract.get("factures", [])
                if not factures:
                    continue
                ref = factures[0]["reference"]
                try:
                    pdf_data = await coord.api.get_invoice_pdf(ref)
                except (
                    NetworkError,
                    WafBlockedError,
                    ApiError,
                    AuthenticationError,
                    OSError,
                    ValueError,
                    KeyError,
                ) as err:
                    raise HomeAssistantError(f"Failed to download invoice {ref}: {err}") from err

                def _save_pdf() -> None:
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with open(target_path, "wb") as fh:
                        fh.write(pdf_data)

                try:
                    await hass.async_add_executor_job(_save_pdf)
                except PermissionError as err:
                    raise HomeAssistantError(f"Permission denied writing to {target_path}") from err
                except OSError as err:
                    raise HomeAssistantError(f"Failed to save invoice: {err}") from err

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
                            "title": "Facture Eau du Grand Lyon",
                            "message": (
                                f"Facture du contrat {contract_ref} téléchargée. "
                                f"[Télécharger le PDF]({download_url})"
                            ),
                            "notification_id": f"eau_grand_lyon_invoice_{contract_ref}",
                        },
                    )
                return

        if contract_ref_filter:
            raise HomeAssistantError(f"No invoices found for contract {contract_ref_filter}")
        raise HomeAssistantError("No invoices found")

    hass.services.async_register(DOMAIN, "clear_cache", async_handle_clear_cache)
    hass.services.async_register(DOMAIN, "update_now", async_handle_update_now)
    hass.services.async_register(DOMAIN, "export_data", async_handle_export_data)
    hass.services.async_register(DOMAIN, "download_latest_invoice", async_handle_download_invoice)


async def async_unload_entry(hass: HomeAssistant, entry: EauGrandLyonConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_close()
        if not hass.config_entries.async_entries(DOMAIN):
            for service_name in SERVICE_NAMES:
                if hass.services.has_service(DOMAIN, service_name):
                    hass.services.async_remove(DOMAIN, service_name)

    return unload_ok


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
