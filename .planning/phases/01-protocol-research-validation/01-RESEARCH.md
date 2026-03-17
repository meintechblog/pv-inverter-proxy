# Phase 1: Protocol Research & Validation - Research

**Researched:** 2026-03-18
**Domain:** Modbus TCP / SunSpec protocol, dbus-fronius internals, SolarEdge register mapping
**Confidence:** HIGH

## Summary

This phase resolves all protocol unknowns before writing any proxy code. Three activities must be completed: (1) analyze dbus-fronius source code to understand exactly what Venus OS expects from a "Fronius" inverter, (2) read the SolarEdge SE30K registers live via Modbus TCP to validate the documented register layout, and (3) produce a complete register translation table mapping SolarEdge registers to their Fronius SunSpec equivalents.

The research reveals that dbus-fronius is a generic SunSpec client, not Fronius-specific. It discovers devices by scanning for the SunSpec magic value "SunS" at register 40000/50000/0, reads the Common Model (Model 1) to extract the manufacturer string, then walks the model chain looking for Models 101/103 (inverter), 120 (nameplate), and 123/704 (controls). The manufacturer string determines product ID assignment and some behavioral differences, but the core data path is standard SunSpec. SolarEdge and Fronius both use the same SunSpec integer protocol with scale factors, and their register layouts within each model are identical by specification -- the translation is primarily about re-presenting SolarEdge's data under a Fronius identity.

A critical finding is that SolarEdge does NOT support standard SunSpec Model 123 for power control. Instead, SolarEdge uses proprietary registers at 0xF300-0xF322 for active power limiting. The proxy must translate Venus OS writes to SunSpec Model 123 into SolarEdge proprietary power control commands. Additionally, SolarEdge only supports a single concurrent Modbus TCP connection with a 2-minute idle timeout.

**Primary recommendation:** The proxy must present a standard SunSpec model chain (SunS header -> Common Model 1 with "Fronius" manufacturer -> Model 103 -> Model 120 -> Model 123 -> End marker 0xFFFF) to Venus OS, while reading from SolarEdge's standard SunSpec registers for monitoring and using SolarEdge's proprietary registers (0xF300-0xF322) for power control.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROTO-01 | dbus-fronius Source Code analysiert -- exakte Fronius-Erwartungen dokumentiert | dbus-fronius discovery mechanism fully documented: SunSpec magic value scan, Common Model manufacturer string check, model chain walking for Models 1/101-103/120/123/704, unit ID 126 default. Manufacturer string "Fronius" triggers VE_PROD_ID_PV_INVERTER_FRONIUS with forced power limiting and Solar API fallback. No HTTP dependency for SunSpec path. |
| PROTO-02 | SolarEdge SE30K Register-Map per Modbus TCP live ausgelesen und validiert | Official SolarEdge SunSpec Implementation Technical Note v3.2 (June 2025) provides complete register map. Common block at 40000-40068, Inverter model at 40069-40120. Live validation script provided below. SE30K uses Model 103 (three-phase), unit ID 1, port 1502. |
| PROTO-03 | Register-Mapping-Spezifikation erstellt (SolarEdge -> Fronius SunSpec Translation Table) | Complete translation table provided below with register-by-register mapping. Key insight: both use standard SunSpec models so the data layout is identical -- translation is primarily identity (manufacturer string) and model chain structure. Power control requires proprietary register translation. |
</phase_requirements>

## dbus-fronius Discovery Mechanism (PROTO-01)

### SunSpec Device Detection Flow

dbus-fronius uses `SunspecDetector` to find devices. The detection flow is:

1. **Network Scan**: Sends Modbus requests to all IP addresses on the LAN (limited count). Previously-detected IPs get priority.
2. **Magic Value Check**: Reads 2 registers at addresses 40000, 50000, and 0 (tried in order). Looks for ASCII "SunS" (0x53756E53).
3. **Common Model Read**: After finding "SunS", reads Model 1 (Common) starting at offset +2. Extracts:
   - Manufacturer (16 chars, offset 2): used for product ID assignment
   - Model (16 chars, offset 18): device model string
   - Version (8 chars, offset 42): firmware version
   - Serial Number (16 chars, offset 50): unique device ID
