# Feature Landscape: Multi-Source Virtual Inverter (v4.0)

**Domain:** Multi-source PV aggregation proxy with device-centric management
**Researched:** 2026-03-20
**Milestone:** v4.0 Multi-Source Virtual Inverter
**Confidence:** HIGH (existing codebase analyzed, OpenDTU API verified against official docs, Venus OS SunSpec behavior verified)

## Table Stakes

Features users expect for a multi-source aggregation proxy. Missing = product feels incomplete or untrustworthy.

| Feature | Why Expected | Complexity | Dependencies | Notes |
|---------|--------------|------------|--------------|-------|
| **OpenDTU plugin (poll + display)** | Core promise of v4.0. Without Hoymiles data, there is nothing to aggregate. Users see OpenDTU at 192.168.3.98 and expect it to "just work" like SolarEdge | Medium | Existing `InverterPlugin` ABC, aiohttp (already in stack) | REST polling via `/api/livedata/status`. Must map OpenDTU JSON fields (AC Power/Voltage/Current, DC per-channel, YieldDay/Total) into SunSpec register format matching `PollResult` |
| **OpenDTU power limit control** | SolarEdge already has power limiting. Hoymiles via OpenDTU must match. Venus OS sends one limit command to the virtual inverter; proxy must distribute | Medium | OpenDTU plugin, `POST /api/limit/config` with Basic Auth | Limit takes ~25s to activate on Hoymiles (vs instant on SolarEdge). Must handle async confirmation via `/api/limit/status` polling. Limit type 1 = relative percentage |
| **Virtual inverter aggregation** | The entire v4.0 value proposition. Venus OS sees ONE Fronius inverter. All active source inverters must sum into that single SunSpec register set | High | All source plugins polling, `RegisterCache`, `proxy.py` poll loop | Sum: AC Power (W), AC Current (A per phase). Weighted average: AC Voltage, Frequency. Sum: DC Power. Sum: Energy (Wh). Synthesize single Common Model identity |
| **Aggregated Model 120 nameplate** | Venus OS reads Model 120 for rated power (WRtg). Virtual inverter must report combined capacity (e.g., SE30K 30kW + Hoymiles 800W = 30800W) | Low | Virtual inverter, all source nameplates known | Recalculate on source add/remove. WRtg = sum of all active source WRtg values |
| **Per-inverter dashboard** | Users want to see individual inverter performance, not just the aggregate. "How much is the Hoymiles producing vs the SolarEdge?" is the first question after setup | High | Device-centric navigation, per-source WebSocket data, existing dashboard components | Reuse existing gauge/sparkline/phase components. Each inverter gets own data stream in WebSocket snapshot |
| **Per-inverter register viewer** | Already exists for SolarEdge. Users expect same register-level debugging for every source. Essential for troubleshooting connection issues | Medium | Per-source poll data in `shared_ctx`, existing register viewer component | SolarEdge: existing Modbus registers. OpenDTU: show raw JSON fields mapped to SunSpec equivalents |
| **Per-inverter config** | Each source needs its own connection settings (host, port, unit_id for Modbus; URL, auth for REST). Must be editable without affecting other sources | Medium | Existing config page patterns, `InverterEntry` dataclass | Extend `InverterEntry` with `type` field ("solaredge", "opendtu") and type-specific connection params |
| **Device sidebar navigation** | With multiple inverters + Venus OS as separate sections, the current 3-tab nav (Dashboard/Config/Registers) breaks down. Users need per-device navigation | High | Frontend restructure, URL hash routing update | Sidebar: Virtual Inverter (aggregate dashboard), SE30K (dashboard/registers/config), Hoymiles (dashboard/registers/config), Venus OS (ESS/MQTT/status), "+" add device |
| **Aggregate dashboard (virtual inverter view)** | The "home" view showing combined power, total yield, all-source health at a glance. This is what users land on | Medium | Virtual inverter data, existing dashboard components | Reuse gauge (now showing aggregate power with combined capacity), sparkline (aggregate), phase table (combined). Add source breakdown bar or mini-cards |
| **Source health indicators** | When one source goes offline, the aggregate still works but users must know which source is down and why | Low | Per-source `ConnectionManager` state, existing `ve-dot` component | Green/amber/red dot per source in sidebar and aggregate dashboard. Night mode state per source independently |

