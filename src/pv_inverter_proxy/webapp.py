"""aiohttp REST API backend for the configuration webapp.

Serves status, health, config, and register data endpoints.
The register viewer provides side-by-side SE30K source and Fronius target values.
WebSocket endpoint at /ws pushes live inverter snapshots to connected browsers.
"""
from __future__ import annotations

import asyncio
import dataclasses
import importlib.resources as pkg_resources
import json
import os
import tempfile
import time
import weakref
from datetime import datetime, timezone
from typing import Any

import aiohttp
import structlog
import yaml
from aiohttp import web

from pv_inverter_proxy.config import (
    Config,
    InverterEntry,
    ScannerConfig,
    get_active_inverter,
    save_config,
    validate_inverter_config,
    validate_venus_config,
)
from pv_inverter_proxy.control import validate_wmaxlimpct
from pv_inverter_proxy.mdns_discovery import discover_mqtt_brokers
from pv_inverter_proxy.shelly_discovery import discover_shelly_devices, probe_shelly_device
from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop
from pv_inverter_proxy.plugin import compute_throttle_score, get_throttle_caps
from pv_inverter_proxy.plugins.opendtu import OpenDTUPlugin
from pv_inverter_proxy.plugins.shelly import ShellyPlugin
from pv_inverter_proxy.scanner import ScanConfig, scan_subnet
from pv_inverter_proxy.venus_reader import venus_mqtt_loop

# Phase 44: Passive Version Badge
from pv_inverter_proxy.updater.version import Version

# Phase 46: Security belt (Plan 46-01) + progress broadcaster (Plan 46-02)
from pv_inverter_proxy.updater.security import (
    IDLE_PHASES,
    RateLimiter,
    audit_log_append,
    csrf_middleware,
    is_update_running,
)
from pv_inverter_proxy.updater.progress import start_broadcaster, stop_broadcaster
from pv_inverter_proxy.updater.status import load_status

# Phase 46 Plan 46-05 (CFG-02): minimal UpdateConfig dataclass + GET/PATCH.
from pv_inverter_proxy.updater.config import (
    UpdateConfig,
    load_update_config,
    save_update_config,
    validate_update_config_patch,
)
from dataclasses import asdict as _asdict_update_config

log = structlog.get_logger()

# Phase 46 D-12/D-13/D-14: single module-level sliding-window rate limiter
# Separate rate limiters: install/rollback share one 60s slot, check-now has
# its own. Prevents "Jetzt prüfen" from burning the install rate limit.
_update_rate_limiter = RateLimiter()  # type: RateLimiter
_check_rate_limiter = RateLimiter()   # type: RateLimiter


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
        ref = pkg_resources.files("pv_inverter_proxy") / "static" / "index.html"
        html = ref.read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")
    except (FileNotFoundError, TypeError, ModuleNotFoundError):
        return web.Response(
            text="<h1>Frontend not deployed</h1>",
            content_type="text/html",
        )


async def status_handler(request: web.Request) -> web.Response:
    """Return connection state and Venus OS status."""
    app_ctx = request.app["app_ctx"]

    # Aggregate connection state from all devices
    conn_states = []
    for ds in app_ctx.devices.values():
        if ds.conn_mgr is not None:
            conn_states.append(ds.conn_mgr.state.value)
    inverter_state = "connected" if "connected" in conn_states else (
        conn_states[0] if conn_states else "no_devices"
    )

    venus_connected = app_ctx.venus_mqtt_connected
    if venus_connected is True:
        venus_status = "connected"
    elif venus_connected is False:
        venus_status = "disconnected"
    else:
        venus_status = "not configured"

    return web.json_response({
        "solaredge": inverter_state,
        "venus_os": venus_status,
        "venus_os_detected": app_ctx.venus_os_detected,
        "venus_os_client_ip": app_ctx.venus_os_client_ip,
        "reconfiguring": request.app.get("reconfiguring", False),
        "device_count": len(app_ctx.devices),
    })


#: Startup grace window in seconds. Inside this window the overall status
#: collapses to "starting" instead of "degraded" so the Phase 45-04 updater
#: healthcheck does not misread a cold boot as an update failure
#: (HEALTH-01..02, read in concert with HEALTH-05's 15s stability check).
_HEALTH_STARTUP_GRACE_S = 30.0


def _derive_health_payload(app_ctx, uptime_s: float, config) -> dict:
    """Pure helper: build the rich /api/health response dict.

    Implements HEALTH-01..03. Factored out of :func:`health_handler` so that
    unit tests can exercise every derivation path without spinning up an
    aiohttp Application. Does no IO — only reads fields off ``app_ctx`` and
    ``config``. Safe to call from any thread.

    Args:
        app_ctx: The live :class:`AppContext` instance.
        uptime_s: Seconds since webapp ``start_time``. Caller computes this
            via ``time.monotonic() - app["start_time"]`` so the helper stays
            deterministic under tests.
        config: A config-like object with a ``venus.host`` attribute. Used
            to decide ``venus_os == "disabled"`` when the host is empty.

    Returns:
        A plain dict with exactly the 8 keys mandated by HEALTH-01:
        ``{status, version, commit, uptime_seconds, webapp, modbus_server,
        devices, venus_os}``.
    """
    # --- per-component derivation ------------------------------------------
    webapp_s = "ok"  # by definition: if this code runs, the webapp is up

    cache = app_ctx.cache
    if cache is None:
        modbus_s = "failed"
    elif cache.is_stale:
        modbus_s = "degraded"
    else:
        modbus_s = "ok"

    devices_s: dict[str, str] = {}
    for dev_id, ds in app_ctx.devices.items():
        if ds.poll_counter.get("success", 0) > 0:
            devices_s[dev_id] = "ok"
        else:
            devices_s[dev_id] = "starting"

    # venus_os is warn-only per HEALTH-03 — even when "degraded" it never
    # flips overall status. "disabled" when host is empty (operator opted out).
    venus_host = getattr(getattr(config, "venus", None), "host", "") or ""
    if venus_host == "":
        venus_s = "disabled"
    elif app_ctx.venus_mqtt_connected:
        venus_s = "ok"
    else:
        venus_s = "degraded"

    # --- overall status derivation (HEALTH-02) ------------------------------
    required_ok = (
        webapp_s == "ok"
        and modbus_s == "ok"
        and any(s == "ok" for s in devices_s.values())
    )
    in_grace = uptime_s < _HEALTH_STARTUP_GRACE_S

    if required_ok:
        overall = "ok"
    elif in_grace:
        overall = "starting"
        # Remap flickering component states during startup so the updater
        # doesn't see a transient "degraded" modbus_server before the first
        # successful poll lands.
        if modbus_s in ("degraded", "failed"):
            modbus_s = "starting"
        devices_s = {
            k: ("ok" if v == "ok" else "starting") for k, v in devices_s.items()
        }
    else:
        overall = "degraded"

    return {
        "status": overall,
        "version": app_ctx.current_version or "unknown",
        "commit": app_ctx.current_commit or "unknown",
        "uptime_seconds": round(uptime_s, 1),
        "webapp": webapp_s,
        "modbus_server": modbus_s,
        "devices": devices_s,
        "venus_os": venus_s,
    }


async def health_handler(request: web.Request) -> web.Response:
    """Return the rich component-level health payload.

    Implements HEALTH-01..03 for Phase 45's in-app updater (Plan 45-04 polls
    this endpoint after restart to decide update success / rollback). The
    schema is::

        {
          "status": "ok" | "starting" | "degraded",
          "version": "8.0.0",
          "commit": "abc123d",
          "uptime_seconds": 42.1,
          "webapp": "ok",
          "modbus_server": "ok" | "starting" | "degraded" | "failed",
          "devices": {"<device_id>": "ok" | "starting" | "degraded" | "failed"},
          "venus_os": "ok" | "degraded" | "disabled"
        }

    HEALTH-04 (``/run/pv-inverter-proxy/healthy`` flag) is not written here —
    ``__main__._healthy_flag_watcher`` (Phase 43) owns that side-effect and
    runs once on the first successful poll.

    The handler itself is a thin wrapper around :func:`_derive_health_payload`
    to keep the hot path pure (no subprocess, no file IO, no DB).
    """
    app_ctx = request.app["app_ctx"]
    config = request.app["config"]
    uptime = time.monotonic() - request.app["start_time"]
    payload = _derive_health_payload(app_ctx, uptime, config)
    return web.json_response(payload)


