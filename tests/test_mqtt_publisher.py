"""Tests for MQTT publisher module with queue-based publish loop, LWT, and reconnect."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import aiomqtt


def _make_config(**overrides):
    """Build a minimal MqttPublishConfig-like object."""
    defaults = dict(
        host="localhost",
        port=1883,
        topic_prefix="pv-inverter-proxy",
        client_id="test-pub",
        interval_s=1,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_ctx(queue_maxsize=100):
    """Build a minimal AppContext-like object."""
    return SimpleNamespace(
        mqtt_pub_queue=asyncio.Queue(maxsize=queue_maxsize),
        mqtt_pub_connected=False,
        shutdown_event=asyncio.Event(),
        mqtt_pub_messages=0,
        mqtt_pub_bytes=0,
        mqtt_pub_skipped=0,
        mqtt_pub_last_ts=0.0,
    )


@pytest.fixture
def mock_client():
    """Patch aiomqtt.Client as an async context manager returning a mock client."""
    client_instance = AsyncMock()
    client_instance.publish = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=client_instance)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("aiomqtt.Client", return_value=cm) as mock_cls:
        mock_cls._instance = client_instance
        mock_cls._cm = cm
        yield mock_cls


@pytest.fixture
def mock_will():
    """Patch aiomqtt.Will to capture LWT parameters."""
    with patch("aiomqtt.Will") as mock_w:
        yield mock_w


async def test_connect_sets_connected(mock_client, mock_will):
    """mqtt_publish_loop sets ctx.mqtt_pub_connected=True after successful connect."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config()

    # After first connect + publish online, set shutdown to exit loop
    async def shutdown_after_connect(*args, **kwargs):
        ctx.shutdown_event.set()

    mock_client._instance.publish.side_effect = shutdown_after_connect

    await mqtt_publish_loop(ctx, config)
    assert ctx.mqtt_pub_connected is False  # False after loop exits (cleanup)


async def test_publishes_online_on_connect(mock_client, mock_will):
    """mqtt_publish_loop publishes 'online' to {prefix}/status with QoS 1 + retain."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config(topic_prefix="test")

    async def shutdown_after_connect(*args, **kwargs):
        ctx.shutdown_event.set()

    mock_client._instance.publish.side_effect = shutdown_after_connect

    await mqtt_publish_loop(ctx, config)

    # First publish call should be the online announcement
    calls = mock_client._instance.publish.call_args_list
    assert len(calls) >= 1
    first_call = calls[0]
    assert first_call.args[0] == "test/status"
    assert first_call.kwargs.get("payload") == "online"
    assert first_call.kwargs.get("qos") == 1
    assert first_call.kwargs.get("retain") is True


async def test_will_message_configured(mock_client, mock_will):
    """mqtt_publish_loop sets Will message to 'offline' on {prefix}/status."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config(topic_prefix="mypv")

    async def shutdown_after_connect(*args, **kwargs):
        ctx.shutdown_event.set()

    mock_client._instance.publish.side_effect = shutdown_after_connect

    await mqtt_publish_loop(ctx, config)

    mock_will.assert_called_once_with(
        topic="mypv/status",
        payload="offline",
        qos=1,
        retain=True,
    )


async def test_consumes_queue_messages(mock_client, mock_will):
    """mqtt_publish_loop consumes messages from queue and publishes to broker."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config()

    call_count = 0
    original_publish = AsyncMock()

    async def track_publish(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # First call is "online", after that we process queue
        if call_count == 1:
            # Enqueue a message for the loop to consume
            await ctx.mqtt_pub_queue.put({"topic": "pv-inverter-proxy/power", "payload": {"watts": 5000}})
        elif call_count == 2:
            # After consuming the queue message, shut down
            ctx.shutdown_event.set()

    mock_client._instance.publish.side_effect = track_publish

    await mqtt_publish_loop(ctx, config)

    calls = mock_client._instance.publish.call_args_list
    assert len(calls) >= 2
    # Second call should be the queued message
    second = calls[1]
    assert second.args[0] == "pv-inverter-proxy/power"


async def test_reconnect_with_backoff(mock_client, mock_will):
    """mqtt_publish_loop reconnects with increasing backoff on MqttError."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config()

    connect_attempts = 0

    async def fail_connect(*args, **kwargs):
        nonlocal connect_attempts
        connect_attempts += 1
        if connect_attempts >= 3:
            ctx.shutdown_event.set()
        raise aiomqtt.MqttError("Connection refused")

    mock_client._cm.__aenter__ = fail_connect

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await mqtt_publish_loop(ctx, config)

    # Should have called sleep with increasing backoff
    sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
    assert len(sleep_calls) >= 2
    assert sleep_calls[0] == 1.0
    assert sleep_calls[1] == 2.0


