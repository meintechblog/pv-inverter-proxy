"""Entry point for venus-os-fronius-proxy service.

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

import structlog
from aiohttp import web

from venus_os_fronius_proxy.aggregation import AggregationLayer
from venus_os_fronius_proxy.config import load_config, DEFAULT_CONFIG_PATH
from venus_os_fronius_proxy.context import AppContext
from venus_os_fronius_proxy.device_registry import DeviceRegistry
from venus_os_fronius_proxy.logging_config import configure_logging
from venus_os_fronius_proxy.proxy import run_modbus_server
from venus_os_fronius_proxy.webapp import create_webapp


HEARTBEAT_INTERVAL = 300  # 5 minutes


def main():
    parser = argparse.ArgumentParser(description="Venus OS Fronius Proxy")
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to config YAML (default: /etc/venus-os-fronius-proxy/config.yaml)",
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
        cache, control_state, server, server_task = await run_modbus_server(
            host=config.proxy.host,
            port=config.proxy.port,
            app_ctx=app_ctx,
        )

        # Create AggregationLayer
        aggregation = AggregationLayer(app_ctx, cache, config)

        # Create DeviceRegistry with aggregation callback
        registry = DeviceRegistry(app_ctx, config, on_poll_success=aggregation.recalculate)
        app_ctx.device_registry = registry

        # Start all enabled devices
        await registry.start_all()

        if registry.get_active_count() == 0:
            log.warning("no_active_inverter", msg="No enabled inverter -- Modbus server will return stale errors")
            # Keep server running but it will return stale errors via StalenessAwareSlaveContext
            # This preserves Venus OS device discovery (per Pitfall 4 from research)

        # Start webapp (pass None for plugin -- multi-device mode)
        runner = await create_webapp(app_ctx, config, app_ctx.config_path, plugin=None)
        app_ctx.webapp = runner.app
        site = web.TCPSite(runner, "0.0.0.0", config.webapp.port)
        await site.start()
        log.info("webapp_started", port=config.webapp.port)

        # Start Venus OS MQTT reader only if host is configured
        if config.venus.host:
            from venus_os_fronius_proxy.venus_reader import venus_mqtt_loop
            venus_task = asyncio.create_task(
                venus_mqtt_loop(app_ctx, config.venus.host, config.venus.port, config.venus.portal_id)
            )
            app_ctx.venus_task = venus_task
        else:
            log.info("venus_mqtt_skipped", reason="no venus.host in config")
            app_ctx.venus_mqtt_connected = False

        # Start health heartbeat task
        heartbeat_task = asyncio.create_task(_health_heartbeat(app_ctx))

        # Wait for shutdown signal
        await app_ctx.shutdown_event.wait()

        log.info("graceful_shutdown_starting")

        # Cancel heartbeat
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

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
