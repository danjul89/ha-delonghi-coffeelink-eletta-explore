"""Coordinator coverage for hybrid DSS updates and diagnostics."""

from __future__ import annotations

import asyncio
import types
from collections.abc import Coroutine
from contextlib import suppress
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from test_reliability import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    _coordinator,
    ayla_client,
    const,
    coordinator_module,
    errors_module,
)

cm = coordinator_module


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


def _dss_event(**changes: Any) -> Any:
    values = {
        "sequence": "1",
        "event_type": "datapoint",
        "dsn": "private-device-id",
        "property_name": "counter",
        "datapoint_id": "dp-1",
        "value": 2,
        "updated_at": "2026-08-20T12:00:00Z",
        "acked_at": None,
        "ack_status": None,
        "ack_message": None,
    }
    values.update(changes)
    return cm.DssEvent(**values)


def test_poll_merge_and_connection_info_are_privacy_safe() -> None:
    coordinator, client = _coordinator()
    coordinator.data = {
        "newer": {"value": 2, "data_updated_at": "2026-08-20T12:00:02Z"},
        "older": {"value": 1, "dataUpdatedAt": "2026-08-20T12:00:00Z"},
        "invalid": "value",
    }
    props = {
        "newer": {"value": 1, "data_updated_at": "2026-08-20T12:00:01Z"},
        "older": {"value": 2, "data_updated_at": "2026-08-20T12:00:01Z"},
        "invalid": {"value": 3},
        "missing": "value",
    }
    merged = coordinator._merge_poll_with_push(props)
    assert merged["newer"]["value"] == 2
    assert merged["older"]["value"] == 2

    async def scenario() -> None:
        client.async_get_connection_info = AsyncMock(
            return_value={
                "connectivityType": "Wifi",
                "rssi": "-57",
                "networkName": "secret",
            }
        )
        # A freshly booted host can have a monotonic clock below the one-hour
        # refresh interval. The first diagnostic read must still run.
        await coordinator._async_refresh_connection_info(1)
        assert coordinator.connection_info == {
            "connectivity_type": "Wifi",
            "rssi": -57,
        }
        assert "secret" not in str(coordinator.connection_info)
        await coordinator._async_refresh_connection_info(2)
        assert client.async_get_connection_info.await_count == 1

        coordinator._last_connection_info_refresh = 0
        client.async_get_connection_info = AsyncMock(return_value={"connectivity_type": 3, "rssi": "invalid"})
        await coordinator._async_refresh_connection_info(8000)
        assert coordinator.connection_info == {
            "connectivity_type": None,
            "rssi": None,
        }

        coordinator._last_connection_info_refresh = 0
        client.async_get_connection_info = AsyncMock(side_effect=ayla_client.CloudError("missing", http_status=404))
        await coordinator._async_refresh_connection_info(12000)
        assert coordinator._connection_info_supported is False
        await coordinator._async_refresh_connection_info(16000)

        coordinator._connection_info_supported = None
        coordinator._last_connection_info_refresh = 0
        client.async_get_connection_info = AsyncMock(side_effect=ayla_client.CloudError("temporary", http_status=503))
        await coordinator._async_refresh_connection_info(20000)
        assert coordinator._connection_info_supported is None

    run(scenario())


def test_monitor_rejects_older_official_ordering_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, _client = _coordinator()
    parsed = {
        "status": 7,
        "status_name": "ready",
        "step": 0,
        "progress_percentage": 0,
        "accessory": 0,
    }
    monkeypatch.setattr(cm, "parse_monitor_b64", lambda _value: dict(parsed))
    monkeypatch.setattr(cm, "monitor_ordering_token", Mock(side_effect=[20, 10]))
    coordinator._update_monitor({"d302_monitor_machine": {"value": "new"}})
    newest = dict(coordinator.monitor)
    coordinator._update_monitor({"d302_monitor_machine": {"value": "old"}})
    assert coordinator.monitor == newest
    assert coordinator._monitor_ordering_token == 20