## Differentiators

Features that set this apart. Not expected, but make the product feel polished and professional.

| Feature | Value Proposition | Complexity | Dependencies | Notes |
|---------|-------------------|------------|--------------|-------|
| **Priority-based power limiting** | Venus OS sends one limit (e.g., "reduce to 50%"). User defines which inverters throttle first. Example: throttle Hoymiles first (cheaper panels), keep SolarEdge at full power longer | High | Virtual inverter, all source plugins with `write_power_limit`, priority config | Distribution algorithm: ordered list of sources. Reduce highest-priority source first until its minimum, then next source. Must handle mixed capabilities (SolarEdge instant vs OpenDTU 25s delay) |
| **Per-inverter exclusion from limiting** | Mark specific inverters as "never throttle". Example: Hoymiles on battery backup should always produce 100% | Low | Priority config, limiting algorithm | Boolean `exclude_from_limiting` per `InverterEntry`. Excluded sources produce at 100%, remaining sources absorb the full reduction |
| **Custom virtual inverter name** | User names the aggregate device (e.g., "Dach PV Gesamt") instead of seeing "Fronius Proxy" | Low | Config dataclass, Common Model manufacturer/model string | Stored in config, applied to SunSpec Common Model C_Model field. Default: "PV Aggregator" or similar |
| **Venus OS as own device section** | Venus OS gets its own sidebar entry with ESS status, MQTT connection health, Portal ID, Grid/Battery power (if available), override log | Medium | Existing `venus_reader.py` MQTT data, sidebar navigation | Consolidates scattered Venus OS info (currently split across dashboard widgets and config page) into one coherent view |
| **Central "+" device management** | Single entry point to add new inverters or configure Venus OS. Guides user through type selection (SolarEdge/OpenDTU) and connection setup | Medium | Config API, plugin factory, sidebar navigation | Replaces current "add inverter" in config page. Flow: click "+" -> select type -> fill connection params -> test -> save |
| **Source contribution breakdown** | Visual bar or mini-chart showing "SE30K: 85% / Hoymiles: 15%" of total production. Makes multi-source value visible at a glance | Low | Aggregate dashboard, per-source power data | Simple stacked bar or percentage labels. Updates in real-time from WebSocket |
| **Graceful degradation on source loss** | When one source goes offline, aggregate continues with remaining sources. No crash, no stale data for the lost source (zero-fill like night mode). Venus OS sees reduced but valid power | Medium | Per-source `ConnectionManager`, virtual inverter aggregation | Each source has independent night mode state machine. Aggregate recalculates from available sources only. Venus OS never sees stale data |
| **OpenDTU auto-discovery** | Like SolarEdge auto-discovery but for OpenDTU devices on the LAN. Scan for HTTP endpoints responding to `/api/system/status` | Medium | aiohttp, network scanning infrastructure from v3.1 | Different protocol than Modbus scan: HTTP GET to candidate IPs. Slower but reliable. Could reuse scan progress UI |

## Anti-Features

