"""Loopback probe for the Venus OS SlaveBusy spike.

Connects a pymodbus TCP client to 127.0.0.1:5503 and writes to Model 123
(register 40154, WMaxLimPct). Verifies that the spike returns exception
code 0x06 (DEVICE_BUSY) rather than silently dropping the write.

This is NOT a Venus-OS test — it only asserts the spike server wiring
is correct so that when Venus OS connects to the spike on the LXC it
sees the expected exception on the wire.

USAGE:

    # Terminal 1
    .venv/bin/python scripts/venus_os_slavebusy_spike.py --port 5503 \
        --slavebusy-duration 15
    # Terminal 2
    .venv/bin/python scripts/venus_os_slavebusy_loopback_probe.py
"""
from __future__ import annotations

import asyncio
import sys

from pymodbus.client import AsyncModbusTcpClient


async def main() -> int:
    client = AsyncModbusTcpClient(host="127.0.0.1", port=5503, name="probe")
    ok = await client.connect()
    if not ok:
        print("ERROR: could not connect to 127.0.0.1:5503", flush=True)
        return 2
    try:
        # Write 42 to register 40154 (WMaxLimPct inside Model 123).
        response = await client.write_register(address=40154, value=42, device_id=126)
        if response.isError():
            # pymodbus parses the exception code into the response object.
            exc_code = getattr(response, "exception_code", None)
            print(
                f"write_register -> exception (as expected): "
                f"exception_code={exc_code}",
                flush=True,
            )
            if exc_code == 6:
                print("PASS: spike returned DEVICE_BUSY (0x06)", flush=True)
                return 0
            print(
                f"FAIL: expected exception_code=6, got {exc_code}",
                flush=True,
            )
            return 1
        print(
            f"FAIL: write succeeded — expected DEVICE_BUSY. response={response}",
            flush=True,
        )
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