async def broadcast_update_in_progress(app) -> None:
    """Plan 45-05 RESTART-03: pre-shutdown WebSocket broadcast.

    Fires the ``update_in_progress`` message to every connected client
    so the UI can show a "reconnect in ~10s" banner before the Modbus
    server + webapp go down. Best-effort: dead clients are silently
    dropped, any send failure is logged but does not abort the other
    sends.

    Accepts either an aiohttp ``web.Application`` or a plain dict-like
    object with a ``ws_clients`` entry (tests use the latter).
    """
    if app is None:
        return
    clients = app.get("ws_clients") if hasattr(app, "get") else None
    if not clients:
        return
    payload = json.dumps({
        "type": "update_in_progress",
        "message": "Update starting — reconnect in ~10s",
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    for ws in list(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, ConnectionResetError, RuntimeError) as exc:
            log.warning("ws_broadcast_update_in_progress_send_failed", error=str(exc))
            try:
                clients.discard(ws)
            except Exception:
                pass
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("ws_broadcast_update_in_progress_unexpected", error=str(exc))


async def _log_and_respond(
    request: web.Request,
    outcome: str | None,
    status: int,
    body: dict,
    *,
    extra_headers: dict | None = None,
) -> web.Response:
    """Emit one audit line (unless ``outcome`` is None) and return ``body``.

    Phase 46 D-15/D-19: every /api/update/{start,rollback,check} decision
    that falls into the closed outcome enum — ``accepted``, ``409_conflict``,
    ``429_rate_limited``, ``422_invalid_csrf`` — is recorded via
    :func:`audit_log_append`. Outcomes outside this set (e.g. malformed JSON
    body yielding 400) pass ``outcome=None`` to skip audit entirely rather
    than synthesizing a fake code. Audit failures never block the response
    so a disk-full condition on the audit log cannot wedge the UI path.
    """
    if outcome is not None:
        try:
            await audit_log_append(
                ip=request.remote or "unknown",
                user_agent=request.headers.get("User-Agent", ""),
                outcome=outcome,  # type: ignore[arg-type]
            )
        except Exception as exc:  # pragma: no cover - best-effort
            log.warning("audit_log_append_failed", error=str(exc))
    headers = extra_headers or {}
    return web.json_response(body, status=status, headers=headers)


async def update_start_handler(request: web.Request) -> web.Response:
    """POST /api/update/start -- EXEC-01, EXEC-02, SEC-07 + Phase 46 guards.

    Writes a trigger file atomically to ``/etc/pv-inverter-proxy/update-trigger.json``
    and returns HTTP 202. The actual update work happens in the root helper
    (``pv-inverter-proxy-updater.service``) triggered by a ``.path`` unit
    on ``PathModified``. Plan 45-02 shipped the producer half; Plan 46-04
    hardens this handler with the full guard belt (rate limit, concurrent
    guard, audit log) and expects CSRF to be enforced upstream by
    :func:`pv_inverter_proxy.updater.security.csrf_middleware`.

    Phase 46 pipeline order (D-20 — mandatory for <100ms latency):

        1. CSRF — enforced by middleware BEFORE reaching this handler.
        2. Rate limit (module-level sliding 60s window per IP).
        3. Concurrent-update guard (reads update-status.json).
        4. Parse + validate JSON body (existing Phase 45 validation).
        5. Enter maintenance mode + ``update_in_progress`` WS broadcast
           (Phase 45 SAFETY-09 / RESTART-01/03) BEFORE the write.
        6. Atomic trigger write (Phase 45 ``write_trigger``).
        7. Audit-log ``accepted`` and return 202.

    Request body (JSON):

        {"op": "update", "target_sha": "<40-char lowercase hex>"}

    or for rollback:

        {"op": "rollback", "target_sha": "previous"}

    Response:

        202 — trigger written, updater will pick it up:
            {"update_id": "<nonce>", "status_url": "/api/update/status"}
        400 — body malformed or schema-invalid:
            {"error": "<reason>"}
        500 — disk write failed (ENOSPC, EACCES, ...):
            {"error": "trigger_write_failed: <detail>"}

    Latency budget (EXEC-01 / D-20): the handler must complete in <100ms.
    The write path is sync and tiny — tempfile create, 5-field json.dumps,
    os.replace, chmod — all within the same filesystem as the target.
    The guard prefix is also hot: rate limit is an in-memory dict lookup,
    the concurrent guard is a single file read, and the audit log write
    runs in the thread pool executor. No network I/O, no subprocess.
    """
    # Local import keeps module-load time flat for webapp.py and avoids a
    # circular-import risk if the updater package ever pulls webapp types.
    from pv_inverter_proxy.updater.trigger import (
        TriggerPayload,
        generate_nonce,
        now_iso_utc,
        write_trigger,
    )

    # (a) Rate limit — 60s sliding window per source IP (D-12/D-13/D-14).
    accepted, retry_after = _update_rate_limiter.check(request.remote or "unknown")
    if not accepted:
        return await _log_and_respond(
            request,
            "429_rate_limited",
            429,
            {"error": "rate_limited", "retry_after": retry_after},
            extra_headers={"Retry-After": str(retry_after)},
        )

    # (b) Concurrent-update guard — status file is source of truth
    # (D-10/D-11). The webapp process never writes update-status.json, so
    # asyncio.Lock would be a false source of authority after a webapp
    # restart during an update.
    running, phase = is_update_running()
    if running:
        return await _log_and_respond(
            request,
            "409_conflict",
            409,
            {"error": "update_in_progress", "phase": phase},
        )

    # (c) Parse body. Malformed JSON is a client bug; not an auditable
    # outcome per the closed D-15 enum, so we skip the audit write.
    try:
        body = await request.json()
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return await _log_and_respond(
            request, None, 400, {"error": f"invalid_json: {exc}"}
        )

    if not isinstance(body, dict):
        return await _log_and_respond(
            request, None, 400, {"error": "body_must_be_json_object"}
        )

    op = body.get("op", "update")
    target_sha = body.get("target_sha")

    if not isinstance(op, str) or not isinstance(target_sha, str):
        return await _log_and_respond(
            request,
            None,
            400,
            {"error": "op and target_sha required as strings"},
        )

    payload = TriggerPayload(
        op=op,
        target_sha=target_sha,
        requested_at=now_iso_utc(),
        requested_by="webapp",
        nonce=generate_nonce(),
    )

    try:
        payload.validate()
    except ValueError as exc:
        return await _log_and_respond(
            request, None, 400, {"error": f"invalid_payload: {exc}"}
        )

    # Plan 45-05 RESTART-01/03: enter maintenance mode + broadcast
    # BEFORE writing the trigger. Venus OS will see DEVICE_BUSY on its
    # next Model 123 write during the drain window; connected web UI
    # clients receive the update_in_progress banner.
    try:
        from pv_inverter_proxy.updater.maintenance import enter_maintenance_mode

        app_ctx = request.app.get("app_ctx") if hasattr(request.app, "get") else None
        if app_ctx is not None:
            await enter_maintenance_mode(app_ctx, reason="update_requested")
    except Exception as exc:  # pragma: no cover - best effort
        log.warning("maintenance_mode_enter_failed", error=str(exc))

    try:
        await broadcast_update_in_progress(request.app)
    except Exception as exc:  # pragma: no cover - best effort
        log.warning("ws_broadcast_update_in_progress_failed", error=str(exc))

    try:
        write_trigger(payload)
    except OSError as exc:
        log.error("update_start_write_failed", error=str(exc))
        return await _log_and_respond(
            request, "500_trigger_write_failed", 500, {"error": f"trigger_write_failed: {exc}"}
        )

    log.info(
        "update_start_accepted",
        op=payload.op,
        target_sha=payload.target_sha,
        nonce=payload.nonce,
    )
    return await _log_and_respond(
        request,
        "accepted",
        202,
        {
            "update_id": payload.nonce,
            "status_url": "/api/update/status",
        },
    )


async def update_rollback_handler(request: web.Request) -> web.Response:
    """POST /api/update/rollback — Plan 46-04 UI-07, D-03.

    Writes a rollback trigger with the sentinel ``target_sha="previous"``.
    The root updater (Plan 45-04) resolves "previous" against the
    update-status.json history to find the prior version. Same 3-guard
    pipeline as :func:`update_start_handler`; CSRF is enforced by
    :func:`csrf_middleware`.
    """
    from pv_inverter_proxy.updater.trigger import (
        TriggerPayload,
        generate_nonce,
        now_iso_utc,
        write_trigger,
    )

    accepted, retry_after = _update_rate_limiter.check(request.remote or "unknown")
    if not accepted:
        return await _log_and_respond(
            request,
            "429_rate_limited",
            429,
            {"error": "rate_limited", "retry_after": retry_after},
            extra_headers={"Retry-After": str(retry_after)},
        )

    running, phase = is_update_running()
    if running:
        return await _log_and_respond(
            request,
            "409_conflict",
            409,
            {"error": "update_in_progress", "phase": phase},
        )

    payload = TriggerPayload(
        op="rollback",
        target_sha="previous",  # D-03 sentinel
        requested_at=now_iso_utc(),
        requested_by="webapp",
        nonce=generate_nonce(),
    )

    # Best-effort maintenance entry mirrors update_start_handler so the
    # Modbus server enters DEVICE_BUSY before the root updater starts
    # ripping files.
    try:
        from pv_inverter_proxy.updater.maintenance import enter_maintenance_mode

        app_ctx = request.app.get("app_ctx") if hasattr(request.app, "get") else None
        if app_ctx is not None:
            await enter_maintenance_mode(app_ctx, reason="rollback_requested")
    except Exception as exc:  # pragma: no cover - best effort
        log.warning("maintenance_mode_enter_failed_rollback", error=str(exc))

    try:
        await broadcast_update_in_progress(request.app)
    except Exception as exc:  # pragma: no cover - best effort
        log.warning("ws_broadcast_update_in_progress_failed", error=str(exc))

    try:
        write_trigger(payload)
    except OSError as exc:
        log.error("rollback_write_failed", error=str(exc))
        return await _log_and_respond(
            request, "500_trigger_write_failed", 500, {"error": f"trigger_write_failed: {exc}"}
        )

    log.info("update_rollback_accepted", nonce=payload.nonce)
    return await _log_and_respond(
        request,
        "accepted",
        202,
        {"update_id": payload.nonce, "status_url": "/api/update/status"},
    )


async def version_handler(request: web.Request) -> web.Response:
    """GET /api/version — D-27.

    Returns ``{version, commit}`` from the AppContext populated at startup
    by ``__main__`` via :func:`get_current_version` + :func:`get_commit_hash`.
    Frontend (Plan 46-03) stores this on first load and re-fetches on WS
    reconnect to detect a post-update restart and trigger ``location.reload()``.
    """
    app_ctx = request.app.get("app_ctx") if hasattr(request.app, "get") else None
    if app_ctx is None:
        return web.json_response({"version": None, "commit": None})
    return web.json_response(
        {
            "version": getattr(app_ctx, "current_version", None),
            "commit": getattr(app_ctx, "current_commit", None),
        }
    )


async def update_status_handler(request: web.Request) -> web.Response:
    """GET /api/update/status — Plan 46-04.

    Returns the full ``{current, history, schema_version}`` payload from
    the defensive status reader. Never raises: :func:`load_status` swallows
    all read errors and returns an empty :class:`UpdateStatus`.
    """
    try:
        status = load_status()
    except Exception as exc:  # pragma: no cover - load_status never raises
        log.warning("update_status_handler_load_failed", error=str(exc))
        return web.json_response({"current": None, "history": [], "schema_version": 1})

    if dataclasses.is_dataclass(status):
        return web.json_response(dataclasses.asdict(status))
    if hasattr(status, "to_dict"):
        return web.json_response(status.to_dict())
    return web.json_response(status)


async def update_check_handler(request: web.Request) -> web.Response:
    """POST /api/update/check — Plan 46-04 UI-02 Check-now button.

    Invokes the Phase 44 :class:`UpdateCheckScheduler.check_once` helper
    to force an immediate GitHub Releases poll. Returns
    ``{checked, available, latest_version}``. Rate-limited together with
    /api/update/start and /api/update/rollback via the shared module-level
    limiter to avoid GitHub API thrash.
    """
    accepted, retry_after = _check_rate_limiter.check(request.remote or "unknown")
    if not accepted:
        return await _log_and_respond(
            request,
            "429_rate_limited",
            429,
            {"error": "rate_limited", "retry_after": retry_after},
            extra_headers={"Retry-After": str(retry_after)},
        )

    scheduler = (
        request.app.get("update_scheduler") if hasattr(request.app, "get") else None
    )
    if scheduler is None:
        return web.json_response({"error": "scheduler_not_running"}, status=503)

    try:
        result = await scheduler.check_once()
    except Exception as exc:
        log.warning("update_check_once_failed", error=str(exc))
        return web.json_response(
            {"error": "check_failed", "detail": str(exc)}, status=500
        )

    if result is None:
        return web.json_response(
            {"checked": True, "available": False, "latest_version": None}
        )
    available = bool(getattr(result, "available", False))
    latest = getattr(result, "latest_version", None)
    return web.json_response(
        {"checked": True, "available": available, "latest_version": latest}
    )


async def update_config_get_handler(request: web.Request) -> web.Response:
    """GET /api/update/config — Plan 46-05 CFG-02 / D-04 / D-06.

    Returns the minimal 3-field ``UpdateConfig`` dataclass as JSON. Read
    is unauthenticated (no secrets among the 3 fields) and does NOT
    require a CSRF token: :func:`csrf_middleware` only gates mutating
    methods on ``/api/update/*``.
    """
    cfg_path = request.app.get("config_path") or ""
    try:
        uc = load_update_config(cfg_path)
    except Exception as exc:  # pragma: no cover - load_update_config never raises
        log.warning("update_config_load_failed", error=str(exc))
        uc = UpdateConfig()
    return web.json_response(_asdict_update_config(uc))


async def update_config_patch_handler(request: web.Request) -> web.Response:
    """PATCH /api/update/config — Plan 46-05 CFG-02 / D-04 / D-06.

    Accepts a subset of the 3 allowed keys
    (``github_repo`` / ``check_interval_hours`` / ``auto_install``) and
    merges the patch onto the current config. Unknown keys or bad types
    return 422 with a machine-readable ``detail`` string. CSRF is
    enforced upstream by :func:`csrf_middleware` (PATCH + ``/api/update/``
    prefix → double-submit cookie check).

    Response on success: the merged ``UpdateConfig`` as JSON, 200.
    """
    try:
        patch = await request.json()
    except Exception:
        return web.json_response(
            {"error": "invalid_json", "detail": "body_not_json"}, status=400
        )

    valid, err = validate_update_config_patch(patch)
    if not valid:
        return web.json_response(
            {"error": "validation_failed", "detail": err}, status=422
        )

    cfg_path = request.app.get("config_path") or ""
    try:
        current = load_update_config(cfg_path)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("update_config_load_failed_for_patch", error=str(exc))
        current = UpdateConfig()

    merged = UpdateConfig(
        github_repo=patch.get("github_repo", current.github_repo),
        check_interval_hours=patch.get(
            "check_interval_hours", current.check_interval_hours
        ),
        auto_install=patch.get("auto_install", current.auto_install),
    )

    try:
        save_update_config(cfg_path, merged)
    except Exception as exc:
        log.warning("update_config_save_failed", error=str(exc))
        return web.json_response(
            {"error": "save_failed", "detail": str(exc)}, status=500
        )

    return web.json_response(_asdict_update_config(merged), status=200)


async def update_available_handler(request: web.Request) -> web.Response:
    """GET /api/update/available -- CHECK-05.

    Returns the current version, commit, and (if available) the latest GitHub
    release info. CHECK-06: also surfaces last_check_at and last_check_failed_at
    so the UI can show a stale/failed indicator.

    Response shape:
        {
          "current_version": "8.0.0",
          "current_commit": "abc123d",
          "available_update": {
             "latest_version": "v8.1.0",
             "tag_name": "v8.1.0",
             "release_notes": "...",
             "published_at": "2026-04-10T...",
             "html_url": "https://github.com/..."
          } | null,
          "last_check_at": 1712755200.0 | null,
          "last_check_failed_at": null | 1712755200.0
        }
    """
    app_ctx = request.app["app_ctx"]
    return web.json_response({
        "current_version": app_ctx.current_version,
        "current_commit": app_ctx.current_commit,
        "available_update": app_ctx.available_update,
        "last_check_at": app_ctx.update_last_check_at,
        "last_check_failed_at": app_ctx.update_last_check_failed_at,
    })


async def config_get_handler(request: web.Request) -> web.Response:
    """Return current inverter list and Venus OS configuration."""
    config: Config = request.app["config"]
    active = get_active_inverter(config)
    items = []
    for inv in config.inverters:
        d = dataclasses.asdict(inv)
        d["active"] = (active is not None and inv.id == active.id)
        items.append(d)
    return web.json_response({
        "inverters": items,
        "venus": {
            "name": config.venus.name,
            "host": config.venus.host,
            "port": config.venus.port,
            "portal_id": config.venus.portal_id,
        },
        "mqtt_publish": {
            "enabled": config.mqtt_publish.enabled,
            "host": config.mqtt_publish.host,
            "port": config.mqtt_publish.port,
            "topic_prefix": config.mqtt_publish.topic_prefix,
            "interval_s": config.mqtt_publish.interval_s,
        },
    })


async def config_save_handler(request: web.Request) -> web.Response:
    """Save inverter and Venus OS settings, trigger hot-reload as needed.

    Accepts two inverter formats:
    - Old: {"inverter": {"host": ..., "port": ..., "unit_id": ...}} -- updates active entry
    - New: {"inverters": [...]} -- replaces entire inverter list
    """
    try:
        body = await request.json()
    except (ValueError, TypeError) as e:
        return web.json_response(
            {"success": False, "error": f"Invalid request: {e}"},
            status=400,
        )

    config: Config = request.app["config"]

    # --- Handle inverter(s) ---
    if "inverters" in body:
        # New multi-inverter format: replace entire list
        raw_list = body["inverters"]
        new_entries = []
        for raw in raw_list:
            host = raw.get("host", "")
            port = raw.get("port", 1502)
            unit_id = raw.get("unit_id", 1)
            error = validate_inverter_config(host, port, unit_id)
            if error:
                return web.json_response(
                    {"success": False, "error": error},
                    status=400,
                )
            new_entries.append(InverterEntry(
                host=host, port=port, unit_id=unit_id,
                enabled=raw.get("enabled", True),
                id=raw.get("id", None) or InverterEntry().id,
                manufacturer=raw.get("manufacturer", ""),
                model=raw.get("model", ""),
                serial=raw.get("serial", ""),
                firmware_version=raw.get("firmware_version", ""),
            ))
        config.inverters = new_entries
    elif "inverter" in body:
        # Old single-inverter format: update the active entry
        inv = body["inverter"]
        try:
            host = inv["host"]
            port = inv["port"]
            unit_id = inv["unit_id"]
        except (KeyError, TypeError) as e:
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
        active = get_active_inverter(config)
        if active:
            active.host = host
            active.port = port
            active.unit_id = unit_id
        else:
            # No active inverter, create one
            config.inverters.append(InverterEntry(host=host, port=port, unit_id=unit_id))

    # --- Parse venus config ---
    venus_body = body.get("venus", {})
    venus_name = venus_body.get("name", "")
    venus_host = venus_body.get("host", "")
    venus_port = venus_body.get("port", 1883)
    venus_portal_id = venus_body.get("portal_id", "")

    error = validate_venus_config(venus_host, venus_port)
    if error:
        return web.json_response(
            {"success": False, "error": error},
            status=400,
        )

    # --- Parse mqtt_publish config ---
    mqtt_pub_body = body.get("mqtt_publish", {})

    try:
        app_ctx = request.app["app_ctx"]

        # Detect venus config change
        old_venus = (config.venus.host, config.venus.port, config.venus.portal_id)
        new_venus = (venus_host, venus_port, venus_portal_id)
        venus_changed = old_venus != new_venus

        # Detect mqtt_publish config change
        old_mqtt_pub = (config.mqtt_publish.enabled, config.mqtt_publish.host,
                        config.mqtt_publish.port, config.mqtt_publish.topic_prefix,
                        config.mqtt_publish.interval_s, config.mqtt_publish.client_id)

        # Update mqtt_publish config fields
        if mqtt_pub_body:
            for k, v in mqtt_pub_body.items():
                if k in config.mqtt_publish.__dataclass_fields__:
                    setattr(config.mqtt_publish, k, v)

        new_mqtt_pub = (config.mqtt_publish.enabled, config.mqtt_publish.host,
                        config.mqtt_publish.port, config.mqtt_publish.topic_prefix,
                        config.mqtt_publish.interval_s, config.mqtt_publish.client_id)
        mqtt_publish_changed = old_mqtt_pub != new_mqtt_pub

        # Update venus config
        config.venus.name = venus_name
        config.venus.host = venus_host
        config.venus.port = venus_port
        config.venus.portal_id = venus_portal_id

        save_config(request.app["config_path"], config)
        log.info("user_action", action="config_saved", venus_changed=venus_changed, venus_host=venus_host)

        # Hot-reload active inverter
        await _reconfigure_active(request.app, config)

        # Hot-reload Venus MQTT if config changed
        if venus_changed:
            # Cancel old venus task if running
            old_task = app_ctx.venus_task
            if old_task is not None and not old_task.done():
                old_task.cancel()

            if venus_host:
                # Start new venus MQTT loop
                app_ctx.venus_task = asyncio.create_task(
                    venus_mqtt_loop(app_ctx, venus_host, venus_port, venus_portal_id)
                )
            else:
                # Venus disabled -- clear state
                app_ctx.venus_mqtt_connected = False
                app_ctx.venus_task = None

        # Hot-reload MQTT publisher if config changed
        if mqtt_publish_changed:
            old_task = app_ctx.mqtt_pub_task
            if old_task is not None and not old_task.done():
                old_task.cancel()
                try:
                    await old_task
                except asyncio.CancelledError:
                    pass

            if config.mqtt_publish.enabled:
                app_ctx.mqtt_pub_queue = asyncio.Queue(maxsize=100)
                app_ctx.mqtt_pub_task = asyncio.create_task(
                    mqtt_publish_loop(
                        app_ctx, config.mqtt_publish,
                        inverters=config.inverters,
                        virtual_name=config.virtual_inverter.name,
                    )
                )
                log.info("user_action", action="mqtt_publisher_reloaded", host=config.mqtt_publish.host)
            else:
                app_ctx.mqtt_pub_connected = False
                app_ctx.mqtt_pub_task = None
                app_ctx.mqtt_pub_queue = None
                log.info("user_action", action="mqtt_publisher_disabled")

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


async def device_registers_handler(request: web.Request) -> web.Response:
    """Return side-by-side register data for a specific device."""
    device_id = request.match_info["id"]
    app_ctx = request.app["app_ctx"]
    cache = app_ctx.cache
    ds = app_ctx.devices.get(device_id)
    if ds is None:
        return web.json_response({"error": "Device not found"}, status=404)
    last_se_poll = ds.last_poll_data
    return _build_register_response(cache, last_se_poll)


async def registers_handler(request: web.Request) -> web.Response:
    """Return side-by-side register data: SE source + Fronius target per field."""
    app_ctx = request.app["app_ctx"]
    cache = app_ctx.cache
    # Legacy endpoint: use first device's data for backward compatibility
    first_dev = next(iter(app_ctx.devices.values()), None)
    last_se_poll = first_dev.last_poll_data if first_dev else None
    return _build_register_response(cache, last_se_poll)


def _build_register_response(cache, last_se_poll) -> web.Response:
    """Build register JSON response from cache and poll data."""

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
    app_ctx = request.app["app_ctx"]
    # Use first device's collector for dashboard data
    # TODO Phase 24: aggregated virtual dashboard
    first_dev = next(iter(app_ctx.devices.values()), None)
    collector = first_dev.collector if first_dev else None
    if collector is None or collector.last_snapshot is None:
        return web.json_response({"error": "no data"}, status=503)
    return web.json_response(collector.last_snapshot)


async def static_handler(request: web.Request) -> web.Response:
    """Serve static files (.css, .js) from the package via importlib.resources."""
    filename = request.match_info["filename"]
    if filename not in CONTENT_TYPES:
        raise web.HTTPNotFound()
    try:
        ref = pkg_resources.files("pv_inverter_proxy") / "static" / filename
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
        ws_app_ctx = request.app["app_ctx"]
        config: Config = request.app["config"]

        # Send per-device snapshots for all active devices
        sent_any = False
        first_collector = None
        for dev_id, ds in ws_app_ctx.devices.items():
            if ds.collector and ds.collector.last_snapshot:
                if first_collector is None:
                    first_collector = ds.collector
                snap = ds.collector.last_snapshot
                # Override with per-device clamp values
                if ws_app_ctx.control_state and "control" in snap:
                    dmin, dmax = ws_app_ctx.control_state.get_device_clamp(dev_id)
                    snap["control"]["clamp_min_pct"] = dmin
                    snap["control"]["clamp_max_pct"] = dmax
                await ws.send_json({
                    "type": "device_snapshot",
                    "device_id": dev_id,
                    "data": snap,
                })
                sent_any = True

        # Also send legacy snapshot for backward compat (first device)
        if first_collector is not None and first_collector.last_snapshot is not None:
            await ws.send_json({"type": "snapshot", "data": first_collector.last_snapshot})
        elif ws_app_ctx.polling_paused:
            await ws.send_json({"type": "no_inverter"})

        # Send virtual snapshot
        if sent_any:
            total_power_w, total_rated_w, contributions = _build_virtual_contributions(ws_app_ctx, config)
            await ws.send_json({"type": "virtual_snapshot", "data": {
                "total_power_w": total_power_w,
                "total_rated_w": total_rated_w,
                "virtual_name": config.virtual_inverter.name,
                "contributions": contributions,
            }})

        # Send downsampled history for sparklines (first device only)
        collector = first_collector
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

        # Send initial device list so client knows connection states (MQTT etc.)
        devices = _build_device_list(ws_app_ctx, config)
        await ws.send_json({"type": "device_list", "data": {"devices": devices}})

        # Phase 44: send initial available_update state so fresh clients know
        # the current version + any pending release info (CHECK-01/05/06)
        await ws.send_json({
            "type": "available_update",
            "data": {
                "current_version": ws_app_ctx.current_version,
                "current_commit": ws_app_ctx.current_commit,
                "available_update": ws_app_ctx.available_update,
                "last_check_at": ws_app_ctx.update_last_check_at,
                "last_check_failed_at": ws_app_ctx.update_last_check_failed_at,
            },
        })

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

    # Attach Venus OS ESS settings if available
    bc_app_ctx = app.get("app_ctx")
    venus_settings = bc_app_ctx.venus_settings if bc_app_ctx is not None else None
    if venus_settings:
        snapshot["venus_settings"] = venus_settings

    payload = json.dumps({"type": "snapshot", "data": snapshot})
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError, ConnectionResetError):
            clients.discard(ws)


async def broadcast_device_snapshot(app: web.Application, device_id: str, snapshot: dict) -> None:
    """Push a per-device snapshot to all connected WebSocket clients."""
    clients = app.get("ws_clients")
    if not clients:
        return
    bc_ctx = app.get("app_ctx")
    venus_settings = bc_ctx.venus_settings if bc_ctx else None
    if venus_settings:
        snapshot["venus_settings"] = venus_settings
    # Override clamp values with per-device clamp if available
    if bc_ctx and bc_ctx.control_state and "control" in snapshot:
        dmin, dmax = bc_ctx.control_state.get_device_clamp(device_id)
        snapshot["control"]["clamp_min_pct"] = dmin
        snapshot["control"]["clamp_max_pct"] = dmax
    # Inject cached OpenDTU data for instant display
    if bc_ctx:
        ds = bc_ctx.devices.get(device_id)
        if ds and ds.plugin and hasattr(ds.plugin, "opendtu_status"):
            if ds.plugin.opendtu_status:
                snapshot["opendtu_status"] = ds.plugin.opendtu_status
            if hasattr(ds.plugin, "dc_channels") and ds.plugin.dc_channels:
                snapshot["dc_channels"] = ds.plugin.dc_channels
    payload = json.dumps({"type": "device_snapshot", "device_id": device_id, "data": snapshot})
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError, ConnectionResetError):
            clients.discard(ws)

    # MQTT telemetry queue (Phase 26)
    if bc_ctx and bc_ctx.mqtt_pub_queue is not None:
        try:
            # Resolve device name from config for MQTT payload
            _cfg = app.get("config")
            _dev_name = ""
            if _cfg:
                for _ie in getattr(_cfg, "inverters", []):
                    if _ie.id == device_id:
                        _dev_name = _ie.name or f"{_ie.manufacturer} {_ie.model}".strip()
                        break
            bc_ctx.mqtt_pub_queue.put_nowait({
                "type": "device",
                "device_id": device_id,
                "device_name": _dev_name or device_id,
                "snapshot": snapshot,
            })
        except asyncio.QueueFull:
            pass  # Drop oldest-style: publisher behind, stale data has no value


