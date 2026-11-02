"""De'Longhi Coffee Link – Eletta Explore integration."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType

from .ayla_client import AuthError, AylaDevice, CloudError, DelonghiAylaClient
from .const import (
    ACTION_START,
    ACTION_STOP,
    BEVERAGES,
    CONF_EMAIL,
    CONF_PASSWORD,
    DOMAIN,
    SERVICE_SEND_RAW_COMMAND,
    SERVICE_START_BEVERAGE,
    SERVICE_STOP_BEVERAGE,
)
from .coordinator import DelonghiCoordinator
from .dss import AylaDssManager
from .errors import translated_auth_error, translated_service_error

if TYPE_CHECKING:
    # Only the static checker imports the current validation engine directly.
    # HA's runtime alias preserves compatibility with the minimum supported HA.
    import probatio as vol
else:
    import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
BEVERAGE_KEYS = [beverage[1] for beverage in BEVERAGES]
BEVERAGE_IDS = {beverage[1]: beverage[0] for beverage in BEVERAGES}
RETIRED_SENSOR_UNIQUE_ID_SUFFIXES = (
    "_last_connected",
    "_data_updated",
    "_statistics_synchronized",
)

DEVICE_TARGET: dict[Any, Any] = {vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string])}
SERVICE_START_SCHEMA = vol.Schema({**DEVICE_TARGET, vol.Required("beverage"): vol.In(BEVERAGE_KEYS)})
SERVICE_STOP_SCHEMA = vol.Schema({**DEVICE_TARGET, vol.Optional("beverage"): vol.In(BEVERAGE_KEYS)})
SERVICE_RAW_SCHEMA = vol.Schema({**DEVICE_TARGET, vol.Required("value_base64"): cv.string})


@dataclass(slots=True)
class DelonghiRuntimeData:
    """Runtime objects owned by one config entry."""

    client: DelonghiAylaClient
    coordinators: list[DelonghiCoordinator]
    dss_manager: AylaDssManager | None = None


type DelonghiConfigEntry = ConfigEntry[DelonghiRuntimeData]


def _coordinators(hass: HomeAssistant) -> list[DelonghiCoordinator]:
    """Return coordinators from loaded config entries only."""
    result: list[DelonghiCoordinator] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        runtime = getattr(entry, "runtime_data", None)
        if isinstance(runtime, DelonghiRuntimeData):
            result.extend(runtime.coordinators)
    return result


def _async_remove_retired_sensor_entities(hass: HomeAssistant, entry: DelonghiConfigEntry) -> None:
    """Remove retired timestamps and the legacy enum superseded by connectivity."""
    registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        unique_id = registry_entry.unique_id
        retired_timestamp = unique_id.endswith(RETIRED_SENSOR_UNIQUE_ID_SUFFIXES)
        legacy_connection_sensor = registry_entry.domain == Platform.SENSOR and unique_id.endswith("_connection_status")
        if retired_timestamp or legacy_connection_sensor:
            registry.async_remove(registry_entry.entity_id)


def _async_remove_stale_devices(
    hass: HomeAssistant,
    entry: DelonghiConfigEntry,
    active_dsns: frozenset[str],
) -> None:
    """Remove registry devices and entities no longer reported by the account."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    stale_devices = [
        device
        for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id)
        if (device_dsns := {dsn for domain, dsn in device.identifiers if domain == DOMAIN})
        and device_dsns.isdisjoint(active_dsns)
    ]
    stale_device_ids = {device.id for device in stale_devices}
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if registry_entry.device_id in stale_device_ids:
            entity_registry.async_remove(registry_entry.entity_id)
    for device in stale_devices:
        device_registry.async_remove_device(device.id)


