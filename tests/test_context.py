"""Tests for AppContext and DeviceState dataclasses."""
from __future__ import annotations


def test_app_context_defaults():
    """AppContext() creates with sensible defaults."""
    from venus_os_fronius_proxy.context import AppContext

    ctx = AppContext()
    assert ctx.cache is None
    assert ctx.control_state is None
    assert ctx.config is None
    assert ctx.config_path == ""
    assert ctx.devices == {}
    assert ctx.venus_mqtt_connected is False
    assert ctx.venus_os_detected is False
    assert ctx.polling_paused is False
    assert ctx.webapp is None
    assert ctx.override_log is None
    assert ctx.device_registry is None


def test_device_state_creation():
    """DeviceState() creates empty state with correct defaults."""
    from venus_os_fronius_proxy.context import DeviceState

    ds = DeviceState()
    assert ds.collector is None
    assert ds.poll_counter == {"success": 0, "total": 0}
    assert ds.conn_mgr is None
    assert ds.last_poll_data is None
    assert ds.plugin is None


def test_app_context_device_registry():
    """device_registry field stores the DeviceRegistry reference."""
    from venus_os_fronius_proxy.context import AppContext

    ctx = AppContext()
    registry_mock = object()
    ctx.device_registry = registry_mock
    assert ctx.device_registry is registry_mock
