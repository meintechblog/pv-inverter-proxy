"""Plan 45-05 RESTART-06: verify pymodbus binds with SO_REUSEADDR.

pymodbus 3.8+ passes ``reuse_address=True`` to
``asyncio.loop.create_server()`` from inside ``ModbusProtocol``. This
test parses the installed pymodbus source to assert that
``reuse_address=True`` is still present, so a silent downgrade that
removes the flag breaks the test rather than breaking the live restart
path.
"""
from __future__ import annotations

import inspect

import pymodbus
from pymodbus.transport import ModbusProtocol


def test_pymodbus_protocol_sets_reuse_address():
    """ModbusProtocol must pass reuse_address=True to create_server."""
    source = inspect.getsource(ModbusProtocol)
    assert "reuse_address=True" in source, (
        f"pymodbus {pymodbus.__version__} ModbusProtocol no longer sets "
        "reuse_address=True — RESTART-06 guarantee broken. "
        "Plan 45-05 Task 3 requires SO_REUSEADDR so fast restarts of the "
        "main service do not fail with EADDRINUSE. Either pin an older "
        "pymodbus version or add an explicit SO_REUSEADDR patch in "
        "proxy.run_modbus_server."
    )


def test_pymodbus_version_is_3_8_or_later():
    """Sanity: Plan 45-05 only verified SO_REUSEADDR on pymodbus 3.8+."""
    parts = pymodbus.__version__.split(".")
    major = int(parts[0])
    minor = int(parts[1])
    assert (major, minor) >= (3, 8), (
        f"pymodbus {pymodbus.__version__} is older than 3.8; Plan 45-05 "
        "did not verify SO_REUSEADDR on this version."
    )


def test_proxy_documents_reuseaddr_decision():
    """proxy.py must carry the RESTART-06 verification comment."""
    from pathlib import Path

    src_path = Path(__file__).parent.parent / "src" / "pv_inverter_proxy" / "proxy.py"
    body = src_path.read_text()
    assert "RESTART-06" in body
    assert "reuse_address=True" in body or "SO_REUSEADDR" in body
