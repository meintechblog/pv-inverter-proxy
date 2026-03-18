"""Tests for TimeSeriesBuffer ring buffer."""
from __future__ import annotations

import time

import pytest

from venus_os_fronius_proxy.timeseries import Sample, TimeSeriesBuffer


def test_sample_dataclass():
    """Sample stores timestamp and value."""
    s = Sample(timestamp=1.0, value=42.0)
    assert s.timestamp == 1.0
    assert s.value == 42.0


def test_append_and_get_all():
    """append(42.0) then get_all() returns [Sample(ts=..., value=42.0)]."""
    buf = TimeSeriesBuffer()
    buf.append(42.0, ts=100.0)
    result = buf.get_all()
    assert len(result) == 1
    assert result[0].value == 42.0
    assert result[0].timestamp == 100.0


def test_eviction_beyond_maxlen():
    """append N+1 items to buffer with maxlen=N evicts oldest."""
    buf = TimeSeriesBuffer(max_seconds=5)
    # maxlen = 5 + 60 = 65
    maxlen = 65
    for i in range(maxlen + 1):
        buf.append(float(i), ts=float(i))
    assert len(buf) == maxlen
    # Oldest (0.0) should be evicted
    all_samples = buf.get_all()
    assert all_samples[0].value == 1.0


def test_latest_returns_most_recent():
    """latest() returns most recent Sample."""
    buf = TimeSeriesBuffer()
    buf.append(10.0, ts=1.0)
    buf.append(20.0, ts=2.0)
    buf.append(30.0, ts=3.0)
    latest = buf.latest()
    assert latest is not None
    assert latest.value == 30.0
    assert latest.timestamp == 3.0


def test_latest_on_empty_returns_none():
    """latest() on empty buffer returns None."""
    buf = TimeSeriesBuffer()
    assert buf.latest() is None


def test_len_returns_count():
    """len() returns number of samples."""
    buf = TimeSeriesBuffer()
    assert len(buf) == 0
    buf.append(1.0, ts=1.0)
    assert len(buf) == 1
    buf.append(2.0, ts=2.0)
    assert len(buf) == 2


def test_append_uses_monotonic_by_default():
    """append without ts uses time.monotonic()."""
    buf = TimeSeriesBuffer()
    before = time.monotonic()
    buf.append(99.0)
    after = time.monotonic()
    s = buf.latest()
    assert s is not None
    assert before <= s.timestamp <= after
