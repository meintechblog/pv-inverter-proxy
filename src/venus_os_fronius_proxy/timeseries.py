"""Time series ring buffer for dashboard metrics.

Stores samples in a collections.deque with automatic maxlen eviction.
One buffer per metric, fed by DashboardCollector after each poll cycle.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass(slots=True)
class Sample:
    """A single time series data point."""

    timestamp: float
    value: float


class TimeSeriesBuffer:
    """Fixed-duration ring buffer using deque(maxlen).

    Stores up to max_seconds + 60 samples (extra margin before eviction).
    At 1 sample/second poll rate, 3600s = 60 minutes of history.
    """

    def __init__(self, max_seconds: int = 3600) -> None:
        self._buf: deque[Sample] = deque(maxlen=max_seconds + 60)

    def append(self, value: float, ts: float | None = None) -> None:
        """Add a sample. Uses time.monotonic() if ts is not provided."""
        self._buf.append(Sample(ts if ts is not None else time.monotonic(), value))

    def get_all(self) -> list[Sample]:
        """Return all samples as a list (oldest first)."""
        return list(self._buf)

    def latest(self) -> Sample | None:
        """Return the most recent sample, or None if empty."""
        return self._buf[-1] if self._buf else None

    def __len__(self) -> int:
        return len(self._buf)