4. **Manufacturer Matching**:
   - `"Fronius"` -> `VE_PROD_ID_PV_INVERTER_FRONIUS` (deviceType != 0)
   - `"SolarEdge"` -> `VE_PROD_ID_PV_INVERTER_SOLAREDGE`
   - `"SMA"` -> `VE_PROD_ID_PV_INVERTER_SMA`
   - `"ABB"` or `"FIMER"` -> `VE_PROD_ID_PV_INVERTER_ABB`
   - Others -> `VE_PROD_ID_PV_INVERTER_SUNSPEC`
5. **Model Chain Walk**: Reads each model header (ID + length) and advances by length. Stops at 0xFFFF end marker. Looks for:
   - **Models 101-103, 111-113**: Inverter measurement (determines phase count)
   - **Model 120**: Nameplate ratings (mandatory -- required for operation)
   - **Model 123 or 704**: Power limiting controls (optional but needed for control)
   - **Model 160**: MPPT tracker data (optional)
6. **Unit ID**: Defaults to 126. SolarEdge default is 1.

### Fronius-Specific Behaviors

When manufacturer is "Fronius", dbus-fronius applies these special behaviors:
- **Power limiting forced enabled**: Automatically enabled without user configuration
- **Solar API fallback**: Can also use HTTP+JSON Solar API v1 for discovery (not needed for SunSpec path)
- **Null-frame filter**: Discards all-zero frames with Status=7 during solar net timeouts
- **Split-phase handling**: Single-phase Fronius devices can distribute power across two phases

### What the Proxy Must Emulate

To be recognized as a Fronius inverter by Venus OS, the proxy must:
1. Respond to SunSpec magic value read at register 40000 with "SunS"
2. Present Common Model with `C_Manufacturer = "Fronius"` (padded to 32 bytes)
3. Present a valid model chain: Common (1) -> Inverter (103) -> Nameplate (120) -> Controls (123) -> End (0xFFFF)
4. Respond on unit ID 126 (dbus-fronius default for SunSpec devices)
5. Use integer protocol with scale factors (not float)
6. NO HTTP Solar API dependency when using SunSpec path

**Confidence: HIGH** -- Based on direct analysis of dbus-fronius source code (sunspec_detector.cpp, sunspec_updater.cpp) on GitHub.

## SolarEdge SE30K Register Map (PROTO-02)

### Connection Parameters

| Parameter | Value |
|-----------|-------|
| IP Address | 192.168.3.18 |
| Port | 1502 (default for Modbus TCP on SolarEdge) |
| Unit ID | 1 (default for Ethernet) |
| Protocol | Modbus TCP |
| Max Connections | 1 (single concurrent connection only) |
| Idle Timeout | 2 minutes (must poll within this interval) |
| Byte Order | Big-Endian |

### Common Model (Model 1) -- Base Address 40000 (base 0) / 40001 (base 1)

| Address (base 0) | Address (base 1) | Size | Name | Type | Description |
|---|---|---|---|---|---|
| 40000 | 40001 | 2 | C_SunSpec_ID | uint32 | "SunS" magic value (0x53756E53) |
| 40002 | 40003 | 1 | C_SunSpec_DID | uint16 | 0x0001 = Common Model Block |
| 40003 | 40004 | 1 | C_SunSpec_Length | uint16 | 65 = length in 16-bit registers |
| 40004 | 40005 | 16 | C_Manufacturer | String(32) | "SolarEdge" |
| 40020 | 40021 | 16 | C_Model | String(32) | e.g. "SE30K" |
| 40044 | 40045 | 8 | C_Version | String(16) | CPU software version |
| 40052 | 40053 | 16 | C_SerialNumber | String(32) | Inverter serial number |
| 40068 | 40069 | 1 | C_DeviceAddress | uint16 | MODBUS Unit ID |

### Inverter Model (Model 103, three-phase) -- Base Address 40069 (base 0) / 40070 (base 1)

