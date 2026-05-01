"""Control state, validation, and SunSpec-to-SolarEdge translation.

Manages the Model 123 Immediate Controls write path:
- Validates WMaxLimPct values before forwarding to inverter
- Translates SunSpec integer+SF encoding to SolarEdge Float32
- Tracks control state for readback by Venus OS

Constants reference SolarEdge SE30K proprietary registers
(0xF300-0xF322) used for dynamic power control.
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from collections import deque

from pv_inverter_proxy.sunspec_models import CONTROLS_ADDR, CONTROLS_DID, CONTROLS_LENGTH

logger = logging.getLogger(__name__)

# Model 123 address range in proxy register space
MODEL_123_START = CONTROLS_ADDR      # 40149
MODEL_123_END = CONTROLS_ADDR + 2 + CONTROLS_LENGTH - 1  # 40174

# Register offsets within Model 123 (relative to DID register)
WMAXLIMPCT_OFFSET = 5    # Register 40154 = 40149 + 5
WMAXLIM_ENA_OFFSET = 9   # Register 40158 = 40149 + 9

# Scale factor for WMaxLimPct
# Venus OS dbus-fronius "legacy sunspec limiter" IGNORES the SF register
# and always writes plain integer percent (raw 36 = 36%).
# Confirmed: even after setting SF=-2 in registers, Venus OS still writes
# the same raw values. SF=0 is required.
WMAXLIMPCT_SF = 0

# SolarEdge proprietary control registers
SE_ENABLE_REG = 0xF300        # 62208 - Enable Dynamic Power Control
SE_POWER_LIMIT_REG = 0xF322   # 62242 - Dynamic Active Power Limit (Float32)
SE_CMD_TIMEOUT_REG = 0xF310   # 62224 - Command Timeout (uint32)

# SunSpec NaN encoding for uint16
_SUNSPEC_NAN_UINT16 = 0x7FC0


def validate_wmaxlimpct(raw_value: int, scale_factor: int = WMAXLIMPCT_SF) -> str | None:
    """Validate a WMaxLimPct raw value before forwarding to inverter.

    Args:
        raw_value: SunSpec integer register value
        scale_factor: SunSpec scale factor (default 0)

    Returns:
        None if valid, error string if invalid.
    """
    # Check for SunSpec NaN encoding
    if raw_value == _SUNSPEC_NAN_UINT16:
        return "Invalid value: NaN encoding (0x7FC0)"

    float_pct = raw_value * (10 ** scale_factor)

    if float_pct < 0:
        return f"Invalid value: negative ({float_pct}%)"

    if float_pct > 100:
        return f"Invalid value: exceeds 100% ({float_pct}%)"

    return None


def wmaxlimpct_to_se_registers(raw_value: int, scale_factor: int = WMAXLIMPCT_SF) -> tuple[int, int]:
    """Translate SunSpec WMaxLimPct to SolarEdge Float32 register pair.

    Converts SunSpec integer+SF encoding to IEEE 754 Float32 big-endian,
    split into two uint16 registers for Modbus write to 0xF322-0xF323.

    Args:
        raw_value: SunSpec integer register value
        scale_factor: SunSpec scale factor (default 0)

    Returns:
        Tuple of (hi_register, lo_register) encoding Float32.
    """
    float_pct = raw_value * (10 ** scale_factor)
    packed = struct.pack(">f", float_pct)
    return struct.unpack(">HH", packed)


_LAST_LIMIT_FILE = "/etc/pv-inverter-proxy/last_limit.json"


class ControlState:
    """Tracks Model 123 control state for the proxy.

    Stores the last-written WMaxLimPct and WMaxLim_Ena values,
    provides readback as a complete Model 123 register block.
    WMaxLim_Ena defaults to DISABLED (0) on startup.
    """

    def __init__(self) -> None:
        self.wmaxlim_ena: int = 0
        self.wmaxlimpct_raw: int = 0
        self.scale_factor: int = WMAXLIMPCT_SF
        # Phase 7: source tracking and auto-revert
        self.last_source: str = "none"              # "none" | "venus_os" | "webapp"
        self.last_change_ts: float = 0.0            # time.time() of last change
        self.webapp_revert_at: float | None = None  # monotonic deadline for auto-revert
        # Phase 11: Venus OS lock state
        self.is_locked: bool = False
        self.lock_expires_at: float | None = None   # time.monotonic() deadline
        # Power clamp: min/max bounds for Venus OS regulation (in %)
        self.clamp_min_pct: int = 0    # 0 = no floor (but proxy enforces min 1%)
        self.clamp_max_pct: int = 100  # 100 = no ceiling
        # Per-device clamps: {device_id: {"min": int, "max": int}}
        self.device_clamps: dict = {}
        # Load persistent clamp + lock state
        self._load_ui_state()
        # Load last Venus OS limit (survives restarts)
        self._load_last_limit()

    def _load_last_limit(self) -> None:
        """Restore last Venus OS power limit from disk."""
        try:
            with open(_LAST_LIMIT_FILE) as f:
                data = json.load(f)
            age = time.time() - data.get("ts", 0)
            # Only restore if less than 5 minutes old
            if age < 300 and data.get("source") == "venus_os":
                self.wmaxlimpct_raw = data["raw"]
                self.wmaxlim_ena = 1
                self.last_source = "venus_os"
                self.last_change_ts = data["ts"]
                logger.info("Restored Venus OS limit from disk: %d%%", self.wmaxlimpct_raw)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    def save_last_limit(self) -> None:
        """Persist current limit for restart recovery.

        Writes to two files for belt-and-braces redundancy:

        1. ``_LAST_LIMIT_FILE`` (legacy, kept for the UI state path).
        2. ``state_file.STATE_FILE_PATH`` — Plan 45-05 SAFETY-09 wiring.
           Merges with any existing state so night_mode_active is
           preserved when only the power limit changes.
        """
        try:
            with open(_LAST_LIMIT_FILE, "w") as f:
                json.dump({
                    "raw": self.wmaxlimpct_raw,
                    "source": self.last_source,
                    "ts": time.time(),
                }, f)
        except OSError:
            pass
        # Plan 45-05 SAFETY-09: also mirror to state.json.
        try:
            from pv_inverter_proxy import state_file

            cur = state_file.load_state()
            cur.power_limit_pct = float(self.wmaxlimpct_raw)
            cur.power_limit_set_at = time.time()
            state_file.save_state(cur)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("state_file_mirror_failed: %s", exc)

    _UI_STATE_FILE = "/etc/pv-inverter-proxy/ui_state.json"

    def _load_ui_state(self) -> None:
        """Load persistent UI state (clamp values, webapp limit, lock).

        Webapp-driven limits are restored unconditionally on boot — the user
        explicitly chose them and expects them to survive restarts. Venus
        OS-driven limits use last_limit.json with a TTL instead.
        """
        try:
            with open(self._UI_STATE_FILE) as f:
                data = json.load(f)
            self.clamp_min_pct = data.get("clamp_min_pct", 0)
            self.clamp_max_pct = data.get("clamp_max_pct", 100)
            self.device_clamps = data.get("device_clamps", {})
            # Restore webapp-driven enable + setpoint so the throttle
            # survives service restarts.
            if data.get("wmaxlim_ena") == 1 and data.get("wmaxlimpct_raw", 0) > 0:
                self.wmaxlim_ena = 1
                self.wmaxlimpct_raw = int(data["wmaxlimpct_raw"])
                self.last_source = data.get("last_source", "webapp")
                logger.info(
                    "Restored webapp limit from ui_state: %d%% (source=%s)",
                    self.wmaxlimpct_raw, self.last_source,
                )
            # Restore lock only if not expired
            if data.get("is_locked") and data.get("lock_ts", 0) > 0:
                age = time.time() - data["lock_ts"]
                remaining = 900 - age
                if remaining > 0:
                    self.is_locked = True
                    self.lock_expires_at = time.monotonic() + remaining
                    logger.info("Restored Venus OS lock (%.0fs remaining)", remaining)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    def save_ui_state(self) -> None:
        """Persist clamp + webapp limit + lock state for restart recovery."""
        try:
            with open(self._UI_STATE_FILE, "w") as f:
                json.dump({
                    "clamp_min_pct": self.clamp_min_pct,
                    "clamp_max_pct": self.clamp_max_pct,
                    "device_clamps": self.device_clamps,
                    "wmaxlim_ena": self.wmaxlim_ena,
                    "wmaxlimpct_raw": self.wmaxlimpct_raw,
                    "last_source": self.last_source,
                    "is_locked": self.is_locked,
                    "lock_ts": time.time() if self.is_locked else 0,
                }, f)
        except OSError:
            pass

    def get_device_clamp(self, device_id: str) -> tuple[int, int]:
        """Return (min_pct, max_pct) for a device.

        If no per-device entry exists, auto-initialize with safe defaults
        (0/100) and persist — prevents new devices from inheriting
        restrictive global clamp values.
        """
        dc = self.device_clamps.get(device_id)
        if dc:
            return dc.get("min", 0), dc.get("max", 100)
        # Auto-initialize new devices with unrestricted defaults
        self.device_clamps[device_id] = {"min": 0, "max": 100}
        self.save_ui_state()
        return 0, 100

    def set_device_clamp(self, device_id: str, min_pct: int, max_pct: int) -> None:
        """Set per-device clamp values."""
        min_pct = max(0, min(100, min_pct))
        max_pct = max(0, min(100, max_pct))
        if min_pct > max_pct:
            min_pct = max_pct
        self.device_clamps[device_id] = {"min": min_pct, "max": max_pct}
        self.save_ui_state()

    @property
    def is_enabled(self) -> bool:
        """Whether power limiting is currently enabled."""
        return self.wmaxlim_ena == 1

    @property
    def wmaxlimpct_float(self) -> float:
        """Current power limit as float percentage."""
        return self.wmaxlimpct_raw * (10 ** self.scale_factor)

    def update_wmaxlimpct(self, raw_value: int) -> None:
        """Store a new WMaxLimPct raw value."""
        self.wmaxlimpct_raw = raw_value

    def update_wmaxlim_ena(self, value: int) -> None:
        """Store a new WMaxLim_Ena value (0 or 1)."""
        self.wmaxlim_ena = value

    def get_model_123_readback(self) -> list[int]:
        """Return 26 uint16 registers representing the full Model 123 block.

        Layout: DID=123 at [0], Length=24 at [1], WMaxLimPct at [5],
        WMaxLim_Ena at [9]. All other fields zero.
        """
        regs = [0] * 26
        regs[0] = CONTROLS_DID      # 123
        regs[1] = CONTROLS_LENGTH   # 24
        regs[WMAXLIMPCT_OFFSET] = self.wmaxlimpct_raw
        regs[WMAXLIM_ENA_OFFSET] = self.wmaxlim_ena
        return regs

    def set_from_webapp(self, raw_value: int, ena: int, revert_timeout: float = 300.0) -> None:
        """Update from webapp with auto-revert timer."""
        self.update_wmaxlimpct(raw_value)
        self.update_wmaxlim_ena(ena)
        self.last_source = "webapp"
        self.last_change_ts = time.time()
        self.webapp_revert_at = time.monotonic() + revert_timeout

    def set_from_venus_os(self) -> None:
        """Mark that Venus OS just wrote a control value."""
        self.last_source = "venus_os"
        self.last_change_ts = time.time()
        self.webapp_revert_at = None  # Cancel any webapp revert timer

    def lock(self, duration_s: float = 900.0) -> None:
        """Lock Venus OS power control writes.

        duration_s=0 means permanent (no auto-unlock).
        Otherwise capped at 900s (15 minutes).
        """
        self.is_locked = True
        if duration_s <= 0:
            self.lock_expires_at = None  # Permanent — no auto-unlock
        else:
            duration_s = min(duration_s, 900.0)
            self.lock_expires_at = time.monotonic() + duration_s

    def unlock(self) -> None:
        """Unlock Venus OS power control writes."""
        self.is_locked = False
        self.lock_expires_at = None

    def check_lock_expiry(self) -> bool:
        """Check if lock has expired; auto-unlock if so.

        Returns:
            True if lock was expired and cleared, False otherwise.
        """
        if (
            self.is_locked
            and self.lock_expires_at is not None
            and time.monotonic() >= self.lock_expires_at
        ):
            self.unlock()
            return True
        return False

    @property
    def lock_remaining_s(self) -> float | None:
        """Seconds remaining on lock, or None if not locked."""
        if self.is_locked and self.lock_expires_at is not None:
            return max(0.0, self.lock_expires_at - time.monotonic())
        return None

    def is_model_123_address(self, address: int, count: int) -> bool:
        """Check if an address range overlaps Model 123 registers.

        Args:
            address: Absolute SunSpec address (e.g. 40154)
            count: Number of registers

        Returns:
            True if any register in [address, address+count) overlaps
            [MODEL_123_START, MODEL_123_END].
        """
        return address <= MODEL_123_END and (address + count - 1) >= MODEL_123_START


class OverrideLog:
    """In-memory ring buffer for control override events.

    Stores the last *maxlen* events as dicts with ts/source/action/value/detail.
    """

    def __init__(self, maxlen: int = 50) -> None:
        self._events: deque[dict] = deque(maxlen=maxlen)

    def append(self, source: str, action: str, value: float | None, detail: str = "") -> None:
        """Record a control event."""
        self._events.append({
            "ts": time.time(),
            "source": source,
            "action": action,
            "value": value,
            "detail": detail,
        })

    def get_all(self) -> list[dict]:
        """Return all events as a list (oldest first)."""
        return list(self._events)


async def edpc_refresh_loop(
    plugin: object,
    control_state: ControlState,
    override_log: OverrideLog,
    interval: float = 5.0,
    broadcast_fn: object | None = None,
) -> None:
    """Periodically refresh power limit on SE30K EDPC registers.

    Runs every 5s to keep our limit active even when Venus OS writes
    competing values directly to the inverter. Also checks auto-revert
    deadline and lock expiry.

    Args:
        plugin: InverterPlugin with write_power_limit(enable, limit_pct).
        control_state: Shared ControlState instance.
        override_log: Shared OverrideLog for event recording.
        interval: Seconds between refresh cycles (default 5).
        broadcast_fn: Optional async callable to push snapshot updates.
    """
    while True:
        await asyncio.sleep(interval)

        # Phase 11: check lock expiry before other checks
        if control_state.check_lock_expiry():
            override_log.append("system", "unlock", None, "auto-unlock after timeout")
            if broadcast_fn is not None:
                await broadcast_fn()

        if not control_state.is_enabled or control_state.last_source == "none":
            continue

        # Check auto-revert deadline
        if (
            control_state.webapp_revert_at is not None
            and time.monotonic() >= control_state.webapp_revert_at
        ):
            await plugin.write_power_limit(False, 0.0)
            control_state.update_wmaxlim_ena(0)
            control_state.last_source = "none"
            control_state.webapp_revert_at = None
            override_log.append("system", "revert", None, "auto-revert after timeout")
            if broadcast_fn is not None:
                await broadcast_fn()
            continue

        # Only refresh webapp-initiated limits (Venus OS manages its own refresh)
        if control_state.last_source != "webapp":
            continue

        result = await plugin.write_power_limit(
            True, control_state.wmaxlimpct_float,
        )
        if not result.success:
            logger.warning("EDPC refresh failed: %s", result.error)
