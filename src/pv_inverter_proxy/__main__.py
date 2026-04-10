"""Entry point for pv-inverter-proxy service.

Loads YAML config, configures structured JSON logging, handles SIGTERM
for graceful shutdown. Uses DeviceRegistry for N poll loops and
AggregationLayer for SunSpec aggregation into a single virtual inverter.
Runs a health heartbeat every 5 minutes.
"""
from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import time
from pathlib import Path

import structlog
from aiohttp import web

from pv_inverter_proxy.aggregation import AggregationLayer
from pv_inverter_proxy.config import load_config, DEFAULT_CONFIG_PATH
from pv_inverter_proxy.context import AppContext
from pv_inverter_proxy.device_registry import DeviceRegistry
from pv_inverter_proxy.distributor import PowerLimitDistributor
from pv_inverter_proxy.logging_config import configure_logging
from pv_inverter_proxy.proxy import run_modbus_server
from pv_inverter_proxy.mqtt_publisher import mqtt_publish_loop
from pv_inverter_proxy.webapp import create_webapp


HEARTBEAT_INTERVAL = 300  # 5 minutes

HEALTHY_FLAG_PATH = Path("/run/pv-inverter-proxy/healthy")
LAST_BOOT_SUCCESS_MARKER_PATH = Path("/var/lib/pv-inverter-proxy/last-boot-success.marker")


def _write_healthy_flag_once(app_ctx, logger) -> None:
    """Write /run/pv-inverter-proxy/healthy and last-boot-success marker.

    Best-effort. Errors logged but never raised (we don't want to crash the
    service over a sentinel file). SAFETY-06 + SAFETY-04 companion write.

    Order of operations:
    1. Write the tmpfs /run/pv-inverter-proxy/healthy sentinel.
    2. Set app_ctx.healthy_flag_written so this function becomes a no-op.
    3. Write the persistent /var/lib/pv-inverter-proxy/last-boot-success.marker.
    4. Clear any stale PENDING marker (we succeeded post-update).

    Steps 3/4 are best-effort and do not gate step 1/2: if the tmpfs write
    succeeds but the persistent write fails, we still consider "this boot"
    healthy. The stale PENDING marker (if any) will just stick around
    harmlessly until the next successful persistent write.
    """
    if app_ctx.healthy_flag_written:
        return
    try:
        HEALTHY_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEALTHY_FLAG_PATH.touch(exist_ok=True)
        app_ctx.healthy_flag_written = True
        logger.info("healthy_flag_written", path=str(HEALTHY_FLAG_PATH))
    except OSError as e:
        logger.warning(
            "healthy_flag_write_failed",
            path=str(HEALTHY_FLAG_PATH),
            error=str(e),
        )
        return
    # Persistent last-boot-success + clear stale PENDING marker
    try:
        LAST_BOOT_SUCCESS_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAST_BOOT_SUCCESS_MARKER_PATH.touch(exist_ok=True)
        logger.info(
            "last_boot_success_marker_written",
            path=str(LAST_BOOT_SUCCESS_MARKER_PATH),
        )
        from pv_inverter_proxy.recovery import clear_pending_marker
        clear_pending_marker()
    except OSError as e:
        logger.warning("last_boot_success_write_failed", error=str(e))
    except Exception as e:  # pragma: no cover - belt and braces
        logger.warning("last_boot_success_unexpected_error", error=str(e))