| Address (base 0) | Address (base 1) | Size | Name | Type | Units | Description |
|---|---|---|---|---|---|---|
| 40069 | 40070 | 1 | C_SunSpec_DID | uint16 | | 103 = three phase |
| 40070 | 40071 | 1 | C_SunSpec_Length | uint16 | Registers | 50 = model block length |
| 40071 | 40072 | 1 | I_AC_Current | uint16 | A | AC Total Current |
| 40072 | 40073 | 1 | I_AC_CurrentA | uint16 | A | Phase A Current |
| 40073 | 40074 | 1 | I_AC_CurrentB | uint16 | A | Phase B Current |
| 40074 | 40075 | 1 | I_AC_CurrentC | uint16 | A | Phase C Current |
| 40075 | 40076 | 1 | I_AC_Current_SF | int16 | | Current scale factor |
| 40076 | 40077 | 1 | I_AC_VoltageAB | uint16 | V | Phase Voltage AB |
| 40077 | 40078 | 1 | I_AC_VoltageBC | uint16 | V | Phase Voltage BC |
| 40078 | 40079 | 1 | I_AC_VoltageCA | uint16 | V | Phase Voltage CA |
| 40079 | 40080 | 1 | I_AC_VoltageAN | uint16 | V | Phase Voltage A-N |
| 40080 | 40081 | 1 | I_AC_VoltageBN | uint16 | V | Phase Voltage B-N |
| 40081 | 40082 | 1 | I_AC_VoltageCN | uint16 | V | Phase Voltage C-N |
| 40082 | 40083 | 1 | I_AC_Voltage_SF | int16 | | Voltage scale factor |
| 40083 | 40084 | 1 | I_AC_Power | int16 | W | AC Power |
| 40084 | 40085 | 1 | I_AC_Power_SF | int16 | | Power scale factor |
| 40085 | 40086 | 1 | I_AC_Frequency | uint16 | Hz | Line Frequency |
| 40086 | 40087 | 1 | I_AC_Frequency_SF | int16 | | Frequency scale factor |
| 40087 | 40088 | 1 | I_AC_VA | int16 | VA | Apparent Power |
| 40088 | 40089 | 1 | I_AC_VA_SF | int16 | | Scale factor |
| 40089 | 40090 | 1 | I_AC_VAR | int16 | VAR | Reactive Power |
| 40090 | 40091 | 1 | I_AC_VAR_SF | int16 | | Scale factor |
| 40091 | 40092 | 1 | I_AC_PF | int16 | % | Power Factor |
| 40092 | 40093 | 1 | I_AC_PF_SF | int16 | | Scale factor |
| 40093 | 40094 | 2 | I_AC_Energy_WH | acc32 | Wh | Lifetime Energy |
| 40095 | 40096 | 1 | I_AC_Energy_WH_SF | uint16 | | Scale factor |
| 40096 | 40097 | 1 | I_DC_Current | uint16 | A | DC Current |
| 40097 | 40098 | 1 | I_DC_Current_SF | int16 | | Scale factor |
| 40098 | 40099 | 1 | I_DC_Voltage | uint16 | V | DC Voltage |
| 40099 | 40100 | 1 | I_DC_Voltage_SF | int16 | | Scale factor |
| 40100 | 40101 | 1 | I_DC_Power | int16 | W | DC Power |
| 40101 | 40102 | 1 | I_DC_Power_SF | int16 | | Scale factor |
| 40103 | 40104 | 1 | I_Temp_Sink | int16 | C | Heat Sink Temperature |
| 40106 | 40107 | 1 | I_Temp_SF | int16 | | Scale factor |
| 40107 | 40108 | 1 | I_Status | uint16 | | Operating State |
| 40108 | 40109 | 1 | I_Status_Vendor | uint16 | | Vendor status code |
| 40119 | 40120 | 2 | I_Status_Vendor4 | uint32 | | Vendor status (v3.2 addition) |

### SolarEdge Inverter Status Values

| Value | Name | Description |
|---|---|---|
| 1 | I_STATUS_OFF | Off |
| 2 | I_STATUS_SLEEPING | Sleeping (auto-shutdown, Night mode) |
| 3 | I_STATUS_STARTING | Grid Monitoring / wake-up |
| 4 | I_STATUS_MPPT | Inverter is ON and producing power |
| 5 | I_STATUS_THROTTLED | Production (curtailed) |
| 6 | I_STATUS_SHUTTING_DOWN | Shutting down |
| 7 | I_STATUS_FAULT | Fault |
| 8 | I_STATUS_STANDBY | Maintenance/setup |

### SolarEdge Proprietary Power Control Registers

SolarEdge does NOT implement SunSpec Model 123. Power control uses proprietary registers:

