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
)
from venus_os_fronius_proxy.proxy import (
    run_proxy,
    StalenessAwareSlaveContext,
    _start_server,
    _poll_loop,
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


async def _start_proxy_and_connect(plugin, port, poll_interval=0.05):
    """Start proxy and return (task, client)."""
    proxy_task = asyncio.create_task(
        run_proxy(plugin, host=TEST_HOST, port=port, poll_interval=poll_interval)
    )

    client = AsyncModbusTcpClient(TEST_HOST, port=port)
    for _ in range(40):
        try:
            connected = await client.connect()
            if connected:
                return proxy_task, client
        except Exception:
            pass
        await asyncio.sleep(0.05)

    proxy_task.cancel()
    try:
        await proxy_task
    except asyncio.CancelledError:
        pass
    pytest.fail("Could not connect to proxy server")


async def _cleanup(proxy_task, client):
    """Clean up proxy task and client."""
    client.close()
    proxy_task.cancel()
    try:
        await proxy_task
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
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            # Wait for first poll to populate cache
            await asyncio.sleep(0.2)

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
            # The last call should be the WMaxLimPct write
            calls = plugin.write_power_limit.call_args_list
            assert len(calls) >= 2  # At least: enable + limit write
            last_call = calls[-1]
            assert last_call.args[0] is True   # enable
            assert last_call.args[1] == 50.0   # limit_pct

        finally:
            await _cleanup(proxy_task, client)

    @pytest.mark.asyncio
    async def test_write_wmaxlimpct_stored_without_enable(self):
        """Write WMaxLimPct=5000 without enabling -- stored locally, no SE30K forward."""
        port = _next_port()
        plugin = _make_write_tracking_plugin()
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            await asyncio.sleep(0.2)

            # Write WMaxLimPct without enabling first
            result = await client.write_register(
                40154, 5000, device_id=PROXY_UNIT_ID,
            )
            assert not result.isError(), f"WMaxLimPct write failed: {result}"

            # Plugin should NOT have been called for write_power_limit
            # (since control is not enabled)
            plugin.write_power_limit.assert_not_called()

        finally:
            await _cleanup(proxy_task, client)

    @pytest.mark.asyncio
    async def test_write_invalid_wmaxlimpct_rejected(self):
        """Write WMaxLimPct=10001 (>100%) to 40154, verify Modbus exception."""
        port = _next_port()
        plugin = _make_write_tracking_plugin()
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            await asyncio.sleep(0.2)

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
            await _cleanup(proxy_task, client)

    @pytest.mark.asyncio
    async def test_readback_returns_last_written_value(self):
        """After writing WMaxLimPct=5000, readback at 40154 returns 5000."""
        port = _next_port()
        plugin = _make_write_tracking_plugin()
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            await asyncio.sleep(0.2)

            # Write WMaxLimPct = 5000
            result = await client.write_register(
                40154, 5000, device_id=PROXY_UNIT_ID,
            )
            assert not result.isError()

            # Read back Model 123 block
            readback = await client.read_holding_registers(
                40149, count=26, device_id=PROXY_UNIT_ID,
            )
            assert not readback.isError()
            assert readback.registers[0] == CONTROLS_DID     # 123
            assert readback.registers[1] == CONTROLS_LENGTH   # 24
            assert readback.registers[5] == 5000              # WMaxLimPct

        finally:
            await _cleanup(proxy_task, client)


class TestWriteWMaxLimEna:
    """Test writing WMaxLim_Ena to Model 123 register 40158."""

    @pytest.mark.asyncio
    async def test_write_enable_calls_plugin(self):
        """Write WMaxLim_Ena=1 to 40158, verify plugin.write_power_limit called."""
        port = _next_port()
        plugin = _make_write_tracking_plugin()
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            await asyncio.sleep(0.2)

            result = await client.write_register(
                40158, 1, device_id=PROXY_UNIT_ID,
            )
            assert not result.isError(), f"Enable write failed: {result}"

            # Verify plugin received the enable command
            plugin.write_power_limit.assert_called_once_with(True, 0.0)

        finally:
            await _cleanup(proxy_task, client)

    @pytest.mark.asyncio
    async def test_write_invalid_ena_rejected(self):
        """Write WMaxLim_Ena=2 (invalid) to 40158, verify Modbus exception."""
        port = _next_port()
        plugin = _make_write_tracking_plugin()
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            await asyncio.sleep(0.2)

            from pymodbus.exceptions import ModbusIOException
            try:
                result = await client.write_register(
                    40158, 2, device_id=PROXY_UNIT_ID,
                )
                assert result.isError(), "Expected error for invalid WMaxLim_Ena"
            except ModbusIOException:
                pass

        finally:
            await _cleanup(proxy_task, client)

    @pytest.mark.asyncio
    async def test_enable_readback(self):
        """After writing WMaxLim_Ena=1, readback at 40158 returns 1."""
        port = _next_port()
        plugin = _make_write_tracking_plugin()
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            await asyncio.sleep(0.2)

            result = await client.write_register(
                40158, 1, device_id=PROXY_UNIT_ID,
            )
            assert not result.isError()

            readback = await client.read_holding_registers(
                40149, count=26, device_id=PROXY_UNIT_ID,
            )
            assert not readback.isError()
            assert readback.registers[9] == 1  # WMaxLim_Ena at offset 9

        finally:
            await _cleanup(proxy_task, client)


class TestFullWritePath:
    """End-to-end write path: enable -> set limit -> verify."""

    @pytest.mark.asyncio
    async def test_full_control_sequence(self):
        """Enable, set 50%, verify plugin calls and readback."""
        port = _next_port()
        plugin = _make_write_tracking_plugin()
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            await asyncio.sleep(0.2)

            # Step 1: Enable
            r1 = await client.write_register(40158, 1, device_id=PROXY_UNIT_ID)
            assert not r1.isError()

            # Step 2: Set limit to 50%
            r2 = await client.write_register(40154, 5000, device_id=PROXY_UNIT_ID)
            assert not r2.isError()

            # Verify calls
            calls = plugin.write_power_limit.call_args_list
            assert len(calls) == 2
            # First call: enable with 0% (default)
            assert calls[0].args == (True, 0.0)
            # Second call: enabled with 50%
            assert calls[1].args == (True, 50.0)

            # Step 3: Readback full Model 123
            rb = await client.read_holding_registers(40149, count=26, device_id=PROXY_UNIT_ID)
            assert not rb.isError()
            assert rb.registers[0] == 123    # DID
            assert rb.registers[1] == 24     # Length
            assert rb.registers[5] == 5000   # WMaxLimPct
            assert rb.registers[9] == 1      # WMaxLim_Ena

            # Step 4: Disable
            r3 = await client.write_register(40158, 0, device_id=PROXY_UNIT_ID)
            assert not r3.isError()

            # Third call: disable
            assert calls[2].args == (False, 50.0)

        finally:
            await _cleanup(proxy_task, client)