def test_finished_beverage_schedules_statistics_request(monkeypatch: pytest.MonkeyPatch) -> None:
    coordinator, _client = _coordinator()
    frames = iter(
        [
            {"status": 7, "step": 11, "progress_percentage": 40},  # brewing at the machine
            {"status": 7, "step": 0, "progress_percentage": 0},  # back to ready
            {"status": 7, "step": 0, "progress_percentage": 0},  # still ready
            {"status": 0, "step": 2, "progress_percentage": 100},  # standby
        ]
    )
    monkeypatch.setattr(cm, "parse_monitor_b64", lambda _value: next(frames))
    monkeypatch.setattr(cm, "monitor_ordering_token", lambda _value: None)
    schedule = Mock()
    coordinator._schedule_post_command_refresh = schedule

    for sequence in ("1", "2", "3", "4"):
        coordinator.handle_dss_event(_dss_event(sequence=sequence, property_name="d302_monitor_machine", value="frame"))
    schedule.assert_called_once_with(trigger="beverage_finished")
    assert not coordinator._machine_is_ready()


def test_dss_state_switches_polling_interval_and_refreshes_on_loss() -> None:
    async def scenario() -> None:
        coordinator, _client = _coordinator()
        coordinator._dss_sequences[("datapoint", "counter")] = 5
        coordinator.async_request_refresh = AsyncMock()
        coordinator.set_dss_state("streaming")
        assert coordinator.update_interval.total_seconds() == const.DSS_FALLBACK_SCAN_INTERVAL
        assert coordinator._dss_sequences == {}
        coordinator.set_dss_state("polling", request_refresh=True)
        task = coordinator._dss_fallback_refresh_task
        coordinator.set_dss_state("polling", request_refresh=True)
        assert coordinator._dss_fallback_refresh_task is task
        await task
        coordinator.async_request_refresh.assert_awaited_once()
        assert coordinator.update_interval.total_seconds() == const.DEFAULT_SCAN_INTERVAL

    run(scenario())


def test_dss_sequence_ack_cache_and_event_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator, _client = _coordinator("DL-striker-cb")
    assert coordinator._normalized_dss_sequence(None) is None
    assert coordinator._normalized_dss_sequence("5") == 5
    assert coordinator._normalized_dss_sequence("x") == "x"
    assert coordinator._accept_dss_sequence(_dss_event(sequence=None)) is True
    assert coordinator._accept_dss_sequence(_dss_event(sequence="2")) is True
    assert coordinator._accept_dss_sequence(_dss_event(sequence="1")) is False
    assert coordinator._accept_dss_sequence(_dss_event(sequence="3")) is True
    assert coordinator._accept_dss_sequence(_dss_event(sequence="x")) is True
    assert coordinator._accept_dss_sequence(_dss_event(sequence="x")) is False

    coordinator._dss_sequences.clear()
    assert coordinator.handle_dss_event(_dss_event(sequence="1")) is True
    assert coordinator.data["counter"]["value"] == 2
    assert coordinator.handle_dss_event(_dss_event(sequence="1")) is False
    assert (
        coordinator.handle_dss_event(
            _dss_event(
                sequence="2",
                event_type="connectivity",
                property_name=None,
                datapoint_id=None,
            )
        )
        is False
    )

    coordinator._dss_sequences.clear()
    assert (
        coordinator.handle_dss_event(
            _dss_event(
                event_type="datapointack",
                property_name=None,
                ack_status=200,
            )
        )
        is True
    )
    assert coordinator._recent_dss_acks["dp-1"] == 200

    assert (
        coordinator.handle_dss_event(
            _dss_event(
                sequence="2",
                event_type="datapointack",
                value=None,
                updated_at=None,
                acked_at="2026-08-20T12:00:01Z",
                ack_status=202,
                ack_message="accepted",
            )
        )
        is True
    )
    assert coordinator.data["counter"]["acked_at"] == "2026-08-20T12:00:01Z"
    assert coordinator.data["counter"]["ack_status"] == 202
    assert coordinator.data["counter"]["ack_message"] == "accepted"

    coordinator.data["counter"]["data_updated_at"] = "2026-08-20T12:00:05Z"
    coordinator._dss_sequences.clear()
    assert coordinator.handle_dss_event(_dss_event(updated_at="2026-08-20T12:00:04Z")) is False

    monitor = Mock()
    sniff = Mock()
    session = Mock()
    monkeypatch.setattr(coordinator, "_update_monitor", monitor)
    monkeypatch.setattr(coordinator, "_sniff_app_traffic", sniff)
    monkeypatch.setattr(coordinator, "_update_session_from_props", session)
    coordinator.command_property = "command"
    coordinator.response_property = "response"
    coordinator._dss_sequences.clear()
    coordinator.handle_dss_event(_dss_event(sequence="3", property_name="d302_monitor_machine", value="frame"))
    coordinator.handle_dss_event(_dss_event(sequence="4", property_name="command", value="frame"))
    coordinator.handle_dss_event(_dss_event(sequence="5", property_name=const.APP_ID_PROPERTY, value=0))
    notify = Mock()
    monkeypatch.setattr(coordinator, "_notify_command_state_waiters", notify)
    coordinator.handle_dss_event(_dss_event(sequence="6", property_name="response", value="ack"))
    monitor.assert_called_once()
    assert sniff.call_count == 2
    session.assert_called_once()
    notify.assert_called_once()

    async def waiter_scenario() -> None:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        coordinator._dss_ack_waiters["live"] = future
        coordinator._remember_dss_ack("live", 201)
        assert await future == 201
        coordinator._remember_dss_ack("live", 202)
        assert coordinator._recent_dss_acks["live"] == 202
        for index in range(40):
            coordinator._remember_dss_ack(f"cached-{index}", 200)
        assert len(coordinator._recent_dss_acks) <= 32

    run(waiter_scenario())