| Address | Size | R/W | Name | Type | Value Range | Units |
|---|---|---|---|---|---|---|
| 0xF300 (62208) | 1 | R/W | Enable Dynamic Power Control | Uint16 | 0-1 | N/A |
| 0xF310 (62224) | 2 | R/W | Command Timeout | Uint32 | 0-MAX_UINT32 | Sec |
| 0xF312 (62226) | 2 | R/W | Fallback Active Power Limit | Float32 | 0-100 | % |
| 0xF318 (62232) | 2 | R/W | Active Power Ramp-up Rate | Float32 | 0-100 | %/min |
| 0xF31A (62234) | 2 | R/W | Active Power Ramp-down Rate | Float32 | 0-100 | %/min |
| 0xF322 (62242) | 2 | R/W | Dynamic Active Power Limit | Float32 | 0-100 | % |

**Important notes on power control:**
- 0xF300 must be enabled (=1) BEFORE any other power control registers
- Dynamic Active Power Limit (0xF322) must be refreshed at least at `Command Timeout / 2` rate
- All registers except 0xF322 should be set only when required (stored in non-volatile memory)
- Modbus TCP must be configured, and "Advanced Power Control" must be enabled via SetApp or LCD
- Also accessible via simpler method: write 0-100 percentage to Modbus address 0xF001 (per community reports)

### Live Validation Script

To validate the SE30K register layout (PROTO-02), use this script from the LXC container:

```python
#!/usr/bin/env python3
"""Validate SolarEdge SE30K register layout via Modbus TCP."""
from pymodbus.client import ModbusTcpClient
import struct

SE_HOST = "192.168.3.18"
SE_PORT = 1502
SE_UNIT = 1

client = ModbusTcpClient(SE_HOST, port=SE_PORT)
client.connect()

# 1. Read SunSpec header (2 registers at 40000)
result = client.read_holding_registers(40000, 2, slave=SE_UNIT)
header = struct.pack('>HH', *result.registers)
assert header == b'SunS', f"SunSpec header mismatch: {header}"
print(f"SunSpec Header: {header}")

# 2. Read Common Model (65 registers at 40002)
result = client.read_holding_registers(40002, 67, slave=SE_UNIT)
regs = result.registers
did = regs[0]
length = regs[1]
manufacturer = struct.pack(f'>{16*2}s', *[r.to_bytes(2, 'big') for r in regs[2:18]])
# Simpler: read raw bytes
print(f"Common DID: {did} (expect 1)")
print(f"Common Length: {length} (expect 65)")

# 3. Read Inverter Model header at 40069
result = client.read_holding_registers(40069, 2, slave=SE_UNIT)
inv_did = result.registers[0]
inv_len = result.registers[1]
print(f"Inverter Model DID: {inv_did} (expect 101/102/103)")
print(f"Inverter Model Length: {inv_len} (expect 50)")

# 4. Read key inverter registers
result = client.read_holding_registers(40071, 50, slave=SE_UNIT)
regs = result.registers
current_sf = struct.unpack('>h', regs[4].to_bytes(2, 'big'))[0]
voltage_sf = struct.unpack('>h', regs[11].to_bytes(2, 'big'))[0]
power_sf = struct.unpack('>h', regs[13].to_bytes(2, 'big'))[0]
power_raw = struct.unpack('>h', regs[12].to_bytes(2, 'big'))[0]
status = regs[36]

print(f"AC Power: {power_raw * 10**power_sf} W (raw={power_raw}, sf={power_sf})")
print(f"Current SF: {current_sf}, Voltage SF: {voltage_sf}")
print(f"Status: {status}")

# 5. Check what follows inverter model (Model 120? or end marker?)
next_addr = 40069 + 2 + inv_len  # header (2) + model length
result = client.read_holding_registers(next_addr, 2, slave=SE_UNIT)
next_did = result.registers[0]
next_len = result.registers[1]
print(f"Next model at {next_addr}: DID={next_did}, Length={next_len}")
if next_did == 0xFFFF:
    print("End of model chain (no Model 120 or 123)")
else:
    print(f"Model {next_did} found")

client.close()
```

**Confidence: HIGH** -- Based on official SolarEdge SunSpec Implementation Technical Note v3.2 (June 2025).

## Register Translation Table (PROTO-03)

### Key Insight

Both SolarEdge and Fronius implement standard SunSpec models. The register layout within each model is defined by the SunSpec specification, so the data format is identical. The translation task is:

