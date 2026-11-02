"""DataUpdateCoordinator for De'Longhi Coffee Link – Eletta Explore."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import TYPE_CHECKING, Any, NoReturn

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .ayla_client import (
    AuthError,
    AylaDevice,
    AylaProperties,
    CloudError,
    DelonghiAylaClient,
    RateLimitError,
    normalize_signed_app_id,
)
from .command_builder import (
    build_and_encode,
    build_session_refresh_encoded,
    build_standby_encoded,
    build_standby_with_session_tail_encoded,
    build_statistics_request_encoded,
    build_wake_encoded,
    build_wake_with_session_tail_encoded,
    decode_command,
    deserialize_learned_frames,
    device_signature_from_frame,
    is_wake_power_frame,
    recipe_dump_lines,
    replay_with_timestamp,
    serialize_learned_frames,
    validate_replayed_beverage_frame,
    validate_replayed_wake_frame,
)
from .command_confirmation import CommandConfirmationTracker
from .const import (
    ACTION_START,
    ACTION_STOP,
    APP_ID_PROPERTY,
    BEVERAGES,
    COMMAND_CONFIRM_POLL_INTERVAL,
    COMMAND_CONFIRM_TIMEOUT,
    COMMAND_PROPERTY_CANDIDATES,
    CONNECT_CONFIRM_POLL_INTERVAL,
    CONNECT_CONFIRM_TIMEOUT,
    CONNECT_REFRESH_INTERVAL,
    CONNECT_SETTLE_DELAY,
    CONNECTED_PROPERTY_CANDIDATES,
    CONNECTION_INFO_REFRESH_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_METADATA_REFRESH_INTERVAL,
    DOMAIN,
    DSS_ACK_GRACE_PERIOD,
    DSS_FALLBACK_SCAN_INTERVAL,
    ELETTA_LEARNED_BEVERAGES,
    INTEGRATION_CLOUD_APP_ID,
    MONITOR_PROPERTY_CANDIDATES,
    POST_COMMAND_REFRESH_DELAY,
    POWER_COMMAND_CONFIRM_TIMEOUT,
    POWER_STANDBY_PARAMS,
    POWER_WAKE_PARAMS,
    RECIPE_STORE_SAVE_DELAY,
    RECIPE_STORE_VERSION,
    RESPONSE_PROPERTY_CANDIDATES,
    STATISTICS_PROPERTY_PREFIXES,
    STATISTICS_SYNC_INTERVAL,
    STATISTICS_SYNC_RETRY_INTERVAL,
    STATISTICS_SYNC_SETTLE_DELAY,
    STATISTICS_SYNC_STARTUP_DELAY,
)
from .dss import DssEvent
from .errors import translated_auth_error, translated_error
from .model_profiles import profile_for
from .monitor import monitor_ordering_token, parse_monitor_b64

if TYPE_CHECKING:
    from . import DelonghiConfigEntry

_LOGGER = logging.getLogger(__name__)


class DelonghiCoordinator(DataUpdateCoordinator[AylaProperties]):
    """Periodically fetch device properties from Ayla cloud."""

    config_entry: DelonghiConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: DelonghiAylaClient,
        device: AylaDevice,
        config_entry: DelonghiConfigEntry,
        device_list_callback: Callable[[list[AylaDevice]], None],
    ) -> None:
        device_hash = hashlib.sha256(device.dsn.encode()).hexdigest()[:12]
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device_hash}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
            config_entry=config_entry,
        )
        self.client = client
        self.device = device
        self._device_log_id = device_hash
        self._device_list_callback = device_list_callback
        # Per-model behaviour (synthesize vs learn-and-replay). All model-specific
        # differences live in model_profiles.py; this object is the single source.
        self.profile = profile_for(device.oem_model)
        self.command_property: str | None = None
        self.response_property: str | None = None
        self.connected_property: str | None = None
        # Cloud session (ECAM / app_device_connected) — DlghIoT-compatible cache.
        # A session owned by Coffee Link or another app is never adopted; command
        # execution waits until the device reports the session as free.
        self._default_app_id = normalize_signed_app_id(INTEGRATION_CLOUD_APP_ID)
        self._integration_app_id = self._default_app_id
        self._last_connect_at: float = 0
        self._session_confirmed = False
        self._session_connect_lock = asyncio.Lock()
        self._command_lock = asyncio.Lock()
        self._statistics_sync_lock = asyncio.Lock()
        self.active_beverage_id: int | None = None
        # Runtime-only status of a command issued by Home Assistant.  Do not
        # restore a stale result after restart: ``None`` truthfully renders as
        # Home Assistant's localized unknown state until a new command runs.
        self.last_command_result: str | None = None
        self.last_command: dict[str, Any] | None = None
        self._last_device_metadata_refresh = 0.0
        self._last_connection_info_refresh: float | None = None
        self._connection_info_supported: bool | None = None
        self.connection_info: dict[str, Any] = {}
        self._post_command_refresh_task: asyncio.Task[None] | None = None
        self._automatic_statistics_sync_task: asyncio.Task[None] | None = None
        self._statistics_update_event = asyncio.Event()
        self._last_statistics_sync_attempt_monotonic: float | None = None
        self.last_statistics_sync_attempt_at: str | None = None
        self.last_statistics_sync_success_at: str | None = None
        self.last_statistics_sync_result: str | None = None
        self.last_statistics_sync_trigger: str | None = None
        self.last_statistics_sync_snapshot_changed: bool | None = None
        self.last_statistics_sync_ack_status: int | None = None
        self.statistics_sync_attempts = 0
        self.statistics_sync_successes = 0
        self._dss_fallback_refresh_task: asyncio.Task[None] | None = None
        self.dss_state = "polling"
        self.dss_events_received = 0
        self._dss_sequences: dict[tuple[str, str], int | str] = {}
        self._dss_ack_waiters: dict[str, asyncio.Future[int | None]] = {}
        self._command_confirmation = CommandConfirmationTracker()
        self._recent_dss_acks: dict[str, int | None] = {}
        self._recent_dss_ack_order: deque[str] = deque(maxlen=32)
        self._monitor_ordering_token: int | None = None
        if self.profile.uses_cloud_session:
            self._last_seen_app_id: int | None = None
        # --- Command sniffer state ---------------------------------------
        # Values WE wrote, so a command echoed back by the cloud is not
        # mis-attributed to the official app. Bounded; only recent writes matter.
        self._sent_values: deque[str] = deque(maxlen=32)
        # Last datapoint marker seen per channel, to detect *new* writes only.
        self._last_cmd_marker: Any = None
        self._last_resp_marker: Any = None
        # Eletta (DL-striker-cb) frame replay: the Soul-style fixed recipe is
        # ignored by Eletta machines, which expect a variable-length recipe block
        # (and a different "start" action byte, plus a device signature). Rather
        # than rebuild all that, we learn the exact frame the official app sends
        # per beverage (sniffed below) and replay it verbatim with only a fresh
        # timestamp. Keyed by beverage_id; start and stop frames kept separately.
        # Persisted to disk so the learning survives Home Assistant restarts.
        self.learned_start_frames: dict[int, str] = {}
        self.learned_stop_frames: dict[int, str] = {}
        # Power-on (wake) is a single frame. The official app appends a 4-byte
        # device signature the integration's synthesized wake lacks - which is
        # why a built wake is ignored while a verbatim app replay works - so we
        # learn and replay the app's power-on frame too.
        self.learned_wake_frame: str | None = None
        self._discarded_learning_keys: set[str] = set()
        self._learning_issue_id = f"relearn_commands_{device_hash}"
        # Decoded d302_monitor_machine state (standby/ready/...), surfaced via
        # the Machine Status sensor. Empty dict until a blob parses.
        self.monitor: dict[str, Any] = {}
        self.stable_maintenance_monitor: dict[str, Any] = {}
        self._maintenance_candidate_signature: tuple[int, int, int, int] | None = None
        self._maintenance_candidate_count = 0
        self._store: Store[dict[str, Any]] = Store(hass, RECIPE_STORE_VERSION, f"{DOMAIN}_recipes_{device.dsn}")

    async def _async_setup(self) -> None:
        """Restore persistent command knowledge before the first cloud refresh."""
        await self.async_load_learned()

    async def async_shutdown(self) -> None:
        """Cancel in-flight session work and reset session state on unload."""
        self._last_connect_at = 0
        if self._integration_app_id != self._default_app_id:
            self._integration_app_id = self._default_app_id
        if self._post_command_refresh_task:
            self._post_command_refresh_task.cancel()
            self._post_command_refresh_task = None
        if self._automatic_statistics_sync_task:
            self._automatic_statistics_sync_task.cancel()
            self._automatic_statistics_sync_task = None
        if self._dss_fallback_refresh_task:
            self._dss_fallback_refresh_task.cancel()
            self._dss_fallback_refresh_task = None
        for waiter in self._dss_ack_waiters.values():
            waiter.cancel()
        self._dss_ack_waiters.clear()
        self._command_confirmation.cancel()
        await super().async_shutdown()

    async def async_confirm_initial_maintenance_snapshot(self) -> None:
        """Confirm a standby maintenance frame before entities are registered."""
        if self.stable_maintenance_monitor or self._maintenance_candidate_count != 1:
            return
        # Standby frames need two identical observations because the final
        # transition frame can briefly contain misleading alarm bits.  Once DSS
        # starts, routine reconciliation slows to five minutes, so perform the
        # independent second read during setup instead of exposing unavailable
        # maintenance entities until the next scheduled poll.
        await self.async_request_refresh()

    async def _async_update_data(self) -> AylaProperties:
        """Fetch all properties + refresh device meta."""
        try:
            props = await self.client.async_get_properties(self.device.dsn)
            props = self._merge_poll_with_push(props)
            if self.command_property is None:
                self.command_property = self._detect_property(props, COMMAND_PROPERTY_CANDIDATES, "command")
                # Refine the model profile now the live command channel is known
                # (only matters for an unrecognised oem_model; idempotent for the
                # PrimaDonna Soul / Eletta Explore which match by oem_model).
                self.profile = profile_for(self.device.oem_model, self.command_property)
            if self.response_property is None:
                # Optional: absence is fine, the sniffer just skips responses.
                self.response_property = self._detect_property(props, RESPONSE_PROPERTY_CANDIDATES, "response", required=False)
            if self.profile.uses_cloud_session and self.connected_property is None:
                self.connected_property = self._detect_property(props, CONNECTED_PROPERTY_CANDIDATES, "connected", required=False)
            self._sniff_app_traffic(props)
            self._update_monitor(props)
            self._update_session_from_props(props)
            # Device metadata changes slowly. Avoid listing every account device
            # on every property reconciliation.
            now = monotonic()
            await self._async_refresh_connection_info(now)
            if now - self._last_device_metadata_refresh >= DEVICE_METADATA_REFRESH_INTERVAL:
                devices = await self.client.async_get_devices(max_age=DEVICE_METADATA_REFRESH_INTERVAL)
                for discovered_device in devices:
                    if discovered_device.dsn == self.device.dsn:
                        self.device = discovered_device
                        break
                self._device_list_callback(devices)
                self._last_device_metadata_refresh = now
            self._schedule_automatic_statistics_sync(now)
            return props
        except AuthError as err:
            raise translated_auth_error() from err
        except RateLimitError as err:
            raise UpdateFailed("Ayla cloud rate limit reached", retry_after=err.retry_after) from err
        except CloudError as err:
            raise UpdateFailed(f"Ayla cloud error: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Error fetching De'Longhi data: {err}") from err

    def _merge_poll_with_push(self, props: AylaProperties) -> AylaProperties:
        """Do not let an eventually-consistent poll replace a newer DSS value."""
        current = self.data or {}
        for property_name, pushed in current.items():
            polled = props.get(property_name)
            if not isinstance(pushed, dict) or not isinstance(polled, dict):
                continue
            pushed_at = pushed.get("data_updated_at", pushed.get("dataUpdatedAt"))
            polled_at = polled.get("data_updated_at", polled.get("dataUpdatedAt"))
            if isinstance(pushed_at, str) and isinstance(polled_at, str) and pushed_at > polled_at:
                props[property_name] = dict(pushed)
        return props

    async def _async_refresh_connection_info(self, now: float) -> None:
        """Refresh privacy-safe Wi-Fi diagnostics without affecting availability."""
        if self._connection_info_supported is False:
            return
        if (
            self._last_connection_info_refresh is not None
            and now - self._last_connection_info_refresh < CONNECTION_INFO_REFRESH_INTERVAL
        ):
            return
        self._last_connection_info_refresh = now
        try:
            raw = await self.client.async_get_connection_info(self.device.dsn)
        except CloudError as err:
            if err.http_status in {400, 403, 404}:
                self._connection_info_supported = False
                self.connection_info = {}
            else:
                _LOGGER.debug(
                    "Ayla connection diagnostics temporarily unavailable for device_ref=%s (error_type=%s)",
                    self._device_log_id,
                    type(err).__name__,
                )
            return

        self._connection_info_supported = True
        connection_type = raw.get("connectivity_type", raw.get("connectivityType"))
        rssi_raw = raw.get("rssi")
        try:
            rssi = int(rssi_raw) if isinstance(rssi_raw, str | int | float) else None
        except TypeError, ValueError:
            rssi = None
        # Zero is the SDK's absent/default value; real Wi-Fi RSSI is negative.
        self.connection_info = {
            "connectivity_type": connection_type if isinstance(connection_type, str) else None,
            "rssi": rssi if rssi is not None and -200 < rssi < 0 else None,
        }

    def _update_monitor(self, props: AylaProperties) -> None:
        """Decode the machine monitor blob (diagnostic; must never break the poll)."""
        previous_monitor = self.monitor
        try:
            self.monitor = {}
            first_error: dict[str, Any] | None = None
            for property_name in MONITOR_PROPERTY_CANDIDATES:
                prop = props.get(property_name)
                value = prop.get("value") if isinstance(prop, dict) else None
                if not isinstance(value, str) or not value.strip():
                    continue
                parsed = parse_monitor_b64(value)
                if "error" not in parsed:
                    ordering_token = monitor_ordering_token(value)
                    if (
                        ordering_token is not None
                        and self._monitor_ordering_token is not None
                        and ordering_token < self._monitor_ordering_token
                    ):
                        # Coffee Link performs the same comparison before
                        # accepting a DSS monitor frame. Retain the newer state.
                        self.monitor = previous_monitor
                        return
                    if ordering_token is not None:
                        self._monitor_ordering_token = ordering_token
                    parsed["source_property"] = property_name
                    self.monitor = parsed
                    status = parsed.get("status")
                    step = parsed.get("step", parsed.get("action"))
                    progress_percentage = parsed.get("progress_percentage", parsed.get("progress"))
                    switches = parsed.get("switches")
                    alarms = parsed.get("alarms")
                    steady_ready = status == 7 and step == 0
                    steady_standby = status == 0 and step == 2 and progress_percentage == 100
                    if (steady_ready or steady_standby) and isinstance(switches, int) and isinstance(alarms, int):
                        accessory = parsed.get("accessory", 0)
                        signature = (
                            7 if steady_ready else 0,
                            accessory if isinstance(accessory, int) else 0,
                            switches,
                            alarms,
                        )
                        if signature == self._maintenance_candidate_signature:
                            self._maintenance_candidate_count += 1
                        else:
                            self._maintenance_candidate_signature = signature
                            self._maintenance_candidate_count = 1
                        # A ready/idle frame is authoritative. Standby must be
                        # unchanged for two polls to reject its transient end frame.
                        if steady_ready or self._maintenance_candidate_count >= 2:
                            self.stable_maintenance_monitor = dict(parsed)
                    return
                if first_error is None:
                    first_error = {**parsed, "source_property": property_name}
            self.monitor = first_error or {}
        except Exception:  # noqa: BLE001 - diagnostic must not break polling
            _LOGGER.debug("Monitor parse failed (non-fatal)", exc_info=True)
            self.monitor = {}

    def set_dss_state(self, state: str, *, request_refresh: bool = False) -> None:
        """Switch between push reconciliation and the polling safety fallback."""
        previous = self.dss_state
        self.dss_state = state
        self.update_interval = timedelta(seconds=(DSS_FALLBACK_SCAN_INTERVAL if state == "streaming" else DEFAULT_SCAN_INTERVAL))
        if state == "streaming" and previous != "streaming":
            # Sequence values can restart when Ayla issues a new stream.
            self._dss_sequences.clear()
        if request_refresh and self._dss_fallback_refresh_task is None:

            async def _refresh_after_stream_loss() -> None:
                try:
                    await self.async_request_refresh()
                finally:
                    self._dss_fallback_refresh_task = None

            self._dss_fallback_refresh_task = self.config_entry.async_create_background_task(
                self.hass,
                _refresh_after_stream_loss(),
                f"{DOMAIN}_dss_fallback_{self._device_log_id}",
            )
        self.async_update_listeners()

    @staticmethod
    def _normalized_dss_sequence(value: str | None) -> int | str | None:
        if value is None:
            return None
        try:
            return int(value)
        except TypeError, ValueError:
            return value

    def _accept_dss_sequence(self, event: DssEvent) -> bool:
        """Reject duplicate or out-of-order events within the current stream."""
        sequence = self._normalized_dss_sequence(event.sequence)
        if sequence is None:
            return True
        key = (event.event_type, event.property_name or "")
        previous = self._dss_sequences.get(key)
        if isinstance(sequence, int) and isinstance(previous, int):
            if sequence <= previous:
                return False
        elif sequence == previous:
            return False
        self._dss_sequences[key] = sequence
        return True

    def _remember_dss_ack(self, datapoint_id: str, status: int | None) -> None:
        if datapoint_id not in self._recent_dss_acks:
            if len(self._recent_dss_ack_order) == self._recent_dss_ack_order.maxlen:
                self._recent_dss_acks.pop(self._recent_dss_ack_order[0], None)
            self._recent_dss_ack_order.append(datapoint_id)
        self._recent_dss_acks[datapoint_id] = status
        waiter = self._dss_ack_waiters.get(datapoint_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(status)

    def _notify_command_state_waiters(self) -> None:
        """Wake command confirmations after a relevant DSS state transition."""
        self._command_confirmation.notify()

    def handle_dss_event(self, event: DssEvent) -> bool:
        """Apply one ordered DSS update and notify Home Assistant entities."""
        if not self._accept_dss_sequence(event):
            return False

        handled = False
        if event.event_type == "datapointack" and event.datapoint_id:
            self._remember_dss_ack(event.datapoint_id, event.ack_status)
            handled = True

        property_name = event.property_name
        if property_name is None or event.event_type == "connectivity":
            return handled

        data = self.data if isinstance(self.data, dict) else {}
        current = data.get(property_name)
        current = dict(current) if isinstance(current, dict) else {"name": property_name}
        current_at = current.get("data_updated_at", current.get("dataUpdatedAt"))
        if event.updated_at is not None and isinstance(current_at, str) and event.updated_at < current_at:
            return handled

        if event.event_type == "datapoint" or event.value is not None:
            current["value"] = event.value
        if event.updated_at is not None:
            current["data_updated_at"] = event.updated_at
        if event.acked_at is not None:
            current["acked_at"] = event.acked_at
        if event.ack_status is not None:
            current["ack_status"] = event.ack_status
        if event.ack_message is not None:
            current["ack_message"] = event.ack_message
        data[property_name] = current
        self.data = data

        confirmation_state_changed = property_name in MONITOR_PROPERTY_CANDIDATES
        if confirmation_state_changed:
            was_preparing = self._machine_is_preparing()
            self._update_monitor(data)
            if was_preparing and self._machine_is_ready():
                # Request the new counters right away instead of waiting for
                # the hourly cooperative sync.
                self._schedule_post_command_refresh(trigger="beverage_finished")
        if property_name in {
            self.command_property,
            self.response_property,
        }:
            self._sniff_app_traffic(data)
        if property_name == APP_ID_PROPERTY:
            self._update_session_from_props(data)
        if property_name == self.response_property:
            confirmation_state_changed = True
        if self._is_statistics_property(property_name):
            self._statistics_update_event.set()
        if confirmation_state_changed:
            self._notify_command_state_waiters()
        self.dss_events_received += 1
        self.async_update_listeners()
        return True

    async def _async_wait_for_dss_ack(self, datapoint_id: str) -> tuple[bool, int | None]:
        """Wait for an exact device ACK before using cloud-state inference."""
        if self.dss_state != "streaming":
            return False, None
        if datapoint_id in self._recent_dss_acks:
            return True, self._recent_dss_acks.pop(datapoint_id)
        waiter = asyncio.get_running_loop().create_future()
        self._dss_ack_waiters[datapoint_id] = waiter
        if datapoint_id in self._recent_dss_acks:
            waiter.set_result(self._recent_dss_acks.pop(datapoint_id))
        try:
            return True, await asyncio.wait_for(waiter, DSS_ACK_GRACE_PERIOD)
        except TimeoutError:
            return False, None
        finally:
            self._dss_ack_waiters.pop(datapoint_id, None)

    @property
    def command_ack_enabled(self) -> bool | None:
        """Return the cloud-declared ACK capability of the command property."""
        data = self.data if isinstance(self.data, dict) else {}
        if self.command_property is None:
            return None
        command_property = data.get(self.command_property)
        if not isinstance(command_property, dict):
            return None
        value = command_property.get("ack_enabled", command_property.get("ackEnabled"))
        return value if isinstance(value, bool) else None

    def _detect_property(
        self,
        props: AylaProperties,
        candidates: list[str],
        kind: str,
        required: bool = True,
    ) -> str | None:
        """Pick the right property name for this model from a candidate list.

        Different De'Longhi models expose the binary channels under different
        names (e.g. ``data_request`` on Soul vs ``app_data_request`` on Eletta).
        """
        for candidate in candidates:
            if candidate in props:
                _LOGGER.info(
                    "Using %s property '%s' for device_ref=%s (oem_model=%s)",
                    kind,
                    candidate,
                    self._device_log_id,
                    self.device.oem_model,
                )
                return candidate
        if not required:
            _LOGGER.debug(
                "No %s property among %s for device_ref=%s (sniffer will skip it)",
                kind,
                candidates,
                self._device_log_id,
            )
            return None
        raise CloudError(
            f"No known {kind} property found for device_ref={self._device_log_id} "
            f"(oem_model={self.device.oem_model}). Tried {candidates}. "
            "Please open an issue with debug logs."
        )

    # ------------------------------------------------------------------ #
    # Cloud session (app_device_connected)
    #
    # ECAM models require a registered cloud session before commands are
    # relayed. Logic follows DlghIoT connect(): adopt foreign app_id, POST +
    # settle delay on cold connect only (on-demand before commands). Poll does
    # NOT register a session — that would block the official Coffee Link app
    # while HA is idle. After an HA command the machine keeps app_id for ~300 s
    # (protocol limit); Coffee Link may be temporarily blocked until timeout.
    # Cold path runs in a background task so button/service handlers return
    # immediately.
    # ------------------------------------------------------------------ #

    def _parse_app_id_value(self, raw: Any) -> int | None:
        if raw is None:
            return None
        try:
            return normalize_signed_app_id(int(str(raw).strip()))
        except TypeError, ValueError:
            return None

    def _app_id_from_props(self, props: AylaProperties) -> int | None:
        prop = props.get(APP_ID_PROPERTY)
        if isinstance(prop, dict):
            return self._parse_app_id_value(prop.get("value"))
        return None

    async def _read_app_id(self, *, live: bool = False) -> int | None:
        if not live and self.data:
            app_id = self._app_id_from_props(self.data)
            if app_id is not None:
                return app_id
        app_id, _ok = await self._fetch_app_id_live()
        return app_id

    async def _fetch_app_id_live(self) -> tuple[int | None, bool]:
        """Direct GET app_id. Returns (value, fetch_ok); fetch_ok=False on cloud error."""
        try:
            prop = await self.client.async_get_property_resilient(self.device.dsn, APP_ID_PROPERTY)
        except CloudError as err:
            status = getattr(err, "http_status", None)
            _LOGGER.warning(
                "Live app_id fetch failed for device_ref=%s (http=%s): %s",
                self._device_log_id,
                status,
                err,
            )
            return None, False
        return self._parse_app_id_value(prop.get("value")), True

    async def _wait_for_session_confirmed(self) -> bool:
        """Poll app_id until it matches our integration id (DlghIoT connect loop)."""
        started = monotonic()
        last_progress = started
        poll_count = 0
        cloud_errors = 0
        _LOGGER.debug(
            "Waiting for cloud session confirmation (timeout=%ds)",
            CONNECT_CONFIRM_TIMEOUT,
        )
        while monotonic() - started < CONNECT_CONFIRM_TIMEOUT:
            poll_count += 1
            app_id, fetch_ok = await self._fetch_app_id_live()
            if not fetch_ok:
                cloud_errors += 1
            elif app_id == self._integration_app_id:
                elapsed = monotonic() - started
                self._session_confirmed = True
                _LOGGER.info(
                    "Cloud session confirmed after %.1fs (polls=%d, cloud_errors=%d)",
                    elapsed,
                    poll_count,
                    cloud_errors,
                )
                return True
            await asyncio.sleep(CONNECT_CONFIRM_POLL_INTERVAL)
            now = monotonic()
            if now - last_progress >= 15:
                _LOGGER.debug(
                    "Still waiting for cloud session confirmation (%.0fs/%ds, polls=%d, cloud_errors=%d)",
                    now - started,
                    CONNECT_CONFIRM_TIMEOUT,
                    poll_count,
                    cloud_errors,
                )
                last_progress = now
        _last_app_id, last_ok = await self._fetch_app_id_live()
        _LOGGER.warning(
            "Connect POST sent but the session was not confirmed after %ds (last fetch ok=%s, polls=%d, cloud_errors=%d)",
            CONNECT_CONFIRM_TIMEOUT,
            last_ok,
            poll_count,
            cloud_errors,
        )
        self._session_confirmed = False
        return False

    def _update_session_from_props(self, props: AylaProperties) -> None:
        """Parse app_id from poll data; must never break the poll."""
        try:
            app_id = self._app_id_from_props(props)
            if self.profile.uses_cloud_session and app_id != self._last_seen_app_id:
                if app_id in (None, 0):
                    holder = "free"
                elif app_id == self._default_app_id:
                    holder = "ha"
                else:
                    holder = "foreign"
                _LOGGER.debug(
                    "Cloud session holder changed to %s",
                    holder,
                )
                self._last_seen_app_id = app_id
            self._session_confirmed = app_id is not None and app_id == self._integration_app_id
            # An adopted foreign session (official app's id) is transient: once
            # the machine reports no session holder, revert to our own id so we
            # never keep a foreign session alive on the app's behalf.
            if app_id == 0 and self._integration_app_id != self._default_app_id:
                _LOGGER.info(
                    "Foreign cloud session released on device_ref=%s; reverting to own app_id",
                    self._device_log_id,
                )
                self._integration_app_id = self._default_app_id
                self._last_connect_at = 0
        except Exception:  # noqa: BLE001 - diagnostic must not break polling
            _LOGGER.debug("Session parse failed (non-fatal)", exc_info=True)

    def cloud_session_holder(self, app_id: int | None) -> str:
        """Return a privacy-safe, backward-compatible session-holder key.

        The device-specific ID can be shared by Coffee Link and this integration,
        so the legacy ``ha`` key is displayed as the neutral "Active".
        """
        if app_id is None:
            return "unknown"
        if app_id == 0:
            return "free"
        if app_id == self._integration_app_id:
            return "ha"
        return "foreign"

    def _revert_foreign_app_id_if_session_clear(self, app_id: int | None) -> None:
        """Before a cold POST, use our own cloud id when no session is held."""
        if app_id in (None, 0) and self._integration_app_id != self._default_app_id:
            _LOGGER.info(
                "No cloud session holder on device_ref=%s; reverting to own app_id before connect",
                self._device_log_id,
            )
            self._integration_app_id = self._default_app_id
            self._last_connect_at = 0

    def _command_confirmation_snapshot(self) -> tuple[Any, dict[str, Any]]:
        """Return privacy-safe state used to detect a machine acknowledgement."""
        return self._last_resp_marker, dict(self.monitor)

    def _command_confirmation_changed(self, before: tuple[Any, dict[str, Any]]) -> bool:
        """Return whether response or monitor state changed after a command."""
        response_marker, monitor = before
        return bool(
            (self.response_property and self._last_resp_marker != response_marker) or (self.monitor and self.monitor != monitor)
        )

    def _validate_beverage_start(self) -> None:
        """Reject a start command when a known blocking condition is present."""
        if str(self.device.connection_status).strip().lower() != "online":
            raise translated_error("coffee_maker_not_connected")
        monitor = self.monitor or {}
        if not monitor or "error" in monitor:
            if self.profile.learns_from_app:
                raise translated_error("state_unverified")
            return
        status = monitor.get("status")
        if status != 7:
            raise translated_error("not_ready")
        step = monitor.get("step", monitor.get("action"))
        if step != 0:
            raise translated_error("already_preparing")
        alarms = monitor.get("alarms")
        switches = monitor.get("switches")
        if isinstance(alarms, int):
            if (alarms >> 0) & 1:
                raise translated_error("water_tank_empty")
            if (alarms >> 1) & 1:
                raise translated_error("grounds_container_full")
        if isinstance(switches, int):
            if (switches >> 4) & 1:
                raise translated_error("water_tank_missing")
            if (switches >> 3) & 1:
                raise translated_error("grounds_container_missing")

    def has_device_signature(self) -> bool:
        """Return whether ECAM commands can use a learned machine signature."""
        return not self.profile.uses_cloud_session or self._learned_device_signature() is not None

    @staticmethod
    def _command_timestamp() -> str:
        """Return an unambiguous UTC timestamp for diagnostic attributes."""
        return datetime.now(UTC).isoformat()

    def _begin_command(self, context: dict[str, Any] | None) -> None:
        """Start one HA command diagnostic without app-sniffer metadata."""
        self.last_command = {
            "source": "home_assistant",
            **(context or {"command_type": "unknown"}),
            "started_at": self._command_timestamp(),
        }
        self._set_last_command_result("pending")

    def _set_last_command_result(self, result: str, *, completed: bool = False) -> None:
        """Publish one command-state transition and its completion time."""
        self.last_command_result = result
        if completed and self.last_command is not None:
            self.last_command["completed_at"] = self._command_timestamp()
        self.async_update_listeners()

    @staticmethod
    def _beverage_command_context(beverage_id: int, action: int) -> dict[str, Any]:
        """Return privacy-safe metadata for a beverage command issued by HA."""
        beverage_name = next(
            (name for candidate, _key, name, _icon in BEVERAGES if candidate == beverage_id),
            ELETTA_LEARNED_BEVERAGES.get(beverage_id, ("", f"0x{beverage_id:02x}", ""))[1],
        )
        return {
            "command_type": "beverage",
            "action": "stop" if action == ACTION_STOP else "start",
            "beverage_id": f"0x{beverage_id:02x}",
            "beverage_name": beverage_name,
        }

    @staticmethod
    def _is_statistics_property(property_name: str) -> bool:
        """Return whether a property belongs to Coffee Link's counter snapshot."""
        return property_name.startswith(STATISTICS_PROPERTY_PREFIXES)

    @classmethod
    def _statistics_snapshot_marker(cls, props: AylaProperties | None) -> str | None:
        """Return a private digest used only to verify that a snapshot advanced."""
        if not isinstance(props, dict):
            return None
        snapshot: list[tuple[str, Any, Any]] = []
        for property_name, prop in sorted(props.items()):
            if not cls._is_statistics_property(property_name) or not isinstance(prop, dict):
                continue
            updated_at = prop.get("data_updated_at", prop.get("dataUpdatedAt", prop.get("updated_at")))
            snapshot.append((property_name, updated_at, prop.get("value")))
        if not snapshot:
            return None
        return hashlib.sha256(repr(snapshot).encode()).hexdigest()

    def _machine_is_preparing(self) -> bool:
        """Return true only while the live monitor reports an active preparation."""
        status = self.monitor.get("status")
        step = self.monitor.get("step", self.monitor.get("action"))
        return bool((status == 7 and step not in (None, 0)) or status in {5, 10, 11, 16, 17})

    def _machine_is_ready(self) -> bool:
        """Return true when the live monitor reports an idle, awake machine."""
        step = self.monitor.get("step", self.monitor.get("action"))
        return self.monitor.get("status") == 7 and step in (None, 0)

    def _record_statistics_sync(
        self,
        result: str,
        *,
        trigger: str,
        success: bool = False,
        snapshot_changed: bool | None = None,
    ) -> str:
        """Record privacy-safe runtime diagnostics without creating HA history."""
        self.last_statistics_sync_result = result
        self.last_statistics_sync_trigger = trigger
        self.last_statistics_sync_snapshot_changed = snapshot_changed
        if success:
            self.statistics_sync_successes += 1
            self.last_statistics_sync_success_at = datetime.now(UTC).isoformat()
        self.async_update_listeners()
        return result

    async def _send_statistics_refresh(self) -> None:
        """Send Coffee Link's statistics request without command-state side effects.

        This is distinct from the 03 02 session refresh. Delivery alone does not
        prove that the appliance has published a fresh counter snapshot.
        """
        prop = self.command_property or COMMAND_PROPERTY_CANDIDATES[0]
        value = build_statistics_request_encoded(self._integration_app_id)
        self._record_sent(value)
        _LOGGER.info("Requesting a fresh cloud snapshot via %s", prop)
        result = await self.client.async_set_property_value(self.device.dsn, prop, value)
        datapoint = result.get("datapoint", result) if isinstance(result, dict) else {}
        datapoint_id = datapoint.get("id") if isinstance(datapoint, dict) else None
        if datapoint_id is None or self.command_ack_enabled is not True:
            return
        ack_received, ack_status = await self._async_wait_for_dss_ack(str(datapoint_id))
        if ack_received:
            self.last_statistics_sync_ack_status = ack_status
        if ack_received and ack_status is not None and ack_status >= 400:
            raise translated_error("command_rejected_by_device")

    async def async_synchronize_statistics(
        self,
        *,
        automatic: bool = False,
        trigger: str = "manual",
    ) -> str:
        """Serialize snapshot requests without locking normal appliance commands."""
        if self._statistics_sync_lock.locked():
            # No second request was attempted. Keep the in-flight diagnostics.
            if automatic:
                return "skipped_busy"
            raise translated_error("command_in_progress")
        async with self._statistics_sync_lock:
            return await self._async_synchronize_statistics(automatic=automatic, trigger=trigger)

    async def _async_wait_for_statistics_update(self, before: str | None) -> bool:
        """Wait within one deadline; unchanged events cannot finish it early."""
        deadline = monotonic() + STATISTICS_SYNC_SETTLE_DELAY
        observed = self._statistics_update_event.is_set()
        while True:
            current = self._statistics_snapshot_marker(self.data)
            if current is not None and current != before:
                return True
            remaining = deadline - monotonic()
            if remaining <= 0:
                return observed
            self._statistics_update_event.clear()
            try:
                await asyncio.wait_for(self._statistics_update_event.wait(), remaining)
            except TimeoutError:
                return observed
            observed = True

    async def _async_synchronize_statistics(self, *, automatic: bool, trigger: str) -> str:
        """Ask for a snapshot, then distinguish delivery from observed data."""
        self.statistics_sync_attempts += 1
        self._last_statistics_sync_attempt_monotonic = monotonic()
        self.last_statistics_sync_attempt_at = datetime.now(UTC).isoformat()
        self.last_statistics_sync_ack_status = None

        if str(self.device.connection_status).strip().lower() != "online":
            if automatic:
                return self._record_statistics_sync("skipped_offline", trigger=trigger)
            raise translated_error("coffee_maker_not_connected")
        if self._command_lock.locked() or self._machine_is_preparing():
            if automatic:
                return self._record_statistics_sync("skipped_busy", trigger=trigger)
            raise translated_error("command_in_progress")

        before = self._statistics_snapshot_marker(self.data)
        self._statistics_update_event.clear()
        observed_update = not self.profile.uses_cloud_session
        try:
            if self.profile.uses_cloud_session:
                if not self.connected_property or not self.has_device_signature():
                    if automatic:
                        return self._record_statistics_sync("skipped_unsupported", trigger=trigger)
                    raise translated_error("command_not_learned")
                async with self._command_lock:
                    if self._machine_is_preparing():
                        if automatic:
                            return self._record_statistics_sync("skipped_busy", trigger=trigger)
                        raise translated_error("command_in_progress")
                    await self._with_cloud_session(self._send_statistics_refresh)
                # Polling remains authoritative when DSS is unavailable or the
                # appliance republishes byte-identical counter values.
                observed_update = await self._async_wait_for_statistics_update(before)
            await self.async_request_refresh()
        except ConfigEntryAuthFailed:
            self._record_statistics_sync("failed_authentication", trigger=trigger)
            if automatic:
                _LOGGER.warning("Automatic cloud snapshot refresh needs reauthentication")
                return "failed_authentication"
            raise
        except HomeAssistantError as err:
            result = "skipped_foreign_session" if err.translation_key == "cloud_session_in_use" else "failed"
            self._record_statistics_sync(result, trigger=trigger)
            if automatic:
                _LOGGER.debug("Automatic cloud snapshot refresh deferred: %s", err)
                return result
            raise
        except (AuthError, CloudError, TimeoutError) as err:
            self._record_statistics_sync("failed", trigger=trigger)
            if automatic:
                _LOGGER.debug("Automatic cloud snapshot refresh failed", exc_info=True)
                return "failed"
            if isinstance(err, AuthError):
                raise translated_auth_error() from err
            raise translated_error("cloud_command_failed") from err

        after = self._statistics_snapshot_marker(self.data)
        changed = None if before is None or after is None else before != after
        if changed:
            result = "completed_updated"
        elif changed is None or not observed_update:
            result = "completed_unverified"
        else:
            result = "completed_unchanged"
        return self._record_statistics_sync(result, trigger=trigger, success=True, snapshot_changed=changed)

    def _schedule_automatic_statistics_sync(self, now: float) -> None:
        """Schedule one cooperative snapshot refresh; never keep the app session alive."""
        task = self._automatic_statistics_sync_task
        if task is not None and not task.done():
            return
        if (
            not self.profile.uses_cloud_session
            or not self.connected_property
            or not self.has_device_signature()
            or str(self.device.connection_status).strip().lower() != "online"
        ):
            return

        delay: float
        if self._last_statistics_sync_attempt_monotonic is None:
            delay = float(STATISTICS_SYNC_STARTUP_DELAY)
        else:
            retry = self.last_statistics_sync_result is not None and not self.last_statistics_sync_result.startswith("completed_")
            interval = STATISTICS_SYNC_RETRY_INTERVAL if retry else STATISTICS_SYNC_INTERVAL
            delay = max(0.0, interval - (now - self._last_statistics_sync_attempt_monotonic))

        async def _delayed_sync() -> None:
            try:
                await asyncio.sleep(delay)
                await self.async_synchronize_statistics(automatic=True, trigger="automatic")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - polling must survive optional automation
                _LOGGER.debug("Automatic cloud snapshot refresh task failed", exc_info=True)
            finally:
                self._automatic_statistics_sync_task = None

        self._automatic_statistics_sync_task = self.config_entry.async_create_background_task(
            self.hass,
            _delayed_sync(),
            f"{DOMAIN}_automatic_statistics_sync_{self._device_log_id}",
        )

    def _schedule_post_command_refresh(self, *, trigger: str = "post_command") -> None:
        """Refresh counters after the cloud has had time to persist a command."""
        if self._post_command_refresh_task:
            self._post_command_refresh_task.cancel()

        async def _delayed_refresh() -> None:
            try:
                await asyncio.sleep(POST_COMMAND_REFRESH_DELAY)
                if self.profile.uses_cloud_session and not self._machine_is_preparing():
                    result = await self.async_synchronize_statistics(automatic=True, trigger=trigger)
                    if result.startswith("completed_"):
                        return
                await self.async_request_refresh()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - command already succeeded
                _LOGGER.debug("Post-command refresh failed", exc_info=True)

        coroutine = _delayed_refresh()
        self._post_command_refresh_task = self.config_entry.async_create_background_task(
            self.hass,
            coroutine,
            f"{DOMAIN}_post_command_refresh_{self._device_log_id}",
        )

    async def _wait_for_command_confirmation(
        self,
        before: tuple[Any, dict[str, Any]],
        *,
        timeout: float = COMMAND_CONFIRM_TIMEOUT,
    ) -> bool | None:
        """Return True/False for supported confirmation, or None if unavailable."""
        if self.response_property is None and not self.monitor:
            return None

        return await self._command_confirmation.async_wait(
            changed=lambda: self._command_confirmation_changed(before),
            streaming=lambda: self.dss_state == "streaming",
            refresh=self.async_request_refresh,
            timeout=timeout,
            poll_interval=COMMAND_CONFIRM_POLL_INTERVAL,
        )

    async def _send_property_command(
        self,
        value: str,
        label: str,
        *,
        confirm: bool = True,
        confirmation_timeout: float | None = None,
    ) -> None:
        prop = self.command_property or COMMAND_PROPERTY_CANDIDATES[0]
        before = self._command_confirmation_snapshot()
        self._record_sent(value)
        _LOGGER.info("Sending %s via %s (len=%d)", label, prop, len(value))
        result = await self.client.async_set_property_value(self.device.dsn, prop, value)
        self._set_last_command_result("sent")
        if not confirm:
            return

        datapoint = result.get("datapoint", result) if isinstance(result, dict) else {}
        datapoint_id = datapoint.get("id") if isinstance(datapoint, dict) else None
        if datapoint_id is not None and self.command_ack_enabled is True:
            ack_received, ack_status = await self._async_wait_for_dss_ack(str(datapoint_id))
            if ack_received and ack_status is not None:
                if self.last_command is not None:
                    # Privacy-safe evidence that the ACK belonged to the exact
                    # datapoint created by this command.  The cloud datapoint
                    # identifier and command payload are intentionally omitted.
                    self.last_command["ack_status"] = ack_status
                if 200 <= ack_status < 300:
                    if self.last_command is not None:
                        self.last_command["confirmation_source"] = "dss_ack"
                    self._set_last_command_result("acknowledged", completed=True)
                    return
                if ack_status >= 400:
                    if self.last_command is not None:
                        self.last_command["confirmation_source"] = "dss_ack"
                    self._set_last_command_result("rejected", completed=True)
                    raise translated_error("command_rejected_by_device")

        confirmed = (
            await self._wait_for_command_confirmation(before)
            if confirmation_timeout is None
            else await self._wait_for_command_confirmation(before, timeout=confirmation_timeout)
        )
        if confirmed is True:
            if self.last_command is not None:
                self.last_command["confirmation_source"] = "cloud_state"
            self._set_last_command_result("acknowledged", completed=True)
        elif confirmed is False:
            self._set_last_command_result("timed_out", completed=True)
            raise translated_error("command_not_acknowledged")

    async def _maybe_send_session_refresh(self) -> None:
        """DlghIoT refresh(): nudge deep standby before wake when monitor=0."""
        if self.monitor.get("status") != 0:
            return
        value = build_session_refresh_encoded(self._integration_app_id)
        _LOGGER.info("Machine in standby; sending a session refresh before wake")
        await self._send_property_command(value, "SESSION REFRESH", confirm=False)

    def _wake_command_value(self) -> str:
        """Build wake frame for ECAM models (session tail). Soul uses main inline path."""
        return build_wake_with_session_tail_encoded(self._integration_app_id)

    def _standby_command_value(self) -> str:
        """Build standby frame for ECAM models (session tail). Soul uses main inline path."""
        return build_standby_with_session_tail_encoded(self._integration_app_id)

    def _session_is_fresh(self, app_id: int | None) -> bool:
        now = monotonic()
        if self._last_connect_at + CONNECT_SETTLE_DELAY > now:
            return True
        if self._last_connect_at + CONNECT_REFRESH_INTERVAL > now:
            return app_id is None or app_id == self._integration_app_id
        return False

    async def _post_cloud_session(self) -> None:
        if not self.connected_property:
            return
        await self.client.async_post_cloud_session(
            self.device.dsn,
            self.connected_property,
            self._integration_app_id,
        )

    async def _with_cloud_session(self, send_fn: Callable[[], Awaitable[None]]) -> None:
        if not self.profile.uses_cloud_session or not self.connected_property:
            await send_fn()
            return

        async with self._session_connect_lock:
            # Never claim a session from a cached ``app_id`` value. Coffee Link
            # may have opened the mobile session since the last reconciliation.
            app_id, fetch_ok = await self._fetch_app_id_live()
            if not fetch_ok:
                raise translated_error("cached_session_unverified")
            self._revert_foreign_app_id_if_session_clear(app_id)

            if app_id not in (None, 0) and app_id != self._integration_app_id:
                raise translated_error("cloud_session_in_use")
            elif self._session_is_fresh(app_id):
                if app_id != self._integration_app_id:
                    raise translated_error("cached_session_unverified")
                self._session_confirmed = True
            else:
                await self._post_cloud_session()
                await asyncio.sleep(CONNECT_SETTLE_DELAY)
                if not await self._wait_for_session_confirmed():
                    raise translated_error("cloud_session_timeout")
                self._last_connect_at = monotonic()

            await send_fn()

    # ------------------------------------------------------------------ #
    # Command sniffer
    #
    # We already fetch every property each poll, so watching the command and
    # response channels is free (no extra API calls). When the value changes to
    # something this integration did not write, it was written by the official
    # Coffee Link app - i.e. the ground-truth bytes we need to compare against.
    # ------------------------------------------------------------------ #

    def _sniff_app_traffic(self, props: AylaProperties) -> None:
        # The sniffer is a diagnostic; it must never break the data update and
        # take the device unavailable. Swallow and log any unexpected error.
        try:
            if self.command_property:
                self._capture_channel(props, self.command_property, channel="command")
            if self.response_property:
                self._capture_channel(props, self.response_property, channel="response")
        except Exception:  # noqa: BLE001 - diagnostic must not break polling
            _LOGGER.debug("Command sniffer failed (non-fatal)", exc_info=True)

    def _capture_channel(self, props: AylaProperties, prop_name: str, channel: str) -> None:
        prop = props.get(prop_name)
        if not isinstance(prop, dict):
            return
        value = prop.get("value")
        if not isinstance(value, str) or not value.strip():
            return
        # Ayla wraps string datapoints in whitespace (e.g. a trailing newline);
        # normalise so attribution against _sent_values and the decode succeed.
        value = value.strip()
        # Prefer the cloud's datapoint timestamp to detect a new write (it also
        # catches the app re-sending byte-identical bytes); fall back to value.
        marker = prop.get("data_updated_at", value)
        marker_attr = "_last_cmd_marker" if channel == "command" else "_last_resp_marker"
        previous = getattr(self, marker_attr)
        if marker == previous:
            return  # nothing new this poll
        first_observation = previous is None
        setattr(self, marker_attr, marker)
        if first_observation:
            # The value already present at startup is not a fresh capture.
            return

        decoded = decode_command(value)
        if channel == "command":
            origin = "integration" if value in self._sent_values else "app"
            if origin == "app":
                self._maybe_learn_frame(decoded)
            summary = (
                f"type={decoded.get('type')} style={decoded.get('style')} "
                f"beverage={decoded.get('beverage_name')} "
                f"action={decoded.get('action_name')} crc_valid={decoded.get('crc_valid')}"
            )
            if origin == "app":
                _LOGGER.warning(
                    "Captured app-to-machine command on %s: %s",
                    prop_name,
                    summary,
                )
            else:
                _LOGGER.debug("Observed own command echoed on %s: %s", prop_name, summary)
        else:
            _LOGGER.debug(
                "Machine-to-app response on %s: type=%s",
                prop_name,
                decoded.get("type"),
            )

    def _record_sent(self, value: str) -> None:
        """Remember a value we wrote so the sniffer won't flag it as app traffic."""
        self._sent_values.append(value)

    async def async_load_learned(self) -> None:
        """Load learned Eletta frames persisted from previous runs.

        Called once at setup so a restart does not lose the per-beverage frames
        the integration learned from the official app.
        """
        try:
            data = await self._store.async_load()
        except Exception:  # noqa: BLE001 - persistence must not block setup
            _LOGGER.debug("Could not load learned recipes (non-fatal)", exc_info=True)
            return
        if not data:
            self._sync_learning_repair_issue()
            return
        (
            self.learned_start_frames,
            self.learned_stop_frames,
            self.learned_wake_frame,
        ) = deserialize_learned_frames(data)
        expected_signature: bytes | None = None
        if self.profile.learns_from_app:
            valid_start: dict[int, str] = {}
            valid_stop: dict[int, str] = {}
            for action, source, target in (
                (ACTION_START, self.learned_start_frames, valid_start),
                (ACTION_STOP, self.learned_stop_frames, valid_stop),
            ):
                for beverage_id, frame in source.items():
                    if not validate_replayed_beverage_frame(
                        frame,
                        beverage_id,
                        action,
                        require_eletta=True,
                        expected_signature=expected_signature,
                    ):
                        _LOGGER.warning(
                            "Discarding persisted beverage frame 0x%02x action %d "
                            "because its integrity or device signature is invalid",
                            beverage_id,
                            action,
                        )
                        self._discarded_learning_keys.add(self._learning_key(beverage_id, action))
                        continue
                    signature = device_signature_from_frame(frame)
                    if expected_signature is None:
                        expected_signature = signature
                    target[beverage_id] = frame
            self.learned_start_frames = valid_start
            self.learned_stop_frames = valid_stop
        # Sanitize a wake frame persisted BEFORE the params guard existed: a
        # session-refresh packet (e.g. params 03 02) stored as the wake frame
        # would otherwise be replayed forever. Drop it so a real power-on from
        # the app re-teaches it.
        if self.learned_wake_frame is not None:
            if self.profile.learns_from_app:
                if not validate_replayed_wake_frame(replay_with_timestamp(self.learned_wake_frame)) or (
                    device_signature_from_frame(self.learned_wake_frame) is None
                    or (
                        expected_signature is not None
                        and device_signature_from_frame(self.learned_wake_frame) != expected_signature
                    )
                ):
                    _LOGGER.warning(
                        "Discarding persisted wake frame (integrity check failed). "
                        "Power the machine on once from the official app to re-learn it.",
                    )
                    self._discarded_learning_keys.add("wake")
                    self.learned_wake_frame = None
            elif not is_wake_power_frame(decode_command(self.learned_wake_frame)):
                _LOGGER.warning(
                    "Discarding persisted wake frame (not a real power-on). "
                    "Power the machine on once from the official app to re-learn it.",
                )
                self.learned_wake_frame = None
        total = len(self.learned_start_frames) + len(self.learned_stop_frames) + (1 if self.learned_wake_frame else 0)
        if total:
            _LOGGER.debug("Restored %d learned command frame(s)", total)
        self._restore_device_app_id()
        self._sync_learning_repair_issue()

    @staticmethod
    def _learning_key(beverage_id: int, action: int) -> str:
        """Return a stable key for one learned beverage command."""
        action_name = "stop" if action == ACTION_STOP else "start"
        return f"{action_name}_{beverage_id:02x}"

    def _sync_learning_repair_issue(self) -> None:
        """Create or clear an actionable repair for discarded learned frames."""
        if not self.profile.learns_from_app:
            return
        if not self._discarded_learning_keys:
            ir.async_delete_issue(self.hass, DOMAIN, self._learning_issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._learning_issue_id,
            is_fixable=False,
            is_persistent=True,
            issue_domain=DOMAIN,
            severity=ir.IssueSeverity.ERROR,
            translation_key="relearn_commands",
            translation_placeholders={
                "device_name": self.device.name,
                "count": str(len(self._discarded_learning_keys)),
            },
        )

    def log_recipe_datapoints(self) -> None:
        """Dump the machine's stored recipe datapoints to the log (read-only).

        Diagnostic for the "zero-touch" work: lets a tester surface the recipes
        the machine stores so the recipe->command mapping can be confirmed.
        Sends nothing to the machine.
        """
        if not self.data:
            _LOGGER.warning("Recipe dump requested but no data fetched yet.")
            return
        lines = recipe_dump_lines(self.data)
        if not lines:
            _LOGGER.warning("No recipe datapoints were reported by this coffee maker.")
            return
        _LOGGER.warning("Recipe datapoints detected (%d):", len(lines))
        for line in lines:
            _LOGGER.warning("Recipe datapoint: %s", line)

    def _learned_storage_data(self) -> dict[str, Any]:
        """Callback for the debounced Store save."""
        return serialize_learned_frames(self.learned_start_frames, self.learned_stop_frames, self.learned_wake_frame)

    def _maybe_learn_frame(self, decoded: dict[str, Any]) -> None:
        """Learn the exact frame the official app sent for a beverage.

        Models that ``learns_from_app`` ignore the Soul-style fixed recipe;
        replaying the app's own frame verbatim is the reliable way to reproduce a
        beverage (quantity / intensity / milk, the right start-action byte, and
        the device signature are all preserved). Stop frames (action 0x02) are
        kept separately from start frames so a captured stop never gets replayed
        for a start press. The power-on (wake) frame is learned too - the app
        appends a device signature a synthesized wake lacks. New/changed frames
        are persisted (debounced) so they survive restarts.
        """
        if not self.profile.learns_from_app:
            return
        raw_b64 = decoded.get("raw_b64")
        if not raw_b64:
            return
        ftype = decoded.get("type")

        if ftype == "power":
            # The app also emits 0x84 0x0f frames that are NOT a power-on (e.g.
            # session-refresh packets with params 03 02, seen in issue #1
            # captures). Only the real wake params may be learned, otherwise a
            # refresh packet would overwrite the learned power-on frame.
            current_signature = self._learned_device_signature()
            signature = device_signature_from_frame(raw_b64)
            if (
                not is_wake_power_frame(decoded)
                or decoded.get("crc_valid") is not True
                or signature is None
                or (current_signature is not None and signature != current_signature)
            ):
                _LOGGER.debug(
                    "Ignoring power-family frame with params [%s] (not a valid device wake frame, keeping learned wake frame)",
                    decoded.get("params"),
                )
                return
            if self.learned_wake_frame != raw_b64:
                self.learned_wake_frame = raw_b64
                self._restore_device_app_id()
                _LOGGER.info("Learned a %s wake/power-on frame", self.profile.key)
                self._store.async_delay_save(self._learned_storage_data, RECIPE_STORE_SAVE_DELAY)
            if "wake" in self._discarded_learning_keys:
                self._discarded_learning_keys.remove("wake")
                self._sync_learning_repair_issue()
            return

        if ftype != "beverage":
            return
        bev_hex = decoded.get("beverage_id")
        if not bev_hex:
            return
        try:
            bev_id = int(bev_hex, 16)
        except ValueError, TypeError:
            return
        action = decoded.get("action")
        monitor_status = self.monitor.get("status")
        monitor_step = self.monitor.get("step", self.monitor.get("action"))
        monitor_reports_preparation = (monitor_status == 7 and monitor_step not in (None, 0)) or monitor_status in {
            5,
            10,
            11,
            16,
            17,
        }
        # Eletta uses 0x02 both in some start recipes (notably Espresso) and in
        # stop traffic. Treat it as Stop only when it targets the beverage that
        # was already active and the previous monitor frame showed preparation.
        logical_action = (
            ACTION_STOP
            if action == ACTION_STOP and self.active_beverage_id == bev_id and monitor_reports_preparation
            else ACTION_START
        )
        if action not in {ACTION_START, ACTION_STOP, 0x03} or not validate_replayed_beverage_frame(
            raw_b64,
            bev_id,
            logical_action,
            require_eletta=True,
            expected_signature=self._learned_device_signature(),
        ):
            _LOGGER.warning(
                "Ignoring invalid learned beverage frame 0x%02x action %r",
                bev_id,
                action,
            )
            return
        if logical_action == ACTION_STOP:
            # ``logical_action`` can be Stop only when the same beverage was
            # already tracked as active (see the predicate above).
            self.active_beverage_id = None
        else:
            self.active_beverage_id = bev_id
        table = self.learned_stop_frames if logical_action == ACTION_STOP else self.learned_start_frames
        if table.get(bev_id) != raw_b64:
            table[bev_id] = raw_b64
            self._restore_device_app_id()
            _LOGGER.info(
                "Learned a %s %s frame for beverage 0x%02x (%s)",
                self.profile.key,
                "stop" if logical_action == ACTION_STOP else "start",
                bev_id,
                decoded.get("beverage_name"),
            )
            self._store.async_delay_save(self._learned_storage_data, RECIPE_STORE_SAVE_DELAY)
        learning_key = self._learning_key(bev_id, logical_action)
        if learning_key in self._discarded_learning_keys:
            self._discarded_learning_keys.remove(learning_key)
            self._sync_learning_repair_issue()

    async def async_send_beverage(self, beverage_id: int, action: int) -> None:
        """Build + send a beverage command via the resolved command property."""
        command_written = False

        async def _do() -> None:
            nonlocal command_written
            if action != ACTION_STOP:
                self._validate_beverage_start()
            table = self.learned_stop_frames if action == ACTION_STOP else self.learned_start_frames
            learned = table.get(beverage_id)
            if (
                learned is not None
                and self.profile.learns_from_app
                and not validate_replayed_beverage_frame(
                    learned,
                    beverage_id,
                    action,
                    require_eletta=True,
                    expected_signature=self._learned_device_signature(),
                )
            ):
                table.pop(beverage_id, None)
                self._discarded_learning_keys.add(self._learning_key(beverage_id, action))
                self._sync_learning_repair_issue()
                self._store.async_delay_save(self._learned_storage_data, RECIPE_STORE_SAVE_DELAY)
                raise translated_error("learned_command_invalid")
            value = self.profile.beverage_value(beverage_id, action, learned)
            if value is None:
                if self.profile.learns_from_app:
                    raise translated_error("command_not_learned")
                value = build_and_encode(beverage_id, action)
            try:
                await self._send_property_command(
                    value,
                    f"beverage 0x{beverage_id:02x} action {action}",
                )
            finally:
                command_written = self.last_command_result in {
                    "sent",
                    "acknowledged",
                    "timed_out",
                }

        try:
            await self._run_command_transaction(_do, self._beverage_command_context(beverage_id, action))
        except HomeAssistantError:
            if action != ACTION_STOP and command_written:
                # The property write succeeded even if cloud state propagation
                # missed the confirmation window. Retain the beverage identity
                # so a learned Stop command remains available as a safety path.
                self.active_beverage_id = beverage_id
                self._schedule_post_command_refresh()
                self.async_update_listeners()
            raise
        if action == ACTION_STOP:
            if self.active_beverage_id == beverage_id:
                self.active_beverage_id = None
        else:
            self.active_beverage_id = beverage_id
        self._schedule_post_command_refresh()
        self.async_update_listeners()

    async def async_stop_active_beverage(self) -> None:
        """Stop the tracked active beverage without guessing an identifier."""
        if self.active_beverage_id is None:
            self._begin_command({"command_type": "beverage", "action": "stop"})
            self._set_last_command_result("rejected", completed=True)
            raise translated_error("active_beverage_unknown")
        await self.async_send_beverage(self.active_beverage_id, ACTION_STOP)

    async def _run_command_transaction(
        self,
        send_fn: Callable[[], Awaitable[None]],
        context: dict[str, Any] | None = None,
    ) -> None:
        """Serialize one complete connect, write and confirmation transaction."""
        if self._command_lock.locked():
            # Keep the status and context of the command that is genuinely in
            # progress. The rejected second request is already reported to its
            # caller by the translated validation error below.
            raise translated_error("command_in_progress")

        async with self._command_lock:
            self._begin_command(context)
            try:
                await self._with_cloud_session(send_fn)
            except ConfigEntryAuthFailed:
                self._set_last_command_result("rejected", completed=True)
                raise
            except AuthError as err:
                self._set_last_command_result("rejected", completed=True)
                raise translated_auth_error() from err
            except HomeAssistantError as err:
                if err.translation_key == "cloud_session_timeout":
                    self._set_last_command_result("timed_out", completed=True)
                elif self.last_command_result != "timed_out":
                    self._set_last_command_result("rejected", completed=True)
                raise
            except (TimeoutError, CloudError) as err:
                self._set_last_command_result("timed_out", completed=True)
                raise translated_error("cloud_command_failed") from err
            except Exception as err:
                self._set_last_command_result("rejected", completed=True)
                raise translated_error("command_failed") from err
            if self.last_command_result not in {"sent", "acknowledged"}:
                self._set_last_command_result("sent", completed=True)
            elif self.last_command_result == "sent":
                # No explicit acknowledgement channel is available. The cloud
                # write is still a completed, truthful terminal outcome.
                self._set_last_command_result("sent", completed=True)

    async def async_send_wake(self) -> None:
        """Send the WAKE / power-on command to bring the machine out of standby."""
        if not self.profile.uses_cloud_session:

            async def _send_without_session() -> None:
                value = self.profile.wake_value(self.learned_wake_frame)
                if value is None:
                    if self.profile.learns_from_app:
                        raise translated_error("wake_not_learned")
                    value = build_wake_encoded()
                await self._send_property_command(value, "WAKE command")

            await self._run_command_transaction(_send_without_session, {"command_type": "power", "action": "wake"})
            return

        async def _send_with_session() -> None:
            await self._maybe_send_session_refresh()
            await self._send_property_command(
                self._wake_command_value(),
                "WAKE command",
                confirmation_timeout=POWER_COMMAND_CONFIRM_TIMEOUT,
            )

        await self._run_command_transaction(_send_with_session, {"command_type": "power", "action": "wake"})

    def _learned_device_signature(self) -> bytes | None:
        """Return the device signature carried by any learned app frame."""
        for frame in (
            self.learned_wake_frame,
            *self.learned_start_frames.values(),
            *self.learned_stop_frames.values(),
        ):
            signature = device_signature_from_frame(frame)
            if signature is not None:
                return signature
        return None

    def _restore_device_app_id(self) -> None:
        """Use the learned per-device signature for ECAM cloud sessions."""
        if not self.profile.uses_cloud_session:
            return
        signature = self._learned_device_signature()
        if signature is None:
            return
        app_id = normalize_signed_app_id(int.from_bytes(signature, "big"))
        self._default_app_id = app_id
        self._integration_app_id = app_id

    async def async_send_standby(self) -> None:
        """Send the STANDBY / power-off command."""
        if not self.profile.uses_cloud_session:

            async def _send_without_session() -> None:
                value = self.profile.standby_value(self._learned_device_signature())
                if value is None:
                    if self.profile.learns_from_app:
                        raise translated_error("standby_not_learned")
                    value = build_standby_encoded()
                await self._send_property_command(value, "STANDBY command")

            await self._run_command_transaction(_send_without_session, {"command_type": "power", "action": "standby"})
            return

        async def _send_with_session() -> None:
            await self._send_property_command(
                self._standby_command_value(),
                "STANDBY command",
                confirmation_timeout=POWER_COMMAND_CONFIRM_TIMEOUT,
            )

        await self._run_command_transaction(_send_with_session, {"command_type": "power", "action": "standby"})

    async def async_send_raw(self, value: str) -> None:
        """Validate and safely send a raw administrator-only protocol command.

        A raw action must never become a shortcut around the safeguards used by
        the normal entity and service actions.  Only beverage and wake/standby
        frames for the current model are accepted.  Eletta frames must carry
        the already learned signature of this exact coffee maker, and beverage
        starts pass the same readiness and container checks as normal starts.
        """
        decoded = decode_command(value)
        if "error" in decoded or decoded.get("type") not in {"beverage", "power"} or decoded.get("crc_valid") is not True:
            self._reject_raw_command()

        command_type = decoded["type"]
        action_name = "send"
        beverage_id: int | None = None
        if command_type == "beverage":
            try:
                beverage_id = int(decoded["beverage_id"], 16)
            except KeyError, TypeError, ValueError:
                self._reject_raw_command()

            wire_action = decoded.get("action")
            monitor_status = self.monitor.get("status")
            monitor_step = self.monitor.get("step", self.monitor.get("action"))
            monitor_reports_preparation = (monitor_status == 7 and monitor_step not in (None, 0)) or monitor_status in {
                5,
                10,
                11,
                16,
                17,
            }
            if self.profile.learns_from_app:
                # Eletta uses 0x02 both for some starts and for Stop.  Only an
                # active matching preparation makes it safe to classify as Stop.
                logical_action = (
                    ACTION_STOP
                    if wire_action == ACTION_STOP and self.active_beverage_id == beverage_id and monitor_reports_preparation
                    else ACTION_START
                )
            elif wire_action in {ACTION_START, ACTION_STOP}:
                logical_action = wire_action
            else:
                self._reject_raw_command()
            expected_signature = self._learned_device_signature()
            if (self.profile.learns_from_app and expected_signature is None) or not validate_replayed_beverage_frame(
                value,
                beverage_id,
                logical_action,
                require_eletta=self.profile.learns_from_app,
                expected_signature=expected_signature,
            ):
                self._reject_raw_command()
            action_name = "stop" if logical_action == ACTION_STOP else "start"
        else:
            params = decoded.get("params")
            if params == POWER_WAKE_PARAMS.hex(" "):
                action_name = "wake"
            elif params == POWER_STANDBY_PARAMS.hex(" "):
                action_name = "standby"
            else:
                self._reject_raw_command()
            expected_signature = self._learned_device_signature()
            signature = device_signature_from_frame(value)
            if self.profile.learns_from_app and (expected_signature is None or signature != expected_signature):
                self._reject_raw_command()

        async def _do() -> None:
            if command_type == "beverage" and action_name == "start":
                self._validate_beverage_start()
            await self._send_property_command(value, "RAW command")

        context = {
            "command_type": command_type,
            "action": action_name,
        }
        for key in ("beverage_id", "beverage_name"):
            if key in decoded:
                context[key] = decoded[key]
        await self._run_command_transaction(_do, context)

    def _reject_raw_command(self) -> NoReturn:
        """Publish a rejected raw command and raise its translated error."""
        self._begin_command({"command_type": "raw", "action": "send"})
        self._set_last_command_result("rejected", completed=True)
        raise translated_error("raw_command_invalid")
