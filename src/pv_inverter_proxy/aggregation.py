"""AggregationLayer: sum N device register sets into one virtual Fronius inverter.

Decodes per-device SunSpec Model 103 registers to physical values,
sums power/current/energy, averages voltage/frequency, takes max temperature,
and re-encodes with consistent fixed scale factors into the shared RegisterCache
that Venus OS reads via Modbus TCP.
"""
from __future__ import annotations

import structlog

from pv_inverter_proxy.config import Config
from pv_inverter_proxy.context import AppContext
from pv_inverter_proxy.proxy import COMMON_CACHE_ADDR, INVERTER_CACHE_ADDR
from pv_inverter_proxy.register_cache import RegisterCache
from pv_inverter_proxy.sunspec_models import (
    COMMON_ADDR,
    COMMON_DID,
    COMMON_LENGTH,
    PROXY_UNIT_ID,
    _int16_as_uint16,
    encode_string,
)

logger = structlog.get_logger()


def decode_model_103_to_physical(inverter_regs: list[int]) -> dict:
    """Decode Model 103 register list to physical values.

    Args:
        inverter_regs: 52 uint16 values (DID + Length + 50 data fields)

    Returns:
        Dict with physical values in standard units (W, A, V, Hz, Wh, C)
    """
    if len(inverter_regs) < 40:
        return None  # Insufficient register data

    def _sf(idx: int) -> int:
        raw = inverter_regs[idx]
        return raw - 65536 if raw > 32767 else raw

    def _val(idx: int, sf_idx: int) -> float:
        if idx >= len(inverter_regs) or sf_idx >= len(inverter_regs):
            return 0.0
        raw = inverter_regs[idx]
        if raw in (0x8000, 0xFFFF):
            return 0.0
        return raw * (10 ** _sf(sf_idx))

    return {
        "ac_current_a": _val(2, 6),
        "ac_current_l1_a": _val(3, 6),
        "ac_current_l2_a": _val(4, 6),
        "ac_current_l3_a": _val(5, 6),
        "ac_voltage_ab_v": _val(7, 13),
        "ac_voltage_bc_v": _val(8, 13),
        "ac_voltage_ca_v": _val(9, 13),
        "ac_voltage_an_v": _val(10, 13),
        "ac_voltage_bn_v": _val(11, 13),
        "ac_voltage_cn_v": _val(12, 13),
        "ac_power_w": _val(14, 15),
        "ac_frequency_hz": _val(16, 17),
        "ac_va": _val(18, 19),
        "ac_var": _val(20, 21),
        "ac_pf": _val(22, 23),
        "energy_total_wh": ((inverter_regs[24] << 16) | inverter_regs[25]) * (10 ** _sf(26)),
        "dc_current_a": _val(27, 28),
        "dc_voltage_v": _val(29, 30),
        "dc_power_w": _val(31, 32),
        "temperature_c": _val(33, 37),
        "temperature_sink_c": _val(34, 37),
        "status_code": inverter_regs[38],
        "status_vendor": inverter_regs[39] if len(inverter_regs) > 39 else 0,
    }


def encode_aggregated_model_103(totals: dict) -> list[int]:
    """Encode aggregated physical values to 52 uint16 SunSpec Model 103 registers.

    Uses FIXED scale factors for consistency:
    - Power: SF=0 (watts as integer)
    - Current: SF=-2 (0.01A resolution)
    - Voltage: SF=-1 (0.1V resolution)
    - Frequency: SF=-2 (0.01Hz resolution)
    - Energy: SF=0 (Wh as integer)
    - Temperature: SF=-1 (0.1C resolution)
    """
    regs = [0] * 52
    regs[0] = 103  # DID
    regs[1] = 50   # Length

    # AC Current (SF=-2)
    regs[2] = int(round(totals["ac_current_a"] * 100)) & 0xFFFF
    regs[3] = int(round(totals["ac_current_l1_a"] * 100)) & 0xFFFF
    regs[4] = int(round(totals["ac_current_l2_a"] * 100)) & 0xFFFF
    regs[5] = int(round(totals["ac_current_l3_a"] * 100)) & 0xFFFF
    regs[6] = _int16_as_uint16(-2)

    # AC Voltage (SF=-1)
    regs[10] = int(round(totals["ac_voltage_an_v"] * 10)) & 0xFFFF
    regs[13] = _int16_as_uint16(-1)

    # AC Power (SF=0)
    regs[14] = int(round(totals["ac_power_w"])) & 0xFFFF
    regs[15] = 0

    # AC Frequency (SF=-2)
    regs[16] = int(round(totals["ac_frequency_hz"] * 100)) & 0xFFFF
    regs[17] = _int16_as_uint16(-2)

    # Energy (SF=0, Wh) -- uint32 split across 2 registers
    energy_wh = int(round(totals["energy_total_wh"]))
    regs[24] = (energy_wh >> 16) & 0xFFFF
    regs[25] = energy_wh & 0xFFFF
    regs[26] = 0

    # DC Current (SF=-2)
    regs[27] = int(round(totals["dc_current_a"] * 100)) & 0xFFFF
    regs[28] = _int16_as_uint16(-2)

    # DC Voltage (SF=-1)
    regs[29] = int(round(totals["dc_voltage_v"] * 10)) & 0xFFFF
    regs[30] = _int16_as_uint16(-1)

    # DC Power (SF=0)
    regs[31] = int(round(totals["dc_power_w"])) & 0xFFFF
    regs[32] = 0

    # Temperature (SF=-1)
    regs[33] = int(round(totals["temperature_c"] * 10)) & 0xFFFF
    regs[37] = _int16_as_uint16(-1)

    # Status -- worst-case across devices
    regs[38] = totals["status_code"]

    return regs


