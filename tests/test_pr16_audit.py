"""Independent PR16 audit probes; temporary test branch, no real appliance I/O."""

from __future__ import annotations

import asyncio
import base64
import binascii
import random
from contextlib import suppress
from unittest.mock import AsyncMock, Mock

import pytest
from test_dss_coordinator import _dss_event
from test_reliability import _coordinator
from test_reliability import command_builder as cb
from test_reliability import coordinator_module as cm


@pytest.mark.parametrize("app_id", [0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, -1])
@pytest.mark.parametrize("timestamp", [0, 1, 0x7FFFFFFF, 0xFFFFFFFF])
def test_independent_frame_crc_timestamp_and_signed_session(app_id, timestamp):
    raw = cb.build_statistics_request_command(app_id, timestamp=timestamp)
    assert len(raw) == 17
    assert raw[:9] == bytes.fromhex("0d 06 e8 f0 00 ed 7c 00 00")
    assert binascii.crc_hqx(raw[:5], 0x1D0F) == int.from_bytes(raw[5:7], "big")
    assert binascii.crc_hqx(raw[:7], 0x1D0F) == 0
    assert raw[9:13] == timestamp.to_bytes(4, "big")
    assert raw[13:] == (app_id & 0xFFFFFFFF).to_bytes(4, "big")
    decoded = cb.decode_command(base64.b64encode(raw).decode())
    assert decoded["type"] == "statistics_request"
    assert decoded["crc_valid"] is True
    assert not cb.is_wake_power_frame(decoded)


def test_deterministic_frame_roundtrips_do_not_mutate_learned_commands():
    coordinator, _client = _coordinator("DL-striker-cb")
    random_values = random.Random(16)
    for _ in range(200):
        app_id = random_values.getrandbits(32)
        timestamp = random_values.getrandbits(32)
        raw = cb.build_statistics_request_command(app_id, timestamp=timestamp)
        decoded = cb.decode_command(base64.b64encode(raw).decode())
        assert decoded["timestamp"] == timestamp
        assert decoded["crc_valid"] is True
        coordinator._maybe_learn_frame(decoded)
    assert coordinator.learned_start_frames == {}
    assert coordinator.learned_stop_frames == {}
    assert coordinator.learned_wake_frame is None
    assert coordinator.active_beverage_id is None


def test_corrupt_and_truncated_frames_cannot_become_learned_commands():
    coordinator, _client = _coordinator("DL-striker-cb")
    valid = cb.build_statistics_request_command(0xC0FFEE11, timestamp=1)
    for length in range(len(valid) + 1):
        decoded = cb.decode_command(base64.b64encode(valid[:length]).decode())
        assert decoded.get("type") not in {"power", "beverage"}
        coordinator._maybe_learn_frame(decoded)
    for offset in range(7):
        altered = bytearray(valid)
        altered[offset] ^= 1
        decoded = cb.decode_command(base64.b64encode(altered).decode())
        if decoded.get("type") == "statistics_request":
            # Prefix and length are not checked by this diagnostic decoder.
            assert decoded["crc_valid"] is False
        coordinator._maybe_learn_frame(decoded)
    assert not coordinator.learned_start_frames
    assert not coordinator.learned_stop_frames
    assert coordinator.learned_wake_frame is None


