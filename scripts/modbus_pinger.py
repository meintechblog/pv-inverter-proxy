"""Modbus connectivity pinger — Plan 45-05 Task 5 measurement tool.

Connects to a pv-inverter-proxy Modbus TCP endpoint every 0.5s and
reads a few SunSpec Common model registers. Writes "OK"/"DOWN"/"BUSY"
entries with millisecond-precision timestamps to stdout so the operator
can tail the log and compute the Venus OS disconnect window against
the Plan 45-04 baseline (~15s).

``BUSY`` entries are printed when the server returns a standard Modbus
exception (0x06 / DEVICE_BUSY). Venus OS treats these as retryable,
not as a disconnect — so they MUST NOT be counted as downtime.

USAGE:

    .venv/bin/python scripts/modbus_pinger.py \
        --host 192.168.3.191 --port 502 --device-id 126 \
        --duration 120
"""
from __future__ import annotations

import argparse
import asyncio
import time

from pymodbus.client import AsyncModbusTcpClient


async def ping_once(host: str, port: int, device_id: int, timeout_s: float) -> tuple[str, str]:
    """Return (status, detail). status ∈ {OK, BUSY, DOWN}."""
    # Use a generous per-call timeout so slow polls are not misclassified
    # as DOWN; the caller enforces the outer cadence via sleep.
    op_timeout = max(timeout_s, 1.5)
    client = AsyncModbusTcpClient(host=host, port=port, timeout=op_timeout)
    try:
        try:
            connected = await asyncio.wait_for(client.connect(), timeout=op_timeout)
        except (asyncio.TimeoutError, OSError) as exc:
            return "DOWN", f"connect_failed: {exc}"
        if not connected:
            return "DOWN", "connect_returned_false"
        try:
            response = await asyncio.wait_for(
                client.read_holding_registers(address=40003, count=5, device_id=device_id),
                timeout=op_timeout,
            )
        except (asyncio.TimeoutError, OSError, Exception) as exc:
            return "DOWN", f"read_failed: {type(exc).__name__}: {exc}"
        if response.isError():
            exc_code = getattr(response, "exception_code", None)
            if exc_code == 6:
                return "BUSY", "device_busy_0x06"
            return "DOWN", f"modbus_error: exc_code={exc_code}"
        return "OK", f"regs={list(response.registers)[:3]}"
    finally:
        try:
            client.close()
        except Exception:
            pass


async def main(host: str, port: int, device_id: int, duration: int, interval: float) -> int:
    deadline = time.monotonic() + duration
    first_down_ts: float | None = None
    last_down_ts: float | None = None
    total_down = 0
    total_busy = 0
    total_ok = 0
    max_gap_start: float | None = None
    max_gap_s: float = 0.0

    while time.monotonic() < deadline:
        ts = time.time()
        status, detail = await ping_once(host, port, device_id, timeout_s=interval)
        ts_str = time.strftime("%H:%M:%S", time.localtime(ts)) + f".{int((ts % 1) * 1000):03d}"
        print(f"{ts_str} {status:<4} {detail}", flush=True)

        if status == "DOWN":
            total_down += 1
            if first_down_ts is None:
                first_down_ts = ts
                max_gap_start = ts
            last_down_ts = ts
            if max_gap_start is not None:
                max_gap_s = max(max_gap_s, ts - max_gap_start)
        else:
            if max_gap_start is not None and status == "OK":
                # consecutive downtime ended
                max_gap_start = None
            if status == "OK":
                total_ok += 1
            else:
                total_busy += 1

        # Wait for next tick
        next_tick = time.monotonic() + interval - 0  # sleep full interval
        remaining = next_tick - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)

    print("---")
    print(f"totals: OK={total_ok} BUSY={total_busy} DOWN={total_down}")
    if first_down_ts is not None and last_down_ts is not None:
        gross = last_down_ts - first_down_ts + interval
        print(f"first_DOWN={time.strftime('%H:%M:%S', time.localtime(first_down_ts))}")
        print(f"last_DOWN={time.strftime('%H:%M:%S', time.localtime(last_down_ts))}")
        print(f"gross_outage_s={gross:.1f} (first_DOWN→last_DOWN + one interval)")
        print(f"longest_consecutive_DOWN_s={max_gap_s:.1f}")
    else:
        print("no DOWN entries — service stayed connected throughout")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.3.191")
    parser.add_argument("--port", type=int, default=502)
    parser.add_argument("--device-id", type=int, default=126)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.host, args.port, args.device_id, args.duration, args.interval))
    except KeyboardInterrupt:
        pass
