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
)
from venus_os_fronius_proxy.proxy import (
    run_proxy,
    StalenessAwareSlaveContext,
    POLL_INTERVAL,
    STALENESS_TIMEOUT,
    _poll_loop,
    _start_server,
    COMMON_CACHE_ADDR,
    INVERTER_CACHE_ADDR,
)
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


async def _wait_for_cache_update(
    client: AsyncModbusTcpClient,
    address: int,
    count: int,
    timeout: float = 2.0,
    poll_interval: float = 0.05,
) -> list[int]:
    """Polling-with-retry: read registers until non-zero or timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        result = await client.read_holding_registers(
            address, count=count, device_id=PROXY_UNIT_ID,
        )
        if not result.isError():
            if any(v != 0 for v in result.registers):
                return list(result.registers)
        await asyncio.sleep(poll_interval)
    raise TimeoutError(f"Cache not updated within {timeout}s for address {address}")


async def _start_proxy_and_connect(plugin, port, poll_interval=0.05):
    """Start a proxy and return (task, client). Caller must clean up."""
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

class TestServerConnection:
    @pytest.mark.asyncio
    async def test_server_accepts_connection(self):
        """Proxy accepts Modbus TCP connections."""
        port = _next_port()
        plugin = _make_mock_plugin(poll_success=True)
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            assert client.connected
        finally:
            await _cleanup(proxy_task, client)

    @pytest.mark.asyncio
    async def test_unit_id_126_only(self):
        """Reads from unit ID 1 fail; reads from unit ID 126 succeed."""
        port = _next_port()
        plugin = _make_mock_plugin(poll_success=True)
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            # Unit 126 should work
            result_126 = await client.read_holding_registers(
                40000, count=2, device_id=PROXY_UNIT_ID,
            )
            assert not result_126.isError()

            # Unit 1 should fail -- pymodbus may raise ModbusIOException
            # or return an error response depending on version/framing
            from pymodbus.exceptions import ModbusIOException
            try:
                result_1 = await client.read_holding_registers(
                    40000, count=2, device_id=1,
                )
                # If we get here, it should be an error response
                assert result_1.isError()
            except ModbusIOException:
                # pymodbus raises this for unknown unit IDs -- this IS the error
                pass
        finally:
            await _cleanup(proxy_task, client)


class TestSunSpecDiscovery:
    @pytest.mark.asyncio
    async def test_sunspec_discovery_flow(self):
        """Walk the SunSpec model chain: Header -> 1 -> 103 -> 120 -> 123 -> 0xFFFF."""
        port = _next_port()
        plugin = _make_mock_plugin(poll_success=True)
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
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
            await _cleanup(proxy_task, client)


class TestCacheServing:
    @pytest.mark.asyncio
    async def test_inverter_registers_from_cache(self):
        """After polling, inverter registers match mock plugin data."""
        port = _next_port()
        plugin = _make_mock_plugin(poll_success=True)
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            regs = await _wait_for_cache_update(
                client, 40071, count=1, timeout=2.0,
            )
            assert regs[0] == 440  # Sample I_AC_Current
        finally:
            await _cleanup(proxy_task, client)

    @pytest.mark.asyncio
    async def test_serves_from_cache(self):
        """Server reads from cache, not passthrough. Initial read may be zeros."""
        port = _next_port()
        plugin = _make_mock_plugin(poll_success=True)
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            # Read immediately -- may be zeros before first poll
            initial = await client.read_holding_registers(
                40071, count=1, device_id=PROXY_UNIT_ID,
            )
            assert not initial.isError()

            # Wait for cache update
            regs = await _wait_for_cache_update(
                client, 40071, count=1, timeout=2.0,
            )
            assert regs[0] == 440
        finally:
            await _cleanup(proxy_task, client)

    @pytest.mark.asyncio
    async def test_common_model_has_fronius_manufacturer(self):
        """After poll, Common Model manufacturer reads 'Fronius' (translated)."""
        port = _next_port()
        plugin = _make_mock_plugin(poll_success=True)
        proxy_task, client = await _start_proxy_and_connect(plugin, port)
        try:
            regs = await _wait_for_cache_update(
                client, 40004, count=16, timeout=2.0,
            )
            raw = b"".join(r.to_bytes(2, "big") for r in regs)
            manufacturer = raw.decode("ascii").rstrip("\x00")
            assert manufacturer == "Fronius"
        finally:
            await _cleanup(proxy_task, client)


class TestStaleness:
    @pytest.mark.asyncio
    async def test_returns_error_when_stale(self):
        """When cache is stale, server returns Modbus error on reads."""
        port = _next_port()
        plugin = _make_mock_plugin(poll_success=False)

        from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext
        from pymodbus.server import ModbusTcpServer

        initial_values = build_initial_registers()
        datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
        cache = RegisterCache(datablock, staleness_timeout=0.1)

        model_120_regs = plugin.get_model_120_registers()
        datablock.setValues(40122, model_120_regs)

        slave_ctx = StalenessAwareSlaveContext(cache=cache, hr=datablock)
        server_ctx = ModbusServerContext(
            devices={PROXY_UNIT_ID: slave_ctx}, single=False,
        )

        await plugin.connect()

        server = ModbusTcpServer(
            context=server_ctx, address=(TEST_HOST, port),
        )

        async def run_stale():
            await asyncio.gather(
                _start_server(server),
                _poll_loop(plugin, cache, poll_interval=0.05),
            )

        proxy_task = asyncio.create_task(run_stale())

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
            proxy_task.cancel()
            pytest.fail("Could not connect to stale proxy server")

        try:
            # Wait for staleness timeout to pass
            await asyncio.sleep(0.3)

            # When cache is stale, server raises exception which pymodbus
            # converts to ExceptionResponse (SLAVE_FAILURE 0x04).
            # Client may receive this as isError() or as ModbusIOException.
            from pymodbus.exceptions import ModbusIOException
            try:
                result = await client.read_holding_registers(
                    40071, count=1, device_id=PROXY_UNIT_ID,
                )
                assert result.isError(), "Expected Modbus error when cache is stale"
            except ModbusIOException:
                # Client framing error on exception response -- still proves
                # server rejected the read (stale cache behavior working)
                pass
        finally:
            client.close()
            proxy_task.cancel()
            try:
                await proxy_task
            except asyncio.CancelledError:
                pass


class TestProxyConstants:
    def test_poll_interval_default(self):
        """POLL_INTERVAL is 1.0 seconds."""
        assert POLL_INTERVAL == 1.0

    def test_staleness_timeout_default(self):
        """STALENESS_TIMEOUT is 30.0 seconds."""
        assert STALENESS_TIMEOUT == 30.0