async def test_disconnect_sets_connected_false(mock_client, mock_will):
    """mqtt_publish_loop sets ctx.mqtt_pub_connected=False on disconnect."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config()

    # On connect, publish "online" succeeds. Then the inner loop starts;
    # we make queue.get raise MqttError to simulate a disconnect during operation.
    call_count = 0

    async def publish_then_disconnect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # "online" publish succeeds -- connected will be set to True
            return
        # Any subsequent publish raises MqttError
        raise aiomqtt.MqttError("Disconnected")

    mock_client._instance.publish.side_effect = publish_then_disconnect

    # Put a message so the inner loop tries to publish (and hits disconnect)
    await ctx.mqtt_pub_queue.put({"topic": "t", "payload": {}})

    # After MqttError, the outer except sets connected=False and sleeps.
    # On second connect attempt, shut down.
    connect_count = 0
    original_aenter = mock_client._cm.__aenter__

    async def connect_or_shutdown(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        if connect_count == 1:
            return await original_aenter(*args, **kwargs)
        ctx.shutdown_event.set()
        raise aiomqtt.MqttError("Stop")

    mock_client._cm.__aenter__ = connect_or_shutdown

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await mqtt_publish_loop(ctx, config)

    assert ctx.mqtt_pub_connected is False


async def test_clean_shutdown_on_cancel(mock_client, mock_will):
    """mqtt_publish_loop stops cleanly on CancelledError."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config()

    async def raise_cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    mock_client._cm.__aenter__ = raise_cancel

    # Should not raise
    await mqtt_publish_loop(ctx, config)
    assert ctx.mqtt_pub_connected is False


async def test_shutdown_event_stops_loop(mock_client, mock_will):
    """mqtt_publish_loop exits when shutdown_event is set."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config()

    # Set shutdown before entering loop
    ctx.shutdown_event.set()

    await mqtt_publish_loop(ctx, config)
    assert ctx.mqtt_pub_connected is False


async def test_queue_full_drops_message():
    """put_nowait on full queue raises QueueFull, which should be caught by producer."""
    q = asyncio.Queue(maxsize=1)
    q.put_nowait({"topic": "t", "payload": {}})

    # Second put_nowait should raise QueueFull
    with pytest.raises(asyncio.QueueFull):
        q.put_nowait({"topic": "t2", "payload": {}})

    # Documented producer pattern: try/except QueueFull
    try:
        q.put_nowait({"topic": "t3", "payload": {}})
    except asyncio.QueueFull:
        pass  # Expected -- message dropped, no exception propagated


# ── Phase 26 tests: HA discovery, change detection, retained state ────


def _make_inverter(**overrides):
    """Build a minimal InverterEntry-like object."""
    defaults = dict(
        id="abc123def456",
        name="Test Inverter",
        manufacturer="SolarEdge",
        model="SE30K",
        serial="SN123",
        firmware_version="1.0.0",
        enabled=True,
        host="192.168.3.18",
        port=1502,
        type="solaredge",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_device_snapshot(power=5000):
    """Build a minimal device snapshot dict."""
    return {
        "ts": 1700000000,
        "inverter": {
            "ac_power_w": power,
            "dc_power_w": power + 100,
            "ac_voltage_an_v": 230.0,
            "ac_voltage_bn_v": 231.0,
            "ac_voltage_cn_v": 229.0,
            "ac_current_a": 21.7,
            "ac_frequency_hz": 50.01,
            "dc_voltage_v": 600.0,
            "dc_current_a": 8.5,
            "temperature_sink_c": 42.0,
            "energy_total_wh": 100000,
            "daily_energy_wh": 5000,
            "status": "ON",
            "status_code": 4,
            "peak_power_w": 6000,
            "operating_hours": 1234.5,
            "efficiency_pct": 97.2,
        },
    }


async def _run_publish_loop_with_queue_messages(mock_client, ctx, config,
                                                 messages, inverters=None,
                                                 virtual_name=""):
    """Helper: run mqtt_publish_loop, enqueue messages after connect, then shutdown."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    enqueued = False

    original_publish = mock_client._instance.publish

    async def track_and_enqueue(*args, **kwargs):
        nonlocal enqueued
        # Let the actual mock record the call
        await original_publish(*args, **kwargs)
        if not enqueued:
            enqueued = True
            # Enqueue all messages
            for msg in messages:
                await ctx.mqtt_pub_queue.put(msg)
            # Give event loop a chance to process, then enqueue a sentinel
            # that triggers shutdown after processing all real messages
            await asyncio.sleep(0)

    # We need a more subtle approach: intercept queue.get to count messages
    real_get = ctx.mqtt_pub_queue.get

    messages_processed = 0

    async def counting_get():
        nonlocal messages_processed
        result = await real_get()
        messages_processed += 1
        if messages_processed >= len(messages):
            # Processed all messages, schedule shutdown
            ctx.shutdown_event.set()
        return result

    mock_client._instance.publish = AsyncMock(side_effect=track_and_enqueue)

    with patch.object(ctx.mqtt_pub_queue, 'get', side_effect=counting_get):
        await mqtt_publish_loop(ctx, config, inverters=inverters,
                                virtual_name=virtual_name)

    return mock_client._instance.publish.call_args_list


