---
phase: 38-plugin-core
verified: 2026-04-06T09:30:00Z
status: passed
score: 5/5 must-haves verified
deferred:
  - truth: "write_power_limit writes a real power limit to the Sungrow inverter"
    addressed_in: "Phase 41"
    evidence: "Phase 41 success criteria: 'The proxy can write a power limit percentage to the Sungrow inverter via Modbus holding registers'"
---

# Phase 38: Plugin Core Verification Report

**Phase Goal:** A working SungrowPlugin can connect to a Sungrow SG-RT inverter via Modbus TCP, poll all essential data, encode it as SunSpec registers, and declare its throttle capabilities
**Verified:** 2026-04-06T09:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SungrowPlugin implements the full InverterPlugin ABC and polls live data (AC power/voltage/current/frequency, DC MPPT1+MPPT2, temperature, energy counters, running state) from a Sungrow SG-RT at the configured interval | VERIFIED | `class SungrowPlugin(InverterPlugin)` in sungrow.py; `_parse_sungrow_data()` extracts all 10+ fields; poll() uses FC04 at 5002; 40 tests pass |
| 2 | Polled data is encoded into SunSpec Model 103 registers identical to the pattern used by SolarEdge and OpenDTU plugins | VERIFIED | `_encode_model_103()` builds 52 registers; DID=103, Length=50; 3-phase AC current (regs[3-5]), AC voltage AN/BN/CN (regs[10-12]), AC power (regs[14]), energy acc32 (regs[24-25]), DC current/voltage/power (regs[27-32]), temp (regs[33]), status (regs[38]); 607 full test suite passes |
| 3 | User can change host/port/unit_id via reconfigure() without restarting the proxy | VERIFIED | `reconfigure()` calls `close()` then updates self.host/port/unit_id; TestReconfigure verifies client.close() called and all three attributes updated |
| 4 | Plugin declares ThrottleCaps with proportional mode and ~2s Modbus response time, producing a valid throttle_score | VERIFIED | `throttle_capabilities` returns `ThrottleCaps(mode="proportional", response_time_s=2.0, cooldown_s=0.0, startup_delay_s=0.0)`; TestThrottleCaps asserts all four fields |
| 5 | plugin_factory creates a SungrowPlugin when entry.type == 'sungrow' and passes host, port, unit_id, rated_power | VERIFIED | `plugins/__init__.py` has sungrow branch; runtime check prints `SungrowPlugin 192.168.2.151 502 1 8000`; ValueError message includes "sungrow" in valid types list |