async def broadcast_virtual_snapshot(app: web.Application) -> None:
    """Broadcast aggregated virtual inverter snapshot to all WebSocket clients."""
    clients = app.get("ws_clients")
    if not clients:
        return
    app_ctx = app.get("app_ctx")
    config: Config = app.get("config")
    if app_ctx is None or config is None:
        return

    total_power_w, total_rated_w, contributions = _build_virtual_contributions(app_ctx, config)

    payload = json.dumps({"type": "virtual_snapshot", "data": {
        "total_power_w": total_power_w,
        "total_rated_w": total_rated_w,
        "virtual_name": config.virtual_inverter.name,
        "contributions": contributions,
    }})
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError, ConnectionResetError):
            clients.discard(ws)

    # MQTT telemetry queue (Phase 26)
    if app_ctx and app_ctx.mqtt_pub_queue is not None:
        try:
            app_ctx.mqtt_pub_queue.put_nowait({
                "type": "virtual",
                "virtual_data": {
                    "total_power_w": total_power_w,
                    "virtual_name": config.virtual_inverter.name,
                    "contributions": contributions,
                },
            })
        except asyncio.QueueFull:
            pass


def _build_virtual_contributions(
    app_ctx: Any, config: Config,
) -> tuple[float, float, list[dict]]:
    """Aggregate power and per-device contributions for the virtual inverter.

    Returns (total_power_w, total_rated_w, contributions).
    """
    total_power_w = 0
    total_rated_w = 0
    contributions: list[dict] = []
    distributor = (
        getattr(app_ctx, "device_registry", None)
        and app_ctx.device_registry.distributor
    )
    device_limits = distributor.get_device_limits() if distributor is not None else {}

    for inv in config.inverters:
        if not inv.aggregate:
            continue
        ds = app_ctx.devices.get(inv.id)
        power_w = 0
        rated_w = inv.rated_power
        if ds and ds.collector and ds.collector.last_snapshot:
            snap_inv = ds.collector.last_snapshot.get("inverter", {})
            power_w = snap_inv.get("ac_power_w", 0)
            # Use snapshot rated_power_w if config has 0
            if not rated_w:
                rated_w = ds.collector.last_snapshot.get("rated_power_w", 0)
        total_power_w += power_w
        total_rated_w += rated_w
        display_name = inv.name or f"{inv.manufacturer} {inv.model}".strip() or "Inverter"
        contrib: dict = {
            "device_id": inv.id,
            "name": display_name,
            "power_w": power_w,
            "throttle_order": inv.throttle_order,
            "throttle_enabled": inv.throttle_enabled,
            "current_limit_pct": device_limits.get(inv.id, 100.0),
        }

        plugin = ds.plugin if ds else None
        caps = get_throttle_caps(plugin)
        throttle_score = compute_throttle_score(caps) if caps else 0.0
        throttle_mode = caps.mode if caps else "none"

        # Build score breakdown for UI transparency
        if caps and caps.mode != "none":
            base = 7.0 if caps.mode == "proportional" else 3.0
            response_bonus = round(max(0.0, 3.0 * (1.0 - caps.response_time_s / 10.0)), 2)
            cooldown_penalty = round(min(2.0, caps.cooldown_s / 150.0), 2)
            startup_penalty = round(min(1.0, caps.startup_delay_s / 30.0), 2)
            score_breakdown = {
                "base": base,
                "response_time_s": caps.response_time_s,
                "response_bonus": response_bonus,
                "cooldown_s": caps.cooldown_s,
                "cooldown_penalty": cooldown_penalty,
                "startup_delay_s": caps.startup_delay_s,
                "startup_penalty": startup_penalty,
            }
        else:
            score_breakdown = None

        display = distributor.get_device_display_state(inv.id) if distributor else None
        if display:
            contrib["throttle_score"] = throttle_score
            contrib["throttle_mode"] = throttle_mode
            contrib["score_breakdown"] = score_breakdown
            contrib["measured_response_time_s"] = display["measured_response_time_s"]
            contrib["relay_on"] = display["relay_on"]
            contrib["throttle_state"] = display["throttle_state"]
        else:
            contrib["throttle_score"] = throttle_score
            contrib["throttle_mode"] = throttle_mode
            contrib["score_breakdown"] = score_breakdown
            contrib["measured_response_time_s"] = None
            contrib["relay_on"] = True
            contrib["throttle_state"] = "active" if inv.throttle_enabled else "disabled"
        contributions.append(contrib)

    return total_power_w, total_rated_w, contributions


