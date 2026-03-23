"""Tests for ConnectionManager state machine with exponential backoff and night mode."""
from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest

from pv_inverter_proxy.connection import (
    ConnectionManager,
    ConnectionState,
    build_night_mode_inverter_registers,
)
from pv_inverter_proxy.control import ControlState
from pv_inverter_proxy.plugin import InverterPlugin, PollResult, WriteResult
from pv_inverter_proxy.proxy import INVERTER_CACHE_ADDR
from pv_inverter_proxy.register_cache import RegisterCache
from pv_inverter_proxy.sunspec_models import (
    build_initial_registers,
    DATABLOCK_START,
    encode_string,
    COMMON_DID,
    COMMON_LENGTH,
    INVERTER_DID,
    INVERTER_LENGTH,
)
from pymodbus.datastore import ModbusSequentialDataBlock


class TestConnectionStateTransitions:
    """Test state machine transitions."""

    def test_initial_state_is_connected(self):
        mgr = ConnectionManager(poll_interval=1.0)
        assert mgr.state == ConnectionState.CONNECTED

    def test_first_failure_stays_connected(self):
        mgr = ConnectionManager()
        new_state = mgr.on_poll_failure(now=0.0)
        assert new_state == ConnectionState.CONNECTED
        assert mgr.state == ConnectionState.CONNECTED

    def test_third_failure_transitions_to_reconnecting(self):
        mgr = ConnectionManager()
        mgr.on_poll_failure(now=0.0)
        mgr.on_poll_failure(now=1.0)
        new_state = mgr.on_poll_failure(now=2.0)
        assert new_state == ConnectionState.RECONNECTING
        assert mgr.state == ConnectionState.RECONNECTING

    def test_success_resets_consecutive_failures(self):
        mgr = ConnectionManager()
        mgr.on_poll_failure(now=0.0)
        mgr.on_poll_failure(now=1.0)
        # 2 failures, still CONNECTED
        assert mgr.state == ConnectionState.CONNECTED
        new_state = mgr.on_poll_success()
        assert new_state == ConnectionState.CONNECTED
        assert mgr.state == ConnectionState.CONNECTED

    def test_success_returns_to_connected_from_reconnecting(self):
        mgr = ConnectionManager()
        mgr.on_poll_failure(now=0.0)
        mgr.on_poll_failure(now=1.0)
        mgr.on_poll_failure(now=2.0)
        assert mgr.state == ConnectionState.RECONNECTING
        new_state = mgr.on_poll_success()
        assert new_state == ConnectionState.CONNECTED
        assert mgr.state == ConnectionState.CONNECTED


class TestBackoff:
    """Test exponential backoff behavior."""

    def test_backoff_doubles(self):
        mgr = ConnectionManager(poll_interval=1.0)
        # First 2 failures: state stays CONNECTED, no backoff increase
        mgr.on_poll_failure(now=0.0)
        assert mgr.sleep_duration == 1.0  # still CONNECTED → poll_interval
        mgr.on_poll_failure(now=1.0)
        assert mgr.sleep_duration == 1.0  # still CONNECTED → poll_interval
        # 3rd failure: transitions to RECONNECTING, backoff doubles
        mgr.on_poll_failure(now=2.0)
        assert mgr.sleep_duration == 10.0  # 5.0 * 2
        # 4th failure: backoff doubles again
        mgr.on_poll_failure(now=12.0)
        assert mgr.sleep_duration == 20.0  # 10.0 * 2

    def test_backoff_caps_at_max(self):
        mgr = ConnectionManager(poll_interval=1.0)
        # Drive backoff up past max
        # First 2 failures stay CONNECTED (no backoff change)
        # Then: 5->10->20->40->60(capped)->60
        for i in range(12):
            mgr.on_poll_failure(now=float(i))
        assert mgr.sleep_duration == 60.0

    def test_reconnect_resets_backoff(self):
        mgr = ConnectionManager(poll_interval=1.0)
        # 3 failures to reach RECONNECTING
        mgr.on_poll_failure(now=0.0)
        mgr.on_poll_failure(now=1.0)
        mgr.on_poll_failure(now=2.0)
        assert mgr.state == ConnectionState.RECONNECTING
        # One more failure to increase backoff further
        mgr.on_poll_failure(now=12.0)
        assert mgr.sleep_duration == 20.0
        mgr.on_poll_success()
        assert mgr.sleep_duration == 1.0  # poll_interval when CONNECTED

    def test_sleep_duration_is_poll_interval_when_connected(self):
        mgr = ConnectionManager(poll_interval=2.5)
        assert mgr.sleep_duration == 2.5

    def test_sleep_duration_is_backoff_when_reconnecting(self):
        mgr = ConnectionManager(poll_interval=1.0)
        mgr.on_poll_failure(now=0.0)
        mgr.on_poll_failure(now=1.0)
        mgr.on_poll_failure(now=2.0)
        assert mgr.state == ConnectionState.RECONNECTING
        assert mgr.sleep_duration == 10.0  # INITIAL_BACKOFF * 2


