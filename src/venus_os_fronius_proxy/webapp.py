"""aiohttp REST API backend for the configuration webapp.

Serves status, health, config, and register data endpoints.
The register viewer provides side-by-side SE30K source and Fronius target values.
WebSocket endpoint at /ws pushes live inverter snapshots to connected browsers.
"""
from __future__ import annotations

import json
import time
import weakref

from aiohttp import web

from venus_os_fronius_proxy.config import (
    Config,
    save_config,
    validate_inverter_config,
)
from venus_os_fronius_proxy.control import validate_wmaxlimpct


# SunSpec register layout for the register viewer.
# Each model defines fields with addresses, names, and SE source mapping.
REGISTER_MODELS = [
    {
        "name": "Common (Model 1)",
        "start": 40002,
        "source": "se",
        "se_offset_key": "common_registers",
        "se_base_addr": 40002,
        "fields": [
            {"addr": 40002, "name": "DID", "size": 1},
            {"addr": 40003, "name": "Length", "size": 1},
            {"addr": 40004, "name": "Manufacturer", "size": 16, "type": "string"},
            {"addr": 40020, "name": "Model", "size": 16, "type": "string"},
            {"addr": 40036, "name": "Options", "size": 8, "type": "string"},
            {"addr": 40044, "name": "Version", "size": 8, "type": "string"},
            {"addr": 40052, "name": "Serial Number", "size": 16, "type": "string"},
            {"addr": 40068, "name": "Device Address", "size": 1},
        ],
    },
    {
        "name": "Inverter (Model 103)",
        "start": 40069,
        "source": "se",
        "se_offset_key": "inverter_registers",
        "se_base_addr": 40069,
        "fields": [
            {"addr": 40069, "name": "DID", "size": 1},
            {"addr": 40070, "name": "Length", "size": 1},
            {"addr": 40071, "name": "AC Current", "size": 1},
            {"addr": 40072, "name": "AC Current A", "size": 1},
            {"addr": 40073, "name": "AC Current B", "size": 1},
            {"addr": 40074, "name": "AC Current C", "size": 1},
            {"addr": 40075, "name": "AC Current SF", "size": 1},
            {"addr": 40076, "name": "AC Voltage AB", "size": 1},
            {"addr": 40077, "name": "AC Voltage BC", "size": 1},
            {"addr": 40078, "name": "AC Voltage CA", "size": 1},
            {"addr": 40079, "name": "AC Voltage AN", "size": 1},
            {"addr": 40080, "name": "AC Voltage BN", "size": 1},
            {"addr": 40081, "name": "AC Voltage CN", "size": 1},
            {"addr": 40082, "name": "AC Voltage SF", "size": 1},
            {"addr": 40083, "name": "AC Power", "size": 1},
            {"addr": 40084, "name": "AC Power SF", "size": 1},
            {"addr": 40085, "name": "AC Frequency", "size": 1},
            {"addr": 40086, "name": "AC Frequency SF", "size": 1},
            {"addr": 40087, "name": "AC VA", "size": 1},
            {"addr": 40088, "name": "AC VA SF", "size": 1},
            {"addr": 40089, "name": "AC VAR", "size": 1},
            {"addr": 40090, "name": "AC VAR SF", "size": 1},
            {"addr": 40091, "name": "AC PF", "size": 1},
            {"addr": 40092, "name": "AC PF SF", "size": 1},
            {"addr": 40093, "name": "AC Energy", "size": 2},
            {"addr": 40095, "name": "AC Energy SF", "size": 1},
            {"addr": 40096, "name": "DC Current", "size": 1},
            {"addr": 40097, "name": "DC Current SF", "size": 1},
            {"addr": 40098, "name": "DC Voltage", "size": 1},
            {"addr": 40099, "name": "DC Voltage SF", "size": 1},
            {"addr": 40100, "name": "DC Power", "size": 1},
            {"addr": 40101, "name": "DC Power SF", "size": 1},
            {"addr": 40102, "name": "Cab Temp", "size": 1},
            {"addr": 40103, "name": "Sink Temp", "size": 1},
            {"addr": 40104, "name": "Trans Temp", "size": 1},
            {"addr": 40105, "name": "Other Temp", "size": 1},
            {"addr": 40106, "name": "Temp SF", "size": 1},
            {"addr": 40107, "name": "Status", "size": 1},
            {"addr": 40108, "name": "Status Vendor", "size": 1},
            {"addr": 40109, "name": "Reserved", "size": 12},
        ],
    },
    {
        "name": "Nameplate (Model 120)",
        "start": 40121,
        "source": None,
        "se_offset_key": None,
        "se_base_addr": None,
        "fields": [
            {"addr": 40121, "name": "DID", "size": 1},
            {"addr": 40122, "name": "Length", "size": 1},
            {"addr": 40123, "name": "DER Type", "size": 1},
            {"addr": 40124, "name": "W Rating", "size": 1},
            {"addr": 40125, "name": "W Rating SF", "size": 1},
            {"addr": 40126, "name": "VA Rating", "size": 1},
            {"addr": 40127, "name": "VA Rating SF", "size": 1},
            {"addr": 40128, "name": "VArRtgQ1", "size": 1},
            {"addr": 40129, "name": "VArRtgQ2", "size": 1},
            {"addr": 40130, "name": "VArRtgQ3", "size": 1},
            {"addr": 40131, "name": "VArRtgQ4", "size": 1},
            {"addr": 40132, "name": "VArRtg SF", "size": 1},
            {"addr": 40133, "name": "ARtg", "size": 1},
            {"addr": 40134, "name": "ARtg SF", "size": 1},
            {"addr": 40135, "name": "PFRtgQ1", "size": 1},
            {"addr": 40136, "name": "PFRtgQ2", "size": 1},
            {"addr": 40137, "name": "PFRtgQ3", "size": 1},
            {"addr": 40138, "name": "PFRtgQ4", "size": 1},
            {"addr": 40139, "name": "PFRtg SF", "size": 1},
            {"addr": 40140, "name": "WHRtg", "size": 1},
            {"addr": 40141, "name": "WHRtg SF", "size": 1},
            {"addr": 40142, "name": "AhrRtg", "size": 1},
            {"addr": 40143, "name": "AhrRtg SF", "size": 1},
            {"addr": 40144, "name": "MaxChaRte", "size": 1},
            {"addr": 40145, "name": "MaxChaRte SF", "size": 1},
            {"addr": 40146, "name": "MaxDisChaRte", "size": 1},
            {"addr": 40147, "name": "MaxDisChaRte SF", "size": 1},
            {"addr": 40148, "name": "Pad", "size": 1},
        ],
    },
    {
        "name": "Controls (Model 123)",
        "start": 40149,
        "source": None,
        "se_offset_key": None,
        "se_base_addr": None,
        "fields": [
            {"addr": 40149, "name": "DID", "size": 1},
            {"addr": 40150, "name": "Length", "size": 1},
            {"addr": 40151, "name": "Conn_WinTms", "size": 1},
            {"addr": 40152, "name": "Conn_RvrtTms", "size": 1},
            {"addr": 40153, "name": "Conn", "size": 1},
            {"addr": 40154, "name": "WMaxLimPct", "size": 1},
            {"addr": 40155, "name": "WMaxLimPct_WinTms", "size": 1},
            {"addr": 40156, "name": "WMaxLimPct_RvrtTms", "size": 1},
            {"addr": 40157, "name": "WMaxLimPct_RmpTms", "size": 1},
            {"addr": 40158, "name": "WMaxLim_Ena", "size": 1},
            {"addr": 40159, "name": "OutPFSet", "size": 1},
            {"addr": 40160, "name": "Remaining", "size": 15},
        ],
    },
]