1. **Identity substitution**: Replace "SolarEdge" with "Fronius" in Common Model
2. **Model chain construction**: Build the expected chain (SolarEdge may lack Model 120/123)
3. **Scale factor passthrough**: SunSpec scale factors work the same way
4. **Power control translation**: Map SunSpec Model 123 writes to SolarEdge proprietary registers
5. **Register address remapping**: The proxy serves its own address space, reading from SolarEdge's

### Proxy Register Layout (What Venus OS Sees)

The proxy presents registers starting at 40000 with this model chain:

```
40000-40001: SunSpec Header "SunS"
40002-40068: Model 1 (Common) - length 65 + 2 header = 67 registers
  - C_Manufacturer = "Fronius" (NOT "SolarEdge")
  - C_Model = mapped from SE30K model string
  - C_Version, C_SerialNumber = passed through from SolarEdge
40069-40120: Model 103 (Three Phase Inverter) - length 50 + 2 header = 52 registers
  - All data read from SolarEdge registers 40069-40120
  - Scale factors passed through unchanged
40121-40150: Model 120 (Nameplate Ratings) - length ~26 + 2 header
  - WRtg = 30000 (SE30K = 30kW)
  - Other ratings derived from inverter specs
40151-40178: Model 123 (Immediate Controls) - length ~24 + 2 header
  - Venus OS writes WMaxLimPct here
  - Proxy translates to SolarEdge 0xF300/0xF322 writes
40179-40180: End Marker 0xFFFF + 0x0000
```

### Register-by-Register Translation: Common Model

| Proxy Register | Proxy Value | SolarEdge Source | Translation |
|---|---|---|---|
| 40000-40001 | 0x53756E53 ("SunS") | Static | Hardcoded |
| 40002 | 1 (Common DID) | Static | Hardcoded |
| 40003 | 65 (length) | Static | Hardcoded |
| 40004-40019 | "Fronius" + padding | SE 40004-40019 | **Replaced** (not passthrough) |
| 40020-40035 | Mapped model string | SE 40020-40035 | Passthrough or mapped |
| 40036-40043 | Options | Static | "NOT_IMPLEMENTED" |
| 40044-40051 | Version | SE 40044-40051 | Passthrough |
| 40052-40067 | Serial Number | SE 40052-40067 | Passthrough |
| 40068 | 126 (unit ID) | Static | Hardcoded to 126 |

### Register-by-Register Translation: Inverter Model 103

| Proxy Register | Name | SolarEdge Source | Translation |
|---|---|---|---|
| 40069 | Model ID = 103 | SE 40069 | Passthrough (should already be 103) |
| 40070 | Length = 50 | SE 40070 | Passthrough |
| 40071 | I_AC_Current | SE 40071 | Passthrough |
| 40072 | I_AC_CurrentA | SE 40072 | Passthrough |
| 40073 | I_AC_CurrentB | SE 40073 | Passthrough |
| 40074 | I_AC_CurrentC | SE 40074 | Passthrough |
| 40075 | I_AC_Current_SF | SE 40075 | Passthrough |
| 40076-40078 | Voltages AB/BC/CA | SE 40076-40078 | Passthrough |
| 40079-40081 | Voltages AN/BN/CN | SE 40079-40081 | Passthrough |
| 40082 | I_AC_Voltage_SF | SE 40082 | Passthrough |
| 40083 | I_AC_Power | SE 40083 | Passthrough |
| 40084 | I_AC_Power_SF | SE 40084 | Passthrough |
| 40085 | I_AC_Frequency | SE 40085 | Passthrough |
| 40086 | I_AC_Frequency_SF | SE 40086 | Passthrough |
| 40087 | I_AC_VA | SE 40087 | Passthrough |
| 40088 | I_AC_VA_SF | SE 40088 | Passthrough |
| 40089 | I_AC_VAR | SE 40089 | Passthrough |
| 40090 | I_AC_VAR_SF | SE 40090 | Passthrough |
| 40091 | I_AC_PF | SE 40091 | Passthrough |
| 40092 | I_AC_PF_SF | SE 40092 | Passthrough |
| 40093-40094 | I_AC_Energy_WH | SE 40093-40094 | Passthrough |
| 40095 | I_AC_Energy_WH_SF | SE 40095 | Passthrough |
| 40096-40101 | DC measurements | SE 40096-40101 | Passthrough |
| 40103 | I_Temp_Sink | SE 40103 | Passthrough |
| 40106 | I_Temp_SF | SE 40106 | Passthrough |
| 40107 | I_Status | SE 40107 | Passthrough (same SunSpec status codes) |
| 40108 | I_Status_Vendor | SE 40108 | Passthrough |

### Register Translation: Model 120 (Nameplate)

Model 120 may NOT be present on SolarEdge. The proxy must synthesize it.

| Proxy Register | Name | Value | Source |
|---|---|---|---|
| 40121 | Model ID | 120 | Hardcoded |
| 40122 | Length | 26 | Hardcoded |
| 40123 | DERTyp | 4 (PV) | Hardcoded |
| 40124 | WRtg | 30000 | Configuration (SE30K = 30kW) |
| 40125 | WRtg_SF | 0 | Hardcoded |
| 40126 | VARtg | 30000 | Configuration |
| 40127 | VARtg_SF | 0 | Hardcoded |
| 40128-40131 | VArRtg Q1-Q4 | Derived | From SE30K specs |
| 40132 | VArRtg_SF | 0 | Hardcoded |
| 40133 | ARtg | SE30K max current | Configuration |
| 40134 | ARtg_SF | 0 | Hardcoded |
| 40135-40138 | PFRtg Q1-Q4 | -1/1 | Typical values |
| 40139 | PFRtg_SF | -2 | Hardcoded |
| 40140-40148 | Storage params | 0 / NOT_IMPL | Not applicable for PV |

### Register Translation: Model 123 (Controls) -- Write Path

| Proxy Register | Name | SolarEdge Target | Translation |
|---|---|---|---|
| 40151 | Model ID = 123 | N/A | Hardcoded |
| 40152 | Length = 24 | N/A | Hardcoded |
| 40153-40154 | Conn_WinTms, Conn_RvrtTms | N/A | Not used |
| 40155 | Conn | N/A | Always CONNECT |
| 40156 | WMaxLimPct | SE 0xF322 | **Write: value/100 -> 0xF322 as Float32 %** |
| 40157 | WMaxLimPct_WinTms | N/A | Stored locally |
| 40158 | WMaxLimPct_RvrtTms | SE 0xF310 | **Write: -> Command Timeout** |
| 40159 | WMaxLimPct_RmpTms | SE 0xF318/0xF31A | **Write: -> Ramp rates** |
| 40160 | WMaxLim_Ena | SE 0xF300 | **Write: ENABLED->1, DISABLED->0** |
| 40161 | WMaxLimPct_SF | -2 | Hardcoded (values in 0.01% resolution) |
| ... | PF/VAR controls | | Not implemented in v1 |

**Power Control Write Sequence (proxy -> SolarEdge):**
1. Venus OS writes `WMaxLim_Ena = 1` -> Proxy writes `0xF300 = 1` (enable dynamic power control)
2. Venus OS writes `WMaxLimPct = 5000` (50.00%) -> Proxy writes `0xF322 = 50.0` (Float32)
3. Proxy must refresh `0xF322` at least every `Command Timeout / 2` seconds
4. Venus OS writes `WMaxLim_Ena = 0` -> Proxy writes `0xF300 = 0` (disable)

## Architecture Patterns

### Data Flow

```
Venus OS (192.168.3.146)
    |
    | Modbus TCP (port 502, unit ID 126)
    |
    v
+-------------------+
| Fronius Proxy     |
| (192.168.3.191)   |
|                   |
| Register Cache    |
| [SunSpec Models]  |
|                   |
| Async Poller -----+--- Modbus TCP (port 1502, unit ID 1) ---> SolarEdge SE30K
| Write Translator -+--- Modbus TCP (port 1502, unit ID 1) ---> (192.168.3.18)
+-------------------+
```

### Critical Architecture Constraints

1. **Single Connection**: SolarEdge only supports ONE concurrent Modbus TCP connection. The proxy must be the exclusive Modbus client. No other tool/system can connect to the SE30K simultaneously.
2. **Cache-Based Serving**: Venus OS reads must be served from a local register cache, NOT proxied synchronously through to SolarEdge. This decouples read latency from upstream polling.
3. **Polling Interval**: Must poll SolarEdge within 2-minute idle timeout. Recommended: 1-5 second interval for live data.
4. **Power Control Refresh**: When active power limiting is enabled, the Dynamic Active Power Limit register (0xF322) must be refreshed at least every `Command Timeout / 2` seconds.

