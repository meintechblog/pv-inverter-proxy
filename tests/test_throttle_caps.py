"""Tests for ThrottleCaps dataclass and compute_throttle_score function."""
import pytest

from pv_inverter_proxy.plugin import ThrottleCaps, compute_throttle_score


class TestThrottleCapsDataclass:
    """Verify ThrottleCaps is a frozen dataclass."""

    def test_frozen_dataclass(self):
        caps = ThrottleCaps(mode="none", response_time_s=0.0, cooldown_s=0.0, startup_delay_s=0.0)
        with pytest.raises(AttributeError):
            caps.mode = "binary"  # type: ignore[misc]


class TestComputeThrottleScore:
    """Verify compute_throttle_score scoring logic."""

    def test_none_scores_zero(self):
        caps = ThrottleCaps(mode="none", response_time_s=0.0, cooldown_s=0.0, startup_delay_s=0.0)
        assert compute_throttle_score(caps) == 0.0

    def test_score_bounded_0_to_10(self):
        # Extreme proportional: 0s response, 0s cooldown, 0s startup -> should not exceed 10
        caps = ThrottleCaps(mode="proportional", response_time_s=0.0, cooldown_s=0.0, startup_delay_s=0.0)
        score = compute_throttle_score(caps)
        assert 0.0 <= score <= 10.0

    def test_proportional_scores_higher_than_binary(self):
        proportional = ThrottleCaps(mode="proportional", response_time_s=1.0, cooldown_s=0.0, startup_delay_s=0.0)
        binary = ThrottleCaps(mode="binary", response_time_s=1.0, cooldown_s=0.0, startup_delay_s=0.0)
        assert compute_throttle_score(proportional) > compute_throttle_score(binary)

    def test_solaredge_caps(self):
        caps = ThrottleCaps(mode="proportional", response_time_s=1.0, cooldown_s=0.0, startup_delay_s=0.0)
        score = compute_throttle_score(caps)
        assert score > 9.0

    def test_opendtu_caps(self):
        caps = ThrottleCaps(mode="proportional", response_time_s=10.0, cooldown_s=0.0, startup_delay_s=0.0)
        score = compute_throttle_score(caps)
        assert score == 7.0

    def test_shelly_caps(self):
        caps = ThrottleCaps(mode="binary", response_time_s=0.5, cooldown_s=300.0, startup_delay_s=30.0)
        score = compute_throttle_score(caps)
        assert 2.0 < score < 4.0