class TestNightMode:
    """Test night mode transitions after 5-minute threshold."""

    def test_night_mode_after_threshold(self):
        mgr = ConnectionManager(poll_interval=1.0)
        # First failure sets the clock, stays CONNECTED (strike 1)
        mgr.on_poll_failure(now=0.0)
        assert mgr.state == ConnectionState.CONNECTED
        # Second failure (strike 2), still CONNECTED
        mgr.on_poll_failure(now=1.0)
        assert mgr.state == ConnectionState.CONNECTED
        # Third failure transitions to RECONNECTING
        mgr.on_poll_failure(now=2.0)
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
        mgr.on_poll_failure(now=1.0)
        mgr.on_poll_failure(now=2.0)
        mgr.on_poll_failure(now=301.0)
        assert mgr.state == ConnectionState.NIGHT_MODE
        mgr.on_poll_failure(now=600.0)
        assert mgr.state == ConnectionState.NIGHT_MODE

    def test_reconnect_from_night_mode(self):
        mgr = ConnectionManager(poll_interval=1.0)
        mgr.on_poll_failure(now=0.0)
        mgr.on_poll_failure(now=1.0)
        mgr.on_poll_failure(now=2.0)
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
        mgr.on_poll_failure(now=1.0)
        mgr.on_poll_failure(now=2.0)
        assert mgr.state == ConnectionState.RECONNECTING
        mgr.on_poll_success()
        assert mgr.reconnected_from_night is False

    def test_backoff_resets_after_night_mode_reconnect(self):
        mgr = ConnectionManager(poll_interval=1.0)
        mgr.on_poll_failure(now=0.0)
        mgr.on_poll_failure(now=1.0)
        mgr.on_poll_failure(now=2.0)
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


# ---------- Integration Tests ----------

def _make_sample_common() -> list[int]:
    """67 registers: DID=1, Length=65, Manufacturer='SolarEdge', rest zeros."""
    regs = [0] * 67
    regs[0] = COMMON_DID
    regs[1] = COMMON_LENGTH
    regs[2:18] = encode_string("SolarEdge", 16)
    regs[66] = 1
    return regs


def _make_sample_inverter(energy_wh: int = 50000) -> list[int]:
    """52 registers: DID=103, Length=50, with sample values including energy."""
    regs = [0] * 52
    regs[0] = INVERTER_DID
    regs[1] = INVERTER_LENGTH
    regs[2] = 440  # I_AC_Current
    regs[26] = (energy_wh >> 16) & 0xFFFF
    regs[27] = energy_wh & 0xFFFF
    regs[38] = 4  # I_Status = MPPT
    return regs


def _make_cache_and_datablock():
    """Create a RegisterCache + datablock for integration tests."""
    initial_values = build_initial_registers()
    datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
    cache = RegisterCache(datablock, staleness_timeout=30.0)
    return cache, datablock


def _make_mock_plugin_with_sequence(poll_results: list[PollResult]) -> InverterPlugin:
    """Create a mock plugin that returns a sequence of poll results."""
    plugin = MagicMock(spec=InverterPlugin)
    plugin.connect = AsyncMock()
    plugin.close = AsyncMock()
    plugin.poll = AsyncMock(side_effect=poll_results)
    plugin.write_power_limit = AsyncMock(return_value=WriteResult(success=True))
    return plugin