def _decode_register_value(regs: list[int], field: dict) -> object:
    """Decode register value(s) based on field type."""
    if field.get("type") == "string":
        # Decode uint16 list to ASCII string
        chars = []
        for val in regs:
            chars.append(chr((val >> 8) & 0xFF))
            chars.append(chr(val & 0xFF))
        return "".join(chars).rstrip("\x00")
    elif field["size"] == 1:
        return regs[0] if regs else 0
    else:
        return list(regs)


async def index_handler(request: web.Request) -> web.Response:
    """Serve the frontend HTML page."""
    try:
        import importlib.resources as pkg_resources
        ref = pkg_resources.files("venus_os_fronius_proxy") / "static" / "index.html"
        html = ref.read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")
    except (FileNotFoundError, TypeError, ModuleNotFoundError):
        return web.Response(
            text="<h1>Frontend not deployed</h1>",
            content_type="text/html",
        )


async def status_handler(request: web.Request) -> web.Response:
    """Return SolarEdge connection state and Venus OS status."""
    shared_ctx = request.app["shared_ctx"]
    conn_mgr = shared_ctx["conn_mgr"]
    return web.json_response({
        "solaredge": conn_mgr.state.value,
        "venus_os": "active",
        "reconfiguring": request.app.get("reconfiguring", False),
    })


