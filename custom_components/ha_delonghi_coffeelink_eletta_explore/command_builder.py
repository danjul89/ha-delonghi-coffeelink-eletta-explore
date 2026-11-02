"""Binary command builder for De'Longhi Coffee Link – Eletta Explore (Ayla transport)."""

from __future__ import annotations

import base64
import binascii
import time
from typing import Any

from .const import (
    BEVERAGES,
    CMD_FAMILY_BREW,
    CMD_FAMILY_POWER,
    CMD_FAMILY_STATISTICS,
    CMD_LENGTH,
    CMD_PREFIX,
    CMD_RESPONSE_PREFIX,
    CRC_INIT,
    CRC_POLY,
    DEFAULT_RECIPE_PARAMS,
    ELETTA_RECIPE_TRAILER,
    POWER_SESSION_REFRESH_PARAMS,
    POWER_STANDBY_PARAMS,
    POWER_WAKE_PARAMS,
    STATISTICS_REQUEST_PARAMS,
)

_BEV_NAMES = {bev_id: display for bev_id, _key, display, _icon in BEVERAGES}
_ACTION_NAMES = {0x01: "start", 0x02: "stop"}


def _session_id_to_tail_bytes(app_id: int) -> bytes:
    """Encode cloud session app id as signed int32 BE (DlghIoT / ayla_client convention)."""
    signed = ((app_id & 0xFFFFFFFF) ^ 0x80000000) - 0x80000000
    return signed.to_bytes(4, "big", signed=True)


def crc16_aug_ccitt(data: bytes) -> int:
    """CRC16 AUG-CCITT: poly 0x1021, init 0x1D0F, BE, no reflection."""
    crc = CRC_INIT
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ CRC_POLY
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def build_beverage_command(
    beverage_id: int,
    action: int,
    params: bytes = DEFAULT_RECIPE_PARAMS,
    timestamp: int | None = None,
) -> bytes:
    """
    Build a raw binary beverage start/stop command.

    beverage_id: 1 byte (see BEVERAGES in const.py)
    action: 0x01 (start) or 0x02 (stop)
    params: 6 bytes of recipe parameters
    timestamp: Unix seconds; None = now
    """
    if timestamp is None:
        timestamp = int(time.time())
    header = bytes([CMD_PREFIX, CMD_LENGTH, CMD_FAMILY_BREW[0], CMD_FAMILY_BREW[1], beverage_id, action]) + params
    if len(header) != 12:
        raise ValueError(f"Header must be 12 bytes, got {len(header)}")
    crc = crc16_aug_ccitt(header)
    return header + crc.to_bytes(2, "big") + timestamp.to_bytes(4, "big")


def serialize_learned_frames(start: dict[int, str], stop: dict[int, str], wake: str | None = None) -> dict[str, Any]:
    """Serialize the learned Eletta frames for persistence (HA Store / JSON).

    Beverage ids become hex strings (JSON keys must be strings); values are the
    captured base64 frames, replayed as-is later with a fresh timestamp. The
    optional power-on (``wake``) frame is a single captured frame.
    """
    data: dict[str, Any] = {
        "start": {f"0x{bev:02x}": frame for bev, frame in start.items()},
        "stop": {f"0x{bev:02x}": frame for bev, frame in stop.items()},
    }
    if wake:
        data["wake"] = wake
    return data


def deserialize_learned_frames(
    data: dict[str, Any] | None,
) -> tuple[dict[int, str], dict[int, str], str | None]:
    """Inverse of :func:`serialize_learned_frames`; tolerant of missing/odd data."""

    def _section(name: str) -> dict[int, str]:
        out: dict[int, str] = {}
        section = (data or {}).get(name) or {}
        if not isinstance(section, dict):
            return out
        for key, frame in section.items():
            if not isinstance(frame, str):
                continue
            try:
                out[int(key, 16)] = frame
            except ValueError, TypeError:
                continue
        return out

    wake = (data or {}).get("wake")
    if not isinstance(wake, str):
        wake = None
    return _section("start"), _section("stop"), wake


def recipe_dump_lines(props: dict[str, Any]) -> list[str]:
    """Render the machine's stored recipe datapoints for a read-only diagnostic.

    Returns ``name = <hex>`` lines for every property whose name contains
    ``_rec_`` (the per-beverage recipe definitions the machine stores, e.g.
    ``d059_rec_1_espresso``) plus the active-profile indicator. Base64 blobs are
    decoded to hex; other values are shown as-is. Sends nothing to the machine -
    used to confirm whether a stored recipe maps to the beverage command's
    variable recipe block (the path to drop the "teach from the app" step).
    """
    lines: list[str] = []
    for name in sorted(props):
        if "_rec_" not in name and name != "d286_mach_sett_profile":
            continue
        prop = props.get(name)
        value = prop.get("value") if isinstance(prop, dict) else prop
        if isinstance(value, str) and value.strip():
            try:
                rendered = base64.b64decode("".join(value.split()), validate=True).hex(" ")
            except ValueError, binascii.Error:
                rendered = value
        else:
            rendered = repr(value)
        lines.append(f"{name} = {rendered}")
    return lines