Features to explicitly NOT build.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Per-phase power distribution across sources** | Venus OS expects one inverter with consistent L1/L2/L3. Splitting phases across sources (e.g., Hoymiles on L1, SolarEdge on L2/L3) creates impossible SunSpec register states and confuses Venus OS ESS | Sum all sources per phase. If a source is single-phase (Hoymiles), add its power to L1 only. Document this behavior |
| **Real-time limit synchronization display** | Showing "SolarEdge: applied, Hoymiles: pending (15s remaining)" sounds useful but creates anxiety and false error signals. OpenDTU limit latency (25s) is normal, not an error | Show limit status per source as simple state: "Active" / "Applying..." / "Unavailable". No countdown timer |
| **Dynamic priority rebalancing** | Auto-adjusting priority order based on current production, panel efficiency, or weather predictions. Over-engineered, unpredictable, hard to debug | Static user-defined priority list. User knows their setup best. Reorder via drag-and-drop or up/down buttons |
| **Multi-virtual-inverter support** | Running multiple separate virtual inverters for different Venus OS instances from one proxy. Massively increases state complexity for zero real-world demand | One virtual inverter per proxy instance. If user needs two, run two proxy instances |
| **Battery/Grid data aggregation** | Tempting to pull battery SOC or grid power from Venus OS MQTT and show in proxy dashboard. But proxy only has PV data; mixing in consumption data creates a confusing half-complete energy flow | Show Venus OS connection status and ESS mode only. Link to Venus OS Remote Console for full energy flow |
| **OpenDTU WebSocket streaming** | OpenDTU supports WebSocket for live data push instead of REST polling. Adds complexity (two WS connections: one to OpenDTU, one from browser) for marginal latency improvement | Poll OpenDTU REST API at 2-5s interval. More than fast enough for Venus OS (which polls proxy at 1s). Simpler error handling, no reconnection state for WS client |
| **Plugin hot-swap (add source type at runtime)** | Dynamically loading new plugin types without restart. Way over-engineered for 2 plugin types | Restart proxy after config change that adds a new source type. Plugin instances can be hot-reloaded (existing pattern), but new plugin classes require restart |

## Feature Dependencies

```
OpenDTU Plugin (poll) ──────────────────┐
                                        ├──> Virtual Inverter Aggregation ──> Aggregated Nameplate
SolarEdge Plugin (existing) ────────────┘           │
                                                    ├──> Aggregate Dashboard
Per-inverter Dashboard ─────────────────────────────┤
Per-inverter Register Viewer ───────────────────────┤
Per-inverter Config ────────────────────────────────┤
                                                    │
Device Sidebar Navigation <─────────────────────────┘
        │
        ├──> Venus OS Device Section
        ├──> Central "+" Device Management
        └──> URL Hash Routing (per-device pages)

OpenDTU Power Limit Control ────┐
                                ├──> Priority-based Power Limiting
SolarEdge write_power_limit ────┘           │
                                            ├──> Per-inverter Exclusion
                                            └──> (requires Virtual Inverter)

Source Health Indicators ──────────> (standalone, per-source ConnectionManager)
Source Contribution Breakdown ─────> (requires Aggregate Dashboard)
Custom Virtual Inverter Name ──────> (standalone config change)
```

**Critical path:** OpenDTU Plugin must ship first. Virtual Inverter Aggregation depends on having at least two sources. Device Sidebar Navigation is the structural prerequisite for all per-device views.

## MVP Recommendation

### Must Ship (table stakes -- without these, v4.0 has no value):

1. **OpenDTU plugin (poll + display)** -- Without this, there is only one source and nothing to aggregate. Foundation for everything.
2. **Virtual inverter aggregation** -- The core value proposition. Sum N sources into one Fronius for Venus OS.
3. **Aggregated Model 120 nameplate** -- Venus OS needs correct WRtg for ESS calculations. Wrong nameplate = wrong power limiting behavior.
4. **Device sidebar navigation** -- Structural prerequisite for per-device views. Current 3-tab nav cannot accommodate N devices.
5. **Per-inverter dashboard** -- Users must see individual source performance. Reuses existing components.
6. **Aggregate dashboard** -- The "home" view showing combined power. Reuses existing gauge/sparkline with aggregate data.
7. **Per-inverter config** -- Each source needs editable connection settings.
8. **Source health indicators** -- Without these, users cannot diagnose which source is down.
9. **OpenDTU power limit control** -- Venus OS ESS sends limit commands. If Hoymiles cannot be limited, it defeats the purpose of aggregation for zero-export setups.

### Should Ship (differentiators that make v4.0 feel complete):