async def health_handler(request: web.Request) -> web.Response:
    """Return uptime, poll success rate, and cache staleness."""
    shared_ctx = request.app["shared_ctx"]
    cache = shared_ctx["cache"]
    poll_counter = shared_ctx["poll_counter"]

    uptime = time.monotonic() - request.app["start_time"]
    total = poll_counter["total"]
    success = poll_counter["success"]
    rate = (success / total * 100) if total > 0 else 0.0

    last_poll_age = None
    if cache._has_been_updated:
        last_poll_age = round(time.monotonic() - cache.last_successful_poll, 1)

    return web.json_response({
        "uptime_seconds": round(uptime, 1),
        "poll_success_rate": round(rate, 1),
        "poll_total": total,
        "poll_success": success,
        "cache_stale": cache.is_stale,
        "last_poll_age": last_poll_age,
    })


async def config_get_handler(request: web.Request) -> web.Response:
    """Return current inverter configuration."""
    config: Config = request.app["config"]
    return web.json_response({
        "host": config.inverter.host,
        "port": config.inverter.port,
        "unit_id": config.inverter.unit_id,
    })


async def config_save_handler(request: web.Request) -> web.Response:
    """Save new inverter settings, trigger hot-reload."""
    try:
        body = await request.json()
        host = body["host"]
        port = body["port"]
        unit_id = body["unit_id"]
    except (KeyError, ValueError) as e:
        return web.json_response(
            {"success": False, "error": f"Invalid request: {e}"},
            status=400,
        )

    error = validate_inverter_config(host, port, unit_id)
    if error:
        return web.json_response(
            {"success": False, "error": error},
            status=400,
        )

    try:
        config: Config = request.app["config"]
        config.inverter.host = host
        config.inverter.port = port
        config.inverter.unit_id = unit_id
        save_config(request.app["config_path"], config)

        request.app["reconfiguring"] = True
        plugin = request.app["plugin"]
        await plugin.reconfigure(host, port, unit_id)
        request.app["reconfiguring"] = False

        return web.json_response({"success": True})
    except Exception as e:
        request.app["reconfiguring"] = False
        return web.json_response(
            {"success": False, "error": str(e)},
            status=500,
        )


async def config_test_handler(request: web.Request) -> web.Response:
    """Test-connect to a Modbus address without saving."""
    try:
        body = await request.json()
        host = body["host"]
        port = body["port"]
        unit_id = body["unit_id"]
    except (KeyError, ValueError) as e:
        return web.json_response(
            {"success": False, "error": f"Invalid request: {e}"},
            status=400,
        )

    error = validate_inverter_config(host, port, unit_id)
    if error:
        return web.json_response({"success": False, "error": error}, status=400)

    from pymodbus.client import AsyncModbusTcpClient

    client = AsyncModbusTcpClient(host, port=port, timeout=5)
    try:
        await client.connect()
        result = await client.read_holding_registers(40000, 2, device_id=unit_id)
        if result.isError():
            return web.json_response({
                "success": False,
                "error": f"Modbus read error: {result}",
            })
        return web.json_response({"success": True, "error": None})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)})
    finally:
        client.close()


async def registers_handler(request: web.Request) -> web.Response:
    """Return side-by-side register data: SE source + Fronius target per field."""
    shared_ctx = request.app["shared_ctx"]
    cache = shared_ctx["cache"]
    last_se_poll = shared_ctx.get("last_se_poll")

    models_out = []
    for model in REGISTER_MODELS:
        fields_out = []
        for field in model["fields"]:
            # Fronius target value from cache datablock
            # pymodbus datablock uses address+1 internally
            try:
                fronius_regs = cache.datablock.getValues(
                    field["addr"] + 1, field["size"],
                )
                fronius_value = _decode_register_value(fronius_regs, field)
            except Exception:
                fronius_value = None

            # SE30K source value
            se_value = None
            if (
                model["source"] == "se"
                and last_se_poll is not None
                and model["se_offset_key"] in last_se_poll
            ):
                se_data = last_se_poll[model["se_offset_key"]]
                offset = field["addr"] - model["se_base_addr"]
                end = offset + field["size"]
                if end <= len(se_data):
                    se_regs = se_data[offset:end]
                    se_value = _decode_register_value(se_regs, field)

            fields_out.append({
                "addr": field["addr"],
                "name": field["name"],
                "se_value": se_value,
                "fronius_value": fronius_value,
            })

        models_out.append({
            "name": model["name"],
            "fields": fields_out,
        })

    return web.json_response(models_out)


