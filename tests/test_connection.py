"""Tests for ConnectionManager state machine with exponential backoff and night mode."""
from __future__ import annotations

import pytest

from venus_os_fronius_proxy.connection import (
    ConnectionManager,
    ConnectionState,
    build_night_mode_inverter_registers,
)


class TestConnectionStateTransitions:
    """Test state machine transitions."""

    def test_initial_state_is_connected(self):
        mgr = ConnectionManager(poll_interval=1.0)
        assert mgr.state == ConnectionState.CONNECTED

    def test_first_failure_transitions_to_reconnecting(self):
        mgr = ConnectionManager()
        new_state = mgr.on_poll_failure(now=0.0)
        assert new_state == ConnectionState.RECONNECTING
        assert mgr.state == ConnectionState.RECONNECTING

    def test_success_returns_to_connected(self):
        mgr = ConnectionManager()
        mgr.on_poll_failure(now=0.0)
        new_state = mgr.on_poll_success()
        assert new_state == ConnectionState.CONNECTED
        assert mgr.state == ConnectionState.CONNECTED


class TestBackoff:
    """Test exponential backoff behavior."""

    def test_backoff_doubles(self):
        mgr = ConnectionManager(poll_interval=1.0)
        mgr.on_poll_failure(now=0.0)
        assert mgr.sleep_duration == 10.0  # 5.0 * 2
        mgr.on_poll_failure(now=10.0)
        assert mgr.sleep_duration == 20.0  # 10.0 * 2

    def test_backoff_caps_at_max(self):
        mgr = ConnectionManager(poll_interval=1.0)
        # Drive backoff up past max: 5->10->20->40->60(capped)->60
        for i in range(10):
            mgr.on_poll_failure(now=float(i))
        assert mgr.sleep_duration == 60.0

    def test_reconnect_resets_backoff(self):
        mgr = ConnectionManager(poll_interval=1.0)
        mgr.on_poll_failure(now=0.0)
        mgr.on_poll_failure(now=10.0)
        assert mgr.sleep_duration == 20.0
        mgr.on_poll_success()
        assert mgr.sleep_duration == 1.0  # poll_interval when CONNECTED

    def test_sleep_duration_is_poll_interval_when_connected(self):
        mgr = ConnectionManager(poll_interval=2.5)
        assert mgr.sleep_duration == 2.5

    def test_sleep_duration_is_backoff_when_reconnecting(self):
        mgr = ConnectionManager(poll_interval=1.0)
        mgr.on_poll_failure(now=0.0)
        assert mgr.state == ConnectionState.RECONNECTING
        assert mgr.sleep_duration == 10.0  # INITIAL_BACKOFF * 2


class TestNightMode:
    """Test night mode transitions after 5-minute threshold."""

    def test_night_mode_after_threshold(self):
        mgr = ConnectionManager(poll_interval=1.0)
        # First failure sets the clock
        mgr.on_poll_failure(now=0.0)
        assert mgr.state == ConnectionState.RECONNECTING
        # 4 minutes: still reconnecting
        mgr.on_poll_failure(now=240.0)
        assert mgr.state == ConnectionState.RECONNECTING
        # Just over 5 minutes: transitions to night mode
        mgr.on_poll_failure(now=301.0)
        assert mgr.state == ConnectionState.NIGHT_MODE

    def test_night_mode_stays_in_night_mode_on_further_failures(self):
        mgr = ConnectionManager(poll_interval=1.0)
        mgr.on_poll_failure(now=0.0)
        mgr.on_poll_failure(now=301.0)
        assert mgr.state == ConnectionState.NIGHT_MODE
        mgr.on_poll_failure(now=600.0)
        assert mgr.state == ConnectionState.NIGHT_MODE

    def test_reconnect_from_night_mode(self):
        mgr = ConnectionManager(poll_interval=1.0)
        mgr.on_poll_failure(now=0.0)
        mgr.on_poll_failure(now=301.0)
        assert mgr.state == ConnectionState.NIGHT_MODE
        mgr.on_poll_success()
        assert mgr.state == ConnectionState.CONNECTED
        # reconnected_from_night should be True (consumes on read)
        assert mgr.reconnected_from_night is True
        # Second read should be False
        assert mgr.reconnected_from_night is False

    def test_reconnect_from_reconnecting_not_night(self):
        mgr = ConnectionManager(poll_interval=1.0)
        mgr.on_poll_failure(now=0.0)
        assert mgr.state == ConnectionState.RECONNECTING
        mgr.on_poll_success()
        assert mgr.reconnected_from_night is False

    def test_backoff_resets_after_night_mode_reconnect(self):
        mgr = ConnectionManager(poll_interval=1.0)
        mgr.on_poll_failure(now=0.0)
        mgr.on_poll_failure(now=301.0)
        assert mgr.state == ConnectionState.NIGHT_MODE
        mgr.on_poll_success()
        assert mgr.sleep_duration == 1.0  # Back to poll_interval
        assert mgr.state == ConnectionState.CONNECTED


class TestNightModeRegisters:
    """Test synthetic night mode register builder."""

    def test_night_mode_registers(self):
        regs = build_night_mode_inverter_registers(last_energy_wh=12345)
        assert len(regs) == 52
        # DID = 103
        assert regs[0] == 103
        # Length = 50
        assert regs[1] == 50
        # All current/voltage/power = 0
        assert regs[2] == 0   # I_AC_Current
        # Energy preserved (big-endian acc32)
        energy = (regs[26] << 16) | regs[27]
        assert energy == 12345
        # Status = SLEEPING (4)
        assert regs[40] == 4

    def test_night_mode_registers_zero_energy(self):
        regs = build_night_mode_inverter_registers(last_energy_wh=0)
        assert regs[26] == 0
        assert regs[27] == 0
        assert regs[40] == 4  # Still SLEEPING

    def test_night_mode_registers_large_energy(self):
        energy = 987654321
        regs = build_night_mode_inverter_registers(last_energy_wh=energy)
        recovered = (regs[26] << 16) | regs[27]
        assert recovered == energy