def _build_device_list(app_ctx: Any, config: Config) -> list[dict]:
    """Build the device list payload used by WS clients for sidebar + status dots."""
    devices = []
    for inv in config.inverters:
        ds = app_ctx.devices.get(inv.id)
        conn_state = "unknown"
        if ds and ds.conn_mgr:
            conn_state = ds.conn_mgr.state.value
        power_w = 0
        if ds and ds.collector and ds.collector.last_snapshot:
            snap_inv = ds.collector.last_snapshot.get("inverter", {})
            power_w = snap_inv.get("ac_power_w", 0)
        display_name = inv.name or f"{inv.manufacturer} {inv.model}".strip() or "Inverter"
        dev_entry: dict = {
            "id": inv.id,
            "name": display_name,
            "type": inv.type,
            "enabled": inv.enabled,
            "host": inv.host,
            "port": inv.port,
            "unit_id": inv.unit_id,
            "connection_state": conn_state,
            "power_w": power_w,
            "rated_power": inv.rated_power,
            "throttle_order": inv.throttle_order,
            "throttle_enabled": inv.throttle_enabled,
            "aggregate": inv.aggregate,
            "panel_power_wp": inv.panel_power_wp,
        }
        if inv.type == "opendtu":
            dev_entry["gateway_host"] = inv.gateway_host
            dev_entry["gateway_user"] = inv.gateway_user
            dev_entry["gateway_password"] = inv.gateway_password
        if inv.type == "shelly":
            dev_entry["shelly_gen"] = inv.shelly_gen
        caps = get_throttle_caps(ds.plugin if ds else None)
        dev_entry["throttle_mode"] = caps.mode if caps else "none"
        dev_entry["throttle_score"] = compute_throttle_score(caps) if caps else 0.0
        distributor = getattr(app_ctx, 'distributor', None)
        if distributor is not None:
            display = distributor.get_device_display_state(inv.id)
            if display and display["measured_response_time_s"] is not None:
                dev_entry["measured_response_time_s"] = round(display["measured_response_time_s"], 2)
        devices.append(dev_entry)

    venus_conn = "connected" if app_ctx.venus_mqtt_connected else "disconnected"
    devices.append({
        "id": "venus",
        "name": config.venus.name or "Venus OS",
        "type": "venus",
        "enabled": bool(config.venus.host),
        "connection_state": venus_conn,
    })
    virtual_conn = "disconnected"
    webapp = getattr(app_ctx, "webapp", None)
    slave_ctx = webapp.get("slave_ctx") if webapp is not None else None
    if slave_ctx and getattr(slave_ctx, "last_successful_read", 0) > 0:
        age = time.monotonic() - slave_ctx.last_successful_read
        virtual_conn = "connected" if age < 30 else "disconnected"
    virtual_rated_w = sum(inv.rated_power for inv in config.inverters if inv.enabled and inv.aggregate)
    devices.append({
        "id": "virtual",
        "name": config.virtual_inverter.name,
        "type": "virtual",
        "connection_state": virtual_conn,
        "rated_power": virtual_rated_w,
    })
    mqtt_pub_conn = "connected" if app_ctx.mqtt_pub_connected else "disconnected"
    devices.append({
        "id": "mqtt_pub",
        "name": config.mqtt_publish.name or "MQTT Publishing",
        "type": "mqtt_pub",
        "enabled": config.mqtt_publish.enabled,
        "connection_state": mqtt_pub_conn,
        "stats": {
            "messages": app_ctx.mqtt_pub_messages,
            "bytes": app_ctx.mqtt_pub_bytes,
            "skipped": app_ctx.mqtt_pub_skipped,
            "last_ts": app_ctx.mqtt_pub_last_ts,
        },
    })
    return devices


