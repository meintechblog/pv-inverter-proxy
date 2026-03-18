"""Connection management with exponential backoff and night mode.

Handles SE30K connection lifecycle: reconnection on failure with exponential
backoff (5s to 60s), and night mode transition after 5 minutes of continuous
failure. Night mode serves synthetic zero-power registers with SLEEPING status
instead of Modbus errors, since the inverter is expected to be offline at night.
"""
from __future__ import annotations

import enum
import time

from venus_os_fronius_proxy.sunspec_models import INVERTER_DID, INVERTER_LENGTH


class ConnectionState(enum.Enum):
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    NIGHT_MODE = "night_mode"


class ConnectionManager:
    """Manages reconnection backoff and night mode transitions.

    State machine:
      CONNECTED -> RECONNECTING (first poll failure)
      RECONNECTING -> NIGHT_MODE (>5 min continuous failure)
      RECONNECTING -> CONNECTED (poll success)
      NIGHT_MODE -> CONNECTED (poll success)

    Backoff: starts at INITIAL_BACKOFF (5s), doubles each failure, caps at MAX_BACKOFF (60s).
    Resets to INITIAL_BACKOFF on any successful poll.
    """

    INITIAL_BACKOFF = 5.0
    MAX_BACKOFF = 60.0
    NIGHT_MODE_THRESHOLD = 300.0  # 5 minutes

    def __init__(self, poll_interval: float = 1.0):
        self._poll_interval = poll_interval
        self._backoff = self.INITIAL_BACKOFF
        self._first_failure_time: float | None = None
        self._state = ConnectionState.CONNECTED
        self._reconnected_from_night = False

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def reconnected_from_night(self) -> bool:
        """True if last state change was NIGHT_MODE -> CONNECTED. Reset after read."""
        val = self._reconnected_from_night
        self._reconnected_from_night = False
        return val

    @property
    def sleep_duration(self) -> float:
        if self._state == ConnectionState.CONNECTED:
            return self._poll_interval
        return self._backoff

    def on_poll_success(self) -> ConnectionState:
        """Call after a successful poll. Returns the new state."""
        prev = self._state
        self._backoff = self.INITIAL_BACKOFF
        self._first_failure_time = None
        self._state = ConnectionState.CONNECTED
        if prev == ConnectionState.NIGHT_MODE:
            self._reconnected_from_night = True
        return self._state

    def on_poll_failure(self, now: float | None = None) -> ConnectionState:
        """Call after a failed poll. Returns the new state.

        Args:
            now: Current monotonic time (injectable for testing). Defaults to time.monotonic().
        """
        if now is None:
            now = time.monotonic()

        if self._first_failure_time is None:
            self._first_failure_time = now

        elapsed = now - self._first_failure_time

        if elapsed > self.NIGHT_MODE_THRESHOLD and self._state != ConnectionState.NIGHT_MODE:
            self._state = ConnectionState.NIGHT_MODE
        elif self._state == ConnectionState.CONNECTED:
            self._state = ConnectionState.RECONNECTING

        self._backoff = min(self._backoff * 2, self.MAX_BACKOFF)
        return self._state


def build_night_mode_inverter_registers(last_energy_wh: int = 0) -> list[int]:
    """Build synthetic Model 103 inverter registers for night mode.

    Returns 52 uint16 values (DID + Length + 50 data) with:
    - All power, current, voltage = 0
    - Energy = last_energy_wh (preserved from last known value)
    - Status = 4 (SLEEPING per CONTEXT.md decision)
    - Vendor status = 0
    """
    regs = [0] * 52
    regs[0] = INVERTER_DID   # 103
    regs[1] = INVERTER_LENGTH  # 50

    # Energy: I_AC_Energy_WH at offset 26-27 (acc32, big-endian)
    regs[26] = (last_energy_wh >> 16) & 0xFFFF  # high word
    regs[27] = last_energy_wh & 0xFFFF           # low word

    # Status: I_Status at offset 40 = SLEEPING (4)
    regs[40] = 4  # SLEEPING

    return regs
