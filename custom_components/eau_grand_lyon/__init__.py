"""Home Assistant integration for Eau du Grand Lyon."""

from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .api import ApiError, AuthenticationError, NetworkError, WafBlockedError
from .const import (
    CONF_PRICE_ENTITY,
    CONF_TARIF_M3,
    CONF_TARIFF_MODE,
    DOMAIN,
    TARIFF_MODE_DYNAMIC,
    TARIFF_MODE_MANUAL,
)
from .coordinator import EauGrandLyonCoordinator

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    EauGrandLyonConfigEntry: TypeAlias = ConfigEntry[EauGrandLyonCoordinator]
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


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration (no YAML).

    Les services sont enregistrés ici (et non dans async_setup_entry) pour qu'ils
    existent même sans entrée chargée — critère Gold `action-setup`.
    """
    _async_setup_services(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry to a newer version."""
    _LOGGER.debug("Migrating config entry from version %s", entry.version)
    if entry.version in (1, 2, 3):
        data = dict(entry.data)
        options = dict(entry.options)
        if CONF_TARIF_M3 in data:
            options.setdefault(CONF_TARIF_M3, data.pop(CONF_TARIF_M3))
        options.setdefault(
            CONF_TARIFF_MODE,
            (TARIFF_MODE_DYNAMIC if options.get(CONF_PRICE_ENTITY) else TARIFF_MODE_MANUAL),
        )
        hass.config_entries.async_update_entry(entry, data=data, options=options, version=4)
        return True
    if entry.version == 4:
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

    try:
        _async_cleanup_legacy_device(hass, entry)
    except Exception:  # noqa: BLE001 - best-effort migration must never break setup
        _LOGGER.exception("Legacy device cleanup failed; keeping the existing device")

    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True


def _async_cleanup_legacy_device(hass: HomeAssistant, entry: EauGrandLyonConfigEntry) -> bool:
    """Remove the exact legacy account device only when it is demonstrably orphaned.

    This migration touches the device registry exclusively. Entity registry
    entries, entity IDs, unique IDs and recorder statistics are never modified.
    """
    coordinator = getattr(entry, "runtime_data", None)
    contracts = (coordinator.data or {}).get("contracts", {}) if coordinator is not None else {}
    if not contracts:
        return False

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    legacy_identifier = (DOMAIN, entry.entry_id)
    legacy_device = device_registry.async_get_device(identifiers={legacy_identifier})
    if legacy_device is None or legacy_device.identifiers != {legacy_identifier}:
        return False

    other_config_entries = set(legacy_device.config_entries) - {entry.entry_id}
    if other_config_entries:
        _LOGGER.warning(
            "Keeping legacy device %s: shared with config entries %s",
            legacy_device.id,
            sorted(other_config_entries),
        )
        return False

    for device in device_registry.devices.values():
        if device.id != legacy_device.id and device.via_device_id == legacy_device.id:
            _LOGGER.warning("Keeping legacy device %s: device %s depends on it", legacy_device.id, device.id)
            return False

    current_devices = []
    for contract_ref in contracts:
        current_identifier = (DOMAIN, f"{entry.entry_id}_{contract_ref}")
        current_device = device_registry.async_get_device(identifiers={current_identifier})
        if current_device is None:
            _LOGGER.debug("Deferring legacy device cleanup: contract device %s is not registered", current_identifier)
            return False
        current_entities = er.async_entries_for_device(
            entity_registry,
            current_device.id,
            include_disabled_entities=True,
        )
        if not any(entity.config_entry_id == entry.entry_id for entity in current_entities):
            _LOGGER.debug(
                "Deferring legacy device cleanup: contract device %s has no current entities",
                current_device.id,
            )
            return False
        current_devices.append(current_device.id)

    legacy_entities = er.async_entries_for_device(
        entity_registry,
        legacy_device.id,
        include_disabled_entities=True,
    )
    if legacy_entities:
        _LOGGER.warning(
            "Keeping legacy device %s: %d registry entities are still attached",
            legacy_device.id,
            len(legacy_entities),
        )
        return False

    device_registry.async_remove_device(legacy_device.id)
    _LOGGER.info(
        "Removed orphaned legacy device %s; active contract devices remain: %s",
        legacy_device.id,
        ", ".join(current_devices),
    )
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
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_path")
    if not hass.config.is_allowed_path(path):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="path_not_allowed",
            translation_placeholders={"path": path},
        )