def replay_with_timestamp(value_b64: str, timestamp: int | None = None) -> str:
    """Re-emit a captured frame with a fresh timestamp and nothing else changed.

    The 4-byte Unix timestamp sits *after* the CRC (which only covers the bytes
    before it), so swapping it leaves the checksum valid. This is how an Eletta
    beverage frame captured from the official app is replayed: byte-for-byte
    identical - same action byte, same variable recipe block, and any trailing
    device signature the app appended - except the timestamp, which must change
    so the cloud/machine treats it as a new command rather than a duplicate.
    """
    raw = bytearray(base64.b64decode("".join(value_b64.split())))
    if timestamp is None:
        timestamp = int(time.time())
    if len(raw) >= 2:
        frame_len = raw[1] + 1
        if len(raw) >= frame_len + 4:
            raw[frame_len : frame_len + 4] = timestamp.to_bytes(4, "big")
    return base64.b64encode(bytes(raw)).decode("ascii")


def encode_command(command_bytes: bytes) -> str:
    """Base64-encode command for transmission via Ayla data_request property."""
    return base64.b64encode(command_bytes).decode("ascii")


def build_and_encode(beverage_id: int, action: int, params: bytes = DEFAULT_RECIPE_PARAMS) -> str:
    """Shortcut: build command + base64 encode for Ayla."""
    return encode_command(build_beverage_command(beverage_id, action, params))


def build_power_command(params: bytes, timestamp: int | None = None, signature: bytes | None = None) -> bytes:
    """
    Build a power-family command (0x84 0x0f): wake, standby, ...

    Frame: 0d 07 84 0f <params 2B> <crc16> <timestamp> [<device signature 4B>]
    Length byte = 0x07, payload before CRC = 6 bytes. The optional 4-byte
    device signature goes AFTER the timestamp (so the CRC is unaffected);
    some models (Eletta Explore) ignore power commands without it.
    """
    if timestamp is None:
        timestamp = int(time.time())
    header = bytes([CMD_PREFIX, 0x07, CMD_FAMILY_POWER[0], CMD_FAMILY_POWER[1]]) + params
    if len(header) != 6:
        raise ValueError(f"Power header must be 6 bytes, got {len(header)}")
    crc = crc16_aug_ccitt(header)
    frame = header + crc.to_bytes(2, "big") + timestamp.to_bytes(4, "big")
    if signature:
        frame += signature
    return frame


def build_wake_command(timestamp: int | None = None) -> bytes:
    """Build the WAKE / power-on command (captured: 0d 07 84 0f 02 01 55 12 <ts>)."""
    return build_power_command(POWER_WAKE_PARAMS, timestamp)


def build_wake_encoded() -> str:
    """Shortcut: build wake command + base64 encode."""
    return encode_command(build_wake_command())


def build_wake_with_session_tail(app_id: int, timestamp: int | None = None) -> bytes:
    """Wake/power-on with the cloud session id in the 4-byte tail (DlghIoT resume)."""
    return build_power_command(POWER_WAKE_PARAMS, timestamp, _session_id_to_tail_bytes(app_id))


def build_wake_with_session_tail_encoded(app_id: int) -> str:
    return encode_command(build_wake_with_session_tail(app_id))


def build_standby_with_session_tail(app_id: int, timestamp: int | None = None) -> bytes:
    """Standby with the cloud session id in the 4-byte tail (DlghIoT standby)."""
    return build_power_command(POWER_STANDBY_PARAMS, timestamp, _session_id_to_tail_bytes(app_id))


def build_standby_with_session_tail_encoded(app_id: int) -> str:
    return encode_command(build_standby_with_session_tail(app_id))


def build_session_refresh_command(app_id: int, timestamp: int | None = None) -> bytes:
    """Deep-standby session nudge (DlghIoT refresh(), params 03 02)."""
    return build_power_command(POWER_SESSION_REFRESH_PARAMS, timestamp, _session_id_to_tail_bytes(app_id))


def build_session_refresh_encoded(app_id: int) -> str:
    return encode_command(build_session_refresh_command(app_id))


