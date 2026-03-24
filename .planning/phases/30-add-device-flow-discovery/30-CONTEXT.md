# Phase 30: Add-Device Flow & Discovery - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Add Shelly as a third device type in the webapp add-device flow. Users can manually enter a Shelly IP (with auto-generation-probe on Add click), or discover Shelly devices on the LAN via mDNS. The device config page shows Shelly-specific fields. No dashboard changes in this phase — that's Phase 31.

</domain>

<decisions>
## Implementation Decisions

### Shelly Add-Form Fields
- **D-01:** Add-device modal shows "Shelly Device" as third type card alongside "SolarEdge Inverter" and "OpenDTU Inverter"
- **D-02:** Shelly form fields: Host IP (required), Name (optional), Rated Power in W (optional, default 0)
- **D-03:** Rated power defaults to 0W (empty). User fills in if Shelly monitors a micro-inverter for WRtg aggregation

### Generation Probe UX
- **D-04:** Generation probe triggers automatically on Add click (single-click flow). User enters IP, clicks Add, app probes /shelly, shows result, saves
- **D-05:** Successful probe shows green hint-card in the form area with detected generation (Gen1/Gen2/Gen3) and model name, then auto-saves
- **D-06:** Failed probe (unreachable, not a Shelly) shows hint-card in the form area (not a toast) so user can correct the IP and retry. Consistent with existing OpenDTU auth-test pattern

### Shelly Discovery Method
- **D-07:** Discovery uses mDNS (`_shelly._tcp` service) as primary method via zeroconf library. Faster and more reliable than IP-range HTTP scanning
- **D-08:** Discover button scope is type-filtered: when Shelly is selected, only mDNS discovery runs. Existing Modbus/SunSpec scan runs only when SolarEdge is selected
- **D-09:** Discovery results show in the same checkbox-list pattern as existing scan results (Phase 20 pattern)

### Config Page Fields
- **D-10:** Shelly device config page shows: Host IP (editable), Generation (readonly badge — Gen1/Gen2), Rated Power (editable, W)
- **D-11:** Generation is readonly because it's auto-detected and cannot change for a given device

### Claude's Discretion
- Exact hint-card text for successful/failed probe
- mDNS browse timeout duration
- Discovery result card styling details
- How to handle mDNS unavailability (fallback or error message)
- Whether to show MAC/firmware info from /shelly response in discovery results

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Add-Device Flow (existing pattern)
- `src/pv_inverter_proxy/static/app.js` lines 1833-1998 — showAddDeviceModal(), showAddForm(), type picker, discover flow
- `src/pv_inverter_proxy/static/style.css` — ve-add-modal, ve-add-type-card, ve-add-form-area styles

### Discovery Infrastructure
- `src/pv_inverter_proxy/scanner.py` — Existing Modbus SunSpec scanner with progress_callback
- `src/pv_inverter_proxy/webapp.py` — scan_handler, inverters_add_handler patterns

### Plugin System
- `src/pv_inverter_proxy/plugins/shelly.py` — ShellyPlugin with connect() auto-detection
- `src/pv_inverter_proxy/plugins/shelly_profiles.py` — Gen1Profile, Gen2Profile
- `src/pv_inverter_proxy/config.py` — InverterEntry with type and shelly_gen fields

### Prior Phase Context
- `.planning/phases/20-discovery-ui-onboarding/20-CONTEXT.md` — Discovery UI patterns (progress bar, checkbox results, auto-scan)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `showAddDeviceModal()` — Type picker pattern, just add third card
- `showAddForm()` — Form rendering per type, add "shelly" branch
- `triggerAddModalScan()` — Scan flow with progress bar + WebSocket updates
- `ve-add-type-card`, `ve-hint-card` CSS classes — Established UI patterns

### Established Patterns
- Type picker: `data-type` attribute on `.ve-add-type-card` elements
- Form rendering: switch on `type` in `showAddForm()` function
- Auto-test before add: OpenDTU does `fetch('/api/opendtu/test-auth')` before saving — same pattern for Shelly probe
- Discovery: WebSocket-streamed progress + checkbox result list

### Integration Points
- `webapp.py inverters_add_handler` — Already handles `type` field, needs Shelly probe endpoint
- `plugins/__init__.py plugin_factory` — Already handles `type="shelly"`
- `config.py InverterEntry` — Already has `shelly_gen` field

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches following existing patterns.

</specifics>

<deferred>
## Deferred Ideas

- **Plugin Deployment Runbook** — User wants a standardized guide for how to deploy new plugins uniformly. Belongs in documentation, not a phase.

</deferred>

---

*Phase: 30-add-device-flow-discovery*
*Context gathered: 2026-03-24*