def test_statistics_snapshot_helpers_and_dss_notification() -> None:
    coordinator, _client = _coordinator("DL-striker-cb")
    assert coordinator._statistics_snapshot_marker(None) is None
    assert coordinator._statistics_snapshot_marker({"app_id": {"value": 1}, "d500_bad": "value"}) is None
    first = coordinator._statistics_snapshot_marker(
        {
            "d553_water_tot_qty": {"value": 100, "dataUpdatedAt": "one"},
            "d555_water_filter_qty": {"value": 10, "updated_at": "two"},
        }
    )
    second = coordinator._statistics_snapshot_marker(
        {
            "d553_water_tot_qty": {"value": 101, "data_updated_at": "three"},
            "d555_water_filter_qty": {"value": 10},
        }
    )
    assert first is not None and second is not None and first != second

    for monitor, preparing in (
        ({}, False),
        ({"status": 7, "step": 0}, False),
        ({"status": 7, "step": 3}, True),
        ({"status": 10, "step": 0}, True),
    ):
        coordinator.monitor = monitor
        assert coordinator._machine_is_preparing() is preparing

    coordinator._dss_sequences.clear()
    assert not coordinator._statistics_update_event.is_set()
    coordinator.handle_dss_event(_dss_event(property_name="d553_water_tot_qty"))
    assert coordinator._statistics_update_event.is_set()


def test_snapshot_refresh_write_tracks_exact_ack_without_touching_command_state() -> None:
    async def scenario() -> None:
        coordinator, client = _coordinator("DL-striker-cb")
        coordinator.command_property = None
        client.async_set_property_value = AsyncMock(return_value=None)
        await coordinator._send_statistics_refresh()
        assert client.async_set_property_value.await_args.args[1] == const.COMMAND_PROPERTY_CANDIDATES[0]
        sent = cm.decode_command(client.async_set_property_value.await_args.args[2])
        assert sent["type"] == "statistics_request"
        assert sent["crc_valid"] is True
        assert coordinator.last_command_result is None

        coordinator.command_property = "app_data_request"
        coordinator.data = {"app_data_request": {"ack_enabled": True}}
        client.async_set_property_value = AsyncMock(return_value={"datapoint": {"id": "dp-ok"}})
        coordinator._async_wait_for_dss_ack = AsyncMock(return_value=(True, 202))
        await coordinator._send_statistics_refresh()
        assert coordinator.last_statistics_sync_ack_status == 202
        assert coordinator.last_command_result is None

        coordinator._async_wait_for_dss_ack = AsyncMock(return_value=(False, None))
        await coordinator._send_statistics_refresh()
        assert coordinator.last_statistics_sync_ack_status == 202

        coordinator._async_wait_for_dss_ack = AsyncMock(return_value=(True, 409))
        with pytest.raises(HomeAssistantError, match="rejected"):
            await coordinator._send_statistics_refresh()

    run(scenario())


