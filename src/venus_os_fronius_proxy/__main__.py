"""Entry point for venus-os-fronius-proxy service.

Loads YAML config, configures structured JSON logging, handles SIGTERM
for graceful shutdown (reset power limit to 100% before stopping).
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

from venus_os_fronius_proxy.config import load_config, get_active_inverter, DEFAULT_CONFIG_PATH
from venus_os_fronius_proxy.logging_config import configure_logging
from venus_os_fronius_proxy.plugins.solaredge import SolarEdgePlugin
from venus_os_fronius_proxy.proxy import run_proxy
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

    active_inv = get_active_inverter(config)
    if active_inv is None:
        log.warning("no_active_inverter", msg="No enabled inverter in config -- proxy will not poll")

    log.info(
        "starting",
        inverter_host=active_inv.host if active_inv else "(none)",
        inverter_port=active_inv.port if active_inv else 0,
        proxy_port=config.proxy.port,
        venus_host=config.venus.host or "(disabled)",
        log_level=config.log_level,
    )

    # Create plugin from config
    plugin = SolarEdgePlugin(
        host=active_inv.host if active_inv else "0.0.0.0",
        port=active_inv.port if active_inv else 502,
        unit_id=active_inv.unit_id if active_inv else 1,
    )

    # Graceful shutdown handling
    shutdown_event = asyncio.Event()

    async def _health_heartbeat(
        cache,
        conn_mgr,
        control_state,
        poll_counter,
    ):
        """Log health heartbeat every 5 minutes (per locked CONTEXT.md decision).

        Emits: poll_success_rate, cache_age, last_control_value, connection_state.
        """
        hb_log = structlog.get_logger(component="health")
        while not shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    shutdown_event.wait(), timeout=HEARTBEAT_INTERVAL
                )
                break  # shutdown requested
            except asyncio.TimeoutError:
                pass  # 5 minutes elapsed, emit heartbeat

            cache_age = time.monotonic() - cache.last_successful_poll if cache._has_been_updated else -1
            success_rate = (
                poll_counter["success"] / poll_counter["total"] * 100
                if poll_counter["total"] > 0
                else 0.0
            )
            hb_log.info(
                "health_heartbeat",
                poll_success_rate=round(success_rate, 1),
                poll_total=poll_counter["total"],
                cache_age=round(cache_age, 1),
                cache_stale=cache.is_stale,
                connection_state=conn_mgr.state.value,
                last_control_value=control_state.wmaxlimpct_float if control_state.is_enabled else None,
                control_enabled=control_state.is_enabled,
            )

    async def run_with_shutdown():
        loop = asyncio.get_running_loop()

        def handle_signal(sig):
            log.info("shutdown_signal_received", signal=sig.name)
            shutdown_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, handle_signal, sig)

        # Start proxy in background task with shared context for heartbeat
        shared_ctx: dict = {}

        from venus_os_fronius_proxy.dashboard import DashboardCollector
        shared_ctx["dashboard_collector"] = DashboardCollector()

        proxy_task = asyncio.create_task(
            run_proxy(
                plugin,
                host=config.proxy.host,
                port=config.proxy.port,
                poll_interval=config.proxy.poll_interval,
                shared_ctx=shared_ctx,
            )
        )

        # Wait briefly for run_proxy to populate shared_ctx with cache, conn_mgr, etc.
        for _ in range(100):  # up to 1s
            if "cache" in shared_ctx:
                break
            await asyncio.sleep(0.01)

        # Restore last Venus OS limit after restart (if recent)
        if "control_state" in shared_ctx:
            cs = shared_ctx["control_state"]
            if cs.is_enabled and cs.last_source == "venus_os":
                try:
                    await plugin.write_power_limit(True, cs.wmaxlimpct_float)
                    log.info("restored_venus_limit", limit_pct=cs.wmaxlimpct_float)
                except Exception:
                    pass

        # Start webapp alongside proxy
        runner = None
        if shared_ctx:
            config_path = args.config or DEFAULT_CONFIG_PATH
            runner = await create_webapp(shared_ctx, config, config_path, plugin)
            shared_ctx["webapp"] = runner.app
            site = web.TCPSite(runner, "0.0.0.0", config.webapp.port)
            await site.start()
            log.info("webapp_started", port=config.webapp.port)

        # Start Venus OS MQTT reader only if host is configured
        venus_task = None
        if config.venus.host:
            from venus_os_fronius_proxy.venus_reader import venus_mqtt_loop
            venus_task = asyncio.create_task(
                venus_mqtt_loop(shared_ctx, config.venus.host, config.venus.port, config.venus.portal_id)
            )
            shared_ctx["venus_task"] = venus_task
        else:
            log.info("venus_mqtt_skipped", reason="no venus.host in config")
            shared_ctx["venus_mqtt_connected"] = False

        # Start health heartbeat task
        heartbeat_task = None
        if shared_ctx:
            heartbeat_task = asyncio.create_task(
                _health_heartbeat(
                    cache=shared_ctx["cache"],
                    conn_mgr=shared_ctx["conn_mgr"],
                    control_state=shared_ctx["control_state"],
                    poll_counter=shared_ctx["poll_counter"],
                )
            )

        # Wait for shutdown signal
        await shutdown_event.wait()

        log.info("graceful_shutdown_starting")

        # Cancel heartbeat
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        # Stop webapp
        if runner is not None:
            await runner.cleanup()
            log.info("webapp_stopped")

        # Reset power limit to 100% (no limit) before stopping
        try:
            await asyncio.wait_for(
                plugin.write_power_limit(enable=True, limit_pct=100.0),
                timeout=5.0,
            )
            log.info("power_limit_reset", value_pct=100.0)
        except Exception as e:
            log.warning("power_limit_reset_failed", error=str(e))

        # Cancel proxy task
        proxy_task.cancel()
        try:
            await proxy_task
        except asyncio.CancelledError:
            pass

        # Close plugin
        try:
            await plugin.close()
        except Exception as e:
            log.warning("plugin_close_failed", error=str(e))

        log.info("shutdown_complete")

    try:
        asyncio.run(run_with_shutdown())
    except KeyboardInterrupt:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