class AggregationLayer:
    """Sums all active device outputs into one virtual Fronius inverter.

    Called after each successful device poll via the on_poll_success callback.
    Reads DeviceState.last_poll_data from all devices in app_ctx.devices,
    decodes to physical values, aggregates, and writes to the shared
    RegisterCache that Venus OS reads.
    """

    def __init__(self, app_ctx: AppContext, cache: RegisterCache, config: Config, broadcast_fn=None) -> None:
        self._app_ctx = app_ctx
        self._cache = cache
        self._config = config
        self._broadcast_fn = broadcast_fn

    async def recalculate(self, device_id: str) -> None:
        """Aggregate all active device data into the shared cache.

        Called after each successful poll. Takes a snapshot of device IDs
        to avoid RuntimeError from concurrent dict modification.

        Args:
            device_id: The device that just completed polling (for logging).
        """
        # Snapshot to avoid dict-changed-size-during-iteration
        device_ids = list(self._app_ctx.devices.keys())

        # Build set of device IDs that participate in aggregation
        aggregate_ids = {e.id for e in self._config.inverters if e.aggregate}

        # Collect active states (those with poll data containing inverter registers)
        active_data: list[dict] = []
        for did in device_ids:
            if did not in aggregate_ids:
                continue
            ds = self._app_ctx.devices.get(did)
            if ds is None:
                continue
            poll_data = ds.last_poll_data
            if poll_data is not None and "inverter_registers" in poll_data:
                active_data.append(poll_data)

        if not active_data:
            # No data -- cache stays stale, no update
            return

        # Decode each device's registers to physical values
        decoded_list = [
            decode_model_103_to_physical(d["inverter_registers"])
            for d in active_data
        ]
        decoded_list = [d for d in decoded_list if d is not None]
        if not decoded_list:
            return

        # Aggregate: sum, average, max, worst-case
        n = len(decoded_list)

        # Fields to sum
        sum_keys = [
            "ac_power_w", "ac_current_a", "ac_current_l1_a",
            "ac_current_l2_a", "ac_current_l3_a", "energy_total_wh",
            "dc_current_a", "dc_power_w",
        ]
        # Fields to average (dc_voltage_v handled separately below)
        avg_keys = [
            "ac_voltage_ab_v", "ac_voltage_bc_v", "ac_voltage_ca_v",
            "ac_voltage_an_v", "ac_voltage_bn_v", "ac_voltage_cn_v",
            "ac_frequency_hz",
        ]

        totals: dict = {}

        for key in sum_keys:
            totals[key] = sum(d[key] for d in decoded_list)

        for key in avg_keys:
            totals[key] = sum(d[key] for d in decoded_list) / n

        # DC voltage: average only devices with actual DC power (skip Shelly/zero-DC)
        dc_devices = [d for d in decoded_list if d["dc_power_w"] > 0]
        totals["dc_voltage_v"] = (
            sum(d["dc_voltage_v"] for d in dc_devices) / len(dc_devices)
            if dc_devices else 0.0
        )

        # Max temperature
        totals["temperature_c"] = max(d["temperature_c"] for d in decoded_list)

        # Worst status (highest code -- 4=MPPT is best, higher is worse)
        totals["status_code"] = max(d["status_code"] for d in decoded_list)

        # Encode aggregated inverter registers
        inverter_regs = encode_aggregated_model_103(totals)
        self._cache.update(INVERTER_CACHE_ADDR, inverter_regs)

        # Build virtual Common Model registers
        virtual_common = self._build_virtual_common()
        self._cache.update(COMMON_CACHE_ADDR, virtual_common)

        # Update WRtg in Model 120
        self._update_wrtg(device_ids)

        logger.debug(
            "aggregation_complete",
            device_count=n,
            total_power_w=totals["ac_power_w"],
            trigger_device=device_id,
        )

        if self._broadcast_fn is not None:
            await self._broadcast_fn(device_id)

    def update_wrtg(self) -> None:
        """Recalculate and write WRtg to datablock. Called after device add/remove."""
        device_ids = list(self._app_ctx.devices.keys())
        self._update_wrtg(device_ids)

    def _update_wrtg(self, active_device_ids: list[str]) -> None:
        """Write WRtg (sum of active rated powers) to Model 120 in the datablock."""
        total_rated = 0
        for entry in self._config.inverters:
            if entry.enabled and entry.aggregate and entry.id in active_device_ids and entry.rated_power > 0:
                total_rated += entry.rated_power

        if total_rated > 0:
            # WRtg is at Model 120 offset 3 (DID=120, Len=26, DERTyp, WRtg)
            # Address 40124, datablock address = 40124 + 1 = 40125
            self._cache.datablock.setValues(40125, [total_rated])

    def _build_virtual_common(self) -> list[int]:
        """Build a 67-register Common Model block for the virtual inverter."""
        regs = [0] * 67

        # DID and Length
        regs[0] = COMMON_DID     # 1
        regs[1] = COMMON_LENGTH  # 65

        # C_Manufacturer (offset 2-17, 16 registers): "Fronius"
        regs[2:18] = encode_string("Fronius", 16)

        # C_Model (offset 18-33, 16 registers): user-defined name or default
        name = self._config.virtual_inverter.name
        if not name:
            name = "Fronius PV-Inverter-Proxy"
        regs[18:34] = encode_string(name, 16)

        # C_Options (offset 34-41, 8 registers): empty
        regs[34:42] = encode_string("", 8)

        # C_Version (offset 42-49, 8 registers): proxy version
        regs[42:50] = encode_string("v4.0", 8)

        # C_SerialNumber (offset 50-65, 16 registers): empty
        regs[50:66] = encode_string("", 16)

        # C_DeviceAddress (offset 66)
        regs[66] = PROXY_UNIT_ID  # 126

        return regs
