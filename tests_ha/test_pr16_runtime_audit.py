"""Exercise PR16 through a loaded Eletta entry and real HA task ownership."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_delonghi_coffeelink_eletta_explore import coordinator as cm
from custom_components.ha_delonghi_coffeelink_eletta_explore.ayla_client import (
    AylaDevice,
    DelonghiAylaClient,
)
from custom_components.ha_delonghi_coffeelink_eletta_explore.command_builder import decode_command
from custom_components.ha_delonghi_coffeelink_eletta_explore.const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    DOMAIN,
)
from custom_components.ha_delonghi_coffeelink_eletta_explore.dss import AylaDssManager, DssEvent


async def test_loaded_eletta_statistics_frame_and_finish_task(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic Eletta audit",
        unique_id="audit@example.test",
        data={CONF_EMAIL: "audit@example.test", CONF_PASSWORD: "synthetic-password"},
    )
    entry.add_to_hass(hass)
    device = AylaDevice(
        dsn="synthetic-audit-device",
        name="Synthetic audit coffee maker",
        oem_model="DL-striker-cb",
        model="Synthetic model",
        sw_version="test-version",
        connection_status="online",
    )
    properties = {
        "app_data_request": {"value": "", "ack_enabled": False},
        "app_device_connected": {"value": 0},
        "app_id": {"value": 0},
        "d701_tot_bev_b": {"value": 100},
    }
    with (
        patch.object(DelonghiAylaClient, "async_authenticate", AsyncMock()),
        patch.object(DelonghiAylaClient, "async_get_devices", AsyncMock(return_value=[device])),
        patch.object(DelonghiAylaClient, "async_get_properties", AsyncMock(return_value=properties)),
        patch.object(DelonghiAylaClient, "async_get_connection_info", AsyncMock(return_value={})),
        patch.object(DelonghiAylaClient, "async_set_property_value", AsyncMock(return_value=None)) as write,
        patch.object(AylaDssManager, "start", return_value=None),
        patch.object(AylaDssManager, "async_stop", AsyncMock()),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        coordinator = entry.runtime_data.coordinators[0]
        coordinator._integration_app_id = 0xC0FFEE11

        await coordinator._send_statistics_refresh()
        write.assert_awaited_once()
        dsn, property_name, encoded = write.await_args.args
        assert dsn == device.dsn
        assert property_name == "app_data_request"
        raw = base64.b64decode(encoded, validate=True)
        assert len(raw) == 17
        assert raw[:9] == bytes.fromhex("0d 06 e8 f0 00 ed 7c 00 00")
        assert raw[-4:] == bytes.fromhex("c0 ff ee 11")
        assert decode_command(encoded)["crc_valid"] is True
        assert coordinator.last_command_result is None

        coordinator.monitor = {"status": 7, "step": 11}
        with (
            patch.object(cm, "parse_monitor_b64", return_value={"status": 7, "step": 0}),
            patch.object(cm, "monitor_ordering_token", return_value=None),
            patch.object(cm, "POST_COMMAND_REFRESH_DELAY", 0),
            patch.object(coordinator, "async_synchronize_statistics", AsyncMock(return_value="completed_updated")) as refresh,
        ):
            event = DssEvent(
                sequence="1",
                event_type="datapoint",
                dsn=device.dsn,
                property_name="d302_monitor_machine",
                value="synthetic-monitor",
            )
            assert coordinator.handle_dss_event(event)
            await coordinator._post_command_refresh_task
            refresh.assert_awaited_once_with(automatic=True, trigger="beverage_finished")

        assert coordinator.last_command_result is None
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED
