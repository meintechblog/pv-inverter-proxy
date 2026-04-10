"""Root-only privileged updater package (Phase 45).

This package is imported ONLY from the pv-inverter-proxy-updater.service
systemd unit, which runs as root. The main service (pv-inverter-proxy.service,
User=pv-proxy) MUST NEVER import from this package. The trust boundary is
filesystem-enforced and grep-verifiable.

Allowed imports from pv_inverter_proxy.*:
    - releases     (read-only constants + layout helpers)
    - recovery     (PendingMarker schema + path constants)
    - state_file   (Plan 45-04 only)

Forbidden:
    - webapp, __main__, context, proxy, distributor, control, updater.*
"""
UPDATER_ROOT_SCHEMA_VERSION = 1
