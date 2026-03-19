"""Read ESS settings from Venus OS via Modbus TCP.

Polls Venus OS periodically and stores the latest settings in a dict
that gets included in the dashboard snapshot.
"""
from __future__ import annotations

import asyncio
import time

import structlog

logger = structlog.get_logger(component="venus_reader")


async def read_venus_settings(host: str, port: int = 502) -> dict | None:
    """Read ESS settings from Venus OS Modbus TCP (unit 100).

    Returns dict with parsed values, or None on failure.
    """
    from pymodbus.client import AsyncModbusTcpClient

    try:
        client = AsyncModbusTcpClient(host, port=port)
        await client.connect()
        if not client.connected:
            return None

        # ESS settings (unit 100, regs 2700-2709)
        r = await client.read_holding_registers(2700, count=10, device_id=100)
        if r.isError():
            client.close()
            return None
        regs = r.registers

        def s16(v: int) -> int:
            return v - 65536 if v > 32767 else v

        max_feed_in_raw = regs[6]  # 2706, scale *100
        # raw=0 means unlimited (-1 on dbus), raw>0 means limit in hecto-watts
        raw_signed = s16(max_feed_in_raw)
        if raw_signed <= 0:
            max_feed_in_w = -1  # Unlimited
        else:
            max_feed_in_w = raw_signed * 100

        # Grid power (unit 100, regs 820-822: L1/L2/L3 int16, 1W scale)
        # Negative = feeding into grid, positive = consuming from grid
        grid_feed_in_w = 0.0
        try:
            rg = await client.read_holding_registers(820, count=3, device_id=100)
            if not rg.isError():
                total_grid = sum(s16(v) for v in rg.registers)
                # Show as positive feed-in (negative grid = exporting)
                grid_feed_in_w = max(0, -total_grid)
        except Exception:
            pass

        # PV inverter power limit (pvinverter unit, reg 1056, uint32 in W)
        pv_limit_w = None
        try:
            rp = await client.read_holding_registers(1056, count=2, device_id=20)
            if not rp.isError():
                pv_limit_w = (rp.registers[0] << 16) | rp.registers[1]
        except Exception:
            pass

        client.close()

        return {
            "ac_setpoint_w": s16(regs[0]),          # 2700: Grid setpoint
            "max_feed_in_w": max_feed_in_w,          # 2706: Max feed-in setting
            "grid_feed_in_w": grid_feed_in_w,        # Actual grid feed-in (positive = exporting)
            "prevent_feedback": bool(regs[8]),        # 2708: AC-coupled PV excess
            "limiter_active": bool(regs[9]),          # 2709: PV power limiter active
            "pv_limit_w": pv_limit_w,                 # Current PV power limit in W
            "ts": time.time(),
        }
    except Exception as e:
        logger.debug("venus_read_failed", error=str(e))
        return None


async def venus_reader_loop(
    shared_ctx: dict,
    host: str,
    port: int = 502,
    interval: float = 10.0,
) -> None:
    """Background task that polls Venus OS settings periodically."""
    while True:
        try:
            data = await read_venus_settings(host, port)
            if data is not None:
                shared_ctx["venus_settings"] = data
        except Exception:
            pass
        await asyncio.sleep(interval)
