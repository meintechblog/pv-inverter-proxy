"""Tests for control state, validation, and SunSpec-to-SolarEdge translation.

Tests cover:
- WMaxLimPct validation (valid/invalid values, NaN detection)
- SunSpec integer+SF to SolarEdge Float32 register translation
- ControlState tracking and Model 123 readback
- ControlState source tracking (Phase 7)
- OverrideLog ring buffer (Phase 7)
- EDPC refresh loop with auto-revert (Phase 7)
"""
from __future__ import annotations

import asyncio
import struct
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from venus_os_fronius_proxy.control import (
    ControlState,
    OverrideLog,
    edpc_refresh_loop,
    validate_wmaxlimpct,
    wmaxlimpct_to_se_registers,
    MODEL_123_START,
    MODEL_123_END,
    WMAXLIMPCT_OFFSET,
    WMAXLIM_ENA_OFFSET,
    WMAXLIMPCT_SF,
    SE_ENABLE_REG,
    SE_POWER_LIMIT_REG,
    SE_CMD_TIMEOUT_REG,
)


# ---------- validate_wmaxlimpct ----------


class TestValidateWMaxLimPct:
    def test_validate_wmaxlimpct_valid_50pct(self):
        """5000 with SF -2 = 50.0% -> valid (None)."""
        assert validate_wmaxlimpct(5000, -2) is None

    def test_validate_wmaxlimpct_valid_100pct(self):
        """10000 with SF -2 = 100.0% -> valid (None)."""
        assert validate_wmaxlimpct(10000, -2) is None

    def test_validate_wmaxlimpct_valid_0pct(self):
        """0 with SF -2 = 0.0% -> valid (None)."""
        assert validate_wmaxlimpct(0, -2) is None

    def test_validate_wmaxlimpct_over_100(self):
        """10001 with SF -2 = 100.01% -> error containing 'exceeds 100%'."""
        result = validate_wmaxlimpct(10001, -2)
        assert result is not None
        assert "exceeds 100%" in result

    def test_validate_wmaxlimpct_negative(self):
        """-1 with SF -2 -> error containing 'negative'."""
        result = validate_wmaxlimpct(-1, -2)
        assert result is not None
        assert "negative" in result

    def test_validate_wmaxlimpct_nan(self):
        """SunSpec NaN encoding (0x7FC0 as uint16) -> error containing 'NaN'."""
        nan_raw = int.from_bytes(struct.pack(">H", 0x7FC0), "big")
        result = validate_wmaxlimpct(nan_raw, -2)
        assert result is not None
        assert "NaN" in result


# ---------- wmaxlimpct_to_se_registers ----------


class TestWMaxLimPctToSERegisters:
    def test_wmaxlimpct_to_se_registers_50pct(self):
        """5000 with SF -2 -> Float32(50.0) as two uint16 registers."""
        hi, lo = wmaxlimpct_to_se_registers(5000, -2)
        packed = struct.pack(">HH", hi, lo)
        assert packed == struct.pack(">f", 50.0)

    def test_wmaxlimpct_to_se_registers_100pct(self):
        """10000 with SF -2 -> Float32(100.0)."""
        hi, lo = wmaxlimpct_to_se_registers(10000, -2)
        packed = struct.pack(">HH", hi, lo)
        assert packed == struct.pack(">f", 100.0)

    def test_wmaxlimpct_to_se_registers_0pct(self):
        """0 with SF -2 -> Float32(0.0)."""
        hi, lo = wmaxlimpct_to_se_registers(0, -2)
        packed = struct.pack(">HH", hi, lo)
        assert packed == struct.pack(">f", 0.0)


# ---------- ControlState ----------


class TestControlState:
    def test_control_state_defaults(self):
        """ControlState starts with wmaxlim_ena=0, wmaxlimpct_raw=0."""
        cs = ControlState()
        assert cs.wmaxlim_ena == 0
        assert cs.wmaxlimpct_raw == 0
        assert cs.is_enabled is False
        assert cs.wmaxlimpct_float == 0.0

    def test_control_state_update_wmaxlimpct(self):
        """update_wmaxlimpct stores value, wmaxlimpct_float returns correct float."""
        cs = ControlState()
        cs.update_wmaxlimpct(5000)
        assert cs.wmaxlimpct_raw == 5000
        assert cs.wmaxlimpct_float == 50.0

    def test_control_state_update_wmaxlim_ena(self):
        """update_wmaxlim_ena sets enabled state."""
        cs = ControlState()
        cs.update_wmaxlim_ena(1)
        assert cs.is_enabled is True
        cs.update_wmaxlim_ena(0)
        assert cs.is_enabled is False

    def test_control_state_readback(self):
        """get_model_123_readback returns 26 registers with correct layout."""
        cs = ControlState()
        cs.update_wmaxlimpct(5000)
        cs.update_wmaxlim_ena(1)
        readback = cs.get_model_123_readback()

        assert len(readback) == 26
        assert readback[0] == 123   # DID
        assert readback[1] == 24    # Length
        assert readback[5] == 5000  # WMaxLimPct at offset 5
        assert readback[9] == 1     # WMaxLim_Ena at offset 9

    def test_control_state_readback_defaults(self):
        """Readback with defaults has DID=123, Length=24, zeros elsewhere."""
        cs = ControlState()
        readback = cs.get_model_123_readback()

        assert len(readback) == 26
        assert readback[0] == 123
        assert readback[1] == 24
        assert readback[5] == 0     # WMaxLimPct default
        assert readback[9] == 0     # WMaxLim_Ena default