## Common Pitfalls

### Pitfall 1: Unit ID Mismatch
**What goes wrong:** dbus-fronius defaults to unit ID 126 for SunSpec devices, but SolarEdge defaults to unit ID 1 for Modbus TCP.
**Why it happens:** Different vendor defaults.
**How to avoid:** Proxy listens on unit ID 126 (for Venus OS) and connects to SolarEdge on unit ID 1. These are independent.
**Warning signs:** "No device found" or timeout errors from Venus OS.

### Pitfall 2: Missing Model 120
**What goes wrong:** dbus-fronius requires Model 120 (nameplate) for operation. SolarEdge may not provide it in the model chain.
**Why it happens:** SolarEdge implements Models 101/102/103 and optionally Model 160 (Synergy), but Model 120 is not listed in their SunSpec documentation.
**How to avoid:** The proxy MUST synthesize Model 120 with correct WRtg (30000W for SE30K).
**Warning signs:** Venus OS shows the inverter but reports 0W max power or refuses power limiting.

### Pitfall 3: SolarEdge Concurrent Connection Limit
**What goes wrong:** Connection refused errors or dropped connections.
**Why it happens:** SolarEdge firmware only supports a single Modbus TCP session.
**How to avoid:** Ensure no other Modbus client is connecting to the SE30K. Disable SolarEdge monitoring platform Modbus if needed.
**Warning signs:** Intermittent "connection refused" or sudden disconnects.

### Pitfall 4: Scale Factor Interpretation
**What goes wrong:** Values off by orders of magnitude.
**Why it happens:** Scale factors are signed integers representing powers of 10. A scale factor of -2 means multiply by 0.01. Getting the sign wrong inverts the scaling.
**How to avoid:** `actual_value = raw_value * 10^scale_factor`. Use `struct.unpack('>h', ...)` for signed int16 scale factors.
**Warning signs:** Power showing as 2071 instead of 20.71, or absurdly large numbers.

### Pitfall 5: Power Control Protocol Mismatch
**What goes wrong:** Venus OS sends SunSpec Model 123 writes, but SolarEdge uses proprietary registers.
**Why it happens:** SolarEdge does not implement SunSpec Model 123 for writes.
**How to avoid:** Proxy must translate Model 123 WMaxLimPct writes to SolarEdge 0xF300/0xF322 protocol.
**Warning signs:** Power limit commands "accepted" but no effect on inverter output.

### Pitfall 6: Float32 vs Integer Encoding
**What goes wrong:** Garbled values when reading/writing power control registers.
**Why it happens:** SolarEdge power control registers use Float32 (IEEE 754), while SunSpec monitoring uses Integer + scale factor.
**How to avoid:** Use `struct.pack('>f', value)` for writing to 0xF312/0xF318/0xF31A/0xF322. Use integer+SF for all SunSpec model registers.
**Warning signs:** NaN or infinite values in power control responses.

