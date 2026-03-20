"""Read Venus OS settings via MQTT (real-time, no polling).

Subscribes to Venus OS MQTT topics and updates app_ctx on every change.
Replaces the old Modbus TCP polling approach.
"""
from __future__ import annotations

import asyncio
import json
import socket
import struct
import time

import structlog

logger = structlog.get_logger(component="venus_reader")

def _mqtt_connect(host: str, port: int = 1883, client_id: str = "pv-proxy-sub") -> socket.socket:
    """Connect to MQTT broker and return socket."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect((host, port))
    cid = client_id.encode()
    payload = struct.pack("!H", 4) + b"MQTT" + bytes([4, 2, 0, 60])
    payload += struct.pack("!H", len(cid)) + cid
    s.send(bytes([0x10, len(payload)]) + payload)
    connack = s.recv(4)
    if len(connack) < 4 or connack[3] != 0:
        s.close()
        raise ConnectionError(
            f"MQTT CONNACK rejected: rc={connack[3] if len(connack) >= 4 else 'short'}"
        )
    return s


def _mqtt_subscribe(s: socket.socket, topics: list[str]) -> None:
    """Subscribe to MQTT topics."""
    msg_id = 1
    sub = struct.pack("!H", msg_id)
    for t in topics:
        tb = t.encode()
        sub += struct.pack("!H", len(tb)) + tb + bytes([0])
    rem = len(sub)
    hdr = bytearray([0x82])
    while rem > 0:
        b = rem % 128
        rem //= 128
        if rem > 0:
            b |= 0x80
        hdr.append(b)
    s.send(bytes(hdr) + sub)


def _mqtt_publish(s: socket.socket, topic: str, message: str = "") -> None:
    """Publish an MQTT message."""
    tb = topic.encode()
    mb = message.encode()
    rem = 2 + len(tb) + len(mb)
    hdr = bytearray([0x30])
    while rem > 0:
        b = rem % 128
        rem //= 128
        if rem > 0:
            b |= 0x80
        hdr.append(b)
    s.send(bytes(hdr) + struct.pack("!H", len(tb)) + tb + mb)


def _parse_mqtt_messages(data: bytes) -> list[tuple[str, dict]]:
    """Parse MQTT PUBLISH packets from raw data."""
    messages = []
    i = 0
    while i < len(data):
        if data[i] & 0xF0 == 0x30:  # PUBLISH
            mult = 1
            rem_len = 0
            j = i + 1
            while j < len(data):
                byte = data[j]
                rem_len += (byte & 0x7F) * mult
                mult *= 128
                j += 1
                if not (byte & 0x80):
                    break
            hdr_len = j - i
            if j + 2 > len(data):
                break
            topic_len = struct.unpack("!H", data[j : j + 2])[0]
            end_pos = i + hdr_len + rem_len
            if j + 2 + topic_len > len(data) or end_pos > len(data):
                break
            topic = data[j + 2 : j + 2 + topic_len].decode(errors="replace")
            payload_bytes = data[j + 2 + topic_len : end_pos]
            try:
                payload = json.loads(payload_bytes)
                messages.append((topic, payload))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            i = end_pos
        else:
            i += 1
    return messages


async def discover_portal_id(host: str, port: int = 1883, timeout: float = 10.0) -> str | None:
    """Auto-discover Venus OS portal ID via MQTT wildcard subscription."""
    loop = asyncio.get_event_loop()
    try:
        def _discover_blocking():
            s = _mqtt_connect(host, port, client_id="pv-proxy-discover")
            _mqtt_subscribe(s, ["N/+/system/0/Serial"])
            s.settimeout(timeout)
            try:
                data = s.recv(8192)
                for topic, payload in _parse_mqtt_messages(data):
                    if "/system/0/Serial" in topic:
                        parts = topic.split("/")
                        if len(parts) >= 2:
                            portal_id = parts[1]
                            logger.info("portal_id_discovered", portal_id=portal_id)
                            return portal_id
            except socket.timeout:
                logger.warning("portal_id_discovery_timeout", host=host, timeout=timeout)
            finally:
                try:
                    s.close()
                except Exception:
                    pass
            return None
        return await asyncio.wait_for(
            loop.run_in_executor(None, _discover_blocking),
            timeout=timeout + 2,
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning("portal_id_discovery_error", error=str(e))
        return None


async def venus_mqtt_loop(app_ctx: object, host: str, port: int, portal_id: str) -> None:
    """Background task: subscribe to Venus OS MQTT and update settings in real-time."""
    if not host:
        logger.info("venus_mqtt_disabled", reason="no host configured")
        app_ctx.venus_mqtt_connected = False
        return

    portal = portal_id

    while True:
        # Auto-discover portal ID if not provided
        if not portal:
            discovered = await discover_portal_id(host, port)
            if discovered:
                portal = discovered
            else:
                logger.warning("portal_id_discovery_failed", host=host)
                app_ctx.venus_mqtt_connected = False
                await asyncio.sleep(30)
                continue

        break

    prefix = f"N/{portal}"

    # Topics to subscribe (wildcards for grid power)
    sub_topics = [
        f"{prefix}/settings/0/Settings/CGwacs/#",
        f"{prefix}/system/0/Ac/Grid/#",
        f"{prefix}/hub4/0/#",
        f"{prefix}/pvinverter/20/Ac/PowerLimit",
        f"{prefix}/vebus/+/State",
    ]

    # R/ topics to request initial values
    request_topics = [
        f"R/{portal}/settings/0/Settings/CGwacs/MaxFeedInPower",
        f"R/{portal}/settings/0/Settings/CGwacs/PreventFeedback",
        f"R/{portal}/settings/0/Settings/CGwacs/OvervoltageFeedIn",
        f"R/{portal}/settings/0/Settings/CGwacs/MaxDischargePower",
        f"R/{portal}/hub4/0/PvPowerLimiterActive",
        f"R/{portal}/system/0/Ac/Grid/L1/Power",
        f"R/{portal}/system/0/Ac/Grid/L2/Power",
        f"R/{portal}/system/0/Ac/Grid/L3/Power",
        f"R/{portal}/pvinverter/20/Ac/PowerLimit",
    ]

    # State
    state = {
        "max_feed_in_w": -1,
        "prevent_feedback": False,
        "overvoltage_feed_in": False,
        "max_inverter_w": -1,
        "limiter_active": False,
        "grid_l1_w": 0,
        "grid_l2_w": 0,
        "grid_l3_w": 0,
        "grid_feed_in_w": 0,
        "pv_limit_w": None,
        "ac_setpoint_w": 0,
        "ess_available": False,
        "vebus_last_ts": 0,
        "ts": time.time(),
    }

    def update_from_topic(topic: str, payload: dict) -> None:
        val = payload.get("value")
        if val is None:
            return
        # Track VE.Bus (Multi/Quattro) presence → ESS availability
        if "/vebus/" in topic:
            state["vebus_last_ts"] = time.time()
            state["ess_available"] = True
        key = topic.split("/")[-1]
        if key == "MaxFeedInPower":
            state["max_feed_in_w"] = val if val >= 0 else -1
        elif key == "PreventFeedback":
            state["prevent_feedback"] = bool(val)
        elif key == "OvervoltageFeedIn":
            state["overvoltage_feed_in"] = bool(val)
        elif key == "MaxDischargePower":
            state["max_inverter_w"] = val if val >= 0 else -1
        elif key == "PvPowerLimiterActive":
            state["limiter_active"] = bool(val)
        elif key == "AcPowerSetPoint":
            state["ac_setpoint_w"] = val
        elif key == "PowerLimit":
            state["pv_limit_w"] = val
        elif "Grid" in topic:
            if "L1/Power" in topic:
                state["grid_l1_w"] = val
            elif "L2/Power" in topic:
                state["grid_l2_w"] = val
            elif "L3/Power" in topic:
                state["grid_l3_w"] = val
            # Calculate total feed-in (negative grid = exporting)
            total = state["grid_l1_w"] + state["grid_l2_w"] + state["grid_l3_w"]
            state["grid_feed_in_w"] = max(0, -total)
        state["ts"] = time.time()

    while True:
        try:
            s = _mqtt_connect(host, port)
            logger.info("venus_mqtt_connected", host=host)
            app_ctx.venus_mqtt_connected = True

            _mqtt_subscribe(s, sub_topics)

            # Request initial values
            for rt in request_topics:
                _mqtt_publish(s, rt, "")

            s.settimeout(1)

            while True:
                try:
                    data = s.recv(8192)
                    if not data:
                        break
                    for topic, payload in _parse_mqtt_messages(data):
                        update_from_topic(topic, payload)
                    app_ctx.venus_settings = dict(state)
                except socket.timeout:
                    # Check ESS staleness (no VE.Bus messages for 30s)
                    if state["vebus_last_ts"] > 0 and time.time() - state["vebus_last_ts"] > 30:
                        state["ess_available"] = False
                    # Send PINGREQ to keep connection alive
                    try:
                        s.send(bytes([0xC0, 0x00]))
                    except Exception:
                        break
                await asyncio.sleep(0.1)

        except Exception as e:
            app_ctx.venus_mqtt_connected = False
            logger.debug("venus_mqtt_error", error=str(e))

        # Reconnect after 5s
        await asyncio.sleep(5)