def test_cloud_snapshot_refresh_success_skip_and_manual_error_paths() -> None:
    async def scenario() -> None:
        coordinator, client = _coordinator("DL-striker-cb")
        coordinator.connected_property = "app_device_connected"
        coordinator.learned_start_frames[1] = "DRGD8AECAQAoAgQIABsBCn5oaiRo7xEiM0Q="
        coordinator._restore_device_app_id()
        coordinator.data = {"d553_water_tot_qty": {"value": 100, "data_updated_at": "old"}}
        coordinator.monitor = {"status": 7, "step": 0}
        client.async_set_property_value = AsyncMock(return_value=None)

        async def with_session(send: Any) -> None:
            await send()
            coordinator._statistics_update_event.set()

        async def refresh_changed() -> None:
            coordinator.data = {"d553_water_tot_qty": {"value": 101, "data_updated_at": "new"}}

        coordinator._with_cloud_session = with_session
        coordinator.async_request_refresh = refresh_changed
        assert await coordinator.async_synchronize_statistics() == "completed_updated"
        assert coordinator.statistics_sync_attempts == 1
        assert coordinator.statistics_sync_successes == 1
        assert coordinator.last_statistics_sync_trigger == "manual"
        assert coordinator.last_statistics_sync_snapshot_changed is True
        assert coordinator.last_statistics_sync_attempt_at.endswith("+00:00")
        assert coordinator.last_statistics_sync_success_at.endswith("+00:00")
        assert coordinator.last_command_result is None
        client.async_set_property_value.assert_awaited_once()

        coordinator._statistics_update_event.set()
        coordinator.async_request_refresh = AsyncMock()
        assert await coordinator.async_synchronize_statistics(trigger="test") == "completed_unchanged"

        coordinator.data = {}
        coordinator.profile = types.SimpleNamespace(uses_cloud_session=False)
        assert await coordinator.async_synchronize_statistics() == "completed_unverified"

        coordinator.device.connection_status = "offline"
        assert await coordinator.async_synchronize_statistics(automatic=True) == "skipped_offline"
        with pytest.raises(HomeAssistantError, match="not connected"):
            await coordinator.async_synchronize_statistics()

        coordinator.device.connection_status = "online"
        coordinator.profile = types.SimpleNamespace(uses_cloud_session=True)
        coordinator.connected_property = None
        assert await coordinator.async_synchronize_statistics(automatic=True) == "skipped_unsupported"
        with pytest.raises(HomeAssistantError, match="has been learned"):
            await coordinator.async_synchronize_statistics()

    run(scenario())


