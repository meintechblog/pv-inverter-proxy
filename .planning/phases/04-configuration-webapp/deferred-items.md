# Deferred Items - Phase 04

## pymodbus 3.12.1 API rename

- **Found during:** 04-01 Task 2 verification
- **Issue:** pymodbus 3.12.1 renamed `ModbusSlaveContext` to `ModbusDeviceContext`, breaking imports in `proxy.py` and existing tests (`test_connection.py`, `test_integration.py`, `test_proxy.py`)
- **Impact:** Pre-existing tests cannot run with current lock file pymodbus version
- **Recommended fix:** Update proxy.py imports to use `ModbusDeviceContext` or pin pymodbus to `>=3.6,<3.12`
