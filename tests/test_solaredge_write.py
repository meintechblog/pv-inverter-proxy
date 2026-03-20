"""Integration tests for the SunSpec Model 123 write path.

Tests the full write-through chain: Venus OS -> Proxy -> Mock SE30K.
Verifies WMaxLimPct validation, Float32 translation, and Modbus error
responses for invalid values.
"""
from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusDeviceContext,
    ModbusServerContext,
)
from pymodbus.server import ModbusTcpServer

from venus_os_fronius_proxy.plugin import InverterPlugin, PollResult, WriteResult
from venus_os_fronius_proxy.sunspec_models import (
    PROXY_UNIT_ID,
    DATABLOCK_START,
    CONTROLS_DID,
    CONTROLS_LENGTH,
    encode_string,
    build_initial_registers,
    apply_common_translation,
)
from venus_os_fronius_proxy.proxy import (
    StalenessAwareSlaveContext,
    _start_server,
    COMMON_CACHE_ADDR,
    INVERTER_CACHE_ADDR,
)
from venus_os_fronius_proxy.control import (
    ControlState,
    SE_ENABLE_REG,
    SE_POWER_LIMIT_REG,
)
from venus_os_fronius_proxy.register_cache import RegisterCache


# ---------- Port management ----------

TEST_HOST = "127.0.0.1"
_port_counter = 16500


def _next_port() -> int:
    global _port_counter
    _port_counter += 2
    return _port_counter


# ---------- Sample data ----------


def _make_sample_common() -> list[int]:
    """67 registers for mock poll."""
    regs = [0] * 67
    regs[0] = 1    # DID
    regs[1] = 65   # Length
    regs[2:18] = encode_string("SolarEdge", 16)
    regs[18:34] = encode_string("SE30K", 16)
    regs[42:50] = encode_string("4.12.30", 8)
    regs[50:66] = encode_string("7F1234567890ABCD", 16)
    regs[66] = 1
    return regs


def _make_sample_inverter() -> list[int]:
    """52 registers for mock poll."""
    regs = [0] * 52
    regs[0] = 103
    regs[1] = 50
    regs[2] = 440   # I_AC_Current
    regs[38] = 4     # I_Status = MPPT
    return regs


# ---------- Mock plugin with write tracking ----------


def _make_write_tracking_plugin() -> InverterPlugin:
    """Mock InverterPlugin that tracks write_power_limit calls."""
    plugin = MagicMock(spec=InverterPlugin)
    plugin.connect = AsyncMock()
    plugin.close = AsyncMock()
    plugin.poll = AsyncMock(return_value=PollResult(
        common_registers=_make_sample_common(),
        inverter_registers=_make_sample_inverter(),
        success=True,
    ))
    plugin.write_power_limit = AsyncMock(return_value=WriteResult(success=True))

    from venus_os_fronius_proxy.plugins.solaredge import SolarEdgePlugin
    real_plugin = SolarEdgePlugin()
    plugin.get_model_120_registers = MagicMock(
        return_value=real_plugin.get_model_120_registers()
    )
    plugin.get_static_common_overrides = MagicMock(
        return_value=real_plugin.get_static_common_overrides()
    )
    return plugin


# ---------- Helpers ----------


async def _start_write_server_and_connect(plugin, port):
    """Start a Modbus server with plugin for write forwarding, return (cache, control, task, client)."""
    initial_values = build_initial_registers()
    datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
    cache = RegisterCache(datablock, staleness_timeout=30.0)
    control_state = ControlState()

    # Create slave context WITH plugin for write forwarding
    slave_ctx = StalenessAwareSlaveContext(
        cache=cache, plugin=plugin, control_state=control_state,
        hr=datablock,
    )
    server_ctx = ModbusServerContext(
        devices={PROXY_UNIT_ID: slave_ctx}, single=False,
    )

    server = ModbusTcpServer(
        context=server_ctx, address=(TEST_HOST, port),
    )

    # Pre-populate cache so reads don't fail with staleness
    translated_common = apply_common_translation(_make_sample_common())
    cache.update(COMMON_CACHE_ADDR, translated_common)
    cache.update(INVERTER_CACHE_ADDR, _make_sample_inverter())

    server_task = asyncio.create_task(_start_server(server))

    client = AsyncModbusTcpClient(TEST_HOST, port=port)
    for _ in range(40):
        try:
            connected = await client.connect()
            if connected:
                return cache, control_state, server_task, client
        except Exception:
            pass
        await asyncio.sleep(0.05)

    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass
    pytest.fail("Could not connect to write test server")