def test_cloud_snapshot_refresh_busy_foreign_and_failure_paths() -> None:
    async def scenario() -> None:
        coordinator, _client = _coordinator("DL-striker-cb")
        coordinator.connected_property = "app_device_connected"
        coordinator.learned_start_frames[1] = "DRGD8AECAQAoAgQIABsBCn5oaiRo7xEiM0Q="
        coordinator.monitor = {"status": 7, "step": 2}
        assert await coordinator.async_synchronize_statistics(automatic=True) == "skipped_busy"
        with pytest.raises(HomeAssistantError, match="still in progress"):
            await coordinator.async_synchronize_statistics()

        coordinator.monitor = {"status": 7, "step": 0}
        await coordinator._command_lock.acquire()
        assert await coordinator.async_synchronize_statistics(automatic=True) == "skipped_busy"
        coordinator._command_lock.release()

        checks = iter([False, True])
        coordinator._machine_is_preparing = Mock(side_effect=lambda: next(checks))
        assert await coordinator.async_synchronize_statistics(automatic=True) == "skipped_busy"

        checks = iter([False, True])
        coordinator._machine_is_preparing = Mock(side_effect=lambda: next(checks))
        with pytest.raises(HomeAssistantError, match="still in progress"):
            await coordinator.async_synchronize_statistics()

        coordinator._machine_is_preparing = Mock(return_value=False)
        coordinator._with_cloud_session = AsyncMock(side_effect=errors_module.translated_error("cloud_session_in_use"))
        assert await coordinator.async_synchronize_statistics(automatic=True) == "skipped_foreign_session"
        with pytest.raises(HomeAssistantError, match="Coffee Link cloud session"):
            await coordinator.async_synchronize_statistics()

        coordinator._with_cloud_session = AsyncMock(side_effect=ayla_client.CloudError("cloud"))
        assert await coordinator.async_synchronize_statistics(automatic=True) == "failed"
        with pytest.raises(HomeAssistantError, match="cloud command could not"):
            await coordinator.async_synchronize_statistics()

        coordinator._with_cloud_session = AsyncMock(side_effect=ayla_client.AuthError("auth"))
        with pytest.raises(Exception, match="credentials"):
            await coordinator.async_synchronize_statistics()

        coordinator._with_cloud_session = AsyncMock(side_effect=ConfigEntryAuthFailed("reauth"))
        assert await coordinator.async_synchronize_statistics(automatic=True) == "failed_authentication"
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator.async_synchronize_statistics()

    run(scenario())


def test_snapshot_refresh_timeout_falls_back_to_poll_and_post_command_uses_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        coordinator, _client = _coordinator("DL-striker-cb")
        coordinator.connected_property = "app_device_connected"
        coordinator.learned_start_frames[1] = "DRGD8AECAQAoAgQIABsBCn5oaiRo7xEiM0Q="
        coordinator.monitor = {"status": 7, "step": 0}
        coordinator.data = {"d553_water_tot_qty": {"value": 100}}
        coordinator._with_cloud_session = AsyncMock()
        coordinator._statistics_update_event.wait = AsyncMock(side_effect=TimeoutError)
        coordinator.async_request_refresh = AsyncMock()
        assert await coordinator.async_synchronize_statistics() == "completed_unchanged"
        coordinator.async_request_refresh.assert_awaited_once()

        coordinator.async_synchronize_statistics = AsyncMock(return_value="completed_updated")
        coordinator.async_request_refresh.reset_mock()
        monkeypatch.setattr(cm, "POST_COMMAND_REFRESH_DELAY", 0)
        coordinator._schedule_post_command_refresh()
        await coordinator._post_command_refresh_task
        coordinator.async_synchronize_statistics.assert_awaited_once_with(automatic=True, trigger="post_command")
        coordinator.async_request_refresh.assert_not_awaited()

        coordinator.async_synchronize_statistics.reset_mock()
        coordinator._schedule_post_command_refresh(trigger="beverage_finished")
        await coordinator._post_command_refresh_task
        coordinator.async_synchronize_statistics.assert_awaited_once_with(automatic=True, trigger="beverage_finished")

        coordinator.async_synchronize_statistics = AsyncMock(return_value="skipped_busy")
        coordinator._post_command_refresh_task = None
        coordinator._schedule_post_command_refresh()
        await coordinator._post_command_refresh_task
        coordinator.async_request_refresh.assert_awaited_once()

    run(scenario())


