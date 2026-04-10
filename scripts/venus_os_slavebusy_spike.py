"""Venus OS SlaveBusy empirical spike — Plan 45-05 Task 0.

Standalone pymodbus TCP server that returns Modbus exception 0x06
(Slave Device Busy, ``ExcCodes.DEVICE_BUSY``) for every write to the
Model 123 register range during a configurable window. Used to measure
how Venus OS reacts when the proxy signals "busy, come back later"
during a restart — the strategy decision in Plan 45-05 Task 2 depends
on the observed behavior.

USAGE ON LXC (root):

    systemctl stop pv-inverter-proxy.service
    cd /opt/pv-inverter-proxy
    .venv/bin/python scripts/venus_os_slavebusy_spike.py --port 502 \
        --slavebusy-duration 15
    # watch terminal + Venus OS UI for ~60s
    Ctrl-C
    systemctl start pv-inverter-proxy.service

LOCAL DEV (non-disruptive):

    # Loopback sanity check: starts on 5503 so nothing else breaks.
    .venv/bin/python scripts/venus_os_slavebusy_spike.py --port 5503 \
        --slavebusy-duration 5
    # In another shell, probe with any pymodbus client.

WHAT TO OBSERVE ON VENUS OS DURING THE WINDOW:

    1. Does the Fronius device stay visible or disconnect?
    2. Are there errors on the Venus OS UI / console?
    3. After the window ends, does Venus OS resume writes automatically?
    4. Do reads (PV power display) continue during the window?

Record findings in ``.planning/phases/45-privileged-updater-service/\
45-05-SUMMARY.md`` under "Venus OS SlaveBusy Spike Result".
"""
from __future__ import annotations

import argparse
import asyncio
import time

from pymodbus.datastore import (
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.datastore.context import ExcCodes
from pymodbus.server import ModbusTcpServer

# Model 123 Immediate Controls register layout (matches src/pv_inverter_proxy/sunspec_models).
MODEL_123_START = 40149
MODEL_123_END = 40174


class SlaveBusySpikeContext(ModbusDeviceContext):
    """Return DEVICE_BUSY for Model 123 writes while the window is open."""

    def __init__(self, slavebusy_until: float, **kwargs) -> None:
        super().__init__(**kwargs)
        self.slavebusy_until = slavebusy_until
        self.write_count = 0
        self.busy_count = 0
        self.ok_count = 0

    async def async_setValues(self, func_code, address, values):
        self.write_count += 1
        now = time.monotonic()
        in_window = now < self.slavebusy_until
        in_model_123 = (
            address <= MODEL_123_END
            and (address + len(values) - 1) >= MODEL_123_START
        )
        if in_window and in_model_123:
            self.busy_count += 1
            print(
                f"[{time.strftime('%H:%M:%S')}] write #{self.write_count} "
                f"fc={func_code} addr={address} values={values[:3]!r} "
                f"-> DEVICE_BUSY (0x06)",
                flush=True,
            )
            return ExcCodes.DEVICE_BUSY
        self.ok_count += 1
        print(
            f"[{time.strftime('%H:%M:%S')}] write #{self.write_count} "
            f"fc={func_code} addr={address} values={values[:3]!r} "
            f"-> OK",
            flush=True,
        )
        return self.setValues(func_code, address, values)

    def getValues(self, func_code, address, count=1):
        # Reads are always allowed — mirror production behavior: the cache
        # is gated by staleness, not maintenance mode. The spike hard-codes
        # the cache as fresh (the datablock was pre-populated in main()).
        return super().getValues(func_code, address, count)


async def main(port: int, duration_s: int) -> None:
    # Pre-populate a 2000-register block of zeros starting at address 1.
    # Holding registers only — Venus OS pvinverter plugin uses fc=3 reads
    # and fc=6/16 writes.
    datablock = ModbusSequentialDataBlock(1, [0] * 2000)
    slavebusy_until = time.monotonic() + duration_s
    print(
        f"[{time.strftime('%H:%M:%S')}] SlaveBusy window: {duration_s}s starting now",
        flush=True,
    )
    ctx = SlaveBusySpikeContext(slavebusy_until, hr=datablock)
    server_ctx = ModbusServerContext(devices={126: ctx}, single=False)
    server = ModbusTcpServer(context=server_ctx, address=("0.0.0.0", port))
    print(
        f"[{time.strftime('%H:%M:%S')}] Spike server listening on 0.0.0.0:{port} "
        f"(unit ID 126)",
        flush=True,
    )
    print("Press Ctrl-C to stop", flush=True)

    # Periodic heartbeat so the operator can see we're alive even when
    # Venus OS is silent.
    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(5.0)
            remaining = max(0.0, ctx.slavebusy_until - time.monotonic())
            print(
                f"[{time.strftime('%H:%M:%S')}] heartbeat: "
                f"writes_total={ctx.write_count} busy_returned={ctx.busy_count} "
                f"ok_returned={ctx.ok_count} window_remaining={remaining:.1f}s",
                flush=True,
            )

    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        print(
            f"\n[{time.strftime('%H:%M:%S')}] spike stopped — "
            f"total_writes={ctx.write_count} busy_returned={ctx.busy_count} "
            f"ok_returned={ctx.ok_count}",
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Venus OS SlaveBusy spike")
    parser.add_argument(
        "--port", type=int, default=5503,
        help="Port to listen on (use 502 to masquerade as real proxy on LXC)",
    )
    parser.add_argument(
        "--slavebusy-duration", type=int, default=15,
        help="Seconds to return SlaveBusy before falling back to normal writes",
    )
    args = parser.parse_args()
    try:
        asyncio.run(main(args.port, args.slavebusy_duration))
    except KeyboardInterrupt:
        pass