def build_statistics_request_command(app_id: int, timestamp: int | None = None) -> bytes:
    """Coffee Link statistics request (0d 06 e8 f0 00 <crc> 00 00 <ts> <session tail>).

    Captured from the official app. The machine answers by uploading its changed
    counter properties (d5xx/d7xx) about twenty seconds later, also from standby.
    """
    if timestamp is None:
        timestamp = int(time.time())
    header = bytes([CMD_PREFIX, 0x06, CMD_FAMILY_STATISTICS[0], CMD_FAMILY_STATISTICS[1]]) + STATISTICS_REQUEST_PARAMS
    crc = crc16_aug_ccitt(header)
    return header + crc.to_bytes(2, "big") + bytes(2) + timestamp.to_bytes(4, "big") + _session_id_to_tail_bytes(app_id)


def build_statistics_request_encoded(app_id: int) -> str:
    return encode_command(build_statistics_request_command(app_id))


def validate_power_frame_b64(value_b64: str, expected_params: bytes) -> bool:
    """True if a base64 frame is a valid power command with the expected params."""
    decoded = decode_command(value_b64)
    return (
        decoded.get("type") == "power" and decoded.get("params") == expected_params.hex(" ") and decoded.get("crc_valid") is True
    )


def validate_replayed_wake_frame(value_b64: str) -> bool:
    """Validate a learned/replayed wake frame before send (params 02 01, CRC ok)."""
    return validate_power_frame_b64(value_b64, POWER_WAKE_PARAMS)


def build_standby_command(timestamp: int | None = None, signature: bytes | None = None) -> bytes:
    """Build the STANDBY / power-off command (0d 07 84 0f 01 01 00 41 <ts>).

    Reported on Eletta Explore (issue #1) and validated live on the reference
    PrimaDonna Soul: the machine powers off as if the physical button was
    pressed. The official app exposes no power-off control, so this frame
    cannot be learned - it is always synthesized.
    """
    return build_power_command(POWER_STANDBY_PARAMS, timestamp, signature)


def build_standby_encoded(signature: bytes | None = None) -> str:
    """Shortcut: build standby command + base64 encode."""
    return encode_command(build_standby_command(signature=signature))


def device_signature_from_frame(frame_b64: str | None) -> bytes | None:
    """Extract the 4-byte device signature from a learned app frame.

    App frames carry a per-machine constant after the timestamp (e.g.
    ``11 22 33 44``). Frame layout: <structural = length_byte + 1> <ts 4B>
    [<signature 4B>]. Returns ``None`` if the frame has no signature.
    """
    if not frame_b64:
        return None
    try:
        raw = base64.b64decode(frame_b64.strip(), validate=True)
    except binascii.Error, ValueError, AttributeError:
        return None
    if len(raw) < 2:
        return None
    structural_len = raw[1] + 1
    sig = raw[structural_len + 4 : structural_len + 8]
    return sig if len(sig) == 4 else None


def validate_replayed_beverage_frame(
    value_b64: str,
    beverage_id: int,
    action: int,
    *,
    require_eletta: bool = False,
    expected_signature: bytes | None = None,
) -> bool:
    """Validate a learned beverage frame before persistence or transmission.

    Learned frames originate outside Home Assistant and are persisted in Store,
    so they must be treated as untrusted input.  A valid replay must identify the
    requested beverage and action, have a valid CRC and internally consistent
    length, use the Eletta layout when requested, and carry the same device
    signature as the already learned frames (when one is known).
    """
    decoded = decode_command(value_b64)
    wire_action = decoded.get("action")
    action_matches = wire_action == 0x02 if action == 0x02 else wire_action in {0x01, 0x02, 0x03}
    if (
        "error" in decoded
        or decoded.get("type") != "beverage"
        or decoded.get("crc_valid") is not True
        or not action_matches
        or decoded.get("beverage_id") != f"0x{beverage_id:02x}"
        or (require_eletta and decoded.get("style") != "eletta")
    ):
        return False
    signature = device_signature_from_frame(value_b64)
    if require_eletta and signature is None:
        return False
    return expected_signature is None or signature == expected_signature


def is_wake_power_frame(decoded: dict[str, Any]) -> bool:
    """True if a decoded frame is a real wake/power-on command (params 02 01).

    The app also emits 0x84 0x0f frames that are NOT a power-on (e.g.
    session-refresh packets with params 03 02, seen in issue #1 captures);
    those must never be learned as the wake frame or they would overwrite
    the learned power-on frame.
    """
    return decoded.get("type") == "power" and decoded.get("params") == POWER_WAKE_PARAMS.hex(" ")


# ---------------------------------------------------------------------------
# Decoding / inspection (used by the diagnostic command sniffer)
#
# These functions never raise on bad input - they return a dict describing what
# could be parsed, so a value captured live from the cloud (possibly written by
# the official Coffee Link app, possibly malformed) can always be logged.
# ---------------------------------------------------------------------------