@pytest.mark.parametrize(
    ("previous", "following", "expected"),
    [
        ({"status": 7, "step": 11}, {"status": 7, "step": 0}, True),
        ({"status": 7, "step": 1}, {"status": 7, "step": 0}, True),
        ({"status": 10, "step": 0}, {"status": 7, "step": 0}, True),
        ({"status": 11, "step": 0}, {"status": 7, "step": 0}, True),
        ({"status": 7, "step": 0}, {"status": 7, "step": 0}, False),
        ({"status": 0, "step": 2}, {"status": 7, "step": 0}, False),
        ({"status": 1, "step": 0}, {"status": 7, "step": 0}, False),
        ({"status": 8, "step": 0}, {"status": 7, "step": 0}, False),
        ({"status": 12, "step": 0}, {"status": 7, "step": 0}, False),
        ({"status": 7, "step": 11}, {"status": 7, "step": 10}, False),
        ({"status": 7, "step": 11}, {"status": 0, "step": 2}, False),
        ({"status": 7, "step": 11}, {"error": "bad monitor"}, False),
    ],
)
def test_monitor_transitions_only_schedule_when_preparation_becomes_ready(monkeypatch, previous, following, expected):
    coordinator, _client = _coordinator("DL-striker-cb")
    coordinator.monitor = dict(previous)
    schedule = Mock()
    coordinator._schedule_post_command_refresh = schedule
    monkeypatch.setattr(cm, "parse_monitor_b64", lambda _value: dict(following))
    monkeypatch.setattr(cm, "monitor_ordering_token", lambda _value: None)
    assert coordinator.handle_dss_event(_dss_event(property_name="d302_monitor_machine", value="synthetic"))
    assert schedule.call_count == int(expected)
    if expected:
        schedule.assert_called_once_with(trigger="beverage_finished")


def test_duplicate_and_out_of_order_finish_events_cannot_schedule_again(monkeypatch):
    coordinator, _client = _coordinator("DL-striker-cb")
    coordinator.monitor = {"status": 7, "step": 11}
    coordinator._monitor_ordering_token = 100
    schedule = Mock()
    coordinator._schedule_post_command_refresh = schedule
    monkeypatch.setattr(cm, "parse_monitor_b64", lambda _value: {"status": 7, "step": 0})
    monkeypatch.setattr(cm, "monitor_ordering_token", lambda value: int(value))
    assert coordinator.handle_dss_event(_dss_event(sequence="1", property_name="d302_monitor_machine", value="99"))
    schedule.assert_not_called()
    assert coordinator.handle_dss_event(_dss_event(sequence="2", property_name="d302_monitor_machine", value="101"))
    assert not coordinator.handle_dss_event(_dss_event(sequence="2", property_name="d302_monitor_machine", value="101"))
    assert not coordinator.handle_dss_event(_dss_event(sequence="1", property_name="d302_monitor_machine", value="99"))
    schedule.assert_called_once_with(trigger="beverage_finished")


@pytest.mark.parametrize("guard", ["offline", "busy", "locked", "unsigned", "foreign"])
def test_new_trigger_keeps_write_safety_guards(guard):
    async def scenario():
        coordinator, client = _coordinator("DL-striker-cb")
        coordinator.connected_property = "app_device_connected"
        coordinator.monitor = {"status": 7, "step": 0}
        coordinator.has_device_signature = lambda: guard != "unsigned"
        coordinator._with_cloud_session = AsyncMock()
        if guard == "offline":
            coordinator.device.connection_status = "offline"
        elif guard == "busy":
            coordinator.monitor = {"status": 7, "step": 11}
        elif guard == "locked":
            await coordinator._command_lock.acquire()
        elif guard == "foreign":
            coordinator._with_cloud_session.side_effect = cm.translated_error("cloud_session_in_use")
        expected = {
            "offline": "skipped_offline",
            "busy": "skipped_busy",
            "locked": "skipped_busy",
            "unsigned": "skipped_unsupported",
            "foreign": "skipped_foreign_session",
        }[guard]
        try:
            assert await coordinator.async_synchronize_statistics(automatic=True, trigger="beverage_finished") == expected
            assert client.writes == []
            assert coordinator.last_command_result is None
        finally:
            if coordinator._command_lock.locked():
                coordinator._command_lock.release()

    asyncio.run(scenario())