10. **Priority-based power limiting** -- Core differentiator. Without it, the proxy just splits limits equally, which is rarely what users want.
11. **Per-inverter exclusion from limiting** -- Simple boolean, huge value for users with mixed setups.
12. **Venus OS as own device section** -- Consolidates existing scattered Venus info into coherent view.
13. **Custom virtual inverter name** -- Low effort, nice personalization.
14. **Source contribution breakdown** -- Visual proof that multi-source is working.

### Defer to v4.1+:

15. **Central "+" device management** -- Nice UX but not blocking. Users can add devices via config page initially.
16. **Per-inverter register viewer** -- Useful for debugging but not essential for basic operation. SolarEdge viewer already exists; OpenDTU equivalent can come later.
17. **OpenDTU auto-discovery** -- Different protocol than Modbus scan. Lower priority since users typically know their OpenDTU IP.
18. **Graceful degradation on source loss** -- Important for reliability but complex. Initially, a source going offline can show error state while aggregate zeroes that source's contribution.

## Implementation Notes

### OpenDTU Plugin Data Mapping

OpenDTU `/api/livedata/status` JSON maps to SunSpec registers as follows:

| OpenDTU JSON Field | SunSpec Register | Notes |
|-------------------|-----------------|-------|
| `inverters[].AC.Power.v` | Model 103 W (offset 14) | Total AC power in watts |
| `inverters[].AC.Voltage.v` | Model 103 PhVphA (offset 8) | Phase A voltage |
| `inverters[].AC.Current.v` | Model 103 A (offset 2) | Total AC current |
| `inverters[].AC.Frequency.v` | Model 103 Hz (offset 16) | Grid frequency |
| `inverters[].DC[n].Power.v` | Model 103 DCW (offset 18) | Sum all DC channel power |
| `inverters[].DC[n].Voltage.v` | Model 103 DCV (offset 20) | Average DC voltage |
| `inverters[].INV.YieldTotal.v` | Model 103 WH (offset 26-27) | Total energy in Wh (uint32) |
| `inverters[].INV.YieldDay.v` | Used for dashboard only | Not in SunSpec, display only |

OpenDTU reports single-phase AC (Hoymiles micro-inverters are single-phase). Map to L1 only in 3-phase SunSpec model.

### Virtual Inverter Aggregation Logic

```
For each poll cycle:
  1. Collect PollResult from each active source
  2. Sum AC power (W), AC current (A) per phase
  3. Weighted-average AC voltage and frequency (weight = power contribution)
  4. Sum DC power, weighted-average DC voltage
  5. Sum energy counters (WH)
  6. Build single PollResult with aggregated registers
  7. Update RegisterCache (Venus OS reads this)
```

Scale factors: Use the most conservative (most negative) scale factor from any source. For mixed sources where one uses SF=-2 and another SF=0, normalize all values to the most precise SF before summing.

### Power Limit Distribution Algorithm

```
Given: Venus OS requests X% limit on virtual inverter
Given: Priority list [Source A (priority 1), Source B (priority 2)]
Given: Each source has max_power (WRtg from nameplate)

Target watts = X% * sum(all source WRtg)
Remaining watts = Target watts

For each source in priority order (lowest priority = throttled first):
  If source.exclude_from_limiting:
    Remaining watts -= source.current_power  # This source keeps producing
    Continue

  source_limit = min(remaining_watts, source.max_power)
  source_pct = (source_limit / source.max_power) * 100
  await source.write_power_limit(True, source_pct)
  Remaining watts -= source_limit
```

### OpenDTU Authentication

OpenDTU requires HTTP Basic Auth for write operations (`/api/limit/config`). Store credentials in `InverterEntry`:

```python
@dataclass
class InverterEntry:
    # ... existing fields ...
    type: str = "solaredge"      # "solaredge" | "opendtu"
    api_url: str = ""            # OpenDTU base URL (e.g., "http://192.168.3.98")
    api_user: str = "admin"      # OpenDTU auth username
    api_password: str = "openDTU42"  # OpenDTU auth password (default)
    opendtu_serial: str = ""     # Hoymiles serial number for API calls
```

