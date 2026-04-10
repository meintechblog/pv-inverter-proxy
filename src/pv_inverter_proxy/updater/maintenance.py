"""Maintenance mode for the Phase 45 update flow.

Encapsulates the three-state lifecycle that protects Venus OS while the
updater is restarting the main service:

1. ``enter_maintenance_mode`` flips ``app_ctx.maintenance_mode`` to True
   and records ``maintenance_entered_at``. The proxy's ``async_setValues``
   observes the flag and rejects Model 123 writes per
   ``MAINTENANCE_STRATEGY`` (see below).

2. ``drain_inflight_modbus`` waits up to ``timeout_s`` seconds for the
   Modbus server's per-slave in-flight counter to reach zero. The counter
   is maintained in ``StalenessAwareSlaveContext`` — this helper reads it
   via ``app_ctx._slave_ctx``. RESTART-02.

3. ``exit_maintenance_mode`` clears the flag. Normally the process is
   going away (systemd restart), so this is only called when an error
   caused the update trigger to be aborted before the restart actually
   happened.

MAINTENANCE_STRATEGY
====================

Decided empirically in Plan 45-05 Task 1:

- ``"slavebusy"``  (default): reject writes with Modbus exception 0x06
  (DEVICE_BUSY). This is a standard retryable exception; Venus OS's
  Fronius plugin follows Modbus convention and will retry silently.
  Loopback probe in ``scripts/venus_os_slavebusy_loopback_probe.py``
  confirmed pymodbus 3.12 translates ``ExcCodes.DEVICE_BUSY`` into wire
  exception code 6.

- ``"silent_drop"`` (fallback): swallow the write, return success
  without forwarding to the distributor. Used only if live LXC testing
  in Plan 45-05 Task 5 shows that SlaveBusy causes Venus OS to drop the
  connection — flip this constant in ``proxy.py`` as a one-line rollback.
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:  # pragma: no cover
    from pv_inverter_proxy.context import AppContext

log = structlog.get_logger(component="updater.maintenance")

# Decision from Plan 45-05 Task 1: slavebusy is the default strategy.
# Rollback by changing this constant to "silent_drop" and redeploying.
MAINTENANCE_STRATEGY = "slavebusy"


async def enter_maintenance_mode(
    app_ctx: "AppContext",
    reason: str = "update",
) -> None:
    """Set the maintenance flag and log a structured event.

    Idempotent: calling twice in a row does not re-log or reset the
    entered_at timestamp on the second call. This matters because the
    POST /api/update/start handler and _graceful_shutdown_maintenance
    may both call this path on different code legs.
    """
    if app_ctx.maintenance_mode:
        log.debug("maintenance_mode_already_active", reason=reason)
        return
    app_ctx.maintenance_mode = True
    app_ctx.maintenance_entered_at = time.time()
    log.info(
        "maintenance_mode_entered",
        reason=reason,
        entered_at=app_ctx.maintenance_entered_at,
        strategy=MAINTENANCE_STRATEGY,
    )


async def exit_maintenance_mode(app_ctx: "AppContext") -> None:
    """Clear the maintenance flag.

    Only meaningful in failure-recovery paths — under normal operation
    the process exits during shutdown and the flag goes away with it.
    """
    if not app_ctx.maintenance_mode:
        log.debug("maintenance_mode_already_inactive")
        return
    app_ctx.maintenance_mode = False
    log.info("maintenance_mode_exited")


def is_modbus_write_allowed(app_ctx: "AppContext") -> bool:
    """Return True iff Modbus writes should be forwarded to the distributor.

    Used by tests and by proxy.py's gate (which calls this via a simpler
    attribute check on the hot path — see ``StalenessAwareSlaveContext.async_setValues``).
    """
    return not getattr(app_ctx, "maintenance_mode", False)


async def drain_inflight_modbus(
    app_ctx: "AppContext",
    timeout_s: float = 2.0,
) -> bool:
    """Wait up to ``timeout_s`` seconds for in-flight Modbus writes to finish.

    RESTART-02: "Mindestens 3 Sekunden Drain-Zeit nach Maintenance-Mode
    (laenger als Venus OS Poll-Zyklus) bevor Prozess beendet wird;
    in-flight pymodbus-Transaktionen werden via
    asyncio.wait_for(drain(), 2.0) abgewartet"

    Returns True if the counter reached zero within the timeout, False
    if the wait timed out. Also returns True if the slave context has
    not been wired yet (nothing to drain).
    """
    slave_ctx = getattr(app_ctx, "_slave_ctx", None)
    if slave_ctx is None:
        log.debug("drain_inflight_no_slave_ctx")
        return True
    inflight = getattr(slave_ctx, "_inflight_count", 0)
    event = getattr(slave_ctx, "_inflight_drained", None)
    if inflight == 0 or event is None:
        return True
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout_s)
        log.info(
            "modbus_drain_complete",
            timeout_s=timeout_s,
            final_inflight=getattr(slave_ctx, "_inflight_count", -1),
        )
        return True
    except asyncio.TimeoutError:
        log.warning(
            "modbus_drain_timeout",
            timeout_s=timeout_s,
            stuck_inflight=getattr(slave_ctx, "_inflight_count", -1),
        )
        return False
