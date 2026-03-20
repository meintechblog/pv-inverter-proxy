"""Integration tests for proxy server orchestration.

Uses a real pymodbus server on high ports with mock plugins.
Tests verify SunSpec discovery, cache-based serving, staleness error behavior,
and unit ID filtering.
"""
from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.datastore import ModbusSequentialDataBlock

from venus_os_fronius_proxy.plugin import InverterPlugin, PollResult, WriteResult
from venus_os_fronius_proxy.sunspec_models import (
    PROXY_UNIT_ID,
    encode_string,
    COMMON_DID,
    COMMON_LENGTH,
    INVERTER_DID,
    INVERTER_LENGTH,
    NAMEPLATE_DID,
    NAMEPLATE_LENGTH,
    CONTROLS_DID,
    CONTROLS_LENGTH,
    DATABLOCK_START,
    build_initial_registers,
    apply_common_translation,
)
from venus_os_fronius_proxy.proxy import (
    run_modbus_server,
    StalenessAwareSlaveContext,
    POLL_INTERVAL,
    STALENESS_TIMEOUT,
    _start_server,
    COMMON_CACHE_ADDR,
    INVERTER_CACHE_ADDR,
)
from venus_os_fronius_proxy.context import AppContext
from venus_os_fronius_proxy.control import ControlState, OverrideLog
from venus_os_fronius_proxy.register_cache import RegisterCache


# ---------- Sample Data ----------

def _make_sample_common() -> list[int]:
    """67 registers: DID=1, Length=65, Manufacturer='SolarEdge', rest zeros."""
    regs = [0] * 67
    regs[0] = COMMON_DID       # 1
    regs[1] = COMMON_LENGTH    # 65
    regs[2:18] = encode_string("SolarEdge", 16)
    regs[18:34] = encode_string("SE30K", 16)
    regs[42:50] = encode_string("4.12.30", 8)
    regs[50:66] = encode_string("7F1234567890ABCD", 16)
    regs[66] = 1
    return regs


def _make_sample_inverter() -> list[int]:
    """52 registers: DID=103, Length=50, with sample measurement values."""
    regs = [0] * 52
    regs[0] = INVERTER_DID     # 103
    regs[1] = INVERTER_LENGTH  # 50
    regs[2] = 440              # I_AC_Current
    regs[3] = 147              # I_AC_CurrentA
    regs[6] = struct.unpack(">H", struct.pack(">h", -1))[0]  # I_AC_Current_SF
    regs[14] = 28500           # I_AC_Power
    regs[15] = 0               # I_AC_Power_SF
    regs[38] = 4               # I_Status = MPPT
    return regs


# ---------- Mock Plugin ----------