def _target_coordinator(hass: HomeAssistant, call: ServiceCall) -> DelonghiCoordinator:
    """Resolve one explicit Home Assistant device target."""
    device_ids = call.data[ATTR_DEVICE_ID]
    if len(device_ids) != 1:
        raise translated_service_error("target_exactly_one")

    device = dr.async_get(hass).async_get(device_ids[0])
    if device is None:
        raise translated_service_error("target_missing")

    dsns = {identifier[1] for identifier in device.identifiers if identifier[0] == DOMAIN}
    matches = [coord for coord in _coordinators(hass) if coord.device.dsn in dsns]
    if len(matches) != 1:
        raise translated_service_error("target_not_loaded")
    return matches[0]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration actions once for the lifetime of Home Assistant."""

    async def _start_beverage(call: ServiceCall) -> None:
        coordinator = _target_coordinator(hass, call)
        await coordinator.async_send_beverage(BEVERAGE_IDS[call.data["beverage"]], ACTION_START)

    async def _stop_beverage(call: ServiceCall) -> None:
        coordinator = _target_coordinator(hass, call)
        if beverage := call.data.get("beverage"):
            await coordinator.async_send_beverage(BEVERAGE_IDS[beverage], ACTION_STOP)
        else:
            await coordinator.async_stop_active_beverage()

    async def _send_raw(call: ServiceCall) -> None:
        coordinator = _target_coordinator(hass, call)
        await coordinator.async_send_raw(call.data["value_base64"])

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_BEVERAGE,
        _start_beverage,
        schema=SERVICE_START_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_BEVERAGE,
        _stop_beverage,
        schema=SERVICE_STOP_SCHEMA,
    )
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_SEND_RAW_COMMAND,
        _send_raw,
        schema=SERVICE_RAW_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DelonghiConfigEntry) -> bool:
    """Set up one Coffee Link account and refresh every discovered machine."""
    session = async_get_clientsession(hass)
    client = DelonghiAylaClient(session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])

    try:
        await client.async_authenticate()
        devices = await client.async_get_devices()
    except AuthError as err:
        raise translated_auth_error() from err
    except CloudError as err:
        raise ConfigEntryNotReady(f"De'Longhi cloud is temporarily unavailable: {err}") from err

    if not devices:
        _async_remove_stale_devices(hass, entry, frozenset())
        raise ConfigEntryNotReady("No De'Longhi devices found on this account")

    coordinators: list[DelonghiCoordinator] = []
    active_dsns = frozenset(device.dsn for device in devices)
    device_reload_task: asyncio.Task[bool] | None = None

    def _handle_device_list(discovered: list[AylaDevice]) -> None:
        """Update metadata and reload once when account membership changes."""
        nonlocal device_reload_task
        discovered_by_dsn = {device.dsn: device for device in discovered}
        for existing in coordinators:
            if updated := discovered_by_dsn.get(existing.device.dsn):
                existing.device = updated
        if frozenset(discovered_by_dsn) == active_dsns:
            return
        if device_reload_task is not None and not device_reload_task.done():
            return
        _LOGGER.info("Coffee Link account device list changed; reloading integration")
        device_reload_task = entry.async_create_background_task(
            hass,
            hass.config_entries.async_reload(entry.entry_id),
            f"{DOMAIN}_reload_devices",
        )

    try:
        for device in devices:
            coordinator = DelonghiCoordinator(hass, client, device, entry, _handle_device_list)
            coordinators.append(coordinator)
            await coordinator.async_config_entry_first_refresh()
            await coordinator.async_confirm_initial_maintenance_snapshot()
    except Exception:
        await asyncio.gather(
            *(coordinator.async_shutdown() for coordinator in coordinators),
            return_exceptions=True,
        )
        raise

    dss_manager = AylaDssManager(hass, entry, client, coordinators)
    entry.runtime_data = DelonghiRuntimeData(client, coordinators, dss_manager)
    _async_remove_stale_devices(hass, entry, active_dsns)
    _async_remove_retired_sensor_entities(hass, entry)
    dss_manager.start()
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await dss_manager.async_stop()
        await asyncio.gather(
            *(coordinator.async_shutdown() for coordinator in coordinators),
            return_exceptions=True,
        )
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DelonghiConfigEntry) -> bool:
    """Unload platforms and stop coordinator work for one account."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and entry.runtime_data.dss_manager is not None:
        await entry.runtime_data.dss_manager.async_stop()
    return unload_ok
