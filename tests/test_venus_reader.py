"""Tests for venus_reader MQTT connection, CONNACK validation, and parameterization."""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest


def test_mqtt_connect_connack_accepted():
    """_mqtt_connect returns socket when CONNACK byte[3] == 0."""
    from venus_os_fronius_proxy.venus_reader import _mqtt_connect

    mock_sock = MagicMock()
    mock_sock.recv.return_value = b"\x20\x02\x00\x00"

    with patch("venus_os_fronius_proxy.venus_reader.socket.socket", return_value=mock_sock):
        result = _mqtt_connect("192.168.3.146", 1883)

    assert result is mock_sock


def test_mqtt_connect_connack_rejected():
    """_mqtt_connect raises ConnectionError when CONNACK byte[3] != 0."""
    from venus_os_fronius_proxy.venus_reader import _mqtt_connect

    mock_sock = MagicMock()
    mock_sock.recv.return_value = b"\x20\x02\x00\x01"

    with patch("venus_os_fronius_proxy.venus_reader.socket.socket", return_value=mock_sock):
        with pytest.raises(ConnectionError, match="rc=1"):
            _mqtt_connect("192.168.3.146", 1883)

    mock_sock.close.assert_called_once()


def test_mqtt_connect_connack_short():
    """_mqtt_connect raises ConnectionError when CONNACK is less than 4 bytes."""
    from venus_os_fronius_proxy.venus_reader import _mqtt_connect

    mock_sock = MagicMock()
    mock_sock.recv.return_value = b"\x20\x02"

    with patch("venus_os_fronius_proxy.venus_reader.socket.socket", return_value=mock_sock):
        with pytest.raises(ConnectionError, match="short"):
            _mqtt_connect("192.168.3.146", 1883)

    mock_sock.close.assert_called_once()


def test_mqtt_connect_uses_port():
    """_mqtt_connect connects to specified host:port."""
    from venus_os_fronius_proxy.venus_reader import _mqtt_connect

    mock_sock = MagicMock()
    mock_sock.recv.return_value = b"\x20\x02\x00\x00"

    with patch("venus_os_fronius_proxy.venus_reader.socket.socket", return_value=mock_sock):
        _mqtt_connect("10.0.0.1", 1884)

    mock_sock.connect.assert_called_once_with(("10.0.0.1", 1884))


@pytest.mark.asyncio
async def test_venus_mqtt_loop_empty_host():
    """venus_mqtt_loop returns immediately if host is empty."""
    from venus_os_fronius_proxy.venus_reader import venus_mqtt_loop

    ctx: dict = {}
    await venus_mqtt_loop(ctx, "", 1883, "")

    assert ctx["venus_mqtt_connected"] is False


def test_no_hardcoded_ips():
    """venus_reader.py contains no hardcoded IPs or portal IDs."""
    import venus_os_fronius_proxy.venus_reader as vr

    source = inspect.getsource(vr)
    assert "192.168.3.146" not in source, "Hardcoded VENUS_HOST IP found"
    assert "88a29ec1e5f4" not in source, "Hardcoded PORTAL_ID found"


@pytest.mark.asyncio
async def test_discover_portal_id_success():
    """discover_portal_id returns portal ID extracted from MQTT topic."""
    import struct
    from venus_os_fronius_proxy.venus_reader import discover_portal_id

    # Build a fake PUBLISH packet: topic = "N/abc123/system/0/Serial", payload = {"value": "abc123"}
    topic = b"N/abc123/system/0/Serial"
    payload = b'{"value": "abc123"}'
    topic_len = struct.pack("!H", len(topic))
    rem_len = 2 + len(topic) + len(payload)
    publish_packet = bytes([0x30, rem_len]) + topic_len + topic + payload

    mock_sock = MagicMock()
    # recv sequence: first call returns PUBLISH packet
    mock_sock.recv.return_value = publish_packet

    with patch("venus_os_fronius_proxy.venus_reader._mqtt_connect", return_value=mock_sock):
        result = await discover_portal_id("10.0.0.1", 1883, timeout=2.0)

    assert result == "abc123"
    mock_sock.close.assert_called()


@pytest.mark.asyncio
async def test_discover_portal_id_timeout():
    """discover_portal_id returns None when socket times out."""
    import socket as socket_mod
    from venus_os_fronius_proxy.venus_reader import discover_portal_id

    mock_sock = MagicMock()
    mock_sock.recv.side_effect = socket_mod.timeout("timed out")

    with patch("venus_os_fronius_proxy.venus_reader._mqtt_connect", return_value=mock_sock):
        result = await discover_portal_id("10.0.0.1", 1883, timeout=1.0)

    assert result is None


@pytest.mark.asyncio
async def test_discover_portal_id_connection_error():
    """discover_portal_id returns None when connection fails."""
    from venus_os_fronius_proxy.venus_reader import discover_portal_id

    with patch("venus_os_fronius_proxy.venus_reader._mqtt_connect", side_effect=ConnectionError("refused")):
        result = await discover_portal_id("10.0.0.1", 1883, timeout=1.0)

    assert result is None
