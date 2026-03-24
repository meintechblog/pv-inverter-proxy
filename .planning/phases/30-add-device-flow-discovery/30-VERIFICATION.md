---
phase: 30-add-device-flow-discovery
verified: 2026-03-24T08:40:52Z
status: human_needed
score: 11/11 must-haves verified
human_verification:
  - test: "Open webapp at http://192.168.3.191:8080. Click + to open Add Device dialog. Confirm three cards appear: SolarEdge Inverter, OpenDTU Inverter, Shelly Device."
    expected: "Shelly Device card is visible as third option."
    why_human: "DOM rendering cannot be verified from grep alone."
  - test: "Click Shelly Device card. Confirm form shows Name (optional), Host IP, Rated Power (W) fields and no Port or Unit ID fields."
    expected: "Three fields visible; Port and Unit ID absent."
    why_human: "Conditional DOM omission requires visual confirmation."
  - test: "Enter a reachable Shelly IP and click Add. Confirm a green hint-card appears in the form area (not a toast) showing generation and model before the save call completes."
    expected: "Green hint-card with text 'Detected Gen2 — Plus1PM' (or similar) visible inside form, not as a floating toast."
    why_human: "Probe timing and hint-card placement require live browser test."
  - test: "Enter an unreachable IP (e.g. 192.168.99.1) and click Add. Confirm an orange hint-card with error text appears inside the form area."
    expected: "Orange hint-card with 'Could not reach device' visible in form; no page navigation."
    why_human: "Error path UX requires live browser test."
  - test: "With Shelly Device selected, click Discover. Confirm mDNS scan runs and results appear as a checkbox list using ve-scan-result rows (or the empty-state hint about Gen1 if no devices found)."
    expected: "No Modbus scan triggered; Shelly-specific mDNS scan runs. Results show host IP and generation label."
    why_human: "Branch logic in Discover handler requires runtime verification."
  - test: "Navigate to an added Shelly device's config page. Confirm Generation is shown as a readonly blue badge (not an editable field) and Rated Power is editable. Change Rated Power and confirm Save/Cancel buttons appear."
    expected: "ve-gen-badge renders in blue; Rated Power input triggers dirty tracking; Save/Cancel appear."
    why_human: "CSS badge rendering and dirty-tracking behavior require visual and interactive verification."
---

# Phase 30: Add Device Flow & Discovery Verification Report

**Phase Goal:** Users can add Shelly devices through the webapp with automatic generation detection, and discover Shelly devices on the LAN
**Verified:** 2026-03-24T08:40:52Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | POST /api/shelly/probe with a valid Shelly IP returns generation, model, and mac | VERIFIED | `shelly_probe_handler` at webapp.py:1401 calls `probe_shelly_device(host)` and returns result; test_probe_gen2/gen3/gen1 all pass |
| 2 | POST /api/shelly/probe with an unreachable IP returns success=false with error message | VERIFIED | `probe_shelly_device` except clause at shelly_discovery.py:167 returns `{"success": False, "error": ...}`; `test_probe_unreachable` passes |
| 3 | POST /api/shelly/discover returns a list of Shelly devices found via mDNS _shelly._tcp | VERIFIED | `shelly_discover_handler` at webapp.py:1412 calls `discover_shelly_devices`; route registered at webapp.py:1906 |
| 4 | Discovery results include host IP, device name, generation, and model for each device | VERIFIED | `shelly_discovery.py:71-78` builds dict with host, name, generation, model, firmware |
| 5 | Discovery results exclude devices already configured in the proxy | VERIFIED | `shelly_discover_handler` builds `existing_ips` set and passes as `skip_ips`; `test_discover_skips_existing_ips` passes |
| 6 | Add-device dialog shows Shelly Device as third option alongside SolarEdge and OpenDTU | VERIFIED | app.js:1906 `data-type="shelly">Shelly Device</div>` present in `showAddDeviceModal()` |
| 7 | Shelly form shows Host IP, Name, and Rated Power fields | VERIFIED | app.js:1959-1964 shows the three ve-form-group blocks with ve-add-host, ve-add-name, ve-add-rated-power |
| 8 | Clicking Add probes the Shelly device and shows green hint-card with generation on success | VERIFIED (code) | app.js:2056-2094 implements probe flow with ve-hint-card--success on result.success; NEEDS HUMAN for visual |
| 9 | Clicking Add shows orange hint-card with error on probe failure so user can correct IP | VERIFIED (code) | app.js:2080-2084 sets className to ve-hint-card (orange) on failure; NEEDS HUMAN for visual |
| 10 | Clicking Discover with Shelly selected runs mDNS discovery, not Modbus scan | VERIFIED (code) | app.js:2101-2107 branches on `type === 'shelly'` → `triggerShellyDiscover`; NEEDS HUMAN for runtime |
| 11 | Shelly device config page shows Host (editable), Generation (readonly), Rated Power (editable) | VERIFIED (code) | app.js:1015-1022 hides Port/UnitID for shelly, shows ve-gen-badge + ve-cfg-rated-power; NEEDS HUMAN for visual |