async def broadcast_device_list(app: web.Application) -> None:
    """Broadcast updated device list to all WebSocket clients."""
    clients = app.get("ws_clients")
    if not clients:
        return
    app_ctx = app.get("app_ctx")
    config: Config = app.get("config")
    if app_ctx is None or config is None:
        return

    devices = _build_device_list(app_ctx, config)
    payload = json.dumps({"type": "device_list", "data": {
        "devices": devices,
    }})
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError, ConnectionResetError):
            clients.discard(ws)


async def broadcast_available_update(app: web.Application) -> None:
    """Push updated available_update + version info to all WS clients.

    Called by the scheduler callback whenever AppContext.available_update or
    the last_check_{at,failed_at} fields change. Mirrors broadcast_device_list
    to reuse its pruning pattern for dead clients.
    """
    clients = app.get("ws_clients")
    if not clients:
        return
    app_ctx = app.get("app_ctx")
    if app_ctx is None:
        return
    payload = json.dumps({
        "type": "available_update",
        "data": {
            "current_version": app_ctx.current_version,
            "current_commit": app_ctx.current_commit,
            "available_update": app_ctx.available_update,
            "last_check_at": app_ctx.update_last_check_at,
            "last_check_failed_at": app_ctx.update_last_check_failed_at,
        },
    })
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError, ConnectionResetError):
            clients.discard(ws)


async def _broadcast_scan_progress(app: web.Application, phase: str, current: int, total: int) -> None:
    """Broadcast scan progress to all WS clients."""
    clients = app.get("ws_clients")
    if not clients:
        return
    payload = json.dumps({
        "type": "scan_progress",
        "data": {"phase": phase, "current": current, "total": total}
    })
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError):
            clients.discard(ws)


async def _broadcast_scan_complete(app: web.Application, devices: list) -> None:
    """Broadcast scan results to all WS clients."""
    clients = app.get("ws_clients")
    if not clients:
        return
    payload = json.dumps({
        "type": "scan_complete",
        "data": {
            "devices": [{**dataclasses.asdict(d), "supported": d.supported} for d in devices],
            "count": len(devices)
        }
    })
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError):
            clients.discard(ws)


async def _broadcast_scan_error(app: web.Application, error: str) -> None:
    """Broadcast scan error to all WS clients."""
    clients = app.get("ws_clients")
    if not clients:
        return
    payload = json.dumps({"type": "scan_error", "data": {"error": error}})
    for ws in set(clients):
        try:
            await ws.send_str(payload)
        except (ConnectionError, RuntimeError):
            clients.discard(ws)


async def _run_scan(app: web.Application, scan_config: ScanConfig, auto_add: bool = False) -> None:
    """Run scan as background task, broadcasting progress via WS.

    If auto_add=True, automatically add supported discovered devices to config
    and start polling. Used for first-run onboarding and manual "Scan & Add".
    """
    app["_scan_running"] = True
    app_ctx = app["app_ctx"]
    # Pause polling during scan to avoid ESP32 contention (OpenDTU)
    was_paused = app_ctx.polling_paused
    app_ctx.polling_paused = True
    log.info("scan.polling_paused")
    await asyncio.sleep(1)  # Let active polls finish
    try:
        def progress_cb(phase: str, current: int, total: int) -> None:
            asyncio.create_task(_broadcast_scan_progress(app, phase, current, total))

        devices = await scan_subnet(scan_config, progress_callback=progress_cb)

        # Auto-add supported devices that aren't already configured
        if auto_add and devices:
            config: Config = app["config"]
            existing_serials = {inv.serial for inv in config.inverters if inv.serial}
            existing_hosts = {(inv.host, inv.port, inv.unit_id) for inv in config.inverters}
            added = 0

            for dev in devices:
                if not dev.supported:
                    continue

                # Skip if already configured by serial (primary dedup key)
                if dev.serial_number and dev.serial_number in existing_serials:
                    log.info("scan.auto_add_skipped", ip=dev.ip, serial=dev.serial_number, reason="already_configured")
                    continue
                # For Modbus devices (no serial yet), dedup by host:port:unit_id
                if not dev.serial_number and (dev.ip, dev.port, dev.unit_id) in existing_hosts:
                    log.info("scan.auto_add_skipped", ip=dev.ip, reason="host_port_match")
                    continue

                entry = InverterEntry(
                    host=dev.ip,
                    port=dev.port,
                    unit_id=dev.unit_id,
                    enabled=True,
                    manufacturer=dev.manufacturer,
                    model=dev.model,
                    serial=dev.serial_number,
                    firmware_version=dev.firmware_version,
                    type=dev.device_type,
                    name=dev.model if dev.device_type == "opendtu" else "",
                    gateway_host=dev.ip if dev.device_type == "opendtu" else "",
                )
                config.inverters.append(entry)
                added += 1
                log.info("scan.auto_added", device_id=entry.id, ip=dev.ip, manufacturer=dev.manufacturer, model=dev.model, type=dev.device_type)

            if added > 0:
                save_config(app["config_path"], config)
                # Start newly added devices
                for inv in config.inverters:
                    if inv.enabled and inv.id not in {d_id for d_id in app["app_ctx"].devices}:
                        try:
                            await _reconfigure_active(app, config, device_id=inv.id, action="start")
                        except Exception as exc:
                            log.warning("scan.auto_start_failed", device_id=inv.id, error=str(exc))
                log.info("scan.auto_add_complete", added=added, total_inverters=len(config.inverters))

        await _broadcast_scan_complete(app, devices)
    except Exception as e:
        log.error("scanner.background_scan_failed", error=str(e))
        await _broadcast_scan_error(app, str(e))
    finally:
        app["_scan_running"] = False
        # Resume polling
        if not was_paused:
            app_ctx.polling_paused = False
            log.info("scan.polling_resumed")


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

    log.info("user_action", action="power_limit", limit_action=action, limit_pct=body.get("limit_pct"))

    app_ctx = request.app["app_ctx"]
    control = app_ctx.control_state
    override_log = app_ctx.override_log

    # No Venus OS priority block -- manual limit is additive (min of webapp + venus wins)

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

        # Accept locally and trigger distribution immediately
        control.set_from_webapp(raw_value, 1)
        if override_log is not None:
            override_log.append("webapp", "set", limit_pct)
        distributor = getattr(app_ctx, 'distributor', None)
        if distributor is not None:
            await distributor.distribute(control.wmaxlimpct_float, control.is_enabled)
        return web.json_response({"success": True, "error": None})

    elif action == "enable":
        control.update_wmaxlim_ena(1)
        control.last_source = "webapp"
        control.last_change_ts = time.time()
        control.webapp_revert_at = time.monotonic() + 300.0
        if override_log is not None:
            override_log.append("webapp", "enable", control.wmaxlimpct_float)
        distributor = getattr(app_ctx, 'distributor', None)
        if distributor is not None:
            await distributor.distribute(control.wmaxlimpct_float, control.is_enabled)
        return web.json_response({"success": True, "error": None})

    else:  # disable
        control.update_wmaxlim_ena(0)
        control.last_source = "none"
        control.webapp_revert_at = None
        if override_log is not None:
            override_log.append("webapp", "disable", None)
        distributor = getattr(app_ctx, 'distributor', None)
        if distributor is not None:
            await distributor.distribute(control.wmaxlimpct_float, False)
        return web.json_response({"success": True, "error": None})