# ---------- Constants ----------


class TestControlConstants:
    def test_model_123_start(self):
        assert MODEL_123_START == 40149

    def test_model_123_end(self):
        assert MODEL_123_END == 40174

    def test_se_power_limit_reg(self):
        assert SE_POWER_LIMIT_REG == 0xF322

    def test_se_enable_reg(self):
        assert SE_ENABLE_REG == 0xF300

    def test_se_cmd_timeout_reg(self):
        assert SE_CMD_TIMEOUT_REG == 0xF310


# ---------- ControlState source tracking (Phase 7) ----------


class TestControlStateSourceTracking:
    def test_defaults(self):
        """New ControlState has last_source='none', last_change_ts=0, no revert."""
        cs = ControlState()
        assert cs.last_source == "none"
        assert cs.last_change_ts == 0.0
        assert cs.webapp_revert_at is None

    def test_set_from_webapp(self):
        """set_from_webapp updates wmaxlimpct, ena, source, ts, revert deadline."""
        cs = ControlState()
        before = time.time()
        cs.set_from_webapp(5000, 1, revert_timeout=300.0)
        after = time.time()

        assert cs.wmaxlimpct_raw == 5000
        assert cs.wmaxlim_ena == 1
        assert cs.last_source == "webapp"
        assert before <= cs.last_change_ts <= after
        assert cs.webapp_revert_at is not None
        # monotonic deadline should be in the future
        assert cs.webapp_revert_at > time.monotonic() - 1

    def test_set_from_venus_os_cancels_revert(self):
        """set_from_venus_os sets source, cancels webapp revert."""
        cs = ControlState()
        cs.set_from_webapp(5000, 1)
        assert cs.webapp_revert_at is not None

        before = time.time()
        cs.set_from_venus_os()
        after = time.time()

        assert cs.last_source == "venus_os"
        assert before <= cs.last_change_ts <= after
        assert cs.webapp_revert_at is None


# ---------- OverrideLog (Phase 7) ----------


class TestOverrideLog:
    def test_empty_log(self):
        """New OverrideLog.get_all() returns empty list."""
        log = OverrideLog()
        assert log.get_all() == []

    def test_append_and_get_all(self):
        """Appended events appear in get_all with correct fields."""
        log = OverrideLog()
        log.append("webapp", "set", 50.0, "manual test")
        events = log.get_all()
        assert len(events) == 1
        e = events[0]
        assert e["source"] == "webapp"
        assert e["action"] == "set"
        assert e["value"] == 50.0
        assert e["detail"] == "manual test"
        assert "ts" in e

    def test_maxlen_eviction(self):
        """When maxlen exceeded, oldest events are evicted."""
        log = OverrideLog(maxlen=3)
        for i in range(5):
            log.append("webapp", "set", float(i))
        events = log.get_all()
        assert len(events) == 3
        assert events[0]["value"] == 2.0
        assert events[2]["value"] == 4.0


# ---------- EDPC refresh loop (Phase 7) ----------


class TestEdpcRefreshLoop:
    @pytest.mark.asyncio
    async def test_refresh_writes_when_active(self):
        """Loop calls plugin.write_power_limit when enabled and source != none."""
        cs = ControlState()
        cs.update_wmaxlimpct(5000)
        cs.update_wmaxlim_ena(1)
        cs.last_source = "webapp"
        cs.webapp_revert_at = time.monotonic() + 9999  # far future

        plugin = AsyncMock()
        from venus_os_fronius_proxy.plugin import WriteResult
        plugin.write_power_limit = AsyncMock(return_value=WriteResult(success=True))
        log = OverrideLog()

        task = asyncio.create_task(
            edpc_refresh_loop(plugin, cs, log, interval=0.05)
        )
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert plugin.write_power_limit.call_count >= 1
        plugin.write_power_limit.assert_called_with(True, 50.0)

    @pytest.mark.asyncio
    async def test_auto_revert_on_deadline(self):
        """Loop auto-reverts when webapp_revert_at deadline has passed."""
        cs = ControlState()
        cs.update_wmaxlimpct(5000)
        cs.update_wmaxlim_ena(1)
        cs.last_source = "webapp"
        cs.webapp_revert_at = time.monotonic() - 1  # already passed

        plugin = AsyncMock()
        from venus_os_fronius_proxy.plugin import WriteResult
        plugin.write_power_limit = AsyncMock(return_value=WriteResult(success=True))
        log = OverrideLog()

        task = asyncio.create_task(
            edpc_refresh_loop(plugin, cs, log, interval=0.05)
        )
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Should have called write_power_limit(False, 0.0) to disable
        plugin.write_power_limit.assert_any_call(False, 0.0)
        assert cs.last_source == "none"
        assert cs.webapp_revert_at is None
        assert cs.wmaxlim_ena == 0
        # Should have logged revert event
        events = log.get_all()
        assert any(e["action"] == "revert" for e in events)

    @pytest.mark.asyncio
    async def test_skip_when_disabled(self):
        """Loop does nothing when control is disabled."""
        cs = ControlState()  # defaults: ena=0, source="none"

        plugin = AsyncMock()
        log = OverrideLog()

        task = asyncio.create_task(
            edpc_refresh_loop(plugin, cs, log, interval=0.05)
        )
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        plugin.write_power_limit.assert_not_called()


