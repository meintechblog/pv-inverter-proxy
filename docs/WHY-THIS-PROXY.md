# Why This Proxy Exists — SolarEdge SE30K + Venus OS

> **TL;DR**: Venus OS v3.60+ added native SolarEdge support, but it requires specific inverter settings (Port 502, Unit ID 126) and only works if the inverter exposes SunSpec over Modbus TCP. The SE30K works — but with important caveats. This proxy solves all of them and adds a web dashboard.

---

## The Question

Since Venus OS v3.60 (June 2025), Victron officially supports SolarEdge inverters with power limiting. So why do we need a proxy?

## What Venus OS v3.60+ Actually Does

Venus OS's `dbus-fronius` driver (v1.7.20+) now includes:

- **`SolarEdgeLimiter`** — A proprietary power limiter that writes SolarEdge EDPC registers (0xF300, 0xF322), NOT standard SunSpec Model 123
- **`SunspecLimiter`** — Standard Model 123 for Fronius/ABB/Generic inverters
- **`Sunspec2018Limiter`** — Model 704 for newer inverters

When `dbus-fronius` sees manufacturer string "SolarEdge", it activates the `SolarEdgeLimiter` with proprietary register support.

## Can the SE30K Work Directly?

**Theoretically yes**, with these SolarEdge SetApp changes:

### Required Settings on SE30K (via SetApp)

1. **Enable Modbus TCP**: `Commissioning → Site Communication → Modbus TCP → Enable`
2. **Change Port to 502**: `Modbus TCP → Port → 502` (default is 1502)
3. **Set Device ID to 126**: `RS485-1 → Device ID → 126` (also applies to TCP)
4. **Set Protocol to SunSpec**: `RS485-1 → Protocol → SunSpec (Non-SE Logger)`
5. **Static IP**: Disable DHCP, set static IP

### What Would Work Directly

| Feature | Direct | Status |
|---------|--------|--------|
| Monitoring (power, energy, voltage) | ✅ | SunSpec Model 103 present |
| Three-phase data | ✅ | SE30K exposes L1/L2/L3 |
| Device discovery | ✅ | With port 502 + unit ID 126 |
| Power limiting (EDPC) | ⚠️ | `SolarEdgeLimiter` uses proprietary registers |

### Blockers and Risks

| Issue | Severity | Detail |
|-------|----------|--------|
| **Single TCP connection** | 🔴 Critical | SE30K allows only ONE Modbus TCP client. Venus OS would block the SolarEdge monitoring platform. |
| **No Model 120 (Nameplate)** | 🟡 Medium | SE30K doesn't expose Nameplate ratings. dbus-fronius requires Model 120 for proper operation. May fall back to defaults. |
| **No Model 123** | 🟢 N/A | Irrelevant — `SolarEdgeLimiter` uses proprietary registers, not Model 123 |
| **Port/Unit ID changes** | 🟡 Medium | Requires SetApp access and reconfiguration of the inverter |
| **Power limit auto-enable** | 🟡 Medium | SolarEdge limiter requires manual enable in Venus OS (unlike Fronius auto-enable) |
| **EDPC register support** | ⚠️ Unknown | `SolarEdgeLimiter` confirmed in binary, but untested with SE30K specifically. Community reports are for SE5K/SE15K only. |
| **Firmware dependency** | 🟡 Medium | SE30K firmware must support EDPC. Our SE30K (fw 0004.0023.0529) should be fine. |

## What the Proxy Adds

| Feature | Direct SE30K | With Proxy |
|---------|-------------|------------|
| Port 502 + Unit ID 126 | Requires inverter reconfiguration | ✅ Handled transparently |
| Model 120 (Nameplate) | ❌ Missing | ✅ Synthesized (30kW, DER Type 4) |
| Model 123 (Controls) | ❌ Missing (uses EDPC) | ✅ Synthesized + translates to EDPC |
| Manufacturer = "Fronius" | ❌ Shows "SolarEdge" | ✅ Auto power limit enabled |
| Monitoring platform | 🔴 Blocked (single connection) | ✅ Proxy is sole client |
| Web dashboard | ❌ None | ✅ http://192.168.3.191 |
| Register viewer | ❌ None | ✅ Side-by-side SE30K ↔ Fronius |
| Config without SSH | ❌ Requires SetApp | ✅ Web-based config editor |
| Night mode | ❌ Venus OS shows errors | ✅ Synthetic zero-power registers |
| Reconnection | ❌ Manual restart needed | ✅ Exponential backoff + auto-reconnect |

## Community-Confirmed SolarEdge Models

From [Victron Community forums](https://community.victronenergy.com/t/help-needed-sma-solar-edge-kostal-and-others/33869) (as of March 2026):

| Model | Type | Power Limiting | Notes |
|-------|------|----------------|-------|
| SE5K | Single-phase | ✅ Confirmed | fw 0004.0021.00023 |
| SE15K | Three-phase | ✅ Confirmed | fw 0004.0020.0036 |
| SE3000 | Single-phase | ✅ Reported | — |
| SE7K | Single-phase | ✅ Reported | — |
| SE10K | Three-phase | ✅ Reported | — |
| **SE30K** | **Three-phase commercial** | **❓ Untested** | **No community reports** |

### Known Issues (Direct SolarEdge)

- [Zero feed-in limit gets stuck](https://community.victronenergy.com/t/bug-solaredge-zero-feed-in-limit-is-stuck/41803) on newer Venus OS versions
- [Limiting capability disappears](https://community.victronenergy.com/t/solaredge-pv-inverter-limiting-capability-repeatedly-disappearing-in-gui/53830) after running for hours/days
- Multiple SolarEdge units: only the first inverter throttles, others ignore commands

## Conclusion

The proxy is the **safer, more feature-rich option** for the SE30K:

1. **Zero inverter reconfiguration** — SE30K stays on factory settings (port 1502, unit ID 1)
2. **Monitoring platform preserved** — SolarEdge cloud monitoring continues working
3. **Guaranteed compatibility** — Tested and verified, unlike untested direct SE30K path
4. **Additional features** — Web dashboard, register viewer, night mode, reconnection
5. **Power control via standard SunSpec** — Model 123 translated to EDPC, cleaner integration

If you want to try direct connection anyway, the SetApp settings above should work — but stop the proxy first (`systemctl stop venus-os-fronius-proxy`) since the SE30K only allows one TCP client.

## References

- [SolarEdge SunSpec Technical Note v3.2 (June 2025)](https://knowledge-center.solaredge.com/sites/kc/files/sunspec-implementation-technical-note.pdf)
- [Victron: Integrating with SolarEdge](https://www.victronenergy.com/live/venus-os:gx_solaredge)
- [Venus OS v3.60 Blog Post](https://www.victronenergy.com/blog/2025/06/10/introducing-venus-os-3-60/)
- [dbus-fronius Source Code](https://github.com/victronenergy/dbus-fronius)
- [Community: SolarEdge Help Thread](https://community.victronenergy.com/t/help-needed-sma-solar-edge-kostal-and-others/33869)
- [Community: PV Inverter Limiting](https://community.victronenergy.com/t/venus-os-v3-60-beta-pv-inverter-limiting-zero-feed-in/20760)