### Pitfall 7: Nighttime / Offline Behavior
**What goes wrong:** Proxy crashes or enters error loops when SolarEdge is sleeping/off.
**Why it happens:** At night, SolarEdge enters I_STATUS_SLEEPING (2) and may return zeros for all measurements, or disconnect entirely.
**How to avoid:** Cache last known status, serve stale data with appropriate status code. Implement reconnection logic with backoff.
**Warning signs:** Crash loops in systemd journal during nighttime hours.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Modbus TCP client/server | Raw TCP socket protocol | pymodbus or similar library | MBAP header, transaction IDs, error handling, function codes |
| SunSpec model parsing | Custom register parser | SunSpec model JSON definitions from sunspec/models GitHub | 700+ models with precise field definitions |
| Scale factor math | Ad-hoc multiplication | Consistent helper: `value * 10**sf` | Sign handling, zero-SF edge case |
| Float32 encode/decode | Manual bit manipulation | `struct.pack/unpack('>f', ...)` | IEEE 754 compliance |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (standard for Python projects) |
| Config file | none -- see Wave 0 |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROTO-01 | dbus-fronius expectations documented | manual-only | N/A (documentation deliverable) | N/A |
| PROTO-02 | SE30K registers read and validated | integration | `python3 scripts/validate_se30k.py` | Wave 0 |
| PROTO-03 | Translation table complete and correct | unit | `pytest tests/test_register_mapping.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `scripts/validate_se30k.py` -- live register validation script (PROTO-02)
- [ ] `tests/test_register_mapping.py` -- translation table unit tests (PROTO-03)
- [ ] `pytest.ini` or `pyproject.toml` -- test framework config
- [ ] `requirements.txt` -- pymodbus dependency for validation scripts

## Open Questions

1. **SolarEdge Model Chain Beyond Model 103**
   - What we know: SolarEdge documents Models 101/102/103 and Model 160 (Synergy). No mention of Model 120 or 123.
   - What's unclear: Does the SE30K's model chain end after Model 103 (with 0xFFFF), or does it include additional models?
   - Recommendation: The live validation script will answer this definitively. Plan to synthesize Model 120 regardless.

2. **Power Control via 0xF001 vs 0xF300/0xF322**
   - What we know: Community reports that writing to 0xF001 works for simple power limiting. Official docs describe 0xF300/0xF322 protocol.
   - What's unclear: Is 0xF001 officially supported? Does it work on all firmware versions?
   - Recommendation: Use the official 0xF300/0xF322 protocol. Test 0xF001 as fallback during validation.

3. **SolarEdge Advanced Power Control Prerequisite**
   - What we know: Power control via Modbus requires "Advanced Power Control" to be enabled via SetApp or LCD menu.
   - What's unclear: Is this already enabled on the user's SE30K?
   - Recommendation: Verify during PROTO-02 validation. Document SetApp configuration path if needed.

4. **dbus-fronius Fronius Null-Frame Filter**
   - What we know: dbus-fronius discards all-zero frames with Status=7 for Fronius devices.
   - What's unclear: Will the proxy need to implement similar filtering, or does this only apply to real Fronius hardware?
   - Recommendation: The proxy controls what it serves, so it can avoid sending null frames. Monitor for any similar behavior from SolarEdge during nighttime.

## Sources

### Primary (HIGH confidence)
- [victronenergy/dbus-fronius](https://github.com/victronenergy/dbus-fronius) -- sunspec_detector.cpp, sunspec_updater.cpp source analysis
- [SolarEdge SunSpec Implementation Technical Note v3.2 (June 2025)](https://knowledge-center.solaredge.com/sites/kc/files/sunspec-implementation-technical-note.pdf) -- Official register map (PDF read directly)
- [SolarEdge Ramp-up/down and Active Power Control v1.0 (Dec 2018)](https://communityarchive.victronenergy.com/storage/attachments/ramp-up-down-and-active-power-control-02-01-19.pdf) -- Official power control register table (PDF read directly)
- [SunSpec Model JSON definitions](https://github.com/sunspec/models) -- model_1.json, model_103.json, model_120.json, model_123.json

### Secondary (MEDIUM confidence)
- [dbus-fronius README](https://github.com/victronenergy/dbus-fronius/blob/master/README.md) -- Supported devices, unit ID defaults, SunSpec vs Solar API
- [dbus-fronius Issue #4](https://github.com/victronenergy/dbus-fronius/issues/4) -- SolarEdge power limit via 0xF001
- [dbus-fronius Issue #6](https://github.com/victronenergy/dbus-fronius/issues/6) -- SolarEdge power throttling implementation status
- [h4ckst0ck/dbus-solaredge](https://github.com/h4ckst0ck/dbus-solaredge) -- Existing SolarEdge-Venus OS integration, confirms single connection limitation
- [binsentsu/home-assistant-solaredge-modbus Issue #82](https://github.com/binsentsu/home-assistant-solaredge-modbus/issues/82) -- Single concurrent connection confirmed

### Tertiary (LOW confidence)
- [Community reports on SolarEdge 0xF001 register](https://github.com/victronenergy/dbus-fronius/issues/4) -- Alternative power control method, needs live validation

## Metadata

**Confidence breakdown:**
- dbus-fronius discovery mechanism: HIGH -- direct source code analysis
- SolarEdge register map: HIGH -- official documentation v3.2 (June 2025), PDF read directly
- SolarEdge power control: HIGH -- official documentation, PDF read directly
- Translation table: HIGH -- both sides use standard SunSpec, mapping is straightforward
- Model 120 synthesis: MEDIUM -- need live validation to confirm SolarEdge doesn't provide it
- Power control interop: MEDIUM -- protocol documented but not yet tested end-to-end

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable protocols, unlikely to change)
