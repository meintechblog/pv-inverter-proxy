"""Typed application context replacing the flat shared_ctx dict.

AppContext holds all runtime state for the proxy. DeviceState holds
per-device state (one entry per inverter). DeviceRegistry manages
device lifecycle (Phase 22+).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class DeviceState:
    """Per-device runtime state."""
    collector: object = None       # DashboardCollector (avoid circular import)
    poll_counter: dict = field(default_factory=lambda: {"success": 0, "total": 0})
    conn_mgr: object = None        # ConnectionManager
    last_poll_data: dict | None = None  # raw poll registers for register viewer
    plugin: object = None          # InverterPlugin instance


@dataclass
class AppContext:
    """Typed application context replacing flat shared_ctx dict."""

    # Core infrastructure
    cache: object = None           # RegisterCache
    control_state: object = None   # ControlState
    config: object = None          # Config
    config_path: str = ""

    # Device states (keyed by InverterEntry.id)
    devices: dict[str, DeviceState] = field(default_factory=dict)

    # Venus OS
    venus_mqtt_connected: bool = False
    venus_os_detected: bool = False
    venus_os_detected_ts: float = 0.0
    venus_os_client_ip: str = ""
    venus_task: object = None      # asyncio.Task
    venus_settings: dict | None = None

    # Webapp
    webapp: object = None          # aiohttp web.Application

    # Internal
    polling_paused: bool = False
    healthy_flag_written: bool = False  # True after first successful poll (SAFETY-06)
    _last_modbus_client_ip: str = ""
    override_log: object = None    # OverrideLog
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)

    # DeviceRegistry reference (set in __main__.py after creation)
    device_registry: object = None

    distributor: object = None

    # MQTT Publisher (Phase 25)
    mqtt_pub_task: object = None           # asyncio.Task
    mqtt_pub_connected: bool = False
    mqtt_pub_queue: object = None          # asyncio.Queue

    # MQTT Publisher stats
    mqtt_pub_messages: int = 0             # Total messages published
    mqtt_pub_bytes: int = 0                # Total bytes published
    mqtt_pub_skipped: int = 0              # Messages skipped (change detection)
    mqtt_pub_last_ts: float = 0.0          # Timestamp of last publish

    # Phase 44: Passive Version Badge (CHECK-01, CHECK-05, CHECK-06)
    current_version: str | None = None         # From importlib.metadata at startup
    current_commit: str | None = None          # From git rev-parse --short HEAD at startup
    available_update: dict | None = None       # Parsed GitHub release info when latest > current
    update_last_check_at: float | None = None  # UNIX timestamp of last successful scheduler iteration
    update_last_check_failed_at: float | None = None  # UNIX timestamp of last failed iteration

    # Phase 45 Plan 05: Maintenance mode (RESTART-01/02/03)
    maintenance_mode: bool = False              # True while an update is draining the Modbus server
    maintenance_entered_at: float | None = None  # time.time() when the flag was raised
    _pending_restore_limit_pct: float | None = None  # SAFETY-09 restore pointer set at boot
    _slave_ctx: object = None                   # StalenessAwareSlaveContext — exposed for drain_inflight