CONTENT_TYPES = {
    "index.html": "text/html",
    "style.css": "text/css",
    "app.js": "application/javascript",
}


async def dashboard_handler(request: web.Request) -> web.Response:
    """Return the latest decoded dashboard snapshot as JSON."""
    shared_ctx = request.app["shared_ctx"]
    collector = shared_ctx.get("dashboard_collector")
    if collector is None or collector.last_snapshot is None:
        return web.json_response({"error": "no data"}, status=503)
    return web.json_response(collector.last_snapshot)


async def static_handler(request: web.Request) -> web.Response:
    """Serve static files (.css, .js) from the package via importlib.resources."""
    import importlib.resources as pkg_resources

    filename = request.match_info["filename"]
    if filename not in CONTENT_TYPES:
        raise web.HTTPNotFound()
    try:
        ref = pkg_resources.files("venus_os_fronius_proxy") / "static" / filename
        content = ref.read_text(encoding="utf-8")
        return web.Response(text=content, content_type=CONTENT_TYPES[filename])
    except (FileNotFoundError, TypeError, ModuleNotFoundError):
        raise web.HTTPNotFound()


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Handle WebSocket connections at /ws.

    On connect: send latest snapshot + downsampled history.
    Then keep connection open for broadcast pushes from poll loop.
    """
    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)
    request.app["ws_clients"].add(ws)

    try:
        collector = request.app["shared_ctx"].get("dashboard_collector")

        # Send latest snapshot if available
        if collector is not None and collector.last_snapshot is not None:
            await ws.send_json({"type": "snapshot", "data": collector.last_snapshot})

        # Send downsampled history for sparklines
        if collector is not None:
            mono_offset = time.time() - time.monotonic()
            history: dict[str, list[list[float]]] = {}
            for buf_key, buf in collector._buffers.items():
                samples = buf.get_all()
                if not samples:
                    continue
                # Downsample with step of 3 (5 min / 3 = ~100 points)
                downsampled = samples[::3]
                history[buf_key] = [
                    [s.timestamp + mono_offset, s.value] for s in downsampled
                ]
            if history:
                await ws.send_json({"type": "history", "data": history})

        # Keep connection alive; read loop for future commands (Phase 7)
        async for msg in ws:
            if msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                break
    finally:
        request.app["ws_clients"].discard(ws)

    return ws


async def broadcast_to_clients(app: web.Application, snapshot: dict) -> None:
    """Push a snapshot to all connected WebSocket clients.

    Dead/disconnected clients are silently removed.
    """
    clients = app.get("ws_clients")
    if not clients:
        return

    payload = json.dumps({"type": "snapshot", "data": snapshot})
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError, ConnectionResetError):
            clients.discard(ws)


async def power_limit_handler(request: web.Request) -> web.Response:
    """Handle power limit commands from webapp.

    Actions: "set" (with limit_pct), "enable", "disable".
    Returns 409 if Venus OS wrote within last 60s.
    Returns 400 on invalid values.
    Response always includes success and error fields (CTRL-07).
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "error": "Invalid JSON body"}, status=400,
        )

    action = body.get("action")
    if action not in ("set", "enable", "disable"):
        return web.json_response(
            {"success": False, "error": f"Unknown action: {action}"}, status=400,
        )

    shared_ctx = request.app["shared_ctx"]
    control = shared_ctx["control_state"]
    plugin = request.app["plugin"]
    override_log = shared_ctx.get("override_log")

    # No Venus OS priority block — manual limit is additive (min of webapp + venus wins)

    if action == "set":
        try:
            limit_pct = float(body["limit_pct"])
        except (KeyError, ValueError, TypeError):
            return web.json_response(
                {"success": False, "error": "Missing or invalid limit_pct"}, status=400,
            )

        if limit_pct < 0 or limit_pct > 100:
            return web.json_response(
                {"success": False, "error": f"limit_pct must be 0-100, got {limit_pct}"},
                status=400,
            )

        raw_value = int(round(limit_pct))  # SF=0: 50% -> 50
        error = validate_wmaxlimpct(raw_value)
        if error:
            return web.json_response(
                {"success": False, "error": error}, status=400,
            )

        result = await plugin.write_power_limit(True, limit_pct)
        if result.success:
            control.set_from_webapp(raw_value, 1)
            if override_log is not None:
                override_log.append("webapp", "set", limit_pct)
        return web.json_response({"success": result.success, "error": result.error})

    elif action == "enable":
        result = await plugin.write_power_limit(True, control.wmaxlimpct_float)
        if result.success:
            control.update_wmaxlim_ena(1)
            control.last_source = "webapp"
            control.last_change_ts = time.time()
            control.webapp_revert_at = time.monotonic() + 300.0
            if override_log is not None:
                override_log.append("webapp", "enable", control.wmaxlimpct_float)
        return web.json_response({"success": result.success, "error": result.error})

    else:  # disable
        result = await plugin.write_power_limit(False, 0.0)
        if result.success:
            control.update_wmaxlim_ena(0)
            control.last_source = "none"
            control.webapp_revert_at = None
            if override_log is not None:
                override_log.append("webapp", "disable", None)
        return web.json_response({"success": result.success, "error": result.error})


