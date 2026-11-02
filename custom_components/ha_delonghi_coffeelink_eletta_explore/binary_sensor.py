"""Binary sensor platform for De'Longhi Coffee Link – Eletta Explore (ECAM maintenance alarms).

Maintenance state is decoded from the ``switches``/``alarms`` bitfields of the
``d302_monitor_machine`` MonitorV2 blob (see ``monitor.py``). The parser fills
those bitfields for any model with a long-enough payload, but these maintenance
entities are created ONLY for ECAM models (``uses_cloud_session`` is True, e.g.
Eletta Explore) - so the PrimaDonna Soul gets no binary sensors and is untouched.

Bit layout derived from the DlghIoT client (TischenkoArseny, PR #9 / issue #7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .ayla_client import AylaProperties
from .const import normalize_connection_status
from .coordinator import DelonghiCoordinator
from .entity import DelonghiCoordinatorEntity

if TYPE_CHECKING:
    from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass

    from . import DelonghiConfigEntry
else:
    # The defining const module is absent on the minimum supported HA release.
    # Both generations retain this public runtime export.
    from homeassistant.components.binary_sensor import BinarySensorDeviceClass

_DECALC_PERCENT_PROPERTY = "d512_percentage_to_deca"

PARALLEL_UPDATES = 0


def _prop_int(data: AylaProperties | None, prop_name: str) -> int | None:
    if not data:
        return None
    prop = data.get(prop_name)
    if not isinstance(prop, dict):
        return None
    val = prop.get("value")
    if val is None:
        return None
    try:
        return int(str(val).strip())
    except TypeError, ValueError:
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DelonghiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators = entry.runtime_data.coordinators
    entities: list[BinarySensorEntity] = []
    for coord in coordinators:
        entities.append(DelonghiCloudConnectionBinarySensor(coord))
        # Maintenance bitfields are ECAM-only; never create these on Soul.
        if not coord.profile.uses_cloud_session:
            continue
        entities.extend(
            [
                DelonghiWaterTankBinarySensor(coord),
                DelonghiWasteContainerBinarySensor(coord),
                DelonghiDecalcificationBinarySensor(coord),
                DelonghiFilterBinarySensor(coord),
            ]
        )
    async_add_entities(entities)


class _Base(DelonghiCoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coord: DelonghiCoordinator, unique_suffix: str) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{coord.device.dsn}_{unique_suffix}"
        self._attr_translation_key = unique_suffix

    def _monitor(self) -> dict[str, Any]:
        # Transient wake/standby frames can briefly carry misleading alarm
        # bits. Keep the last steady ready/idle snapshot for maintenance state.
        return self.coordinator.stable_maintenance_monitor or {}

    @property
    def available(self) -> bool:
        monitor = self._monitor()
        return super().available and "alarms" in monitor and "error" not in monitor


class DelonghiCloudConnectionBinarySensor(_Base):
    """Whether the coffee maker is connected to the De'Longhi cloud."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord: DelonghiCoordinator) -> None:
        super().__init__(coord, "connection_status")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool | None:
        status = normalize_connection_status(self.coordinator.device.connection_status)
        if status == "unknown":
            return None
        return status == "online"


class DelonghiWaterTankBinarySensor(_Base):
    """Water tank empty or removed (monitor alarm bit 0 / switch bit 4)."""

    def __init__(self, coord: DelonghiCoordinator) -> None:
        super().__init__(coord, "water_tank_empty")

    @property
    def is_on(self) -> bool | None:
        monitor = self._monitor()
        if "alarms" not in monitor:
            return None
        switches = monitor.get("switches", 0)
        alarms = monitor["alarms"]
        # Switch bit 4 set = tank removed (same polarity as waste container bit 3).
        tank_missing = bool((switches >> 4) & 1)
        # Empty only: alarm bit 0 or tank missing - not bit 16 (low water warning).
        return bool((alarms >> 0) & 1 or tank_missing)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        monitor = self._monitor()
        if "alarms" not in monitor:
            return {}
        switches = monitor.get("switches", 0)
        alarms = monitor["alarms"]
        return {
            "water_tank_present": not bool((switches >> 4) & 1),
            "water_level_low": bool((switches >> 6) & 1),
            "water_empty_alarm": bool((alarms >> 0) & 1),
        }


class DelonghiWasteContainerBinarySensor(_Base):
    """Waste container full or missing."""

    def __init__(self, coord: DelonghiCoordinator) -> None:
        super().__init__(coord, "waste_container_full")

    @property
    def is_on(self) -> bool | None:
        monitor = self._monitor()
        if "alarms" not in monitor:
            return None
        alarms = monitor["alarms"]
        switches = monitor.get("switches", 0)
        waste_full = bool((alarms >> 1) & 1)
        container_present = not bool((switches >> 3) & 1)
        return (not container_present) or waste_full

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        monitor = self._monitor()
        if "alarms" not in monitor:
            return {}
        switches = monitor.get("switches", 0)
        alarms = monitor["alarms"]
        return {
            "waste_container_present": not bool((switches >> 3) & 1),
            "waste_full_alarm": bool((alarms >> 1) & 1),
        }


class DelonghiDecalcificationBinarySensor(_Base):
    """Decalcification needed (alarm bit or percentage threshold)."""

    def __init__(self, coord: DelonghiCoordinator) -> None:
        super().__init__(coord, "decalcification_needed")

    @property
    def is_on(self) -> bool | None:
        monitor = self._monitor()
        if "alarms" not in monitor:
            return None
        descale_alarm = bool((monitor["alarms"] >> 2) & 1)
        decalc_percent = _prop_int(self.coordinator.data, _DECALC_PERCENT_PROPERTY)
        return descale_alarm or (decalc_percent is not None and decalc_percent >= 90)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        monitor = self._monitor()
        if "alarms" not in monitor:
            return {}
        decalc_percentage = _prop_int(self.coordinator.data, _DECALC_PERCENT_PROPERTY)
        return {
            "descale_alarm": bool((monitor["alarms"] >> 2) & 1),
            **({"decalc_percentage": decalc_percentage} if decalc_percentage is not None else {}),
        }


class DelonghiFilterBinarySensor(_Base):
    """Water filter replacement needed."""

    def __init__(self, coord: DelonghiCoordinator) -> None:
        super().__init__(coord, "filter_change_needed")

    @property
    def is_on(self) -> bool | None:
        monitor = self._monitor()
        if "alarms" not in monitor:
            return None
        return bool((monitor["alarms"] >> 3) & 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        monitor = self._monitor()
        if "alarms" not in monitor:
            return {}
        return {
            "filter_alarm": bool((monitor["alarms"] >> 3) & 1),
        }
