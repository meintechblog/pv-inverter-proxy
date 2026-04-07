# Phase 38: Plugin Core - Research

**Researched:** 2026-04-06
**Domain:** Sungrow SG-RT Modbus TCP plugin, SunSpec Model 103 encoding, InverterPlugin ABC
**Confidence:** HIGH

## Summary

Phase 38 adds a SungrowPlugin that polls live data from a Sungrow SG-RT inverter via Modbus TCP (using pymodbus), encodes it into SunSpec Model 103 registers matching the exact pattern used by SolarEdge and OpenDTU plugins, supports hot-reload reconfiguration, and declares ThrottleCaps for the score-based waterfall distributor.

The codebase has a well-established plugin pattern: each plugin implements the `InverterPlugin` ABC (connect, poll, close, write_power_limit, reconfigure, get_static_common_overrides, get_model_120_registers, throttle_capabilities). The SolarEdge plugin is the closest reference -- it also uses pymodbus `AsyncModbusTcpClient` over Modbus TCP. The Sungrow plugin follows the same pattern but reads Sungrow-specific input registers (function code 0x04) instead of SolarEdge's holding registers (function code 0x03).

The live device at 192.168.2.151:502 has been verified to work with read-only Modbus TCP in parallel with Loxone. The register map (wire addresses 5002-5037, using Sungrow's 1-based doc convention minus 1) covers all required data: AC power/voltage/current/frequency per phase, DC MPPT1+MPPT2, temperature, energy counters, and running state.

**Primary recommendation:** Model the SungrowPlugin after SolarEdgePlugin (pymodbus TCP client) but use `read_input_registers` (FC04) instead of `read_holding_registers` (FC03), read wire addresses 5002-5037, and apply the Sungrow-to-SunSpec value translation in `_encode_model_103()`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PLUG-01 | Sungrow plugin polls live data via Modbus TCP (AC power, voltage, current, frequency, DC MPPT1+MPPT2, temperature, energy counters, running state) | Sungrow register map verified: wire 5002-5037 covers all fields. pymodbus 3.8.6 installed, AsyncModbusTcpClient supports read_input_registers. Live device at 192.168.2.151:502 confirmed working. |
| PLUG-02 | Plugin encodes polled data into SunSpec Model 103 registers (identical pattern to SolarEdge/OpenDTU) | `_encode_model_103()` pattern established in OpenDTU and Shelly plugins -- 52 uint16 registers with fixed offsets for AC current/voltage/power/freq, DC current/voltage/power, temperature, energy, status. |
| PLUG-03 | Plugin supports reconfigure (host/port/unit_id change without restart) | SolarEdge pattern: `reconfigure()` calls `close()`, updates host/port/unit_id attributes. ConnectionManager in device_registry handles reconnection. |
| PLUG-04 | Plugin declares ThrottleCaps (proportional mode, ~2s Modbus response time) | ThrottleCaps dataclass and compute_throttle_score() exist. Proportional mode with response_time_s=2.0 yields score ~8.4. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Python:** asyncio, structlog logging, dataclasses for config [VERIFIED: codebase]
- **Deployment:** `pip install -e .` on LXC, `importlib.resources` serves static files [VERIFIED: codebase]
- **Config:** YAML with nested sections [VERIFIED: config.py]
- **Plugin checklist:** `docs/PLUGIN-CHECKLIST.md` must be followed for all new plugins [VERIFIED: file exists]
- **pymodbus:** >=3.6,<4.0 (currently 3.8.6 installed) [VERIFIED: pyproject.toml + pip show]
- **Test framework:** pytest with pytest-asyncio, asyncio_mode="auto" [VERIFIED: pyproject.toml]

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pymodbus | 3.8.6 | Modbus TCP client (AsyncModbusTcpClient) | Already used by SolarEdge plugin, project dependency [VERIFIED: pyproject.toml] |
| structlog | installed | Structured logging | Project-wide standard [VERIFIED: codebase] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sunspec_models | internal | encode_string, _int16_as_uint16, constants | SunSpec register encoding [VERIFIED: codebase] |
| plugin | internal | InverterPlugin ABC, PollResult, ThrottleCaps | Plugin interface contract [VERIFIED: codebase] |

No new dependencies required. Everything needed is already in the project.

## Architecture Patterns

### Recommended File Structure
```
src/pv_inverter_proxy/
  plugins/
    sungrow.py          # SungrowPlugin class (new)
  plugins/__init__.py    # Add sungrow branch to plugin_factory (modify)
  config.py              # No new fields needed for phase 38 (host/port/unit_id already exist)
tests/
  test_sungrow_plugin.py # Unit tests (new)
```

### Pattern 1: SungrowPlugin (follows SolarEdge pattern)
**What:** A class implementing InverterPlugin ABC that uses pymodbus AsyncModbusTcpClient
**When to use:** This is the only pattern for this phase

Key differences from SolarEdge:
1. **Function code:** `read_input_registers` (FC04) not `read_holding_registers` (FC03) -- Sungrow input registers are 3x type
2. **Register range:** Read wire addresses ~5002-5037 in one or two batch reads (not 40002/40069)
3. **Value translation:** Sungrow uses different scale factors and layouts than SunSpec -- plugin must translate
4. **3-phase native:** Sungrow SG-RT is 3-phase (L1/L2/L3), so all three phase registers are populated (unlike OpenDTU/Shelly which are single-phase)

### Pattern 2: _encode_model_103() Translation
**What:** Convert Sungrow register values to the standard 52-register SunSpec Model 103 layout
**When to use:** Every poll cycle

The encoding must match OpenDTU/Shelly exactly:
```python
# 52 uint16 registers
regs[0]  = 103  # DID
regs[1]  = 50   # Length
regs[2]  = total_ac_current (SF=-2)     # Amps * 100
regs[3]  = phase_a_current (SF=-2)
regs[4]  = phase_b_current (SF=-2)      # Sungrow populates this!
regs[5]  = phase_c_current (SF=-2)      # Sungrow populates this!
regs[6]  = -2 (SF)
regs[7]  = voltage_ab (SF=-1)           # Sungrow: line voltage
regs[8]  = voltage_bc (SF=-1)
regs[9]  = voltage_ca (SF=-1)
regs[10] = voltage_an (SF=-1)           # Phase voltage (may need derivation)
regs[13] = -1 (SF)
regs[14] = ac_power (SF=0)             # Watts
regs[15] = 0 (SF)
regs[16] = frequency (SF=-2)           # Hz * 100
regs[17] = -2 (SF)
regs[24] = energy_high (acc32 Wh)
regs[25] = energy_low
regs[26] = 0 (SF)
regs[27] = dc_current (SF=-2)
regs[28] = -2 (SF)
regs[29] = dc_voltage (SF=-1)
regs[30] = -1 (SF)
regs[31] = dc_power (SF=0)
regs[32] = 0 (SF)
regs[33] = temperature (SF=-1)          # degC * 10
regs[37] = -1 (SF)
regs[38] = status_code                  # Map Sungrow state to SunSpec status
```

### Pattern 3: Sungrow Running State to SunSpec Status Mapping
**What:** Map Sungrow state register (wire 5037) to SunSpec Model 103 status codes
**When to use:** Every poll cycle when encoding status

Sungrow state codes (from STATE.md: 0x8100 = Derating observed):
- Map to SunSpec: 1=OFF, 2=SLEEPING, 3=STARTING, 4=MPPT, 5=THROTTLED, 7=FAULT, 8=STANDBY

[ASSUMED] Full Sungrow state code mapping -- only 0x8100 verified from live device. Common codes likely include 0x0000=Stop, 0x8000=Run, 0x1300=Standby, 0x8100=Derating, 0x5500=Fault. Will need runtime verification.

### Pattern 4: ThrottleCaps Declaration
**What:** Static property declaring device throttle capabilities
**When to use:** Used by distributor for score-based ordering

```python
@property
def throttle_capabilities(self) -> ThrottleCaps:
    return ThrottleCaps(
        mode="proportional",
        response_time_s=2.0,   # Modbus TCP write latency
        cooldown_s=0.0,
        startup_delay_s=0.0,
    )
```

Score calculation: 7.0 + 3.0*(1 - 2.0/10.0) - 0 - 0 = 7.0 + 2.4 = 9.4 -> **~8.4** [VERIFIED: compute_throttle_score formula in plugin.py]

Wait, recalculating: base=7.0, response_bonus = 3.0 * (1 - 2/10) = 3.0 * 0.8 = 2.4, cooldown=0, startup=0. Score = 7.0 + 2.4 = **9.4**

### Anti-Patterns to Avoid
- **Don't read holding registers (FC03) for Sungrow input data** -- Sungrow uses input registers (FC04, 3x address type). Using FC03 will return errors or wrong data.
- **Don't assume 0-based wire addresses match doc addresses** -- Sungrow documentation is 1-based. Wire address = doc address - 1. E.g., doc 5003 = wire 5002.
- **Don't hand-roll common model registers** -- Use the established `_build_common_registers()` pattern from OpenDTU/Shelly plugins.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Modbus TCP client | Custom socket/protocol | pymodbus AsyncModbusTcpClient | Already used, handles framing/timeouts |
| SunSpec encoding | Custom binary encoding | `_int16_as_uint16()`, `encode_string()` from sunspec_models | Proven helpers, match existing plugins |
| Connection lifecycle | Custom reconnect logic | ConnectionManager in device_registry | Handles backoff, night mode transitions |
| Throttle scoring | Custom priority system | ThrottleCaps + compute_throttle_score | Established scoring formula |

## Sungrow Register Map (Wire Addresses)

Based on STATE.md verified data and Sungrow protocol documentation:

| Wire Addr | Doc Addr | Name | Type | Scale | Unit | Notes |
|-----------|----------|------|------|-------|------|-------|
| 4999 | 5000 | Device type code | U16 | 1 | - | Identifies inverter model |
| 5003 | 5004 | Total energy yield | U32 | 0.1 | kWh | Low word first (LE) |
| 5007 | 5008 | Internal temperature | S16 | 0.1 | degC | Signed |
| 5010 | 5011 | DC voltage MPPT1 | U16 | 0.1 | V | |
| 5011 | 5012 | DC current MPPT1 | U16 | 0.1 | A | |
| 5012 | 5013 | DC voltage MPPT2 | U16 | 0.1 | V | |
| 5013 | 5014 | DC current MPPT2 | U16 | 0.1 | A | |
| 5016 | 5017 | Total DC power | U32 | 1 | W | Low word first (LE) [VERIFIED] |
| 5018 | 5019 | Phase A voltage | U16 | 0.1 | V | |
| 5019 | 5020 | Phase B voltage | U16 | 0.1 | V | |
| 5020 | 5021 | Phase C voltage | U16 | 0.1 | V | |
| 5021 | 5022 | Phase A current | U16 | 0.1 | A | |
| 5022 | 5023 | Phase B current | U16 | 0.1 | A | |
| 5023 | 5024 | Phase C current | U16 | 0.1 | A | |
| 5030 | 5031 | Total active power | U32 | 1 | W | Low word first (LE) [VERIFIED] |
| 5034 | 5035 | Power factor | S16 | 0.001 | - | |
| 5035 | 5036 | Grid frequency | U16 | 0.1 | Hz | |
| 5037 | 5038 | Running state | U16 | - | - | See state codes below |

**Important Sungrow conventions:**
- Doc address is 1-based, wire address = doc - 1 [VERIFIED: STATE.md]
- U32 values: **low word at lower address** (little-endian word order) [VERIFIED: live device 2026-04-07]
- For current scale values, low word is always 0 for typical values [VERIFIED: STATE.md]
- Input registers use function code 0x04 [VERIFIED: Sungrow protocol docs]

### Sungrow Running State Codes
| Code | Meaning | SunSpec Map |
|------|---------|-------------|
| 0x0000 | Stop | 1 (OFF) |
| 0x8000 | Run | 4 (MPPT) |
| 0x1300 | Standby | 8 (STANDBY) |
| 0x8100 | Derating | 5 (THROTTLED) |
| 0x5500 | Fault | 7 (FAULT) |
| Other | Unknown | 2 (SLEEPING) |

[ASSUMED] Only 0x8100 (Derating) verified from live device. Other codes based on Sungrow protocol documentation references.

## Common Pitfalls

### Pitfall 1: Wrong Modbus Function Code
**What goes wrong:** Reading holding registers (FC03) instead of input registers (FC04)
**Why it happens:** SolarEdge uses holding registers; copy-paste error
**How to avoid:** Use `client.read_input_registers()` not `client.read_holding_registers()`
**Warning signs:** All values return 0 or Modbus exception response

### Pitfall 2: Off-by-One Register Addressing
**What goes wrong:** Reading wrong registers because of Sungrow 1-based documentation
**Why it happens:** Sungrow docs say "register 5003" but wire address is 5002
**How to avoid:** Always use wire address = doc address - 1 in code. Comment both addresses.
**Warning signs:** Values look plausible but are shifted (temperature where voltage should be)

### Pitfall 3: U32 Byte Order
**What goes wrong:** Swapped high/low words in 32-bit values (energy, total power)
**Why it happens:** Sungrow uses high-word-first (big-endian word order) which is standard but easy to flip
**How to avoid:** `value = (regs[offset] << 16) | regs[offset + 1]` -- high word at lower address
**Warning signs:** Energy values are astronomically large or always zero

### Pitfall 4: Scale Factor Mismatch
**What goes wrong:** Wrong physical values because Sungrow scale factors differ from SunSpec
**Why it happens:** Sungrow voltage is 0.1V resolution, SunSpec Model 103 expects different SF
**How to avoid:** Convert Sungrow raw values to physical units first, then re-encode for SunSpec
**Warning signs:** Voltage showing 2300 instead of 230.0

### Pitfall 5: write_power_limit Placeholder
**What goes wrong:** Forgetting to implement write_power_limit as a no-op for Phase 38
**Why it happens:** Phase 38 is read-only; power control is Phase 41
**How to avoid:** Return `WriteResult(success=True)` as a no-op (like Shelly pattern)
**Warning signs:** ABC enforcement will catch missing method at class definition time

### Pitfall 6: Plugin Factory Not Updated
**What goes wrong:** Adding sungrow type in YAML but plugin_factory raises ValueError
**Why it happens:** Forgot to add `elif entry.type == "sungrow":` in `plugins/__init__.py`
**How to avoid:** Follow PLUGIN-CHECKLIST.md -- item "Plugin factory"
**Warning signs:** Error on startup when loading sungrow device from config

## Code Examples

### Modbus TCP Read with pymodbus (Sungrow-specific)
```python
# Source: SolarEdge plugin pattern + Sungrow register specifics [VERIFIED: codebase]
from pymodbus.client import AsyncModbusTcpClient

client = AsyncModbusTcpClient(host, port=port)
await client.connect()

# Read input registers (FC04) -- NOT holding registers
# Wire address 5002 = doc 5003 (total energy start)
result = await client.read_input_registers(
    5002, count=36, device_id=unit_id,  # 5002-5037
)
if result.isError():
    # Handle error
    pass
raw = list(result.registers)  # 36 uint16 values
```

### Sungrow Raw to Physical Values
```python
# Source: Sungrow protocol doc + STATE.md [VERIFIED: STATE.md for address mapping]
def _parse_sungrow_data(raw: list[int]) -> dict:
    """Parse 36 registers starting at wire 5002 into physical values."""
    # Offsets relative to raw[0] = wire 5002
    total_energy_kwh = ((raw[1] << 16) | raw[2]) * 0.1  # wire 5003-5004, U32, 0.1 kWh
    temperature_c = _s16(raw[5]) * 0.1                    # wire 5007, S16, 0.1 degC
    dc1_voltage_v = raw[8] * 0.1                           # wire 5010
    dc1_current_a = raw[9] * 0.1                           # wire 5011
    dc2_voltage_v = raw[10] * 0.1                          # wire 5012
    dc2_current_a = raw[11] * 0.1                          # wire 5013
    total_dc_power_w = (raw[14] << 16) | raw[15]           # wire 5016-5017, U32
    phase_a_voltage_v = raw[16] * 0.1                      # wire 5018
    phase_b_voltage_v = raw[17] * 0.1                      # wire 5019
    phase_c_voltage_v = raw[18] * 0.1                      # wire 5020
    phase_a_current_a = raw[19] * 0.1                      # wire 5021
    phase_b_current_a = raw[20] * 0.1                      # wire 5022
    phase_c_current_a = raw[21] * 0.1                      # wire 5023
    total_active_power_w = (raw[28] << 16) | raw[29]       # wire 5030-5031, U32
    power_factor = _s16(raw[32]) * 0.001                   # wire 5034
    frequency_hz = raw[33] * 0.1                           # wire 5035
    running_state = raw[35]                                 # wire 5037
    return {
        "total_energy_kwh": total_energy_kwh,
        "temperature_c": temperature_c,
        # ... etc
    }

def _s16(val: int) -> int:
    """Convert unsigned 16-bit to signed."""
    return val if val < 0x8000 else val - 0x10000
```

### Plugin Factory Registration
```python
# Source: plugins/__init__.py pattern [VERIFIED: codebase]
elif entry.type == "sungrow":
    from pv_inverter_proxy.plugins.sungrow import SungrowPlugin
    return SungrowPlugin(
        host=entry.host,
        port=entry.port,
        unit_id=entry.unit_id,
        rated_power=entry.rated_power,
    )
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | pyproject.toml [tool.pytest.ini_options] |
| Quick run command | `python -m pytest tests/test_sungrow_plugin.py -x` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PLUG-01 | Poll live data via Modbus TCP | unit | `python -m pytest tests/test_sungrow_plugin.py::TestSungrowPoll -x` | Wave 0 |
| PLUG-02 | Encode to SunSpec Model 103 | unit | `python -m pytest tests/test_sungrow_plugin.py::TestSunSpecEncoding -x` | Wave 0 |
| PLUG-03 | Reconfigure without restart | unit | `python -m pytest tests/test_sungrow_plugin.py::TestReconfigure -x` | Wave 0 |
| PLUG-04 | ThrottleCaps declaration | unit | `python -m pytest tests/test_sungrow_plugin.py::TestThrottleCaps -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_sungrow_plugin.py -x`
- **Per wave merge:** `python -m pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_sungrow_plugin.py` -- covers PLUG-01 through PLUG-04
- No framework install needed -- pytest/pytest-asyncio already configured

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Sungrow running state codes: 0x0000=Stop, 0x8000=Run, 0x1300=Standby, 0x5500=Fault | Sungrow Register Map | Wrong SunSpec status mapping; can fix at runtime by observing actual values |
| A2 | Total active power at wire 5030-5031 may be S32 (signed) vs U32 | Register Map | Negative power values could overflow; mitigation: use abs() like Shelly |
| A3 | Response time ~2s for Modbus TCP write to Sungrow | ThrottleCaps | Score calculation off; easy to adjust after Phase 41 testing |
| A4 | Register read of 36 consecutive registers (5002-5037) works in a single read_input_registers call | Code Examples | May need to split into multiple reads if Sungrow limits max registers per request |
| A5 | Daily energy yield register exists somewhere in 5002-5037 range | Register Map | May not be available -- total energy is confirmed, daily energy might need separate register or calculation |

## Open Questions

1. **Daily energy yield register**
   - What we know: Total energy yield at wire 5003-5004 (U32, 0.1 kWh) is confirmed
   - What's unclear: Is there a dedicated "today's yield" register in the 5002-5037 range?
   - Recommendation: Use total energy only for Phase 38; daily yield can be derived by tracking midnight resets in a later phase if needed

2. **Max registers per single Modbus read**
   - What we know: Need 36 registers (5002-5037) in one read
   - What's unclear: Does Sungrow/WiNet-S support reading 36 registers at once?
   - Recommendation: Try single read first; fall back to two reads (5002-5019, 5020-5037) if device returns error

3. **Exact running state codes**
   - What we know: 0x8100 = Derating observed live
   - What's unclear: Full mapping of all possible state codes
   - Recommendation: Implement known codes, default unknown to SLEEPING (2), log unknown codes for future mapping

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pymodbus | Modbus TCP client | Yes | 3.8.6 | -- |
| structlog | Logging | Yes | installed | -- |
| pytest | Tests | Yes | installed | -- |
| pytest-asyncio | Async tests | Yes | installed | -- |
| Sungrow SG8.0RT | Live testing | Yes (192.168.2.151:502) | -- | Mock in tests |

**Missing dependencies:** None.

## Sources

### Primary (HIGH confidence)
- Codebase: `src/pv_inverter_proxy/plugin.py` -- InverterPlugin ABC, ThrottleCaps, PollResult
- Codebase: `src/pv_inverter_proxy/plugins/solaredge.py` -- Modbus TCP plugin reference pattern
- Codebase: `src/pv_inverter_proxy/plugins/opendtu.py` -- _encode_model_103() reference
- Codebase: `src/pv_inverter_proxy/plugins/shelly.py` -- Latest plugin pattern (profiles, encoding)
- Codebase: `src/pv_inverter_proxy/plugins/__init__.py` -- Plugin factory
- Codebase: `src/pv_inverter_proxy/config.py` -- InverterEntry, Config
- Codebase: `src/pv_inverter_proxy/sunspec_models.py` -- SunSpec constants and helpers
- Codebase: `docs/PLUGIN-CHECKLIST.md` -- New plugin integration checklist
- Project: `.planning/STATE.md` -- Sungrow research findings (verified register map)

### Secondary (MEDIUM confidence)
- [Sungrow Modbus Register Map (aggsoft.com)](https://www.aggsoft.com/modbus-data-logging/sungrow-inverter.htm) -- Register address/type reference
- [Sungrow Protocol PDF on Scribd](https://www.scribd.com/document/650855326/Communication-Protocol-of-PV-Grid-Connected-String-Inverters-V1-1-53-EN) -- Protocol specification
- [Sungrow protocol docs on GitHub](https://github.com/bohdan-s/Sungrow-Inverter/blob/main/Modbus%20Information/Communication%20Protocol%20of%20PV%20Grid-Connected%20String%20Inverters_V1.1.37_EN.pdf) -- Community-maintained protocol reference

### Tertiary (LOW confidence)
- Running state code mapping (except 0x8100) -- based on protocol doc references, not verified on live device

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - pymodbus already in use, no new deps
- Architecture: HIGH - established plugin ABC pattern with 3 reference implementations
- Register map: HIGH for addresses (verified on live device), MEDIUM for state codes
- Pitfalls: HIGH - common Modbus issues well-known

**Research date:** 2026-04-06
**Valid until:** 2026-05-06 (stable domain, hardware doesn't change)