class TestPollLoopReconnection:
    """Integration tests for poll loop with ConnectionManager."""

    @pytest.mark.asyncio
    async def test_poll_loop_reconnects_on_failure(self):
        """Poll loop transitions through RECONNECTING and back to CONNECTED."""
        fail_result = PollResult(
            common_registers=[], inverter_registers=[],
            success=False, error="Connection refused",
        )
        success_result = PollResult(
            common_registers=_make_sample_common(),
            inverter_registers=_make_sample_inverter(),
            success=True,
        )
        # Fail 3 times (to trigger RECONNECTING), then succeed
        results = [fail_result, fail_result, fail_result, success_result]
        plugin = _make_mock_plugin_with_sequence(results)

        cache, _ = _make_cache_and_datablock()
        conn_mgr = ConnectionManager(poll_interval=0.01)

        # Run poll loop for a limited number of iterations
        loop_count = 0

        async def limited_poll_loop():
            nonlocal loop_count
            while loop_count < 4:
                loop_count += 1
                try:
                    result = await plugin.poll()
                    if result.success:
                        conn_mgr.on_poll_success()
                    else:
                        conn_mgr.on_poll_failure()
                        try:
                            await plugin.close()
                        except Exception:
                            pass
                        try:
                            await plugin.connect()
                        except Exception:
                            pass
                except Exception:
                    conn_mgr.on_poll_failure()
                await asyncio.sleep(0.001)

        await limited_poll_loop()

        # After 3 failures and 1 success, should be back to CONNECTED
        assert conn_mgr.state == ConnectionState.CONNECTED
        # Plugin should have been reconnected (close + connect called)
        assert plugin.close.call_count >= 1
        assert plugin.connect.call_count >= 1

    @pytest.mark.asyncio
    async def test_night_mode_injects_synthetic_registers(self):
        """After >5 min failure, cache contains night mode registers with SLEEPING status."""
        cache, datablock = _make_cache_and_datablock()
        conn_mgr = ConnectionManager(poll_interval=0.01)

        # Manually simulate: failures over 5+ minutes using injectable time
        conn_mgr.on_poll_failure(now=0.0)
        conn_mgr.on_poll_failure(now=1.0)
        conn_mgr.on_poll_failure(now=2.0)
        assert conn_mgr.state == ConnectionState.RECONNECTING

        conn_mgr.on_poll_failure(now=301.0)
        assert conn_mgr.state == ConnectionState.NIGHT_MODE

        # Now inject night mode registers into cache (as poll loop would)
        last_energy_wh = 12345
        night_regs = build_night_mode_inverter_registers(last_energy_wh)
        cache.update(INVERTER_CACHE_ADDR, night_regs)

        # Verify cache contains night mode data
        # Read status register: Model 103 offset 40 from INVERTER_CACHE_ADDR
        # INVERTER_CACHE_ADDR = 40070, status at offset 40 = address 40110
        status_values = datablock.getValues(40070 + 40, 1)
        assert status_values[0] == 4  # SLEEPING

        # Verify energy preserved
        energy_hi = datablock.getValues(40070 + 26, 1)[0]
        energy_lo = datablock.getValues(40070 + 27, 1)[0]
        assert (energy_hi << 16) | energy_lo == 12345

    @pytest.mark.asyncio
    async def test_power_limit_restored_after_reconnect(self):
        """After reconnect from night mode, plugin.write_power_limit is called."""
        success_result = PollResult(
            common_registers=_make_sample_common(),
            inverter_registers=_make_sample_inverter(),
            success=True,
        )
        plugin = _make_mock_plugin_with_sequence([success_result])

        cache, _ = _make_cache_and_datablock()
        conn_mgr = ConnectionManager(poll_interval=0.01)

        # Simulate: was in night mode, now reconnecting
        conn_mgr.on_poll_failure(now=0.0)
        conn_mgr.on_poll_failure(now=1.0)
        conn_mgr.on_poll_failure(now=2.0)
        conn_mgr.on_poll_failure(now=301.0)
        assert conn_mgr.state == ConnectionState.NIGHT_MODE

        # Set up control state with an active power limit
        control_state = ControlState()
        control_state.update_wmaxlimpct(75)  # 75% (SF=0)
        control_state.update_wmaxlim_ena(1)     # enabled
        assert control_state.is_enabled
        assert control_state.wmaxlimpct_float == 75.0

        # Now simulate a successful poll (as _poll_loop would do)
        result = await plugin.poll()
        assert result.success
        conn_mgr.on_poll_success()

        # reconnected_from_night should be True
        if conn_mgr.reconnected_from_night and control_state.is_enabled:
            await plugin.write_power_limit(True, control_state.wmaxlimpct_float)

        # Verify write_power_limit was called with correct values
        plugin.write_power_limit.assert_called_once_with(True, 75.0)