async def _cleanup(server_task, client):
    """Clean up server task and client."""
    client.close()
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass


# ---------- Tests ----------


class TestWriteWMaxLimPct:
    """Test writing WMaxLimPct to Model 123 register 40154."""

    @pytest.mark.asyncio
    async def test_write_wmaxlimpct_50pct_forwards_to_plugin(self):
        """Write WMaxLimPct=5000 to 40154, enable first, verify plugin receives Float32 50.0."""
        port = _next_port()
        plugin = _make_write_tracking_plugin()
        cache, control, server_task, client = await _start_write_server_and_connect(plugin, port)
        try:
            # Enable power control first (write 1 to 40158)
            result_ena = await client.write_register(
                40158, 1, device_id=PROXY_UNIT_ID,
            )
            assert not result_ena.isError(), f"Enable write failed: {result_ena}"

            # Write WMaxLimPct = 5000 (50.00%) to register 40154
            result = await client.write_register(
                40154, 5000, device_id=PROXY_UNIT_ID,
            )
            assert not result.isError(), f"WMaxLimPct write failed: {result}"

            # Verify plugin.write_power_limit was called with enable=True, limit_pct=50.0
            calls = plugin.write_power_limit.call_args_list
            assert len(calls) >= 2  # At least: enable + limit write
            last_call = calls[-1]
            assert last_call.args[0] is True   # enable
            assert last_call.args[1] == 50.0   # limit_pct

        finally:
            await _cleanup(server_task, client)

    @pytest.mark.asyncio
    async def test_write_wmaxlimpct_stored_without_enable(self):
        """Write WMaxLimPct=5000 without enabling -- stored locally, implicitly enables."""
        port = _next_port()
        plugin = _make_write_tracking_plugin()
        cache, control, server_task, client = await _start_write_server_and_connect(plugin, port)
        try:
            # Write WMaxLimPct without enabling first
            # Note: in the new code, writing WMaxLimPct implicitly enables
            result = await client.write_register(
                40154, 5000, device_id=PROXY_UNIT_ID,
            )
            assert not result.isError(), f"WMaxLimPct write failed: {result}"

            # Plugin should have been called (implicit enable)
            plugin.write_power_limit.assert_called()

        finally:
            await _cleanup(server_task, client)

    @pytest.mark.asyncio
    async def test_write_invalid_wmaxlimpct_rejected(self):
        """Write WMaxLimPct=10001 (>100%) to 40154, verify Modbus exception."""
        port = _next_port()
        plugin = _make_write_tracking_plugin()
        cache, control, server_task, client = await _start_write_server_and_connect(plugin, port)
        try:
            # Write invalid value (10001 = 100.01%)
            from pymodbus.exceptions import ModbusIOException
            try:
                result = await client.write_register(
                    40154, 10001, device_id=PROXY_UNIT_ID,
                )
                # Should get an error response
                assert result.isError(), "Expected error for invalid WMaxLimPct"
            except ModbusIOException:
                # Also acceptable -- framing error on exception response
                pass

        finally:
            await _cleanup(server_task, client)

    @pytest.mark.asyncio
    async def test_readback_returns_last_written_value(self):
        """After writing WMaxLimPct=5000, readback at 40154 returns 5000."""
        port = _next_port()
        plugin = _make_write_tracking_plugin()
        cache, control, server_task, client = await _start_write_server_and_connect(plugin, port)
        try:
            # Write WMaxLimPct
            result = await client.write_register(
                40154, 5000, device_id=PROXY_UNIT_ID,
            )
            assert not result.isError()

            # Read back -- Model 123 readback is written after each control write
            readback = await client.read_holding_registers(
                40154, count=1, device_id=PROXY_UNIT_ID,
            )
            assert not readback.isError()
            assert readback.registers[0] == 5000

        finally:
            await _cleanup(server_task, client)