### Sidebar Navigation Structure

```
[Virtual Inverter]     <-- aggregate dashboard (home)
  Dashboard            <-- gauge + phases + sparkline (aggregate)

[SE30K]                <-- per-device section
  Dashboard            <-- individual gauge + phases
  Registers            <-- existing register viewer
  Config               <-- connection settings

[Hoymiles HM-800]     <-- per-device section
  Dashboard            <-- individual gauge (single phase)
  Config               <-- OpenDTU URL, serial, auth

[Venus OS]             <-- system section
  Status               <-- ESS mode, MQTT health, Portal ID
  Config               <-- Venus IP, MQTT port

[+]                    <-- add device
```

URL hash format: `#device/{id}/dashboard`, `#device/{id}/registers`, `#device/{id}/config`, `#venus/status`, `#add-device`

### OpenDTU Poll Interval

OpenDTU REST API is served by ESP32 with limited resources. Poll at 3-5 second interval (not 1s like SolarEdge Modbus). The ESP32 can handle ~1 req/s but running close to that limit causes occasional timeouts. 3s is conservative and sufficient since Venus OS polls the proxy at 1s anyway -- the aggregate will update with slightly stale OpenDTU data between polls.

## Complexity Budget

| Feature | Backend LOC | Frontend LOC | Total Effort |
|---------|-------------|--------------|--------------|
| OpenDTU plugin (poll) | ~200 | 0 | Medium |
| OpenDTU power limit | ~80 | 0 | Medium |
| Virtual inverter aggregation | ~250 | 0 | High |
| Aggregated nameplate | ~30 | 0 | Low |
| Device sidebar navigation | ~20 (API routes) | ~300 | High |
| Per-inverter dashboard | ~50 (snapshot restructure) | ~250 | High |
| Aggregate dashboard | ~30 | ~150 | Medium |
| Per-inverter config | ~60 | ~150 | Medium |
| Source health indicators | ~20 | ~60 | Low |
| Priority-based limiting | ~150 | ~100 | High |
| Per-inverter exclusion | ~20 | ~30 | Low |
| Venus OS device section | ~30 | ~120 | Medium |
| Custom virtual inverter name | ~15 | ~20 | Low |
| Source contribution breakdown | ~10 | ~60 | Low |

**Total estimate: ~965 LOC backend, ~1,240 LOC frontend**

## Sources

- [OpenDTU Web API Documentation](https://www.opendtu.solar/firmware/web_api/) -- Official REST API endpoints, authentication, response formats
- [OpenDTU GitHub - Power Limit Latency (Issue #571)](https://github.com/tbnobody/OpenDTU/issues/571) -- Limit activation takes ~25s on Hoymiles
- [OpenDTU GitHub - Setting limit via API (Discussion #602)](https://github.com/tbnobody/OpenDTU/discussions/602) -- limit_type and limit_value parameters
- [OpenDTU GitHub - API limit types (Discussion #742)](https://github.com/tbnobody/OpenDTU/discussions/742) -- Limit type 0=absolute, 1=relative
- [victronenergy/dbus-fronius](https://github.com/victronenergy/dbus-fronius) -- Venus OS Fronius driver, SunSpec power limiting via Model 123/704
- [Venus OS SunSpec Inverter Support](https://community.victronenergy.com/t/support-of-sunspec-inverters-via-modbus-rtu-and-extended-sunspec-support/34855) -- Multi-inverter handling in Venus OS
- [OpenDTU-OnBattery Dynamic Power Limiter](https://github.com/hoylabs/OpenDTU-OnBattery/wiki/Dynamic-Power-Limiter) -- Power distribution strategies for Hoymiles
- [dbus-opendtu Integration](https://github.com/henne49/dbus-opendtu) -- Existing OpenDTU-to-Venus-OS bridge (different approach: dbus driver vs proxy)
- Codebase analysis: `plugin.py`, `plugins/solaredge.py`, `proxy.py`, `config.py`, `app.js`, `webapp.py`