def main():
    parser = argparse.ArgumentParser(description="PV-Inverter-Proxy")
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to config YAML (default: /etc/pv-inverter-proxy/config.yaml)",
    )
    args = parser.parse_args()

    # Load config
    config = load_config(args.config)

    # Configure structured JSON logging
    configure_logging(config.log_level)
    log = structlog.get_logger(component="main")

    enabled_count = sum(1 for inv in config.inverters if inv.enabled)
    log.info(
        "starting",
        enabled_inverters=enabled_count,
        total_inverters=len(config.inverters),
        proxy_port=config.proxy.port,
        venus_host=config.venus.host or "(disabled)",
        log_level=config.log_level,
    )

    # SAFETY-09: load persisted power-limit / night-mode state and log it.
    # The actual boot-time restoration (re-issuing the Modbus write to SE30K)
    # is deferred to Phase 45 where the full restart-safety flow lives. For
    # Phase 43 we deliver the persistence infrastructure + a boot-time observable
    # so Phase 45 can confirm the state file is being read correctly.
    try:
        from pv_inverter_proxy.state_file import load_state, is_power_limit_fresh
        persisted = load_state()
        if persisted.power_limit_pct is not None:
            # 900s is a placeholder for the SE30K CommandTimeout register.
            # Phase 45 will read the real value from register 0xF100 at startup.
            fresh = is_power_limit_fresh(persisted, command_timeout_s=900.0)
            log.info(
                "persisted_state_loaded",
                power_limit_pct=persisted.power_limit_pct,
                power_limit_set_at=persisted.power_limit_set_at,
                night_mode_active=persisted.night_mode_active,
                fresh_within_timeout_half=fresh,
                note="restoration wiring deferred to Phase 45",
            )
        else:
            log.info("persisted_state_empty")
    except Exception as e:
        log.warning("persisted_state_load_failed", error=str(e))

    # Build typed application context
    app_ctx = AppContext()
    app_ctx.config = config
    app_ctx.config_path = args.config or DEFAULT_CONFIG_PATH

    async def _health_heartbeat(ctx: AppContext):
        """Log health heartbeat every 5 minutes (per locked CONTEXT.md decision).

        Emits: poll_success_rate, cache_age, last_control_value, connection_state.
        Uses aggregated stats from all devices.
        """
        hb_log = structlog.get_logger(component="health")
        while not ctx.shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    ctx.shutdown_event.wait(), timeout=HEARTBEAT_INTERVAL
                )
                break  # shutdown requested
            except asyncio.TimeoutError:
                pass  # 5 minutes elapsed, emit heartbeat

            cache = ctx.cache
            control_state = ctx.control_state

            # Aggregate poll stats from all devices
            poll_total = sum(ds.poll_counter["total"] for ds in ctx.devices.values())
            poll_success = sum(ds.poll_counter["success"] for ds in ctx.devices.values())

            cache_age = time.monotonic() - cache.last_successful_poll if cache._has_been_updated else -1
            success_rate = (
                poll_success / poll_total * 100
                if poll_total > 0
                else 0.0
            )

            # Connection state: "connected" if any device connected
            conn_states = []
            for ds in ctx.devices.values():
                if ds.conn_mgr is not None:
                    conn_states.append(ds.conn_mgr.state.value)
            connection_state = "connected" if "connected" in conn_states else (
                conn_states[0] if conn_states else "no_devices"
            )

            hb_log.info(
                "health_heartbeat",
                poll_success_rate=round(success_rate, 1),
                poll_total=poll_total,
                cache_age=round(cache_age, 1),
                cache_stale=cache.is_stale,
                connection_state=connection_state,
                device_count=len(ctx.devices),
                last_control_value=control_state.wmaxlimpct_float if control_state.is_enabled else None,
                control_enabled=control_state.is_enabled,
            )

    async def run_with_shutdown():
        loop = asyncio.get_running_loop()

        def handle_signal(sig):
            log.info("shutdown_signal_received", signal=sig.name)
            app_ctx.shutdown_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, handle_signal, sig)

        # Create Modbus server infrastructure (no plugin needed)
        cache, control_state, server, server_task, slave_ctx = await run_modbus_server(
            host=config.proxy.host,
            port=config.proxy.port,
            app_ctx=app_ctx,
        )

        # Create AggregationLayer
        aggregation = AggregationLayer(app_ctx, cache, config)

        # Create DeviceRegistry with aggregation callback
        registry = DeviceRegistry(app_ctx, config, on_poll_success=aggregation.recalculate)
        app_ctx.device_registry = registry

        # Create PowerLimitDistributor for multi-device power limiting
        distributor = PowerLimitDistributor(registry, config)
        slave_ctx._distributor = distributor
        app_ctx.distributor = distributor
        registry._distributor = distributor
        log.info("distributor_created", msg="PowerLimitDistributor ready for multi-device power limiting")

        # Start all enabled devices
        await registry.start_all()

        if registry.get_active_count() == 0:
            log.warning("no_active_inverter", msg="No enabled inverter -- Modbus server will return stale errors")
            # Keep server running but it will return stale errors via StalenessAwareSlaveContext
            # This preserves Venus OS device discovery (per Pitfall 4 from research)

        # Start webapp (pass None for plugin -- multi-device mode)
        runner = await create_webapp(app_ctx, config, app_ctx.config_path)
        app_ctx.webapp = runner.app
        runner.app["slave_ctx"] = slave_ctx  # For Virtual PV connection status
        site = web.TCPSite(runner, "0.0.0.0", config.webapp.port)
        await site.start()
        log.info("webapp_started", port=config.webapp.port)

        # Wire broadcast callback into aggregation layer (Phase 24)
        from pv_inverter_proxy.webapp import broadcast_device_snapshot, broadcast_virtual_snapshot

        async def _on_aggregation_broadcast(device_id: str) -> None:
            app = app_ctx.webapp
            ds = app_ctx.devices.get(device_id)
            if ds and ds.collector and ds.collector.last_snapshot:
                await broadcast_device_snapshot(app, device_id, ds.collector.last_snapshot)
            await broadcast_virtual_snapshot(app)

        aggregation._broadcast_fn = _on_aggregation_broadcast

        # Start MQTT publisher if enabled (per D-11)
        if config.mqtt_publish.enabled:
            app_ctx.mqtt_pub_queue = asyncio.Queue(maxsize=100)
            app_ctx.mqtt_pub_task = asyncio.create_task(
                mqtt_publish_loop(
                    app_ctx, config.mqtt_publish,
                    inverters=config.inverters,
                    virtual_name=config.virtual_inverter.name,
                )
            )
            log.info("mqtt_publisher_started", host=config.mqtt_publish.host, port=config.mqtt_publish.port)
        else:
            log.info("mqtt_publish_skipped", reason="mqtt_publish.enabled is false")

        # Start Venus OS MQTT reader only if host is configured
        if config.venus.host:
            from pv_inverter_proxy.venus_reader import venus_mqtt_loop
            venus_task = asyncio.create_task(
                venus_mqtt_loop(app_ctx, config.venus.host, config.venus.port, config.venus.portal_id)
            )
            app_ctx.venus_task = venus_task
        else:
            log.info("venus_mqtt_skipped", reason="no venus.host in config")
            app_ctx.venus_mqtt_connected = False

        # Periodic device list broadcast (keeps sidebar + MQTT stats live)
        from pv_inverter_proxy.webapp import broadcast_device_list

        async def _device_list_refresh(ctx: AppContext):
            while not ctx.shutdown_event.is_set():
                try:
                    await asyncio.wait_for(ctx.shutdown_event.wait(), timeout=5.0)
                    break
                except asyncio.TimeoutError:
                    pass
                app = ctx.webapp
                if app is not None:
                    await broadcast_device_list(app)

        device_list_task = asyncio.create_task(_device_list_refresh(app_ctx))

        async def _healthy_flag_watcher(ctx: AppContext):
            """Write /run/pv-inverter-proxy/healthy on first successful poll.

            Polls every 500ms for the first device to register a successful poll,
            then writes the healthy flag (and the persistent last-boot-success
            marker) exactly once, and exits. If shutdown fires before any poll
            succeeds, the task exits without writing anything.
            """
            watcher_log = structlog.get_logger(component="healthy_flag")
            while not ctx.shutdown_event.is_set():
                try:
                    await asyncio.wait_for(ctx.shutdown_event.wait(), timeout=0.5)
                    return  # shutdown before first healthy poll
                except asyncio.TimeoutError:
                    pass
                if any(
                    ds.poll_counter["success"] > 0 for ds in ctx.devices.values()
                ):
                    _write_healthy_flag_once(ctx, watcher_log)
                    return

        healthy_flag_task = asyncio.create_task(_healthy_flag_watcher(app_ctx))

        # Start health heartbeat task
        heartbeat_task = asyncio.create_task(_health_heartbeat(app_ctx))

        # Wait for shutdown signal
        await app_ctx.shutdown_event.wait()

        log.info("graceful_shutdown_starting")

        # Cancel periodic tasks
        for task in (heartbeat_task, device_list_task, healthy_flag_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Stop MQTT publisher
        if app_ctx.mqtt_pub_task is not None:
            app_ctx.mqtt_pub_task.cancel()
            try:
                await app_ctx.mqtt_pub_task
            except asyncio.CancelledError:
                pass
            log.info("mqtt_publisher_stopped")

        # Stop webapp
        if runner is not None:
            await runner.cleanup()
            log.info("webapp_stopped")

        # Stop all device poll loops
        await registry.stop_all()
        log.info("devices_stopped")

        # Cancel Modbus server
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

        log.info("shutdown_complete")

    try:
        asyncio.run(run_with_shutdown())
    except KeyboardInterrupt:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
