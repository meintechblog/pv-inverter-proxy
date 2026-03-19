"""Tests for the aiohttp webapp API endpoints."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer

from pymodbus.datastore import ModbusSequentialDataBlock

from venus_os_fronius_proxy.config import Config, InverterConfig, VenusConfig, WebappConfig
from venus_os_fronius_proxy.connection import ConnectionManager, ConnectionState
from venus_os_fronius_proxy.control import ControlState, OverrideLog
from venus_os_fronius_proxy.plugin import WriteResult
from venus_os_fronius_proxy.register_cache import RegisterCache
from venus_os_fronius_proxy.sunspec_models import build_initial_registers, DATABLOCK_START


@pytest.fixture
def shared_ctx():
    """Build a mock shared_ctx with realistic components."""
    initial_values = build_initial_registers()
    datablock = ModbusSequentialDataBlock(DATABLOCK_START, initial_values)
    cache = RegisterCache(datablock, staleness_timeout=30.0)
    # Mark cache as updated so it's not stale
    cache.last_successful_poll = time.monotonic()
    cache._has_been_updated = True

    conn_mgr = ConnectionManager(poll_interval=1.0)
    control_state = ControlState()

    # Sample SE30K poll data for side-by-side register viewer
    # Common: 67 registers - DID=1, Length=65, then "SolarEdge" manufacturer string etc
    common_regs = [0] * 67
    common_regs[0] = 1  # DID
    common_regs[1] = 65  # Length
    # "SolarEdge" in registers 2-17
    se_bytes = b"SolarEdge\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    for i in range(16):
        common_regs[2 + i] = int.from_bytes(se_bytes[i*2:i*2+2], "big")

    # Inverter: 52 registers
    inverter_regs = [0] * 52
    inverter_regs[0] = 103  # DID
    inverter_regs[1] = 50   # Length
    inverter_regs[2] = 1234  # AC Current sample

    ctx = {
        "cache": cache,
        "conn_mgr": conn_mgr,
        "control_state": control_state,
        "override_log": OverrideLog(),
        "poll_counter": {"success": 50, "total": 55},
        "last_se_poll": {
            "common_registers": common_regs,
            "inverter_registers": inverter_regs,
        },
    }
    return ctx


@pytest.fixture
def mock_config(tmp_path):
    """Create a Config with defaults and a temp config path."""
    config = Config()
    config_path = str(tmp_path / "config.yaml")
    return config, config_path


@pytest.fixture
def mock_plugin():
    """Create a mock InverterPlugin."""
    plugin = AsyncMock()
    plugin.host = "192.168.3.18"
    plugin.port = 1502
    plugin.unit_id = 1
    return plugin


@pytest.fixture
async def client(shared_ctx, mock_config, mock_plugin):
    """Create an aiohttp test client for the webapp."""
    from venus_os_fronius_proxy.webapp import create_webapp

    config, config_path = mock_config
    runner = await create_webapp(shared_ctx, config, config_path, mock_plugin)
    # Get the app from the runner
    app = runner.app
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


async def test_index_returns_html(client):
    """GET / returns 200 with content-type text/html."""
    resp = await client.get("/")
    assert resp.status == 200
    assert "text/html" in resp.content_type


async def test_status_endpoint(client):
    """GET /api/status returns JSON with solaredge connection state."""
    resp = await client.get("/api/status")
    assert resp.status == 200
    data = await resp.json()
    assert "solaredge" in data
    assert data["solaredge"] == "connected"


async def test_health_endpoint(client):
    """GET /api/health returns JSON with uptime, poll rate, cache staleness."""
    resp = await client.get("/api/health")
    assert resp.status == 200
    data = await resp.json()
    assert "uptime_seconds" in data
    assert "poll_success_rate" in data
    assert "cache_stale" in data
    assert "poll_total" in data
    assert "poll_success" in data


async def test_config_get(client):
    """GET /api/config returns nested inverter and venus sections."""
    resp = await client.get("/api/config")
    assert resp.status == 200
    data = await resp.json()
    assert "inverter" in data
    assert "venus" in data
    assert data["inverter"]["host"] == "192.168.3.18"
    assert data["inverter"]["port"] == 1502
    assert data["inverter"]["unit_id"] == 1


async def test_config_save_valid(client):
    """POST /api/config with valid nested JSON saves config and returns success."""
    resp = await client.post("/api/config", json={
        "inverter": {"host": "192.168.1.100", "port": 1502, "unit_id": 1},
        "venus": {"host": "", "port": 1883, "portal_id": ""},
    })
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True


async def test_config_save_invalid_ip(client):
    """POST /api/config with invalid inverter IP returns 400."""
    resp = await client.post("/api/config", json={
        "inverter": {"host": "not-valid", "port": 1502, "unit_id": 1},
        "venus": {"host": "", "port": 1883, "portal_id": ""},
    })
    assert resp.status == 400
    data = await resp.json()
    assert data["success"] is False
    assert "error" in data


async def test_registers_side_by_side(client):
    """GET /api/registers returns side-by-side SE source + Fronius target data."""
    resp = await client.get("/api/registers")
    assert resp.status == 200
    data = await resp.json()
    assert isinstance(data, list)
    assert len(data) > 0

    # First model should be Common
    common = data[0]
    assert "name" in common
    assert "fields" in common
    assert len(common["fields"]) > 0

    # Each field should have side-by-side keys
    field = common["fields"][0]
    assert "addr" in field
    assert "name" in field
    assert "se_value" in field
    assert "fronius_value" in field


async def test_registers_synthesized_model_null_se(client):
    """Nameplate model fields have se_value=null (synthesized, no SE source)."""
    resp = await client.get("/api/registers")
    data = await resp.json()

    # Find Nameplate model
    nameplate = None
    for model in data:
        if "Nameplate" in model["name"]:
            nameplate = model
            break

    assert nameplate is not None
    for field in nameplate["fields"]:
        assert field["se_value"] is None


async def test_registers_no_se_poll(client, shared_ctx):
    """When last_se_poll is None, all se_value fields are null."""
    shared_ctx["last_se_poll"] = None

    resp = await client.get("/api/registers")
    data = await resp.json()

    for model in data:
        for field in model["fields"]:
            assert field["se_value"] is None


# ---------- POST /api/power-limit ----------


async def test_power_limit_set_valid(client, shared_ctx, mock_plugin):
    """POST /api/power-limit with action=set, valid limit_pct returns 200."""
    mock_plugin.write_power_limit = AsyncMock(
        return_value=WriteResult(success=True)
    )
    resp = await client.post("/api/power-limit", json={
        "action": "set",
        "limit_pct": 50.0,
    })
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["error"] is None
    mock_plugin.write_power_limit.assert_called_once_with(True, 50.0)

    # ControlState should be updated
    cs = shared_ctx["control_state"]
    assert cs.last_source == "webapp"
    assert cs.wmaxlimpct_raw == 5000
    assert cs.wmaxlim_ena == 1


async def test_power_limit_set_invalid(client, mock_plugin):
    """POST /api/power-limit with limit_pct=150 returns 400."""
    resp = await client.post("/api/power-limit", json={
        "action": "set",
        "limit_pct": 150.0,
    })
    assert resp.status == 400
    data = await resp.json()
    assert data["success"] is False
    mock_plugin.write_power_limit.assert_not_called()


async def test_power_limit_venus_override_rejection(client, shared_ctx, mock_plugin):
    """POST /api/power-limit returns 409 when Venus OS wrote recently."""
    cs = shared_ctx["control_state"]
    cs.last_source = "venus_os"
    cs.last_change_ts = time.time()  # just now

    resp = await client.post("/api/power-limit", json={
        "action": "set",
        "limit_pct": 50.0,
    })
    assert resp.status == 409
    data = await resp.json()
    assert data["success"] is False
    assert "Venus OS" in data["error"]
    mock_plugin.write_power_limit.assert_not_called()


async def test_power_limit_enable_disable(client, shared_ctx, mock_plugin):
    """POST /api/power-limit with action=enable and disable work."""
    mock_plugin.write_power_limit = AsyncMock(
        return_value=WriteResult(success=True)
    )
    # First set a limit to have a value
    shared_ctx["control_state"].update_wmaxlimpct(5000)

    # Enable
    resp = await client.post("/api/power-limit", json={"action": "enable"})
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True

    # Disable
    resp = await client.post("/api/power-limit", json={"action": "disable"})
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert shared_ctx["control_state"].last_source == "none"


async def test_power_limit_feedback(client, shared_ctx, mock_plugin):
    """POST response includes success/error from WriteResult (CTRL-07)."""
    mock_plugin.write_power_limit = AsyncMock(
        return_value=WriteResult(success=False, error="Inverter timeout")
    )
    resp = await client.post("/api/power-limit", json={
        "action": "set",
        "limit_pct": 50.0,
    })
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is False
    assert data["error"] == "Inverter timeout"


# ---------- POST /api/venus-lock (Phase 11) ----------


async def test_venus_lock_endpoint_lock(client, shared_ctx):
    """POST /api/venus-lock with action=lock locks for 15 min."""
    resp = await client.post("/api/venus-lock", json={"action": "lock"})
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert shared_ctx["control_state"].is_locked is True


async def test_venus_lock_endpoint_unlock(client, shared_ctx):
    """POST /api/venus-lock with action=unlock unlocks."""
    shared_ctx["control_state"].lock(900.0)
    resp = await client.post("/api/venus-lock", json={"action": "unlock"})
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert shared_ctx["control_state"].is_locked is False


async def test_venus_lock_endpoint_invalid_action(client):
    """POST /api/venus-lock with invalid action returns 400."""
    resp = await client.post("/api/venus-lock", json={"action": "foo"})
    assert resp.status == 400


async def test_venus_lock_endpoint_invalid_json(client):
    """POST /api/venus-lock with invalid JSON returns 400."""
    resp = await client.post(
        "/api/venus-lock",
        data=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 400


# ---------- Venus config de-hardcode tests (Phase 13) ----------


async def test_venus_write_no_config(client):
    """POST /api/venus-write returns 503 when venus.host is empty."""
    # Default Config() has venus.host = ""
    resp = await client.post("/api/venus-write", json={
        "register": 2706,
        "value": 100,
    })
    assert resp.status == 503
    data = await resp.json()
    assert data["success"] is False
    assert "not configured" in data["error"].lower()


async def test_venus_dbus_no_config(client):
    """POST /api/venus-dbus returns 503 when venus host/portal_id empty."""
    resp = await client.post("/api/venus-dbus", json={
        "path": "/Settings/CGwacs/MaxFeedInPower",
        "value": 5000,
    })
    assert resp.status == 503
    data = await resp.json()
    assert data["success"] is False
    assert "not configured" in data["error"].lower()


# ---------- Venus config API tests (Phase 14) ----------


async def test_config_get_returns_venus(client):
    """GET /api/config returns venus section with default values."""
    resp = await client.get("/api/config")
    assert resp.status == 200
    data = await resp.json()
    assert "venus" in data
    venus = data["venus"]
    assert venus["host"] == ""
    assert venus["port"] == 1883
    assert venus["portal_id"] == ""


async def test_config_get_venus_defaults(client):
    """With default Config(), venus section has host='', port=1883, portal_id=''."""
    resp = await client.get("/api/config")
    data = await resp.json()
    assert data["venus"] == {"host": "", "port": 1883, "portal_id": ""}


async def test_config_save_venus(client):
    """POST /api/config with venus fields saves them correctly."""
    resp = await client.post("/api/config", json={
        "inverter": {"host": "192.168.3.18", "port": 1502, "unit_id": 1},
        "venus": {"host": "10.0.0.5", "port": 1883, "portal_id": ""},
    })
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert client.app["config"].venus.host == "10.0.0.5"


async def test_config_save_venus_hot_reload(client, shared_ctx):
    """POST /api/config with changed venus host cancels old task and starts new one."""
    # Create a mock old venus task
    old_task = MagicMock()
    old_task.done.return_value = False
    shared_ctx["venus_task"] = old_task

    with patch("venus_os_fronius_proxy.webapp.venus_mqtt_loop", new_callable=MagicMock) as mock_loop:
        # Make venus_mqtt_loop return a coroutine
        mock_coro = AsyncMock()
        mock_loop.return_value = mock_coro()

        resp = await client.post("/api/config", json={
            "inverter": {"host": "192.168.3.18", "port": 1502, "unit_id": 1},
            "venus": {"host": "10.0.0.5", "port": 1883, "portal_id": ""},
        })
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is True

        # Old task should have been cancelled
        old_task.cancel.assert_called_once()

        # New task should be created
        assert "venus_task" in shared_ctx


async def test_config_save_venus_empty_host_clears(client, shared_ctx):
    """POST /api/config with venus.host='' clears MQTT state."""
    # Set up existing venus state (simulate previously configured venus)
    old_task = MagicMock()
    old_task.done.return_value = False
    shared_ctx["venus_task"] = old_task
    shared_ctx["venus_mqtt_connected"] = True
    # Set current config to have a non-empty host so the change is detected
    client.app["config"].venus.host = "10.0.0.5"

    resp = await client.post("/api/config", json={
        "inverter": {"host": "192.168.3.18", "port": 1502, "unit_id": 1},
        "venus": {"host": "", "port": 1883, "portal_id": ""},
    })
    assert resp.status == 200
    assert shared_ctx["venus_mqtt_connected"] is False
    assert "venus_task" not in shared_ctx


async def test_status_venus_mqtt_state(client, shared_ctx):
    """GET /api/status returns real venus_mqtt_connected state."""
    # Connected
    shared_ctx["venus_mqtt_connected"] = True
    resp = await client.get("/api/status")
    data = await resp.json()
    assert data["venus_os"] == "connected"

    # Disconnected
    shared_ctx["venus_mqtt_connected"] = False
    resp = await client.get("/api/status")
    data = await resp.json()
    assert data["venus_os"] == "disconnected"

    # Not configured (key missing)
    del shared_ctx["venus_mqtt_connected"]
    resp = await client.get("/api/status")
    data = await resp.json()
    assert data["venus_os"] == "not configured"


# ---------- Venus OS Auto-Detection (Phase 15) ----------


class TestVenusAutoDetect:
    async def test_status_includes_detected_flag(self, client, shared_ctx):
        """GET /api/status includes venus_os_detected based on shared_ctx."""
        shared_ctx["venus_os_detected"] = True
        resp = await client.get("/api/status")
        data = await resp.json()
        assert data["venus_os_detected"] is True

        del shared_ctx["venus_os_detected"]
        resp = await client.get("/api/status")
        data = await resp.json()
        assert data["venus_os_detected"] is False

    async def test_detection_does_not_modify_config(self, client, shared_ctx):
        """Setting venus_os_detected does NOT modify config keys in shared_ctx."""
        # Take a snapshot of config-related keys before
        config_keys_before = {k: v for k, v in shared_ctx.items() if "config" in k.lower()}

        shared_ctx["venus_os_detected"] = True
        resp = await client.get("/api/status")
        await resp.json()

        # Config keys should be unchanged
        config_keys_after = {k: v for k, v in shared_ctx.items() if "config" in k.lower()}
        assert config_keys_before == config_keys_after


def test_no_hardcoded_ips_webapp():
    """webapp.py contains no hardcoded Venus OS IPs or portal IDs."""
    import inspect
    import venus_os_fronius_proxy.webapp as wa

    source = inspect.getsource(wa)
    assert "192.168.3.146" not in source, "Hardcoded VENUS_HOST IP in webapp.py"
    assert "88a29ec1e5f4" not in source, "Hardcoded PORTAL_ID in webapp.py"