def _local_invoice_url(hass: HomeAssistant, target_path: str) -> str | None:
    """Return a /local URL only for a real descendant of Home Assistant's www directory."""
    www_root = Path(hass.config.path("www")).resolve()
    target = Path(target_path).resolve()
    try:
        relative = target.relative_to(www_root)
    except ValueError:
        return None
    return f"/local/{relative.as_posix()}"


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
        except (PermissionError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="export_failed",
                translation_placeholders={"reason": str(err)},
            ) from err

    async def async_handle_download_invoice(call: ServiceCall) -> None:
        target_path = call.data.get("path", "/config/www/eau_grand_lyon/latest_invoice.pdf")
        contract_ref_filter = call.data.get("contract_reference")
        _validate_write_path(hass, target_path)
        found_invoice = False

        for coord in _iter_coordinators(hass):
            if not coord.data:
                continue
            for contract_ref, contract in coord.data.get("contracts", {}).items():
                if contract_ref_filter and contract_ref != contract_ref_filter:
                    continue
                factures = contract.get("factures", [])
                if not factures:
                    continue
                found_invoice = True
                facture = next(
                    (
                        item
                        for item in factures
                        if item.get("id") not in (None, "") and item.get("telechargeable") is not False
                    ),
                    None,
                )
                if facture is None:
                    continue
                invoice_id = str(facture["id"])
                try:
                    pdf_data = await coord.api.get_invoice_pdf(invoice_id)
                except (
                    NetworkError,
                    WafBlockedError,
                    ApiError,
                    AuthenticationError,
                    OSError,
                    ValueError,
                    KeyError,
                ) as err:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="download_failed",
                        translation_placeholders={"reason": str(err)},
                    ) from err

                def _save_pdf() -> None:
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    with open(target_path, "wb") as fh:
                        fh.write(pdf_data)

                try:
                    await hass.async_add_executor_job(_save_pdf)
                except (PermissionError, OSError) as err:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="download_failed",
                        translation_placeholders={"reason": str(err)},
                    ) from err

                download_url = _local_invoice_url(hass, target_path)
                if download_url:
                    notification_message = f"Facture du contrat {contract_ref} téléchargée. "
                    notification_message += f"[Télécharger le PDF]({download_url})"
                else:
                    notification_message = (
                        f"Facture du contrat {contract_ref} téléchargée dans :\n`{Path(target_path).resolve()}`"
                    )
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": "Facture Eau du Grand Lyon",
                        "message": notification_message,
                        "notification_id": f"eau_grand_lyon_invoice_{contract_ref}",
                    },
                )
                return

        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=("no_downloadable_invoices" if found_invoice else "no_invoices"),
        )

    hass.services.async_register(DOMAIN, "clear_cache", async_handle_clear_cache)
    hass.services.async_register(DOMAIN, "update_now", async_handle_update_now)
    hass.services.async_register(DOMAIN, "export_data", async_handle_export_data)
    hass.services.async_register(DOMAIN, "download_latest_invoice", async_handle_download_invoice)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: EauGrandLyonConfigEntry,
    device_entry,
) -> bool:
    """Autorise la suppression d'un device qui ne correspond plus à un contrat actif.

    Home Assistant propose alors un bouton de suppression pour les compteurs
    dont le contrat a disparu de l'API (critère Gold `stale-devices`).
    """
    coordinator = getattr(config_entry, "runtime_data", None)
    contracts = (coordinator.data or {}).get("contracts", {}) if coordinator is not None else {}
    if contracts:
        valid_ids = {(DOMAIN, f"{config_entry.entry_id}_{ref}") for ref in contracts}
    else:
        valid_ids = {(DOMAIN, config_entry.entry_id)}
    return not any(identifier in valid_ids for identifier in device_entry.identifiers)


async def async_unload_entry(hass: HomeAssistant, entry: EauGrandLyonConfigEntry) -> bool:
    """Unload a config entry.

    Les services restent enregistrés (cf. async_setup) pour toute la durée de vie
    de l'intégration ; Home Assistant les retire au déchargement du composant.
    """
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_close()

    return unload_ok


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