def test_automatic_snapshot_scheduling_intervals_exceptions_and_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        original_sleep = asyncio.sleep
        coordinator, _client = _coordinator()
        coordinator._schedule_automatic_statistics_sync(100)
        assert coordinator._automatic_statistics_sync_task is None

        coordinator, _client = _coordinator("DL-striker-cb")
        coordinator._schedule_automatic_statistics_sync(100)
        assert coordinator._automatic_statistics_sync_task is None
        coordinator.connected_property = "app_device_connected"
        coordinator._schedule_automatic_statistics_sync(100)
        assert coordinator._automatic_statistics_sync_task is None
        coordinator.learned_start_frames[1] = "DRGD8AECAQAoAgQIABsBCn5oaiRo7xEiM0Q="
        coordinator.device.connection_status = "offline"
        coordinator._schedule_automatic_statistics_sync(100)
        assert coordinator._automatic_statistics_sync_task is None

        coordinator.device.connection_status = "online"
        sleeps: list[float] = []

        async def capture_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr(cm.asyncio, "sleep", capture_sleep)
        coordinator.async_synchronize_statistics = AsyncMock()
        coordinator._schedule_automatic_statistics_sync(100)
        active = coordinator._automatic_statistics_sync_task
        coordinator._schedule_automatic_statistics_sync(100)
        assert coordinator._automatic_statistics_sync_task is active
        await active
        assert sleeps == [const.STATISTICS_SYNC_STARTUP_DELAY]
        coordinator.async_synchronize_statistics.assert_awaited_once_with(automatic=True, trigger="automatic")

        coordinator._last_statistics_sync_attempt_monotonic = 100
        coordinator.last_statistics_sync_result = "completed_updated"
        coordinator._schedule_automatic_statistics_sync(200)
        await coordinator._automatic_statistics_sync_task
        assert sleeps[-1] == const.STATISTICS_SYNC_INTERVAL - 100

        coordinator.last_statistics_sync_result = "failed"
        coordinator.async_synchronize_statistics = AsyncMock(side_effect=RuntimeError("optional"))
        coordinator._schedule_automatic_statistics_sync(700)
        await coordinator._automatic_statistics_sync_task
        assert sleeps[-1] == 0

        async def blocking_sleep(_delay: float) -> None:
            await asyncio.Event().wait()

        monkeypatch.setattr(cm.asyncio, "sleep", blocking_sleep)
        coordinator.async_synchronize_statistics = AsyncMock()
        coordinator._automatic_statistics_sync_task = None
        coordinator._last_statistics_sync_attempt_monotonic = None
        coordinator._schedule_automatic_statistics_sync(800)
        task = coordinator._automatic_statistics_sync_task
        await original_sleep(0)
        await coordinator.async_shutdown()
        with suppress(asyncio.CancelledError):
            await task
        assert coordinator._automatic_statistics_sync_task is None

    run(scenario())


def test_exact_dss_ack_wait_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    # Match the default acknowledgement window in Coffee Link's bundled Ayla SDK.
    assert const.DSS_ACK_GRACE_PERIOD == 10

    async def scenario() -> None:
        coordinator, _client = _coordinator()
        assert await coordinator._async_wait_for_dss_ack("one") == (False, None)
        coordinator.dss_state = "streaming"
        coordinator._recent_dss_acks["cached"] = 200
        assert await coordinator._async_wait_for_dss_ack("cached") == (True, 200)

        task = asyncio.create_task(coordinator._async_wait_for_dss_ack("live"))
        await asyncio.sleep(0)
        coordinator._remember_dss_ack("live", None)
        assert await task == (True, None)

        class AckArrivesBetweenChecks(dict[str, int]):
            checks = 0

            def __contains__(self, key: object) -> bool:
                self.checks += 1
                return self.checks > 1

        coordinator._recent_dss_acks = AckArrivesBetweenChecks(race=204)
        assert await coordinator._async_wait_for_dss_ack("race") == (True, 204)
        coordinator._recent_dss_acks = {}

        monkeypatch.setattr(cm, "DSS_ACK_GRACE_PERIOD", 0)
        assert await coordinator._async_wait_for_dss_ack("timeout") == (False, None)

    run(scenario())