# ---------- Lock state (Phase 11) ----------


class TestControlStateLock:
    def test_lock_defaults(self):
        """New ControlState has is_locked=False, lock_expires_at=None."""
        cs = ControlState()
        assert cs.is_locked is False
        assert cs.lock_expires_at is None

    def test_lock_sets_is_locked(self):
        """lock() sets is_locked=True."""
        cs = ControlState()
        cs.lock()
        assert cs.is_locked is True

    def test_lock_sets_deadline(self):
        """lock() sets lock_expires_at in the future."""
        cs = ControlState()
        before = time.monotonic()
        cs.lock(900.0)
        after = time.monotonic()
        assert cs.lock_expires_at is not None
        assert before + 900.0 <= cs.lock_expires_at <= after + 900.0

    def test_lock_caps_at_900s(self):
        """lock(2000) caps duration at 900s (HARD CAP)."""
        cs = ControlState()
        before = time.monotonic()
        cs.lock(2000.0)
        after = time.monotonic()
        assert cs.lock_expires_at is not None
        # Must be capped at 900, not 2000
        assert cs.lock_expires_at <= after + 900.1
        assert cs.lock_expires_at >= before + 899.9

    def test_lock_default_duration_900(self):
        """lock() with no args uses 900s default."""
        cs = ControlState()
        before = time.monotonic()
        cs.lock()
        after = time.monotonic()
        assert cs.lock_expires_at is not None
        assert before + 899.9 <= cs.lock_expires_at <= after + 900.1

    def test_unlock_clears_state(self):
        """unlock() clears is_locked and lock_expires_at."""
        cs = ControlState()
        cs.lock(900.0)
        assert cs.is_locked is True
        cs.unlock()
        assert cs.is_locked is False
        assert cs.lock_expires_at is None

    def test_check_lock_expiry_not_expired(self):
        """check_lock_expiry() returns False when lock not expired."""
        cs = ControlState()
        cs.lock(900.0)
        assert cs.check_lock_expiry() is False
        assert cs.is_locked is True

    def test_check_lock_expiry_expired(self):
        """check_lock_expiry() returns True and unlocks when expired."""
        cs = ControlState()
        cs.lock(0.0)  # Expires immediately
        # monotonic should now be >= lock_expires_at
        assert cs.check_lock_expiry() is True
        assert cs.is_locked is False
        assert cs.lock_expires_at is None

    def test_check_lock_expiry_not_locked(self):
        """check_lock_expiry() returns False when not locked."""
        cs = ControlState()
        assert cs.check_lock_expiry() is False

    def test_lock_remaining_s_not_locked(self):
        """lock_remaining_s returns None when not locked."""
        cs = ControlState()
        assert cs.lock_remaining_s is None

    def test_lock_remaining_s_locked(self):
        """lock_remaining_s returns approximate remaining seconds when locked."""
        cs = ControlState()
        cs.lock(900.0)
        remaining = cs.lock_remaining_s
        assert remaining is not None
        assert 899.0 <= remaining <= 900.1


class TestEdpcLockExpiry:
    @pytest.mark.asyncio
    async def test_edpc_auto_unlock_expired(self):
        """edpc_refresh_loop auto-unlocks expired lock and broadcasts."""
        cs = ControlState()
        cs.lock(0.0)  # Expires immediately

        plugin = AsyncMock()
        from venus_os_fronius_proxy.plugin import WriteResult
        plugin.write_power_limit = AsyncMock(return_value=WriteResult(success=True))
        log = OverrideLog()
        broadcast = AsyncMock()

        task = asyncio.create_task(
            edpc_refresh_loop(plugin, cs, log, interval=0.05, broadcast_fn=broadcast)
        )
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Lock should have been cleared
        assert cs.is_locked is False
        # Should have logged the auto-unlock
        events = log.get_all()
        assert any(e["action"] == "unlock" and "auto-unlock" in e.get("detail", "") for e in events)
        # Should have broadcast
        assert broadcast.call_count >= 1