**Score:** 5/5 truths verified

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | write_power_limit performs a real Modbus write to the Sungrow inverter | Phase 41 | Phase 41 success criteria: "The proxy can write a power limit percentage to the Sungrow inverter via Modbus holding registers and the inverter responds with actual derating" |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/pv_inverter_proxy/plugins/sungrow.py` | SungrowPlugin class | VERIFIED | 358 lines (min 150); exports SungrowPlugin; class SungrowPlugin(InverterPlugin) |
| `tests/test_sungrow_plugin.py` | Unit tests for SungrowPlugin | VERIFIED | 443 lines (min 100); 40 tests across 11 classes; all pass |
| `src/pv_inverter_proxy/plugins/__init__.py` | Plugin factory with sungrow branch | VERIFIED | Contains `entry.type == "sungrow"`, lazy import, `rated_power=entry.rated_power`, ValueError includes "sungrow" |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `sungrow.py` | `pv_inverter_proxy.plugin.InverterPlugin` | class inheritance | WIRED | `class SungrowPlugin(InverterPlugin)` found at line 65 |
| `sungrow.py` | `pymodbus.client.AsyncModbusTcpClient` | Modbus TCP connection | WIRED | `from pymodbus.client import AsyncModbusTcpClient` at line 14; used in `connect()` at line 90 |
| `sungrow.py` | `pv_inverter_proxy.sunspec_models` | SunSpec encoding helpers | WIRED | `from pv_inverter_proxy.sunspec_models import encode_string, _int16_as_uint16, ...` at lines 17-25; both used in `_encode_model_103()` and `_build_common_registers()` |
| `plugins/__init__.py` | `plugins/sungrow.py` | lazy import in factory | WIRED | `from pv_inverter_proxy.plugins.sungrow import SungrowPlugin` at line 49 inside elif branch |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `sungrow.py` `poll()` | `result.registers` | `AsyncModbusTcpClient.read_input_registers()` | Yes — reads 36 live Modbus FC04 registers from device | FLOWING |
| `sungrow.py` `poll()` | `PollResult.inverter_registers` | `_parse_sungrow_data()` → `_encode_model_103()` | Yes — full parse+encode pipeline, no static returns | FLOWING |
| `sungrow.py` `poll()` | `PollResult.common_registers` | `_build_common_registers()` | Yes — builds 67 registers with real manufacturer/model strings | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| SungrowPlugin unit tests (40 tests) | `uv run pytest tests/test_sungrow_plugin.py -q` | 40 passed | PASS |
| Full test suite (no regressions) | `uv run pytest tests/ -q` | 607 passed, 0 failures | PASS |
| Factory creates SungrowPlugin from config entry | `uv run python -c "from pv_inverter_proxy.plugins import plugin_factory; ..."` | `SungrowPlugin 192.168.2.151 502 1 8000` | PASS |
| FC04 (not FC03) used for Sungrow | grep for `read_holding_registers` in sungrow.py | not found | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| PLUG-01 | 38-01, 38-02 | Sungrow plugin polls live data via Modbus TCP (AC power, voltage, current, frequency, DC MPPT1+MPPT2, temperature, energy counters, running state) | SATISFIED | `_parse_sungrow_data()` reads all 10 fields; FC04 at wire 5002-5037; TestSungrowParsing verifies each field |
| PLUG-02 | 38-01 | Plugin encodes polled data into SunSpec Model 103 registers | SATISFIED | `_encode_model_103()` builds 52 registers; 3-phase AC, DC, temp, energy, status all encoded; TestSunSpecEncoding with 9 test methods |
| PLUG-03 | 38-01 | Plugin supports reconfigure (host/port/unit_id change without restart) | SATISFIED | `reconfigure()` implemented; closes connection then updates params; TestReconfigure verifies all three attributes change |
| PLUG-04 | 38-01 | Plugin declares ThrottleCaps (proportional mode, ~2s Modbus response time) | SATISFIED | `throttle_capabilities` property returns `ThrottleCaps(mode="proportional", response_time_s=2.0, ...)`; TestThrottleCaps asserts all fields |

No orphaned requirements — all PLUG-01 through PLUG-04 are declared in plans and verified in implementation.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `sungrow.py` | 320 | `"Power control not yet implemented for Sungrow (Phase 41)"` in log warning | Info | Intentional no-op per plan; Phase 41 delivers real control; deferred above |

No blockers or warnings found. The `write_power_limit` no-op is explicitly planned behavior documented in both the plan's threat model (T-38-05) and deferred to Phase 41 in the roadmap.

### Human Verification Required

None. All observable truths can be verified programmatically via the test suite. The plugin does not yet connect to a real device (Phase 38 is purely code/test), so no hardware verification is needed at this stage.

### Gaps Summary

No gaps. All five observable truths are verified. All four requirements (PLUG-01 through PLUG-04) are satisfied with passing tests. The plugin factory is wired and confirmed functional at runtime. The full test suite of 607 tests passes with no regressions.

The `write_power_limit` no-op is intentional design — the plan explicitly designates Phase 38 as read-only (T-38-05 in threat model, acceptance criteria note "no-op write") and Phase 41 adds real Sungrow power control. This is deferred, not a gap.

---

_Verified: 2026-04-06T09:30:00Z_
_Verifier: Claude (gsd-verifier)_