async def power_clamp_handler(request: web.Request) -> web.Response:
    """Set per-device min/max power limit.

    Body: {"device_id": "abc123", "min_pct": 0, "max_pct": 13}
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "error": "Invalid JSON body"}, status=400,
        )

    device_id = body.get("device_id")
    if not device_id:
        return web.json_response(
            {"success": False, "error": "device_id required"}, status=400,
        )

    app_ctx = request.app["app_ctx"]
    control = app_ctx.control_state
    min_pct = max(0, min(100, int(body.get("min_pct", 0))))
    max_pct = max(0, min(100, int(body.get("max_pct", 100))))

    control.set_device_clamp(device_id, min_pct, max_pct)

    # Virtual aggregate: clamp applies to the whole Fronius proxy. Update the
    # global clamp_min/max_pct (read by proxy.async_setValues to clip Venus OS
    # writes), re-clamp the current limit, and trigger an immediate
    # distribution so the limit takes effect now — not only on the next
    # Venus OS write.
    if device_id == "virtual":
        control.clamp_min_pct = min_pct
        control.clamp_max_pct = max_pct
        # The user's max dropdown is THE active limit, not just an upper
        # bound on Venus OS writes. When they pick "Max" (100/0), release
        # the throttle entirely — distributor sends 100% to all devices
        # and the SolarEdge ramps back up. Otherwise the chosen ceiling is
        # the setpoint.
        full_release = (min_pct == 0 and max_pct >= 100)
        if full_release:
            control.update_wmaxlim_ena(0)
            # Keep wmaxlimpct_raw at 100 so the readback is sane.
            control.update_wmaxlimpct(100)
        else:
            control.update_wmaxlimpct(max_pct)
            control.update_wmaxlim_ena(1)
        # Tag the source so persisted state files record it correctly
        # and the boot-time restore paths re-apply it.
        control.last_source = "webapp"
        control.last_change_ts = time.time()
        control.save_ui_state()
        control.save_last_limit()
        if app_ctx.override_log is not None:
            app_ctx.override_log.append(
                "webapp", "release" if full_release else "clamp",
                control.wmaxlimpct_float,
                detail=f"min={min_pct}% max={max_pct}%",
            )
        distributor = getattr(app_ctx, "distributor", None)
        if distributor is not None:
            await distributor.distribute(
                control.wmaxlimpct_float, control.is_enabled,
            )
        return web.json_response({"success": True})

    # Find the plugin for this device
    plugin = None
    ds = app_ctx.devices.get(device_id)
    if ds and ds.plugin:
        plugin = ds.plugin

    if plugin is not None:
        caps = get_throttle_caps(plugin)
        if caps and caps.mode == "binary":
            # Binary device: switch on/off based on max_pct
            await plugin.switch(max_pct > 0)
        elif max_pct < 100:
            await plugin.write_power_limit(True, max_pct, force=True)
        else:
            await plugin.write_power_limit(True, 100.0, force=True)

    return web.json_response({"success": True})


async def venus_write_handler(request: web.Request) -> web.Response:
    """Write a single register to Venus OS Modbus TCP.

    Body: {"register": 2706, "value": 100}
    Only allows known safe registers (ESS settings).
    """
    ALLOWED_REGISTERS = {2704, 2706, 2707, 2708}  # MaxDischargePower, MaxFeedIn, OvervoltageFeedIn, PreventFeedback

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "error": "Invalid JSON body"}, status=400,
        )

    register = body.get("register")
    value = body.get("value")

    if register not in ALLOWED_REGISTERS:
        return web.json_response(
            {"success": False, "error": f"Register {register} not writable"}, status=400,
        )

    venus_cfg = request.app["config"].venus
    if not venus_cfg.host:
        return web.json_response(
            {"success": False, "error": "Venus OS not configured"}, status=503,
        )

    try:
        from pymodbus.client import AsyncModbusTcpClient
        client = AsyncModbusTcpClient(venus_cfg.host, port=502)
        await client.connect()
        if not client.connected:
            return web.json_response(
                {"success": False, "error": "Cannot connect to Venus OS"}, status=502,
            )

        # Handle signed int16
        raw = int(value)
        if raw < 0:
            raw = raw + 65536

        result = await client.write_register(register, raw, device_id=100)
        client.close()

        if result.isError():
            return web.json_response(
                {"success": False, "error": f"Write failed: {result}"}, status=500,
            )

        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response(
            {"success": False, "error": str(e)}, status=500,
        )


def _mqtt_write_venus(host: str, port: int, portal_id: str, path: str, value) -> bool:
    """Write a dbus value to Venus OS via MQTT (for values Modbus can't set)."""
    import socket, struct, json as _json
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((host, port))
        # MQTT CONNECT
        cid = b"pv-proxy"
        payload = struct.pack("!H", 4) + b"MQTT" + bytes([4, 2, 0, 60])
        payload += struct.pack("!H", len(cid)) + cid
        s.send(bytes([0x10, len(payload)]) + payload)
        connack = s.recv(4)  # CONNACK
        if len(connack) < 4 or connack[3] != 0:
            s.close()
            return False
        # MQTT PUBLISH
        topic = f"W/{portal_id}/settings/0{path}".encode()
        msg = _json.dumps({"value": value}).encode()
        rem = 2 + len(topic) + len(msg)
        hdr = bytearray([0x30])
        while rem > 0:
            b = rem % 128
            rem //= 128
            if rem > 0:
                b |= 0x80
            hdr.append(b)
        s.send(bytes(hdr) + struct.pack("!H", len(topic)) + topic + msg)
        time.sleep(0.5)
        s.send(bytes([0xE0, 0x00]))  # DISCONNECT
        s.close()
        return True
    except Exception:
        return False


async def venus_dbus_handler(request: web.Request) -> web.Response:
    """Write a dbus value to Venus OS via MQTT (for values Modbus can't handle)."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    path = body.get("path")
    value = body.get("value")
    ALLOWED_PATHS = {
        "/Settings/CGwacs/MaxDischargePower",
        "/Settings/CGwacs/MaxFeedInPower",
        "/Settings/CGwacs/PreventFeedback",
        "/Settings/CGwacs/OvervoltageFeedIn",
    }
    if path not in ALLOWED_PATHS:
        return web.json_response({"success": False, "error": f"Path not allowed"}, status=400)

    venus_cfg = request.app["config"].venus
    if not venus_cfg.host or not venus_cfg.portal_id:
        return web.json_response(
            {"success": False, "error": "Venus OS MQTT not configured"}, status=503,
        )
    ok = _mqtt_write_venus(venus_cfg.host, venus_cfg.port, venus_cfg.portal_id, path, value)
    return web.json_response({"success": ok, "error": None if ok else "MQTT write failed"})


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

    log.info("user_action", action="venus_control", control_action=action)

    app_ctx = request.app["app_ctx"]
    control = app_ctx.control_state
    override_log = app_ctx.override_log

    if action == "lock":
        permanent = body.get("permanent", False)
        control.lock(duration_s=0 if permanent else 900.0)
        # Reset limit to 100% so inverter runs at full power while locked
        control.update_wmaxlimpct(100)
        control.update_wmaxlim_ena(0)
        control.last_source = "none"
        control.save_ui_state()
        if override_log is not None:
            override_log.append("webapp", "lock", None, "Venus OS writes blocked, limit reset to 100%")
    else:
        control.unlock()
        control.save_ui_state()
        if override_log is not None:
            override_log.append("webapp", "unlock", None, "Venus OS writes unblocked")

    return web.json_response({"success": True})


async def scanner_config_get_handler(request: web.Request) -> web.Response:
    """GET /api/scanner/config -- return scanner port configuration."""
    config: Config = request.app["config"]
    return web.json_response({"ports": config.scanner.ports})


async def scanner_config_save_handler(request: web.Request) -> web.Response:
    """PUT /api/scanner/config -- update scanner port configuration."""
    try:
        body = await request.json()
    except (ValueError, TypeError) as e:
        return web.json_response(
            {"success": False, "error": f"Invalid request: {e}"}, status=400,
        )

    ports = body.get("ports")
    if not isinstance(ports, list) or not ports:
        return web.json_response(
            {"success": False, "error": "ports must be a non-empty list of integers"},
            status=400,
        )
    for p in ports:
        if not isinstance(p, int) or not (1 <= p <= 65535):
            return web.json_response(
                {"success": False, "error": f"Invalid port: {p} (must be int 1-65535)"},
                status=400,
            )

    config: Config = request.app["config"]
    config.scanner.ports = ports
    save_config(request.app["config_path"], config)
    return web.json_response({"success": True})


async def scanner_discover_handler(request: web.Request) -> web.Response:
    """POST /api/scanner/discover -- trigger background subnet scan."""
    app = request.app
    if app.get("_scan_running"):
        return web.json_response({"error": "Scan already running"}, status=409)

    config: Config = app["config"]
    skip_ips = {inv.host for inv in config.inverters if inv.enabled}

    try:
        body = await request.json()
    except Exception:
        body = {}

    ports = body.get("ports", config.scanner.ports)
    scan_unit_ids = body.get("scan_unit_ids", [1])
    scan_config = ScanConfig(ports=ports, skip_ips=skip_ips, scan_unit_ids=scan_unit_ids)

    # Auto-add: default True if no inverters configured (first-run), else require explicit request
    has_inverters = len(config.inverters) > 0
    auto_add = body.get("auto_add", not has_inverters)

    log.info("user_action", action="scan_triggered", ports=ports, auto_add=auto_add)
    asyncio.create_task(_run_scan(app, scan_config, auto_add=auto_add))
    return web.json_response({"status": "started", "auto_add": auto_add})


async def mqtt_discover_handler(request: web.Request) -> web.Response:
    """POST /api/mqtt/discover -- scan LAN for MQTT brokers via mDNS."""
    try:
        brokers = await discover_mqtt_brokers(timeout=3.0)
        return web.json_response({"success": True, "brokers": brokers})
    except Exception as e:
        log.error("mdns_scan_failed", error=str(e))
        return web.json_response(
            {"success": False, "error": f"mDNS scan failed: {e}"},
            status=500,
        )


async def shelly_probe_handler(request: web.Request) -> web.Response:
    """POST /api/shelly/probe -- probe a Shelly device at given host."""
    try:
        body = await request.json()
        host = body["host"]
    except (KeyError, ValueError, TypeError) as e:
        return web.json_response({"error": f"Invalid request: {e}"}, status=400)
    result = await probe_shelly_device(host)
    return web.json_response(result)


async def shelly_discover_handler(request: web.Request) -> web.Response:
    """POST /api/shelly/discover -- scan LAN for Shelly devices via mDNS."""
    try:
        config: Config = request.app["config"]
        existing_ips = {inv.host for inv in config.inverters if inv.type == "shelly"}
        devices = await discover_shelly_devices(timeout=3.0, skip_ips=existing_ips)
        return web.json_response({"success": True, "devices": devices})
    except Exception as e:
        log.error("shelly_discover_failed", error=str(e))
        return web.json_response(
            {"success": False, "error": f"Shelly discovery failed: {e}"},
            status=500,
        )


async def sungrow_probe_handler(request: web.Request) -> web.Response:
    """POST /api/sungrow/probe -- probe a Sungrow inverter via Modbus TCP."""
    try:
        body = await request.json()
        host = body["host"]
        port = int(body.get("port", 502))
        unit_id = int(body.get("unit_id", 1))
    except (KeyError, ValueError, TypeError) as e:
        return web.json_response({"error": f"Invalid request: {e}"}, status=400)
    try:
        from pymodbus.client import AsyncModbusTcpClient
        client = AsyncModbusTcpClient(host, port=port)
        await client.connect()
        if not client.connected:
            return web.json_response({"success": False, "error": "Connection refused"})
        # Read device type register at wire address 5000 (doc 5001) — 2 registers
        resp = await client.read_input_registers(5000, count=2, slave=unit_id)
        model = "Sungrow Inverter"
        if not resp.isError() and hasattr(resp, "registers"):
            device_code = resp.registers[0]
            model = f"Sungrow (code {device_code:#06x})"
        client.close()
        return web.json_response({
            "success": True,
            "manufacturer": "Sungrow",
            "model": model,
            "host": host,
            "port": port,
            "unit_id": unit_id,
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)})


async def _reconfigure_active(app: web.Application, config: Config, device_id: str = "", action: str = "") -> None:
    """Reconfigure devices via DeviceRegistry.

    Args:
        app: The aiohttp Application.
        config: Current Config object.
        device_id: Specific device to act on (for targeted start/stop).
        action: "start", "stop", "disable" -- what to do with device_id.
    """
    app_ctx = app["app_ctx"]
    registry = app_ctx.device_registry
    app["reconfiguring"] = True
    try:
        if registry is None:
            # Fallback: no registry available (should not happen in normal operation)
            log.warning("no_device_registry", msg="DeviceRegistry not available for reconfigure")
            return

        if action == "start" and device_id:
            await registry.start_device(device_id)
            app_ctx.polling_paused = False
        elif action == "stop" and device_id:
            await registry.stop_device(device_id)
        elif action == "disable" and device_id:
            await registry.disable_device(device_id)
        else:
            # Generic reconfigure: check if any active inverter exists
            active = get_active_inverter(config)
            if not active:
                # Stop all devices
                await registry.stop_all()
                app_ctx.polling_paused = True
                # Broadcast no_inverter event to connected clients
                clients = app.get("ws_clients")
                if clients:
                    payload = json.dumps({"type": "no_inverter"})
                    for ws in set(clients):
                        try:
                            await ws.send_str(payload)
                        except (ConnectionError, RuntimeError, ConnectionResetError):
                            clients.discard(ws)
                log.warning("no_active_inverter", msg="All inverters disabled or removed")

        # Check if we have active devices
        if registry.get_active_count() == 0 and not get_active_inverter(config):
            app_ctx.polling_paused = True
        else:
            app_ctx.polling_paused = False

        # Broadcast updated device list after any CRUD change
        await broadcast_device_list(app)
    finally:
        app["reconfiguring"] = False


async def devices_list_handler(request: web.Request) -> web.Response:
    """Return list of all devices: inverters + venus + virtual pseudo-devices."""
    config: Config = request.app["config"]
    app_ctx = request.app["app_ctx"]
    devices = _build_device_list(app_ctx, config)
    return web.json_response({"devices": devices})


async def device_snapshot_handler(request: web.Request) -> web.Response:
    """Return per-device dashboard snapshot."""
    device_id = request.match_info["id"]
    config: Config = request.app["config"]
    app_ctx = request.app["app_ctx"]

    # Find the inverter entry
    entry = None
    for inv in config.inverters:
        if inv.id == device_id:
            entry = inv
            break
    if entry is None:
        return web.json_response({"error": "Device not found"}, status=404)

    ds = app_ctx.devices.get(device_id)
    display_name = entry.name or f"{entry.manufacturer} {entry.model}".strip() or "Inverter"

    # Always include connection info, even without snapshot data
    conn_info = {
        "state": ds.conn_mgr.state.value if ds and ds.conn_mgr else "unknown",
        "poll_success": ds.poll_counter["success"] if ds else 0,
        "poll_total": ds.poll_counter["total"] if ds else 0,
    }

    if ds is None or ds.collector is None or ds.collector.last_snapshot is None:
        return web.json_response({
            "error": "No data yet",
            "device_id": device_id,
            "device_type": entry.type,
            "display_name": display_name,
            "enabled": entry.enabled,
            "connection": conn_info,
            "inverter": {},
            "host": entry.host,
            "port": entry.port,
            "unit_id": entry.unit_id,
            "type": entry.type,
            "name": entry.name,
            "rated_power": entry.rated_power,
            "shelly_gen": entry.shelly_gen,
            "gateway_user": entry.gateway_user,
            "gateway_password": entry.gateway_password,
            "throttle_order": entry.throttle_order,
            "throttle_enabled": entry.throttle_enabled,
            "throttle_mode": c.mode if ds and ds.plugin and (c := get_throttle_caps(ds.plugin)) else "none",
            "throttle_score": compute_throttle_score(c) if ds and ds.plugin and (c := get_throttle_caps(ds.plugin)) else 0.0,
        })

    snapshot = dict(ds.collector.last_snapshot)
    snapshot["device_id"] = device_id
    snapshot["device_type"] = entry.type
    snapshot["display_name"] = display_name
    snapshot["enabled"] = entry.enabled
    snapshot["connection"] = conn_info
    # Include config fields needed by the config page
    snapshot["host"] = entry.host
    snapshot["port"] = entry.port
    snapshot["unit_id"] = entry.unit_id
    snapshot["type"] = entry.type
    snapshot["name"] = entry.name
    snapshot["rated_power"] = entry.rated_power
    snapshot["shelly_gen"] = entry.shelly_gen
    snapshot["gateway_user"] = entry.gateway_user
    snapshot["gateway_password"] = entry.gateway_password
    snapshot["throttle_order"] = entry.throttle_order
    snapshot["throttle_enabled"] = entry.throttle_enabled
    caps = get_throttle_caps(ds.plugin if ds else None)
    snapshot["throttle_mode"] = caps.mode if caps else "none"
    snapshot["throttle_score"] = compute_throttle_score(caps) if caps else 0.0
    return web.json_response(snapshot)


async def virtual_snapshot_handler(request: web.Request) -> web.Response:
    """Return aggregated virtual inverter snapshot with per-device contributions."""
    config: Config = request.app["config"]
    app_ctx = request.app["app_ctx"]

    total_power_w, total_rated_w, contributions = _build_virtual_contributions(app_ctx, config)

    # Include control limits from the virtual clamp stored in ControlState.
    # (VirtualInverterConfig only carries the display name — the actual clamp
    # lives in control_state.device_clamps["virtual"], populated by
    # /api/power-clamp.)
    cmin, cmax = app_ctx.control_state.get_device_clamp("virtual")
    control = {
        "clamp_min_pct": cmin,
        "clamp_max_pct": cmax,
    }

    return web.json_response({
        "total_power_w": total_power_w,
        "total_rated_w": total_rated_w,
        "rated_power_w": total_rated_w,
        "virtual_name": config.virtual_inverter.name,
        "contributions": contributions,
        "control": control,
    })


async def inverters_list_handler(request: web.Request) -> web.Response:
    """Return all inverter entries with active flag."""
    config: Config = request.app["config"]
    active = get_active_inverter(config)
    items = []
    for inv in config.inverters:
        d = dataclasses.asdict(inv)
        d["active"] = (active is not None and inv.id == active.id)
        items.append(d)
    return web.json_response({"inverters": items})


async def inverters_add_handler(request: web.Request) -> web.Response:
    """Add a new inverter entry."""
    try:
        body = await request.json()
        host = body["host"]
        port = body.get("port", 1502)
        unit_id = body.get("unit_id", 1)
    except (KeyError, ValueError, TypeError) as e:
        return web.json_response({"error": f"Invalid request: {e}"}, status=400)

    error = validate_inverter_config(host, port, unit_id)
    if error:
        return web.json_response({"error": error}, status=400)

    dev_type = body.get("type", "solaredge")
    entry = InverterEntry(
        host=host, port=port, unit_id=unit_id,
        enabled=body.get("enabled", True),
        manufacturer=body.get("manufacturer", ""),
        model=body.get("model", ""),
        serial=body.get("serial", ""),
        firmware_version=body.get("firmware_version", ""),
        name=body.get("name", ""),
        type=dev_type,
        gateway_host=body.get("gateway_host", host if dev_type == "opendtu" else ""),
        gateway_user=body.get("gateway_user", ""),
        gateway_password=body.get("gateway_password", ""),
        shelly_gen=body.get("shelly_gen", ""),
        rated_power=body.get("rated_power", 0),
        panel_power_wp=body.get("panel_power_wp", 0),
        throttle_enabled=body.get("throttle_enabled", dev_type not in ("shelly", "sungrow")),
        aggregate=body.get("aggregate", True),
    )
    config: Config = request.app["config"]
    config.inverters.append(entry)
    save_config(request.app["config_path"], config)
    log.info("user_action", action="inverter_added", device_id=entry.id, host=host, port=port, unit_id=unit_id, name=entry.name, type=entry.type)

    # Start device immediately if enabled (per locked decision)
    if entry.enabled:
        await _reconfigure_active(request.app, config, device_id=entry.id, action="start")

    d = dataclasses.asdict(entry)
    active = get_active_inverter(config)
    d["active"] = (active is not None and entry.id == active.id)
    return web.json_response(d, status=201)


async def inverters_update_handler(request: web.Request) -> web.Response:
    """Update an existing inverter entry by id."""
    inv_id = request.match_info["id"]
    config: Config = request.app["config"]
    entry = None
    for inv in config.inverters:
        if inv.id == inv_id:
            entry = inv
            break
    if entry is None:
        return web.json_response({"error": "Inverter not found"}, status=404)

    try:
        body = await request.json()
    except (ValueError, TypeError) as e:
        return web.json_response({"error": f"Invalid request: {e}"}, status=400)

    was_enabled = entry.enabled
    for field_name in ("host", "port", "unit_id", "enabled", "manufacturer", "model", "serial", "firmware_version", "rated_power", "panel_power_wp", "name", "gateway_host", "gateway_user", "gateway_password", "throttle_order", "throttle_enabled", "aggregate"):
        if field_name in body:
            setattr(entry, field_name, body[field_name])

    error = validate_inverter_config(entry.host, entry.port, entry.unit_id)
    if error:
        return web.json_response({"error": error}, status=400)

    # Determine what changed for logging
    changes = {k: body[k] for k in body if k in ("host", "port", "unit_id", "enabled", "name", "rated_power", "throttle_order", "throttle_enabled", "aggregate")}
    if was_enabled and not entry.enabled:
        log.info("user_action", action="inverter_disabled", device_id=inv_id, name=entry.name or entry.model)
    elif not was_enabled and entry.enabled:
        log.info("user_action", action="inverter_enabled", device_id=inv_id, name=entry.name or entry.model)
    else:
        log.info("user_action", action="inverter_updated", device_id=inv_id, changes=changes)

    save_config(request.app["config_path"], config)

    # Handle enable/disable transitions via DeviceRegistry
    if was_enabled and not entry.enabled:
        await _reconfigure_active(request.app, config, device_id=inv_id, action="disable")
    elif not was_enabled and entry.enabled:
        await _reconfigure_active(request.app, config, device_id=inv_id, action="start")
    elif was_enabled and entry.enabled:
        # Config changed (host/port/unit_id) -- restart device
        await _reconfigure_active(request.app, config, device_id=inv_id, action="stop")
        await _reconfigure_active(request.app, config, device_id=inv_id, action="start")

    d = dataclasses.asdict(entry)
    active = get_active_inverter(config)
    d["active"] = (active is not None and entry.id == active.id)
    return web.json_response(d)


async def inverters_delete_handler(request: web.Request) -> web.Response:
    """Delete an inverter entry by id."""
    inv_id = request.match_info["id"]
    config: Config = request.app["config"]

    original_len = len(config.inverters)
    config.inverters = [inv for inv in config.inverters if inv.id != inv_id]
    if len(config.inverters) == original_len:
        return web.json_response({"error": "Inverter not found"}, status=404)

    save_config(request.app["config_path"], config)
    log.info("user_action", action="inverter_deleted", device_id=inv_id)

    # Stop the device via DeviceRegistry
    await _reconfigure_active(request.app, config, device_id=inv_id, action="stop")

    return web.json_response({"success": True})


async def config_export_handler(request: web.Request) -> web.Response:
    """Export current config as YAML file download."""
    config_path = request.app["config_path"]
    try:
        with open(config_path) as f:
            yaml_content = f.read()
    except FileNotFoundError:
        return web.json_response({"error": "Config file not found"}, status=404)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_pv-inverter-proxy.yaml"
    return web.Response(
        body=yaml_content,
        content_type="application/x-yaml",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


async def config_import_handler(request: web.Request) -> web.Response:
    """Import config from uploaded YAML file. Validates, saves, restarts."""
    try:
        data = await request.read()
        yaml_text = data.decode("utf-8")
        parsed = yaml.safe_load(yaml_text)
        if not isinstance(parsed, dict):
            return web.json_response({"success": False, "error": "Invalid YAML structure"}, status=400)
    except Exception as e:
        return web.json_response({"success": False, "error": f"YAML parse error: {e}"}, status=400)

    # Write to config file
    config_path = request.app["config_path"]
    try:
        dir_name = os.path.dirname(config_path)
        fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".yaml")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(yaml_text)
            os.replace(tmp, config_path)
        except Exception:
            os.unlink(tmp)
            raise
    except Exception as e:
        return web.json_response({"success": False, "error": f"Write failed: {e}"}, status=500)

    # Reload config
    try:
        from pv_inverter_proxy.config import load_config
        new_config = load_config(config_path)
        request.app["config"] = new_config
        app_ctx = request.app["app_ctx"]
        app_ctx.config = new_config
        log.info("user_action", action="config_imported")
    except Exception as e:
        return web.json_response({"success": False, "error": f"Reload failed: {e}"}, status=500)

    return web.json_response({"success": True, "message": "Config imported. Restart recommended."})


async def opendtu_status_handler(request: web.Request) -> web.Response:
    """Get OpenDTU inverter status (producing, reachable, limits)."""
    device_id = request.match_info["id"]
    app_ctx = request.app["app_ctx"]
    ds = app_ctx.devices.get(device_id)
    if not ds or not ds.plugin:
        return web.json_response({"error": "Device not found"}, status=404)

    if not isinstance(ds.plugin, OpenDTUPlugin):
        return web.json_response({"error": "Not an OpenDTU device"}, status=400)

    status = await ds.plugin.get_inverter_status()
    return web.json_response(status)


async def opendtu_power_handler(request: web.Request) -> web.Response:
    """Send power on/off/restart to an OpenDTU inverter.

    Body: {"action": "on"|"off"|"restart"}
    """
    device_id = request.match_info["id"]
    app_ctx = request.app["app_ctx"]
    ds = app_ctx.devices.get(device_id)
    if not ds or not ds.plugin:
        return web.json_response({"success": False, "error": "Device not found"}, status=404)

    if not isinstance(ds.plugin, OpenDTUPlugin):
        return web.json_response({"success": False, "error": "Not an OpenDTU device"}, status=400)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    action = body.get("action", "")
    if action not in ("on", "off", "restart"):
        return web.json_response({"success": False, "error": "action must be on/off/restart"}, status=400)

    result = await ds.plugin.send_power_command(action)
    log.info("user_action", action=f"opendtu_power_{action}", device_id=device_id)
    return web.json_response({"success": result.success, "error": result.error})


async def shelly_switch_handler(request: web.Request) -> web.Response:
    """Send on/off command to a Shelly device relay.

    Body: {"on": true|false}
    """
    device_id = request.match_info["id"]
    app_ctx = request.app["app_ctx"]
    ds = app_ctx.devices.get(device_id)
    if not ds or not ds.plugin:
        return web.json_response({"success": False, "error": "Device not found"}, status=404)

    if not isinstance(ds.plugin, ShellyPlugin):
        return web.json_response({"success": False, "error": "Not a Shelly device"}, status=400)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    on = body.get("on")
    if on is None or not isinstance(on, bool):
        return web.json_response({"success": False, "error": "'on' must be true or false"}, status=400)

    success = await ds.plugin.switch(on)
    log.info("user_action", action=f"shelly_switch_{'on' if on else 'off'}", device_id=device_id)
    return web.json_response({"success": success})


async def opendtu_test_auth_handler(request: web.Request) -> web.Response:
    """Test OpenDTU gateway connectivity and auth.

    Body: {"host": "192.168.1.100", "user": "admin", "password": "openDTU42"}
    Returns: {"success": true/false, "error": "...", "inverters": [...]}
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Invalid JSON"}, status=400)

    host = body.get("host", "")
    user = body.get("user", "admin")
    password = body.get("password", "openDTU42")

    if not host:
        return web.json_response({"success": False, "error": "Host required"}, status=400)

    try:
        auth = aiohttp.BasicAuth(user, password)
        async with aiohttp.ClientSession(auth=auth) as session:
            async with session.get(f"http://{host}/api/livedata/status", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 401:
                    return web.json_response({"success": False, "error": "Authentication failed — check username/password"})
                data = await resp.json()
                inverters = []
                for inv in data.get("inverters", []):
                    inverters.append({
                        "serial": inv.get("serial", ""),
                        "name": inv.get("name", ""),
                        "producing": inv.get("producing", False),
                    })
                return web.json_response({"success": True, "inverters": inverters})
    except Exception as e:
        return web.json_response({"success": False, "error": f"Connection failed: {e}"})


async def create_webapp(
    app_ctx: object,
    config: Config,
    config_path: str,
) -> web.AppRunner:
    """Create and set up the aiohttp webapp.

    Returns an AppRunner (caller manages site creation and lifecycle).
    """
    # Phase 46 D-07..D-09, D-41: csrf_middleware MUST be first so it runs
    # before any body parsing and can reject CSRF violations with an audit
    # trail regardless of the downstream handler's guard pipeline.
    app = web.Application(middlewares=[csrf_middleware])
    app["app_ctx"] = app_ctx
    app["config"] = config
    app["config_path"] = config_path
    app["start_time"] = time.monotonic()
    app["reconfiguring"] = False
    app["_scan_running"] = False
    app["ws_clients"] = weakref.WeakSet()

    # Phase 46 D-22/D-23: start the update-status.json poll + WS broadcaster
    # on startup and stop it on cleanup. Stores the singleton under
    # app["progress_broadcaster"].
    app.on_startup.append(start_broadcaster)
    app.on_cleanup.append(stop_broadcaster)

    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/status", status_handler)
    app.router.add_get("/api/health", health_handler)
    # Phase 44: Passive Version Badge (CHECK-05)
    app.router.add_get("/api/update/available", update_available_handler)
    # Phase 45-02: EXEC-01, EXEC-02 — update trigger producer
    app.router.add_post("/api/update/start", update_start_handler)
    # Phase 46 Plan 04 (D-27, D-41): new update routes
    app.router.add_get("/api/version", version_handler)
    app.router.add_get("/api/update/status", update_status_handler)
    app.router.add_post("/api/update/rollback", update_rollback_handler)
    app.router.add_post("/api/update/check", update_check_handler)
    # Phase 46 Plan 05 (CFG-02 / D-04 / D-06): update-config GET+PATCH.
    app.router.add_get("/api/update/config", update_config_get_handler)
    app.router.add_patch("/api/update/config", update_config_patch_handler)
    app.router.add_get("/api/config", config_get_handler)
    app.router.add_post("/api/config", config_save_handler)
    app.router.add_post("/api/config/test", config_test_handler)
    app.router.add_get("/api/registers", registers_handler)
    app.router.add_get("/api/dashboard", dashboard_handler)
    app.router.add_post("/api/power-limit", power_limit_handler)
    app.router.add_post("/api/power-clamp", power_clamp_handler)
    app.router.add_post("/api/venus-write", venus_write_handler)
    app.router.add_post("/api/venus-dbus", venus_dbus_handler)
    app.router.add_post("/api/venus-lock", venus_lock_handler)
    app.router.add_get("/api/scanner/config", scanner_config_get_handler)
    app.router.add_put("/api/scanner/config", scanner_config_save_handler)
    app.router.add_post("/api/scanner/discover", scanner_discover_handler)
    app.router.add_post("/api/mqtt/discover", mqtt_discover_handler)
    app.router.add_post("/api/shelly/probe", shelly_probe_handler)
    app.router.add_post("/api/shelly/discover", shelly_discover_handler)
    app.router.add_post("/api/sungrow/probe", sungrow_probe_handler)
    app.router.add_post("/api/opendtu/test-auth", opendtu_test_auth_handler)
    app.router.add_get("/api/devices/{id}/opendtu/status", opendtu_status_handler)
    app.router.add_post("/api/devices/{id}/opendtu/power", opendtu_power_handler)
    app.router.add_post("/api/devices/{id}/shelly/switch", shelly_switch_handler)
    app.router.add_get("/api/inverters", inverters_list_handler)
    app.router.add_post("/api/inverters", inverters_add_handler)
    app.router.add_put("/api/inverters/{id}", inverters_update_handler)
    app.router.add_delete("/api/inverters/{id}", inverters_delete_handler)
    # Device-centric GET endpoints (Phase 24)
    app.router.add_get("/api/devices", devices_list_handler)
    app.router.add_get("/api/devices/virtual/snapshot", virtual_snapshot_handler)
    app.router.add_get("/api/devices/{id}/snapshot", device_snapshot_handler)
    app.router.add_get("/api/devices/{id}/registers", device_registers_handler)
    # CRUD aliases at /api/devices (frontend uses these, /api/inverters kept for backward compat)
    app.router.add_post("/api/devices", inverters_add_handler)
    app.router.add_put("/api/devices/{id}", inverters_update_handler)
    app.router.add_delete("/api/devices/{id}", inverters_delete_handler)
    app.router.add_get("/api/config/export", config_export_handler)
    app.router.add_post("/api/config/import", config_import_handler)
    app.router.add_get("/static/{filename}", static_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    return runner