def test_send_property_command_prefers_exact_ack_and_handles_rejection() -> None:
    async def scenario() -> None:
        coordinator, client = _coordinator()
        client.async_set_property_value = AsyncMock(return_value={"datapoint": {"id": "exact"}})
        coordinator.data = {coordinator.command_property: {"ack_enabled": True}}
        coordinator._begin_command({"command_type": "test"})
        coordinator._async_wait_for_dss_ack = AsyncMock(return_value=(True, 200))
        await coordinator._send_property_command("frame", "test")
        assert coordinator.last_command_result == "acknowledged"
        assert coordinator.last_command["confirmation_source"] == "dss_ack"
        assert coordinator.last_command["ack_status"] == 200

        coordinator._begin_command({"command_type": "test"})
        coordinator._async_wait_for_dss_ack = AsyncMock(return_value=(True, 400))
        with pytest.raises(HomeAssistantError, match="explicitly rejected"):
            await coordinator._send_property_command("frame", "test")
        assert coordinator.last_command_result == "rejected"
        assert coordinator.last_command["ack_status"] == 400

        coordinator._begin_command({"command_type": "test"})
        coordinator._async_wait_for_dss_ack = AsyncMock(return_value=(True, 0))
        coordinator._wait_for_command_confirmation = AsyncMock(return_value=True)
        await coordinator._send_property_command("frame", "test", confirmation_timeout=1)
        assert coordinator.last_command["confirmation_source"] == "cloud_state"

        coordinator._begin_command({"command_type": "test"})
        coordinator._async_wait_for_dss_ack = AsyncMock(return_value=(True, None))
        coordinator._wait_for_command_confirmation = AsyncMock(return_value=True)
        await coordinator._send_property_command("frame", "test")

        coordinator.last_command = None
        coordinator._async_wait_for_dss_ack = AsyncMock(return_value=(True, 200))
        await coordinator._send_property_command("frame", "test")
        assert coordinator.last_command_result == "acknowledged"

        coordinator.last_command = None
        coordinator._async_wait_for_dss_ack = AsyncMock(return_value=(True, 400))
        with pytest.raises(HomeAssistantError, match="explicitly rejected"):
            await coordinator._send_property_command("frame", "test")

    run(scenario())


def test_command_ack_capability_and_disabled_fallback() -> None:
    async def scenario() -> None:
        coordinator, client = _coordinator()
        coordinator.command_property = None
        assert coordinator.command_ack_enabled is None
        coordinator.command_property = "data_request"
        coordinator.data = None
        assert coordinator.command_ack_enabled is None
        coordinator.data = {coordinator.command_property: "unexpected"}
        assert coordinator.command_ack_enabled is None
        coordinator.data = {coordinator.command_property: {"ackEnabled": "unknown"}}
        assert coordinator.command_ack_enabled is None
        coordinator.data = {coordinator.command_property: {"ackEnabled": False}}
        assert coordinator.command_ack_enabled is False

        client.async_set_property_value = AsyncMock(return_value={"datapoint": {"id": "not-ack-enabled"}})
        coordinator._begin_command({"command_type": "test"})
        coordinator._async_wait_for_dss_ack = AsyncMock()
        coordinator._wait_for_command_confirmation = AsyncMock(return_value=True)
        await coordinator._send_property_command("frame", "test")
        coordinator._async_wait_for_dss_ack.assert_not_awaited()
        assert coordinator.last_command["confirmation_source"] == "cloud_state"

    run(scenario())


def test_confirmation_checks_push_state_before_poll() -> None:
    async def scenario() -> None:
        coordinator, _client = _coordinator()
        coordinator.response_property = "response"
        coordinator._last_resp_marker = "new"
        coordinator.async_request_refresh = AsyncMock()
        assert await coordinator._wait_for_command_confirmation(("old", {})) is True
        coordinator.async_request_refresh.assert_not_awaited()

        coordinator.response_property = None
        coordinator.monitor = {"status": 7}
        assert await coordinator._wait_for_command_confirmation((None, {"status": 0})) is True

    run(scenario())


def test_shutdown_cancels_dss_refresh_and_ack_waiters() -> None:
    async def scenario() -> None:
        coordinator, _client = _coordinator()
        refresh = asyncio.create_task(asyncio.sleep(30))
        waiter = asyncio.get_running_loop().create_future()
        coordinator._dss_fallback_refresh_task = refresh
        coordinator._dss_ack_waiters["id"] = waiter
        await coordinator.async_shutdown()
        await asyncio.sleep(0)
        assert refresh.cancelled()
        assert waiter.cancelled()
        assert coordinator._dss_ack_waiters == {}

    run(scenario())
