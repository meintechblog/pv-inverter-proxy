"""Register cache with staleness tracking.

Wraps a pymodbus ModbusSequentialDataBlock and tracks when data was last
successfully updated. After staleness_timeout seconds without an update,
is_stale returns True, signaling the proxy should return Modbus errors
to Venus OS instead of serving stale data.
"""
from __future__ import annotations

import time

from pymodbus.datastore import ModbusSequentialDataBlock


class RegisterCache:
    """Manages the Modbus datablock with staleness tracking.

    Wraps a ModbusSequentialDataBlock and tracks when data was last
    successfully updated. After staleness_timeout seconds without an
    update, is_stale returns True, signaling the proxy should return
    Modbus errors to Venus OS instead of serving stale data.
    """

    def __init__(self, datablock: ModbusSequentialDataBlock, staleness_timeout: float = 30.0):
        self.datablock = datablock
        self.staleness_timeout = staleness_timeout
        self.last_successful_poll: float = 0.0
        self._has_been_updated = False

    def update(self, address: int, values: list[int]) -> None:
        """Update registers from a successful poll.

        Args:
            address: Starting register address (datablock-relative, i.e., 40001-based)
            values: List of uint16 register values to write
        """
        self.datablock.setValues(address, values)
        self.last_successful_poll = time.monotonic()
        self._has_been_updated = True

    @property
    def is_stale(self) -> bool:
        """True if no successful poll within staleness_timeout.

        Returns True before the first successful update (cache starts stale).
        """
        if not self._has_been_updated:
            return True
        return (time.monotonic() - self.last_successful_poll) > self.staleness_timeout