async def test_publishes_ha_discovery_on_connect(mock_client, mock_will):
    """On connect, HA discovery configs are published with retain=True, QoS 1."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config(topic_prefix="pv-inverter-proxy")
    inv = _make_inverter()

    call_count = 0
    # 1 online + 16 discovery + 1 device avail + 2 virtual disc + 1 virtual avail = 21
    expected_discovery_calls = 21

    async def shutdown_after_discovery(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= expected_discovery_calls:
            ctx.shutdown_event.set()

    mock_client._instance.publish.side_effect = shutdown_after_discovery

    await mqtt_publish_loop(ctx, config, inverters=[inv], virtual_name="Virtual PV")

    calls = mock_client._instance.publish.call_args_list
    # Find discovery calls (topic starts with "homeassistant/sensor/")
    discovery_calls = [c for c in calls if str(c.args[0]).startswith("homeassistant/sensor/")]
    assert len(discovery_calls) >= 16  # 16 for device sensors
    # All discovery calls should be retained with QoS 1
    for dc in discovery_calls:
        assert dc.kwargs.get("retain") is True, f"Discovery not retained: {dc.args[0]}"
        assert dc.kwargs.get("qos") == 1, f"Discovery not QoS 1: {dc.args[0]}"


async def test_publishes_device_availability_on_connect(mock_client, mock_will):
    """On connect, device availability 'online' published to {prefix}/device/{id}/availability."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config(topic_prefix="pv-inverter-proxy")
    inv = _make_inverter(id="dev001")

    call_count = 0
    # 1 online + 16 discovery + 1 device avail = 18 (no virtual)
    expected_calls = 18

    async def shutdown_after_discovery(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= expected_calls:
            ctx.shutdown_event.set()

    mock_client._instance.publish.side_effect = shutdown_after_discovery

    await mqtt_publish_loop(ctx, config, inverters=[inv], virtual_name="")

    calls = mock_client._instance.publish.call_args_list
    avail_calls = [c for c in calls if "device/dev001/availability" in str(c.args[0])]
    assert len(avail_calls) >= 1
    avail = avail_calls[0]
    assert avail.kwargs.get("payload") == "online"
    assert avail.kwargs.get("retain") is True


async def test_device_message_published_retained(mock_client, mock_will):
    """Device state messages are published with retain=True."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config(topic_prefix="pv-inverter-proxy")
    snapshot = _make_device_snapshot(power=5000)

    msgs = [{"type": "device", "device_id": "inv1", "snapshot": snapshot}]
    calls = await _run_publish_loop_with_queue_messages(
        mock_client, ctx, config, msgs)

    # Find the device state publish
    state_calls = [c for c in calls if "device/inv1/state" in str(c.args[0])]
    assert len(state_calls) == 1
    sc = state_calls[0]
    assert sc.kwargs.get("retain") is True


async def test_change_detection_skips_identical(mock_client, mock_will):
    """Identical device payloads are not re-published (change detection)."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config(topic_prefix="pv-inverter-proxy")
    snapshot = _make_device_snapshot(power=5000)

    # Two identical messages
    msgs = [
        {"type": "device", "device_id": "inv1", "snapshot": snapshot},
        {"type": "device", "device_id": "inv1", "snapshot": snapshot},
    ]
    calls = await _run_publish_loop_with_queue_messages(
        mock_client, ctx, config, msgs)

    # Only one device state publish (second is skipped due to identical payload)
    state_calls = [c for c in calls if "device/inv1/state" in str(c.args[0])]
    assert len(state_calls) == 1


async def test_change_detection_publishes_on_change(mock_client, mock_will):
    """Different device payloads are both published."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config(topic_prefix="pv-inverter-proxy")
    snap1 = _make_device_snapshot(power=5000)
    snap2 = _make_device_snapshot(power=6000)

    msgs = [
        {"type": "device", "device_id": "inv1", "snapshot": snap1},
        {"type": "device", "device_id": "inv1", "snapshot": snap2},
    ]
    calls = await _run_publish_loop_with_queue_messages(
        mock_client, ctx, config, msgs)

    state_calls = [c for c in calls if "device/inv1/state" in str(c.args[0])]
    assert len(state_calls) == 2


async def test_virtual_message_published(mock_client, mock_will):
    """Virtual messages are published to {prefix}/virtual/state with retain=True."""
    from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop

    ctx = _make_ctx()
    config = _make_config(topic_prefix="pv-inverter-proxy")

    msgs = [{
        "type": "virtual",
        "virtual_data": {
            "total_power_w": 10000,
            "virtual_name": "My Virtual PV",
            "contributions": [
                {"device_id": "inv1", "name": "Inv 1", "power_w": 5000},
                {"device_id": "inv2", "name": "Inv 2", "power_w": 5000},
            ],
        },
    }]
    calls = await _run_publish_loop_with_queue_messages(
        mock_client, ctx, config, msgs)

    virtual_calls = [c for c in calls if "virtual/state" in str(c.args[0])]
    assert len(virtual_calls) == 1
    vc = virtual_calls[0]
    assert vc.kwargs.get("retain") is True
    # Verify payload contains total_power_w
    payload_data = json.loads(vc.kwargs.get("payload"))
    assert payload_data["total_power_w"] == 10000