def test_repeated_finish_requests_coalesce_into_one_refresh(monkeypatch):
    async def scenario():
        coordinator, _client = _coordinator("DL-striker-cb")
        coordinator.monitor = {"status": 7, "step": 0}
        coordinator.async_synchronize_statistics = AsyncMock(return_value="completed_updated")
        monkeypatch.setattr(cm, "POST_COMMAND_REFRESH_DELAY", 0)
        tasks = []
        for _ in range(10):
            coordinator._schedule_post_command_refresh(trigger="beverage_finished")
            tasks.append(coordinator._post_command_refresh_task)
        await asyncio.gather(*tasks, return_exceptions=True)
        coordinator.async_synchronize_statistics.assert_awaited_once_with(automatic=True, trigger="beverage_finished")

    asyncio.run(scenario())


def test_shutdown_cancels_scheduled_finish_refresh_without_writing(monkeypatch):
    async def scenario():
        coordinator, client = _coordinator("DL-striker-cb")
        coordinator.async_synchronize_statistics = AsyncMock()
        monkeypatch.setattr(cm, "POST_COMMAND_REFRESH_DELAY", 60)
        coordinator._schedule_post_command_refresh(trigger="beverage_finished")
        task = coordinator._post_command_refresh_task
        await coordinator.async_shutdown()
        with suppress(asyncio.CancelledError):
            await task
        assert task.cancelled()
        coordinator.async_synchronize_statistics.assert_not_awaited()
        assert client.writes == []

    asyncio.run(scenario())


def test_legacy_profile_retains_read_only_refresh(monkeypatch):
    async def scenario():
        coordinator, client = _coordinator("DL-millcore")
        coordinator.monitor = {"status": 7, "step": 0}
        coordinator.async_request_refresh = AsyncMock()
        monkeypatch.setattr(cm, "POST_COMMAND_REFRESH_DELAY", 0)
        coordinator._schedule_post_command_refresh(trigger="beverage_finished")
        await coordinator._post_command_refresh_task
        coordinator.async_request_refresh.assert_awaited_once()
        assert client.writes == []

    asyncio.run(scenario())


def test_late_counter_update_reproduces_premature_unchanged_diagnostic(monkeypatch):
    """Evidence of a timing limitation, not an acceptance assertion for a fix."""

    async def scenario():
        coordinator, _client = _coordinator("DL-striker-cb")
        coordinator.connected_property = "app_device_connected"
        coordinator.has_device_signature = lambda: True
        coordinator.monitor = {"status": 0, "step": 2}
        coordinator.data = {"d701_tot_bev_b": {"value": 100}}
        coordinator._with_cloud_session = AsyncMock()
        coordinator.async_request_refresh = AsyncMock()
        monkeypatch.setattr(cm, "STATISTICS_SYNC_SETTLE_DELAY", 0.001)
        assert await coordinator.async_synchronize_statistics(automatic=True) == "completed_unchanged"
        coordinator.handle_dss_event(_dss_event(property_name="d701_tot_bev_b", value=101))
        assert coordinator.data["d701_tot_bev_b"]["value"] == 101
        assert coordinator.last_statistics_sync_result == "completed_unchanged"
        assert coordinator.last_statistics_sync_snapshot_changed is False

    asyncio.run(scenario())


def test_single_unrelated_counter_event_can_end_settle_before_actual_statistics(monkeypatch):
    """A different d5 property currently satisfies the generic settle event."""

    async def scenario():
        coordinator, _client = _coordinator("DL-striker-cb")
        coordinator.connected_property = "app_device_connected"
        coordinator.has_device_signature = lambda: True
        coordinator.monitor = {"status": 7, "step": 0}
        coordinator.data = {"d701_tot_bev_b": {"value": 100}}

        async def unrelated_update(_send):
            coordinator.handle_dss_event(_dss_event(property_name="d556_water_hardness", value=2))

        coordinator._with_cloud_session = unrelated_update
        coordinator.async_request_refresh = AsyncMock()
        assert await coordinator.async_synchronize_statistics(automatic=True) == "completed_updated"
        assert coordinator.data["d701_tot_bev_b"]["value"] == 100
        # "updated" does not prove the intended drink counter changed.
        assert coordinator.last_statistics_sync_snapshot_changed is True

    asyncio.run(scenario())