**Score:** 11/11 truths verified (6 automated, 5 require human for visual/interactive confirmation)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/pv_inverter_proxy/shelly_discovery.py` | mDNS discovery and HTTP probe | VERIFIED | 176 lines; exports `SHELLY_SERVICE_TYPE`, `discover_shelly_devices`, `probe_shelly_device`; Gen1/Gen2/Gen3 detection |
| `tests/test_shelly_discovery.py` | Unit tests for probe and discovery | VERIFIED | 9 tests; `TestShellyDiscovery` (5) + `TestProbeHandler` (4); all pass |
| `src/pv_inverter_proxy/static/app.js` | Shelly add-device flow, probe, discovery, config fields | VERIFIED | Contains `data-type="shelly"`, probe flow, `triggerShellyDiscover`, ve-gen-badge, ve-cfg-rated-power |
| `src/pv_inverter_proxy/static/style.css` | Generation badge styling | VERIFIED | `.ve-gen-badge` at line 1808 uses `var(--ve-blue-dim)`, `var(--ve-text)`, `var(--ve-radius-sm)` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| webapp.py | shelly_discovery.py | `from pv_inverter_proxy.shelly_discovery import discover_shelly_devices, probe_shelly_device` | WIRED | webapp.py:36 |
| webapp.py | /api/shelly/probe | `app.router.add_post` | WIRED | webapp.py:1905 |
| webapp.py | /api/shelly/discover | `app.router.add_post` | WIRED | webapp.py:1906 |
| app.js | /api/shelly/probe | `fetch` in Add button handler | WIRED | app.js:2061 |
| app.js | /api/shelly/discover | `fetch` in `triggerShellyDiscover` | WIRED | app.js:2152 |
| app.js | /api/devices POST | `payload.shelly_gen = result.generation` before `_doAdd()` | WIRED | app.js:2076; `_doAdd` at app.js:2010 posts payload |
| webapp.py inverters_add_handler | InverterEntry constructor | `shelly_gen=body.get("shelly_gen", "")` | WIRED | webapp.py:1612-1613 |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| UI-01 | 30-02 | Shelly Device as third option in Add-Device Dialog | SATISFIED | app.js:1906 `data-type="shelly">Shelly Device` |
| UI-02 | 30-01, 30-02 | Auto-Detection and Generation display when adding | SATISFIED | `probe_shelly_device` returns gen1/gen2/gen3; hint-card shows result; 4 probe tests pass |
| UI-05 | 30-02 | Config page with Shelly Host and readonly Generation | SATISFIED (code) | app.js:1015-1022 shows ve-gen-badge (readonly) and ve-cfg-rated-power (editable); NEEDS HUMAN visual |
| UI-06 | 30-01 | Auto-Discovery of Shelly devices on LAN | SATISFIED | POST /api/shelly/discover via mDNS; skip_ips dedup; 5 discovery tests pass |

All 4 requirement IDs declared in plan frontmatter (`[UI-01, UI-02, UI-05, UI-06]`) are accounted for.

No ORPHANED requirements: REQUIREMENTS.md traceability table assigns UI-01, UI-02, UI-05, UI-06 to Phase 30, matching plan declarations exactly.

### Post-Plan Fixes Verified

The additional context noted several fixes applied during user testing. All are present in the codebase:

| Fix | File | Evidence |
|-----|------|----------|
| Gen3 detection (gen_value >= 3 → "gen3") | shelly_discovery.py:129-132 | Explicit Gen3 branch; `test_probe_gen3_device` passes |
| Discovery results use existing ve-scan-result CSS classes | app.js:2173-2178 | Uses `ve-scan-result`, `ve-scan-result-check`, `ve-scan-result-identity`, `ve-scan-result-host`, `ve-scan-result-unit` — all defined in style.css:1885-1920 |
| Switch names from /rpc/Switch.GetConfig and /shelly name | shelly_discovery.py:86-102; shelly_discovery.py:146-157 | Both probe and discover fetch switch_name via `/rpc/Switch.GetConfig?id=0` and `/shelly` |
| Config fields rated_power, throttle_order, shelly_gen in _build_device_list and device_snapshot | webapp.py:852-861, 1529-1553 | All three fields present in both `_build_device_list` (lines 852, 853, 861) and `device_snapshot_handler` (lines 1529-1553) |
| Register viewer dynamic headers per device type | app.js:2603-2608 | `_activeDeviceType === 'shelly'` branch sets sourceLabel = 'Shelly Source' |
| Single-phase AC view (no L1/L2/L3) for Shelly via buildDCChannelCard | app.js:579 | `deviceType === 'shelly'` triggers `buildDCChannelCard` (single AC row, no phase columns) |
| DC section hidden when no DC data | app.js:778, 794 | DC Strings block rendered only `if (channels.length > 0)`; fallback only `if (inv.dc_voltage_v || inv.dc_current_a || inv.dc_power_w)` |
| Shelly relay On/Off buttons in connection card | app.js:599-631 | `deviceType === 'shelly'` branch adds Switch On / Switch Off buttons with `/api/devices/{id}/shelly/switch` |
| Power limit dropdowns hidden for Shelly | app.js:468 | `ratedW > 0 && deviceType !== 'shelly'` guards the clamp dropdown build |
| abs() for negative power values in SunSpec encoding | plugins/shelly.py:147-148 | `power_w = abs(data.power_w)` and `current_a = abs(data.current_a)` |

### Anti-Patterns Found

None found in phase-modified files. No TODO/FIXME/placeholder patterns, empty return values, or stub handlers detected.

### Human Verification Required

#### 1. Shelly type card visible in Add Device dialog

**Test:** Open http://192.168.3.191:8080. Click + button. Verify three type cards appear: "SolarEdge Inverter", "OpenDTU Inverter", "Shelly Device".
**Expected:** All three cards visible side by side.
**Why human:** DOM rendering and CSS layout cannot be verified from source alone.

#### 2. Shelly form fields and hidden Port/UnitID

**Test:** Click Shelly Device card. Verify the form shows Name (optional), Host IP, Rated Power (W) — and does NOT show Port or Unit ID.
**Expected:** Exactly three form fields; Modbus fields absent.
**Why human:** Conditional omission of DOM nodes requires visual confirmation.

#### 3. Probe success — green hint-card in form area

**Test:** Enter a reachable Shelly IP (e.g. an actual device on the LAN) and click Add. Verify a green hint-card appears inside the form area (not a floating toast) with the generation and model name.
**Expected:** Green hint-card with "Detected Gen2 — Plus1PM" (or matching device info) visible inline before dialog closes.
**Why human:** Hint-card timing, color, and placement require a live browser test with real device.

#### 4. Probe failure — orange hint-card in form area

**Test:** Enter an unreachable IP (e.g. 192.168.99.254) and click Add. Verify an orange hint-card with an error message appears inside the form area, not a toast. Dialog stays open.
**Expected:** Orange hint-card with "Could not reach device" and error detail visible; no navigation.
**Why human:** Error path UX requires live browser test.

#### 5. Discover button runs mDNS, not Modbus scan

**Test:** With Shelly Device selected, click Discover. Verify the scan runs and results appear as a checkbox list with device name, IP, and generation — or shows the empty-state hint about Gen1 devices.
**Expected:** No Modbus range scan; Shelly-specific mDNS flow runs; results styled with ve-scan-result rows.
**Why human:** Runtime branch selection and visual result rendering require browser test.

#### 6. Config page — readonly generation badge and editable rated power

**Test:** Navigate to an added Shelly device's config page. Verify: (a) Generation shows as a blue badge (not an editable input), (b) Rated Power is an editable number input, (c) Port and Unit ID fields are absent, (d) changing Rated Power makes Save/Cancel buttons appear.
**Expected:** Blue ve-gen-badge renders correctly; dirty tracking activates on Rated Power change.
**Why human:** CSS badge appearance and interactive dirty tracking require visual + interaction verification.

### Gaps Summary

No gaps blocking goal achievement. All code paths exist, are wired, and the full test suite (531 tests) passes. Phase goal is satisfied at the code level. Six items require human visual/interactive confirmation as documented above — these are UX quality checks, not missing functionality.

---

_Verified: 2026-03-24T08:40:52Z_
_Verifier: Claude (gsd-verifier)_