def decode_command(value_b64: str) -> dict[str, Any]:
    """Decode a base64 command/response payload into a human-readable dict.

    Recognises the app->machine frame families this integration emits
    (brew ``0x83 0xf0``, power/wake ``0x84 0x0f`` and statistics request
    ``0xe8 0xf0``) and machine->app
    responses (prefix ``0xd0``). Unknown shapes still get a hex dump.
    """
    if not isinstance(value_b64, str) or not value_b64.strip():
        return {"raw_b64": value_b64, "error": "value is not a non-empty string"}
    # Ayla returns string datapoints with surrounding whitespace (commonly a
    # trailing newline); normalise it so the frame decodes and round-trips.
    value_b64 = "".join(value_b64.split())
    out: dict[str, Any] = {"raw_b64": value_b64}
    try:
        raw = base64.b64decode(value_b64, validate=True)
    except ValueError, binascii.Error:
        out["error"] = "not valid base64"
        return out

    out["hex"] = raw.hex(" ")
    out["length"] = len(raw)
    if len(raw) >= 4:
        out["prefix"] = f"0x{raw[0]:02x}"
        out["length_byte"] = f"0x{raw[1]:02x}"
        out["family"] = raw[2:4].hex(" ")
    family = bytes(raw[2:4]) if len(raw) >= 4 else b""

    if family == CMD_FAMILY_BREW and len(raw) >= 8:
        out["type"] = "beverage"
        out["beverage_id"] = f"0x{raw[4]:02x}"
        out["beverage_name"] = _BEV_NAMES.get(raw[4], "unknown")
        out["action"] = raw[5]
        out["action_name"] = _ACTION_NAMES.get(raw[5], "?")
        # The frame is self-describing: the length byte (raw[1]) gives the total
        # frame size (through the CRC) minus the start byte, so the same decoder
        # handles the fixed Soul frame and the variable-length Eletta frame.
        frame_len = raw[1] + 1
        if frame_len < 8 or frame_len > len(raw):
            out["error"] = "length byte inconsistent with payload"
            return out
        crc_bytes = raw[frame_len - 2 : frame_len]
        out["crc"] = crc_bytes.hex(" ")
        out["crc_valid"] = crc16_aug_ccitt(raw[0 : frame_len - 2]) == int.from_bytes(crc_bytes, "big")
        # Some Eletta recipes (for example Espresso) terminate the recipe block
        # with 0x01 0x0a, while other valid Eletta recipes observed on the same
        # machine (Cappuccino and Cold Brew) omit that trailer. Eletta app frames
        # still carry the four-byte per-device signature after the timestamp;
        # Soul frames do not. Treat either marker as authoritative instead of
        # rejecting valid signed recipes solely because the optional trailer is
        # absent.
        has_eletta_trailer = raw[frame_len - 4 : frame_len - 2] == ELETTA_RECIPE_TRAILER
        has_device_signature = len(raw) >= frame_len + 8
        eletta = has_eletta_trailer or has_device_signature
        out["style"] = "eletta" if eletta else "soul"
        recipe = raw[6 : (frame_len - 4 if has_eletta_trailer else frame_len - 2)]
        out["recipe"] = recipe.hex(" ")
        # Back-compat: the historical "params" key keeps the first 6 recipe bytes.
        out["params"] = recipe[:6].hex(" ")
        if len(raw) >= frame_len + 4:
            out["timestamp"] = int.from_bytes(raw[frame_len : frame_len + 4], "big")
    elif family == CMD_FAMILY_POWER and len(raw) >= 12:
        out["type"] = "power"
        out["params"] = raw[4:6].hex(" ")
        out["crc"] = raw[6:8].hex(" ")
        out["crc_valid"] = crc16_aug_ccitt(raw[0:6]) == int.from_bytes(raw[6:8], "big")
        out["timestamp"] = int.from_bytes(raw[8:12], "big")
    elif family == CMD_FAMILY_STATISTICS and len(raw) >= 7:
        out["type"] = "statistics_request"
        out["params"] = raw[4:5].hex(" ")
        out["crc"] = raw[5:7].hex(" ")
        out["crc_valid"] = crc16_aug_ccitt(raw[0:5]) == int.from_bytes(raw[5:7], "big")
        if len(raw) >= 13:
            out["timestamp"] = int.from_bytes(raw[9:13], "big")
    elif len(raw) >= 1 and raw[0] == CMD_RESPONSE_PREFIX:
        out["type"] = "machine_response"
    else:
        out["type"] = "unknown"
    return out
