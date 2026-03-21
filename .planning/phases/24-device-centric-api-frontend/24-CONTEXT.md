# Phase 24: Device-Centric API & Frontend - Context

**Gathered:** 2026-03-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Per-device REST endpoints, WebSocket updates, and complete UI restructure. Every device (inverter, Venus OS, virtual PV) gets its own sidebar entry, dashboard view, and management interface. Replaces the current 3-tab layout (Dashboard, Config, Registers) with a device-centric navigation.

</domain>

<decisions>
## Implementation Decisions

### Sidebar Navigation
- Grouped by type: **INVERTERS** (SE30K, HM-800, HM-600) → **VENUS OS** → **VIRTUAL PV**. Collapsible sections.
- Each entry shows: **Name + Status-Dot + Live-Wert** (current power in kW for inverters, "Connected" for Venus OS)
- Device names are **user-definable with auto-default** from Manufacturer+Model. Editable in device Config sub-tab. New config field `display_name` on InverterEntry.
- **Virtual PV is always visible** in sidebar, even with only 1 inverter

### Per-Device Dashboard Layout
- **Typ-spezifische Layouts**: SolarEdge gets 3-Phase AC table, OpenDTU gets DC-channel table, etc. Different widgets based on available data.
- Each device page has **Sub-Tabs**: `Dashboard` | `Registers` | `Config`
  - Dashboard: Power gauge, type-specific data tables, status info
  - Registers: SunSpec register viewer (for SolarEdge) or equivalent for OpenDTU
  - Config: Host, Port, Unit ID, Throttle Order, Throttle Enabled, Dead-Time, Display Name
- **Venus OS page**: Single page (no sub-tabs), shows MQTT connection status, ESS mode, Portal ID, and Config fields (IP, Port, Portal ID) all on one view
- Manufacturer + Model displayed in Config sub-tab after successful connection

### Device Add/Remove Flow
- **'+' button placement**: Claude's discretion (sidebar bottom, per-group, or header — pick what's cleanest)
- **Add flow**: Claude's discretion (type picker → form, or dropdown-based)
- **Discover button**: Available in add form for manual network scan (no auto-scan)
- **Disable UX**: Last data stays visible but **ausgegraut** (greyed out). Sidebar entry shows dimmed with "Disabled" label. No data clearing on disable.
- **Delete UX**: **Toast with Undo** — device removed, 5-second toast "Device gelöscht — Rückgängig". After timeout, permanently gone. No inline-confirm needed (toast IS the confirm).

### Virtual PV Contribution View
- **Gestapelte Balken** (stacked horizontal bar) shows proportional power per inverter, color-coded. Legend below with names + kW.
- **Gauge**: Claude's discretion whether to show the familiar power gauge above the bar or just a large number
- **Throttle info in contribution table**: Table shows additional columns: TO number, Throttle On/Off, current limit (%). Overview of Regelverhalten directly in Virtual PV.

### Claude's Discretion
- '+' button exact placement and add-flow UX design
- Virtual PV gauge vs. large number display
- Loading skeleton design
- Error state handling per device type
- Sub-tab visual implementation (underline tabs, pill tabs, etc.)
- OpenDTU dashboard layout specifics (DC channel table format)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design System
- `CLAUDE.md` — Venus OS gui-v2 dark theme design tokens, color variables, component patterns, naming conventions (`ve-*` prefix), responsive breakpoints, typography scale

### Prior Phase Context
- `.planning/phases/19-inverter-management-ui/19-CONTEXT.md` — Inverter list UI patterns (toggle, inline delete, edit form) — patterns to carry forward or replace
- `.planning/phases/22-device-registry-aggregation/22-CONTEXT.md` — DeviceRegistry lifecycle, AggregationLayer architecture
- `.planning/phases/23-power-limit-distribution/23-CONTEXT.md` — Throttle Order, monitoring-only, dead-time config fields

### Backend Integration
- `.planning/phases/22-device-registry-aggregation/22-RESEARCH.md` — DeviceRegistry API, per-device poll loop, DashboardCollector per device
- `.planning/phases/23-power-limit-distribution/23-RESEARCH.md` — PowerLimitDistributor API, ControlState flow

### Architecture
- `.planning/research/ARCHITECTURE.md` — v4.0 architecture: plugin system, DeviceRegistry, AggregationLayer, proxy decoupling

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ve-card`, `ve-panel`, `ve-btn`, `ve-toggle` — all CSS components reusable for device views
- `ve-gauge-*` — power gauge SVG component, reusable per-device dashboard
- `ve-phase-*` — 3-phase AC table, reusable for SolarEdge view
- `ve-reg-*` — register viewer grid, reusable per-device register tab
- `ve-inv-row` — inverter row component from Phase 19, pattern for sidebar entries
- `DashboardCollector` — per-device snapshot collector already exists in device_registry.py
- `createInverterRow()`, `loadInverters()` — JS functions to refactor into device-centric rendering

### Established Patterns
- Hash-based routing: `window.location.hash` for page navigation — extend to `#device/{id}/dashboard`
- WebSocket for live data: existing WS handler broadcasts snapshots
- Toast notifications: existing toast system for save/delete feedback
- Dirty tracking: `_cfgOriginal` pattern for config form changes

### Integration Points
- `GET /api/inverters` — existing CRUD API, extend to `/api/devices` or keep
- `GET /api/config` — existing config endpoint
- WebSocket `message` event — currently broadcasts single snapshot, needs per-device tagging
- Sidebar `nav-item` elements — replace static items with dynamic device list
- `app_ctx.devices` dict — already has per-device state from DeviceRegistry

</code_context>

<specifics>
## Specific Ideas

- User wants it "devicespezifisch" — everything organized by device, not by function
- Old "Registers" menu item must go — registers belong to their inverter
- "Config" as global area also goes — each device has its own config
- ESS belongs to Venus OS section, not embedded in dashboard
- Virtual PV contribution table should show Throttle Order + On/Off + current limit %

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 24-device-centric-api-frontend*
*Context gathered: 2026-03-21*
