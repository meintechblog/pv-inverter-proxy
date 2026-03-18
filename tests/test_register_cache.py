"""Tests for RegisterCache with staleness tracking.

Verifies that RegisterCache wraps a ModbusSequentialDataBlock, tracks
staleness based on time since last successful update, and correctly
writes values to the underlying datablock.
"""
import time

import pytest
from pymodbus.datastore import ModbusSequentialDataBlock

from venus_os_fronius_proxy.register_cache import RegisterCache


def make_cache(timeout: float = 30.0) -> RegisterCache:
    """Create a RegisterCache with a test datablock."""
    datablock = ModbusSequentialDataBlock(40001, [0] * 177)
    return RegisterCache(datablock, staleness_timeout=timeout)


class TestCacheStaleness:
    """Verify staleness tracking behavior."""

    def test_cache_starts_stale(self):
        """New cache with no updates has is_stale == True."""
        cache = make_cache()
        assert cache.is_stale is True

    def test_cache_not_stale_after_update(self):
        """Calling update() makes is_stale False."""
        cache = make_cache()
        cache.update(40001, [1, 2, 3])
        assert cache.is_stale is False

    def test_cache_becomes_stale_after_timeout(self):
        """With short timeout, cache becomes stale after sleeping."""
        cache = make_cache(timeout=0.1)
        cache.update(40001, [1, 2, 3])
        assert cache.is_stale is False
        time.sleep(0.15)
        assert cache.is_stale is True

    def test_cache_staleness_timeout_configurable(self):
        """Constructor accepts custom timeout."""
        cache = make_cache(timeout=60.0)
        assert cache.staleness_timeout == 60.0

    def test_cache_multiple_updates_reset_staleness(self):
        """Multiple updates keep resetting the timer."""
        cache = make_cache(timeout=0.1)
        cache.update(40001, [1])
        time.sleep(0.05)
        cache.update(40001, [2])
        time.sleep(0.05)
        # Should NOT be stale -- second update was only 0.05s ago
        assert cache.is_stale is False


class TestCacheDatablock:
    """Verify data is written to the underlying datablock."""

    def test_cache_update_writes_to_datablock(self):
        """update(addr, values) correctly writes values readable via datablock."""
        cache = make_cache()
        cache.update(40001, [100, 200, 300])
        values = cache.datablock.getValues(40001, 3)
        assert values == [100, 200, 300]

    def test_cache_last_successful_poll_updates(self):
        """last_successful_poll changes after update()."""
        cache = make_cache()
        assert cache.last_successful_poll == 0.0
        cache.update(40001, [1])
        assert cache.last_successful_poll > 0.0

    def test_cache_last_successful_poll_increases(self):
        """Subsequent updates increase last_successful_poll."""
        cache = make_cache()
        cache.update(40001, [1])
        first_time = cache.last_successful_poll
        time.sleep(0.01)
        cache.update(40001, [2])
        assert cache.last_successful_poll > first_time