def _make_mock_plugin(poll_success: bool = True) -> InverterPlugin:
    """Create a mock InverterPlugin with configurable poll behavior."""
    plugin = MagicMock(spec=InverterPlugin)
    plugin.connect = AsyncMock()
    plugin.close = AsyncMock()

    if poll_success:
        plugin.poll = AsyncMock(return_value=PollResult(
            common_registers=_make_sample_common(),
            inverter_registers=_make_sample_inverter(),
            success=True,
        ))
    else:
        plugin.poll = AsyncMock(return_value=PollResult(
            common_registers=[], inverter_registers=[],
            success=False, error="Connection refused",
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


# ---------- Test Helpers ----------

TEST_HOST = "127.0.0.1"
# Use a counter to avoid port conflicts between fixtures
_port_counter = 15500


def _next_port() -> int:
    global _port_counter
    _port_counter += 2
    return _port_counter


async def _start_server_and_connect(port, app_ctx=None):
    """Start a modbus server and return (cache, control_state, server_task, client)."""
    if app_ctx is None:
        app_ctx = AppContext()
    cache, control_state, server, server_task = await run_modbus_server(
        host=TEST_HOST, port=port, app_ctx=app_ctx,
    )

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
    pytest.fail("Could not connect to proxy server")


async def _cleanup_server(server_task, client):
    """Clean up server task and client."""
    client.close()
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass


# ---------- Tests ----------

class TestServerConnection:
    @pytest.mark.asyncio
    async def test_server_accepts_connection(self):
        """Proxy accepts Modbus TCP connections."""
        port = _next_port()
        cache, control_state, server_task, client = await _start_server_and_connect(port)
        try:
            assert client.connected
        finally:
            await _cleanup_server(server_task, client)

    @pytest.mark.asyncio
    async def test_unit_id_126_only(self):
        """Reads from unit ID 1 fail; reads from unit ID 126 succeed."""
        port = _next_port()
        cache, control_state, server_task, client = await _start_server_and_connect(port)
        try:
            # Unit 126 should work (cache is stale initially, so reads may fail
            # with staleness error -- but that's still "accepted" vs "rejected")
            # Populate cache to avoid staleness
            translated_common = apply_common_translation(_make_sample_common())
            cache.update(COMMON_CACHE_ADDR, translated_common)
            cache.update(INVERTER_CACHE_ADDR, _make_sample_inverter())

            result_126 = await client.read_holding_registers(
                40000, count=2, device_id=PROXY_UNIT_ID,
            )
            assert not result_126.isError()

            # Unit 1 should fail
            from pymodbus.exceptions import ModbusIOException
            try:
                result_1 = await client.read_holding_registers(
                    40000, count=2, device_id=1,
                )
                assert result_1.isError()
            except ModbusIOException:
                pass
        finally:
            await _cleanup_server(server_task, client)


class TestSunSpecDiscovery:
    @pytest.mark.asyncio
    async def test_sunspec_discovery_flow(self):
        """Walk the SunSpec model chain: Header -> 1 -> 103 -> 120 -> 123 -> 0xFFFF."""
        port = _next_port()
        cache, control_state, server_task, client = await _start_server_and_connect(port)
        try:
            # Populate cache so reads don't fail with staleness
            translated_common = apply_common_translation(_make_sample_common())
            cache.update(COMMON_CACHE_ADDR, translated_common)
            cache.update(INVERTER_CACHE_ADDR, _make_sample_inverter())

            # SunSpec Header at 40000-40001
            header = await client.read_holding_registers(
                40000, count=2, device_id=PROXY_UNIT_ID,
            )
            assert not header.isError()
            assert header.registers[0] == 0x5375  # "Su"
            assert header.registers[1] == 0x6E53  # "nS"

            # Common Model at 40002
            common = await client.read_holding_registers(
                40002, count=2, device_id=PROXY_UNIT_ID,
            )
            assert not common.isError()
            assert common.registers[0] == COMMON_DID      # 1
            assert common.registers[1] == COMMON_LENGTH    # 65

            # Model 103 at 40069
            inv = await client.read_holding_registers(
                40069, count=2, device_id=PROXY_UNIT_ID,
            )
            assert not inv.isError()
            assert inv.registers[0] == INVERTER_DID    # 103
            assert inv.registers[1] == INVERTER_LENGTH # 50

            # Model 120 at 40121
            np_regs = await client.read_holding_registers(
                40121, count=2, device_id=PROXY_UNIT_ID,
            )
            assert not np_regs.isError()
            assert np_regs.registers[0] == NAMEPLATE_DID    # 120
            assert np_regs.registers[1] == NAMEPLATE_LENGTH # 26

            # Model 123 at 40149
            ctrl = await client.read_holding_registers(
                40149, count=2, device_id=PROXY_UNIT_ID,
            )
            assert not ctrl.isError()
            assert ctrl.registers[0] == CONTROLS_DID    # 123
            assert ctrl.registers[1] == CONTROLS_LENGTH # 24

            # End marker at 40175
            end = await client.read_holding_registers(
                40175, count=2, device_id=PROXY_UNIT_ID,
            )
            assert not end.isError()
            assert end.registers[0] == 0xFFFF
            assert end.registers[1] == 0x0000
        finally:
            await _cleanup_server(server_task, client)


class TestCacheServing:
    @pytest.mark.asyncio
    async def test_inverter_registers_from_cache(self):
        """After cache update, inverter registers match sample data."""
        port = _next_port()
        cache, control_state, server_task, client = await _start_server_and_connect(port)
        try:
            # Populate cache directly (no poll loop in proxy.py anymore)
            cache.update(INVERTER_CACHE_ADDR, _make_sample_inverter())
            cache.update(COMMON_CACHE_ADDR, apply_common_translation(_make_sample_common()))

            await asyncio.sleep(0.1)  # Let server process

            result = await client.read_holding_registers(
                40071, count=1, device_id=PROXY_UNIT_ID,
            )
            assert not result.isError()
            assert result.registers[0] == 440  # Sample I_AC_Current
        finally:
            await _cleanup_server(server_task, client)

    @pytest.mark.asyncio
    async def test_common_model_has_fronius_manufacturer(self):
        """After cache update, Common Model manufacturer reads 'Fronius' (translated)."""
        port = _next_port()
        cache, control_state, server_task, client = await _start_server_and_connect(port)
        try:
            translated_common = apply_common_translation(_make_sample_common())
            cache.update(COMMON_CACHE_ADDR, translated_common)
            cache.update(INVERTER_CACHE_ADDR, _make_sample_inverter())

            await asyncio.sleep(0.1)

            result = await client.read_holding_registers(
                40004, count=16, device_id=PROXY_UNIT_ID,
            )
            assert not result.isError()
            raw = b"".join(r.to_bytes(2, "big") for r in result.registers)
            manufacturer = raw.decode("ascii").rstrip("\x00")
            assert manufacturer == "Fronius"
        finally:
            await _cleanup_server(server_task, client)


class TestStaleness:
    @pytest.mark.asyncio
    async def test_returns_error_when_stale(self):
        """When cache is stale, server returns Modbus error on reads."""
        port = _next_port()

        initial_values = build_initial_registers()
        datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
        cache = RegisterCache(datablock, staleness_timeout=0.1)

        slave_ctx = StalenessAwareSlaveContext(cache=cache, hr=datablock)

        from pymodbus.datastore import ModbusServerContext
        from pymodbus.server import ModbusTcpServer

        server_ctx = ModbusServerContext(
            devices={PROXY_UNIT_ID: slave_ctx}, single=False,
        )

        server = ModbusTcpServer(
            context=server_ctx, address=(TEST_HOST, port),
        )

        server_task = asyncio.create_task(_start_server(server))

        client = AsyncModbusTcpClient(TEST_HOST, port=port)
        for _ in range(40):
            try:
                connected = await client.connect()
                if connected:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.05)
        else:
            server_task.cancel()
            pytest.fail("Could not connect to stale proxy server")

        try:
            # Cache is stale (never updated), wait a bit for staleness to be clear
            await asyncio.sleep(0.2)

            from pymodbus.exceptions import ModbusIOException
            try:
                result = await client.read_holding_registers(
                    40071, count=1, device_id=PROXY_UNIT_ID,
                )
                assert result.isError(), "Expected Modbus error when cache is stale"
            except ModbusIOException:
                pass
        finally:
            client.close()
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                pass


class TestProxyConstants:
    def test_poll_interval_default(self):
        """POLL_INTERVAL is 1.0 seconds."""
        assert POLL_INTERVAL == 1.0

    def test_staleness_timeout_default(self):
        """STALENESS_TIMEOUT is 30.0 seconds."""
        assert STALENESS_TIMEOUT == 30.0


class TestVenusOsOverrideTracking:
    @pytest.mark.asyncio
    async def test_venus_override_sets_source(self):
        """After _handle_control_write for WMaxLimPct, control.last_source == 'venus_os'."""
        plugin = _make_mock_plugin(poll_success=True)
        initial_values = build_initial_registers()
        datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
        cache = RegisterCache(datablock, staleness_timeout=30.0)
        control = ControlState()
        override_log = OverrideLog()

        # Set a webapp revert to verify it gets cancelled
        control.set_from_webapp(5000, 1)
        assert control.webapp_revert_at is not None

        slave_ctx = StalenessAwareSlaveContext(
            cache=cache, plugin=plugin, control_state=control, hr=datablock,
        )

        # Write WMaxLimPct (offset 5 from MODEL_123_START=40149 -> addr 40154)
        await slave_ctx._handle_control_write(40154, [5000])

        assert control.last_source == "venus_os"
        assert control.last_change_ts > 0
        assert control.webapp_revert_at is None  # cancelled

    @pytest.mark.asyncio
    async def test_venus_override_ena_sets_source(self):
        """After _handle_control_write for WMaxLim_Ena, control.last_source == 'venus_os'."""
        plugin = _make_mock_plugin(poll_success=True)
        initial_values = build_initial_registers()
        datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
        cache = RegisterCache(datablock, staleness_timeout=30.0)
        control = ControlState()

        slave_ctx = StalenessAwareSlaveContext(
            cache=cache, plugin=plugin, control_state=control, hr=datablock,
        )

        # Write WMaxLim_Ena (offset 9 from MODEL_123_START -> addr 40158)
        await slave_ctx._handle_control_write(40158, [1])

        assert control.last_source == "venus_os"
        assert control.webapp_revert_at is None


# ---------- Lock check in write path (Phase 11) ----------


class TestProxyLockBehavior:
    @pytest.mark.asyncio
    async def test_locked_wmaxlimpct_not_forwarded(self):
        """When locked, WMaxLimPct write accepted but NOT forwarded to inverter."""
        plugin = _make_mock_plugin(poll_success=True)
        initial_values = build_initial_registers()
        datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
        cache = RegisterCache(datablock, staleness_timeout=30.0)
        control = ControlState()
        control.lock(900.0)
        control.last_source = "webapp"  # Set a known source

        slave_ctx = StalenessAwareSlaveContext(
            cache=cache, plugin=plugin, control_state=control, hr=datablock,
        )

        # Write WMaxLimPct while locked
        await slave_ctx._handle_control_write(40154, [5000])

        # Plugin should NOT have been called
        plugin.write_power_limit.assert_not_called()
        # Local register should still be updated
        assert control.wmaxlimpct_raw == 5000

    @pytest.mark.asyncio
    async def test_locked_wmaxlim_ena_not_forwarded(self):
        """When locked, WMaxLim_Ena write accepted but NOT forwarded to inverter."""
        plugin = _make_mock_plugin(poll_success=True)
        initial_values = build_initial_registers()
        datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
        cache = RegisterCache(datablock, staleness_timeout=30.0)
        control = ControlState()
        control.lock(900.0)
        control.last_source = "webapp"

        slave_ctx = StalenessAwareSlaveContext(
            cache=cache, plugin=plugin, control_state=control, hr=datablock,
        )

        # Write WMaxLim_Ena while locked
        await slave_ctx._handle_control_write(40158, [1])

        # Plugin should NOT have been called
        plugin.write_power_limit.assert_not_called()
        # Local register should still be updated
        assert control.wmaxlim_ena == 1

    @pytest.mark.asyncio
    async def test_locked_does_not_update_source(self):
        """When locked, write does NOT call set_from_venus_os (source unchanged)."""
        plugin = _make_mock_plugin(poll_success=True)
        initial_values = build_initial_registers()
        datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
        cache = RegisterCache(datablock, staleness_timeout=30.0)
        control = ControlState()
        control.lock(900.0)
        control.last_source = "webapp"

        slave_ctx = StalenessAwareSlaveContext(
            cache=cache, plugin=plugin, control_state=control, hr=datablock,
        )

        await slave_ctx._handle_control_write(40154, [5000])

        # Source should NOT have changed to "venus_os"
        assert control.last_source == "webapp"

    @pytest.mark.asyncio
    async def test_unlocked_still_forwards(self):
        """When unlocked (default), write is forwarded to inverter normally."""
        plugin = _make_mock_plugin(poll_success=True)
        initial_values = build_initial_registers()
        datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
        cache = RegisterCache(datablock, staleness_timeout=30.0)
        control = ControlState()
        # is_locked defaults to False
        control.update_wmaxlim_ena(1)  # Enable so the plugin is called

        slave_ctx = StalenessAwareSlaveContext(
            cache=cache, plugin=plugin, control_state=control, hr=datablock,
        )

        await slave_ctx._handle_control_write(40154, [5000])

        # Plugin SHOULD have been called
        plugin.write_power_limit.assert_called_once()
        assert control.last_source == "venus_os"


# ---------- Venus OS Auto-Detection (Phase 15) ----------


class TestVenusAutoDetect:
    @pytest.mark.asyncio
    async def test_first_model123_write_sets_detected(self):
        """After async_setValues with a Model 123 address, venus_os_detected is True."""
        plugin = _make_mock_plugin(poll_success=True)
        initial_values = build_initial_registers()
        datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
        cache = RegisterCache(datablock, staleness_timeout=30.0)
        control = ControlState()
        app_ctx = AppContext()
        app_ctx.override_log = OverrideLog()

        slave_ctx = StalenessAwareSlaveContext(
            cache=cache, plugin=plugin, control_state=control,
            app_ctx=app_ctx, hr=datablock,
        )

        await slave_ctx.async_setValues(0x06, 40154, [50])

        assert app_ctx.venus_os_detected is True
        assert isinstance(app_ctx.venus_os_detected_ts, float)
        assert app_ctx.venus_os_detected_ts > 0

    @pytest.mark.asyncio
    async def test_detection_only_fires_once(self):
        """After two Model 123 writes, timestamp does not change on the second call."""
        plugin = _make_mock_plugin(poll_success=True)
        initial_values = build_initial_registers()
        datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
        cache = RegisterCache(datablock, staleness_timeout=30.0)
        control = ControlState()
        app_ctx = AppContext()
        app_ctx.override_log = OverrideLog()

        slave_ctx = StalenessAwareSlaveContext(
            cache=cache, plugin=plugin, control_state=control,
            app_ctx=app_ctx, hr=datablock,
        )

        await slave_ctx.async_setValues(0x06, 40154, [50])
        ts1 = app_ctx.venus_os_detected_ts

        await slave_ctx.async_setValues(0x06, 40154, [60])
        assert ts1 == app_ctx.venus_os_detected_ts

    @pytest.mark.asyncio
    async def test_non_model123_write_no_detection(self):
        """A setValues call to a non-Model-123 address does NOT set venus_os_detected."""
        initial_values = build_initial_registers()
        datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
        cache = RegisterCache(datablock, staleness_timeout=30.0)
        control = ControlState()
        app_ctx = AppContext()

        slave_ctx = StalenessAwareSlaveContext(
            cache=cache, control_state=control,
            app_ctx=app_ctx, hr=datablock,
        )

        # Write to non-Model-123 address (inverter register area)
        slave_ctx.setValues(0x06, 40070, [100])
        assert app_ctx.venus_os_detected is False