async def power_clamp_handler(request: web.Request) -> web.Response:
    """Set min/max power clamp for Venus OS regulation.

    Body: {"min_kw": 3, "max_kw": 20}
    Venus OS writes will be clamped to [min, max] kW range.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "error": "Invalid JSON body"}, status=400,
        )

    shared_ctx = request.app["shared_ctx"]
    control = shared_ctx["control_state"]

    control.clamp_min_pct = max(0, min(100, int(body.get("min_pct", 0))))
    control.clamp_max_pct = max(0, min(100, int(body.get("max_pct", 100))))

    # Enforce min <= max
    if control.clamp_min_pct > control.clamp_max_pct:
        control.clamp_min_pct = control.clamp_max_pct

    control.save_ui_state()
    return web.json_response({"success": True})


async def venus_lock_handler(request: web.Request) -> web.Response:
    """Handle Venus OS lock toggle commands.

    Actions: "lock" (lock for 15 min), "unlock" (unlock immediately).
    Returns 400 on invalid JSON or unknown action.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "error": "Invalid JSON body"}, status=400,
        )

    action = body.get("action")
    if action not in ("lock", "unlock"):
        return web.json_response(
            {"success": False, "error": f"Unknown action: {action}"}, status=400,
        )

    shared_ctx = request.app["shared_ctx"]
    control = shared_ctx["control_state"]
    override_log = shared_ctx.get("override_log")

    plugin = request.app["plugin"]

    if action == "lock":
        control.lock(duration_s=900.0)
        # Reset limit to 100% so inverter runs at full power while locked
        control.update_wmaxlimpct(100)
        control.update_wmaxlim_ena(0)
        control.last_source = "none"
        await plugin.write_power_limit(True, 100.0)
        control.save_ui_state()
        if override_log is not None:
            override_log.append("webapp", "lock", None, "Venus OS writes blocked, limit reset to 100%")
    else:
        control.unlock()
        control.save_ui_state()
        if override_log is not None:
            override_log.append("webapp", "unlock", None, "Venus OS writes unblocked")

    return web.json_response({"success": True})


async def create_webapp(
    shared_ctx: dict,
    config: Config,
    config_path: str,
    plugin: object,
) -> web.AppRunner:
    """Create and set up the aiohttp webapp.

    Returns an AppRunner (caller manages site creation and lifecycle).
    """
    app = web.Application()
    app["shared_ctx"] = shared_ctx
    app["config"] = config
    app["config_path"] = config_path
    app["plugin"] = plugin
    app["start_time"] = time.monotonic()
    app["reconfiguring"] = False
    app["ws_clients"] = weakref.WeakSet()

    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/status", status_handler)
    app.router.add_get("/api/health", health_handler)
    app.router.add_get("/api/config", config_get_handler)
    app.router.add_post("/api/config", config_save_handler)
    app.router.add_post("/api/config/test", config_test_handler)
    app.router.add_get("/api/registers", registers_handler)
    app.router.add_get("/api/dashboard", dashboard_handler)
    app.router.add_post("/api/power-limit", power_limit_handler)
    app.router.add_post("/api/power-clamp", power_clamp_handler)
    app.router.add_post("/api/venus-lock", venus_lock_handler)
    app.router.add_get("/static/{filename}", static_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    return runner
