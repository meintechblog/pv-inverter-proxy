# PV-Inverter Proxy

Modbus TCP proxy that makes a **SolarEdge SE30K** inverter appear as a **Fronius** to **Venus OS** (Victron). Venus OS natively discovers, monitors, and controls the inverter — including power limiting via DVCC/ESS.

Includes a dark-themed **web dashboard** with live monitoring, power control, and Venus OS integration.

## Features

- **Modbus Proxy** — SolarEdge registers translated to Fronius SunSpec profile (Model 1/103/120/123)
- **Venus OS Native** — Auto-detected as "Fronius SE30K", power limiting via Model 123 → SE EDPC
- **Live Dashboard** — Power gauge, 3-phase AC table, sparkline (60 min), peak statistics
- **Power Control** — Dropdown (5% steps) with confirmation, auto-revert after 5 min
- **Venus OS Widget** — Connection status, override display, disable toggle (15 min safety cap)
- **Smart Notifications** — Toast alerts for overrides, faults, temperature warnings, night mode
- **CSS Animations** — Smooth gauge transitions, entrance animations, prefers-reduced-motion support
- **Night Mode** — Synthetic registers when inverter sleeps, no crashes

## Quick Install

On a fresh **Debian 12+** / **Ubuntu 22.04+** machine (LXC, VM, or bare metal):

```bash
curl -sSL https://raw.githubusercontent.com/meintechblog/pv-inverter-proxy/main/install.sh | bash
```

This installs everything: Python venv, systemd service, default config. Edit the config afterwards:

```bash
nano /etc/venus-os-fronius-proxy/config.yaml
systemctl restart venus-os-fronius-proxy
```

### Update

Same command — the script detects an existing installation and updates in-place:

```bash
curl -sSL https://raw.githubusercontent.com/meintechblog/pv-inverter-proxy/main/install.sh | bash
```

## Configuration

`/etc/venus-os-fronius-proxy/config.yaml`:

```yaml
solaredge:
  host: "192.168.3.18"    # Your SolarEdge inverter IP
  port: 1502              # Modbus TCP port
  unit_id: 1

proxy:
  port: 502               # Venus OS connects here

webapp:
  port: 80                # Dashboard URL

log_level: INFO
```

## Network Setup

All devices must be on the same LAN:

```
SolarEdge SE30K (192.168.3.18:1502)
        ↕ Modbus TCP
Proxy (192.168.3.191:502 + :80)
        ↕ Modbus TCP
Venus OS / Cerbo (192.168.3.146)
```

Venus OS auto-discovers the proxy on port 502 as a Fronius inverter.

## Dashboard

Access at `http://<proxy-ip>` (port 80).

**Pages:**
- **Dashboard** — Power gauge, 3-phase AC, power control, connection status, Venus OS control, sparkline, peak stats, inverter status, service health
- **Config** — SolarEdge IP/port configuration
- **Registers** — Raw Modbus register viewer

## Management

```bash
# Service status
systemctl status venus-os-fronius-proxy

# Live logs
journalctl -u venus-os-fronius-proxy -f

# Restart
systemctl restart venus-os-fronius-proxy

# Stop
systemctl stop venus-os-fronius-proxy
```

## Tech Stack

- **Python 3.12**, pymodbus 3.8+, aiohttp, structlog, PyYAML
- **Frontend**: Vanilla JS, CSS3 (zero dependencies, no build step)
- **Deployment**: systemd service on Debian/Ubuntu (LXC recommended)

## Development

```bash
git clone https://github.com/meintechblog/pv-inverter-proxy.git
cd venus-os-fronius-proxy
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Deploy from dev machine to LXC:

```bash
./deploy.sh              # Update existing installation
./deploy.sh --first-time # First-time setup on LXC
```

## License

MIT
