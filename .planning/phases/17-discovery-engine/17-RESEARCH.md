# Phase 17: Discovery Engine - Research

**Researched:** 2026-03-20
**Domain:** Network scanning, Modbus TCP, SunSpec protocol
**Confidence:** HIGH

## Summary

Phase 17 builds a backend network scanner that finds SunSpec-compatible inverters on the local subnet. The scanner uses asyncio with semaphore-bounded concurrency to TCP-probe all IPs on configurable ports (default 502, 1502), verifies SunSpec compliance via the "SunS" magic number at register 40000, and reads Common Block data (manufacturer, model, serial, firmware) from verified devices.

The project already uses pymodbus 3.8.6 with `AsyncModbusTcpClient` -- the same library and pattern will be reused for scanner reads. Subnet auto-detection will use a subprocess call to `ip -j addr` on Linux (the LXC target), parsed with stdlib `json` and `ipaddress` modules. No additional dependencies are needed.

**Primary recommendation:** Build a single `scanner.py` module with two clean functions: `detect_subnet()` for auto-detecting the local /24, and `scan_subnet()` as the main async entry point that orchestrates TCP probing, SunSpec verification, and Common Block reading. Expose via a POST `/api/scanner/discover` endpoint returning JSON results.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- Already-configured inverter IPs are SKIPPED during scan -- no conflict with active polling
- Scan parallelism: 10-20 concurrent TCP connections via asyncio semaphore
- TCP timeout per IP: 0.5s (LAN devices respond under 50ms)
- Sequential Modbus reads after TCP connect (one at a time per host due to SolarEdge single-connection constraint)
- Scanner returns ALL SunSpec-compatible devices, not just SolarEdge
- Non-SolarEdge devices marked as "not yet supported" (supported=false)
- Data per device: IP, Port, Unit ID, Manufacturer, Model, Serial Number, Firmware Version
- Supported flag: true if manufacturer == "SolarEdge", false otherwise
- Auto-detect subnet from local network interface -- no user input required
- Use first non-loopback, non-link-local interface (filter out 127.x and 169.254.x)
- On LXC typically only one real interface (eth0)
- No multi-subnet scanning -- single detected subnet only

### Claude's Discretion
- Exact asyncio concurrency pattern (Semaphore size within 10-20 range)
- Error handling for edge cases (partial Common Block reads, corrupted data)
- Logging verbosity during scan
- SunSpec verification details (how strict to validate DID/Length)

### Deferred Ideas (OUT OF SCOPE)
- Manufacturer + Model inline display in Config page -- Phase 19
- Production LXC development setup -- operational concern

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DISC-01 | Subnet scan on configurable ports (default 502, 1502) | asyncio TCP probing with semaphore concurrency, `asyncio.open_connection` for port check |
| DISC-02 | SunSpec "SunS" magic number verification at register 40000 | pymodbus `read_holding_registers(40000, count=2)`, check for 0x5375 + 0x6E53 |
| DISC-03 | Read Manufacturer, Model, Serial, Firmware from Common Block | pymodbus read 67 registers at 40002, decode with `encode_string` reverse (bytes->str) |
| DISC-04 | Scan Unit ID 1 (always) + optional 2-10 (RS485 followers) | Loop unit_id parameter in pymodbus calls, configurable range |

</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pymodbus | 3.8.6 (installed) | Modbus TCP client for SunSpec reads | Already in project dependencies (`>=3.6,<4.0`), same `AsyncModbusTcpClient` pattern used by SolarEdge plugin |
| asyncio | stdlib | Concurrent TCP probing + semaphore | Already the project's async framework throughout |
| ipaddress | stdlib | Subnet enumeration (`.hosts()`) | Standard for iterating /24 host IPs |
| subprocess | stdlib | `ip -j addr` for interface detection | Zero-dep interface detection on Linux LXC |
| dataclasses | stdlib | Result data models | Project pattern for all data structures |
| structlog | 24.x (installed) | Logging during scan | Project logging standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| aiohttp | 3.10+ (installed) | REST endpoint for triggering scan | Already used for webapp, add new route |
| json | stdlib | Parse `ip -j addr` output | Only for subnet detection |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `ip -j addr` subprocess | `netifaces` / `ifaddr` package | Extra dependency for one call; `ip` is always available on LXC Debian |
| `asyncio.open_connection` for TCP probe | Raw socket connect | `open_connection` is cleaner asyncio, handles timeout natively |
| pymodbus for TCP probe | Raw socket | pymodbus adds overhead per connection; use raw TCP for port-open check, pymodbus only for verified hosts |

## Architecture Patterns

### Recommended Project Structure
```
src/venus_os_fronius_proxy/
    scanner.py           # NEW: Discovery engine module
    config.py            # Existing: skip-list from InverterConfig
    webapp.py            # Existing: add /api/scanner/discover endpoint
    sunspec_models.py    # Existing: reuse constants
    plugins/solaredge.py # Existing: reference for Modbus patterns
```

### Pattern 1: Two-Phase Scan (TCP Probe then Modbus Verify)
**What:** Separate fast TCP port-open check from slower Modbus register reads
**When to use:** Always -- scanning 254 IPs with full Modbus handshake is too slow
**Example:**
```python
# Phase 1: Fast TCP port probe (0.5s timeout, 15 concurrent)
async def _probe_port(ip: str, port: int, timeout: float) -> bool:
    """Check if TCP port is open. Returns True if connectable."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(str(ip), port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, OSError):
        return False

# Phase 2: Sequential Modbus reads on discovered hosts
async def _verify_sunspec(ip: str, port: int, unit_id: int) -> dict | None:
    """Connect, check SunS magic, read Common Block."""
    client = AsyncModbusTcpClient(ip, port=port, timeout=2.0, retries=0)
    try:
        await client.connect()
        # Read SunSpec header (2 registers at 40000)
        resp = await client.read_holding_registers(40000, count=2, device_id=unit_id)
        if resp.isError() or resp.registers != [0x5375, 0x6E53]:
            return None
        # Read Common Block (67 registers at 40002)
        common = await client.read_holding_registers(40002, count=67, device_id=unit_id)
        if common.isError():
            return None
        return _parse_common_block(common.registers)
    finally:
        client.close()
```

### Pattern 2: Subnet Auto-Detection via `ip -j addr`
**What:** Parse JSON output of `ip -j addr` to find first usable interface
**When to use:** On startup of scan, before enumerating hosts
**Example:**
```python
import subprocess, json
from ipaddress import IPv4Network, IPv4Address

def detect_subnet() -> IPv4Network:
    """Detect local /24 subnet from first non-loopback interface."""
    result = subprocess.run(
        ["ip", "-j", "-4", "addr", "show"],
        capture_output=True, text=True, timeout=5,
    )
    interfaces = json.loads(result.stdout)
    for iface in interfaces:
        for addr_info in iface.get("addr_info", []):
            ip = addr_info.get("local", "")
            prefix = addr_info.get("prefixlen", 24)
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            return IPv4Network(f"{ip}/{prefix}", strict=False)
    raise RuntimeError("No usable network interface found")
```

### Pattern 3: Result Dataclass
**What:** Typed result structure matching user's data requirements
**Example:**
```python
from dataclasses import dataclass

@dataclass
class DiscoveredDevice:
    ip: str
    port: int
    unit_id: int
    manufacturer: str
    model: str
    serial_number: str
    firmware_version: str
    supported: bool  # True if manufacturer contains "SolarEdge"
```

### Pattern 4: Common Block String Decoding
**What:** Reverse of `encode_string()` -- decode uint16 registers back to ASCII string
**Example:**
```python
def decode_string(registers: list[int]) -> str:
    """Decode uint16 register list back to ASCII string, stripping nulls."""
    raw = b"".join(r.to_bytes(2, "big") for r in registers)
    return raw.decode("ascii", errors="replace").rstrip("\x00").strip()
```

**Common Block Register Map (offsets from 40002):**
| Field | Offset | Length (regs) | Description |
|-------|--------|---------------|-------------|
| DID | 0 | 1 | Model identifier (must be 1) |
| Length | 1 | 1 | Block length (must be 65) |
| Manufacturer | 2-17 | 16 | ASCII string |
| Model | 18-33 | 16 | ASCII string |
| Options | 34-41 | 8 | ASCII string (often empty) |
| Version/Firmware | 42-49 | 8 | ASCII string |
| Serial Number | 50-65 | 16 | ASCII string |
| DeviceAddress | 66 | 1 | Modbus unit ID |

### Anti-Patterns to Avoid
- **Opening pymodbus connections for all 254 IPs:** Use raw TCP probe first. pymodbus has reconnection logic overhead that wastes time on dead hosts.
- **Parallel Modbus reads to same SolarEdge host:** SolarEdge allows only ONE simultaneous TCP connection. All reads to a given host must be sequential.
- **Using `socket.connect()` blocking calls:** Use `asyncio.open_connection()` for non-blocking probes within the event loop.
- **Hardcoding subnet:** Always auto-detect. The LXC may move between networks.
- **Leaving connections open:** Close pymodbus client in `finally` block after each host verification. Stale connections block SolarEdge from accepting new ones.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Modbus TCP communication | Raw socket protocol parsing | `pymodbus.client.AsyncModbusTcpClient` | Modbus framing, error detection, retries already handled |
| IP/subnet enumeration | Manual IP math | `ipaddress.IPv4Network.hosts()` | Correct handling of network/broadcast addresses |
| String encoding | Manual byte packing | Reverse of existing `encode_string()` pattern | Null-padding, big-endian already proven |
| Async concurrency control | Manual connection counting | `asyncio.Semaphore` | Race-condition-free bounded concurrency |

## Common Pitfalls

### Pitfall 1: SolarEdge Single-Connection Constraint
**What goes wrong:** Scanner opens connection while active poller has one open -- SolarEdge rejects or drops existing connection
**Why it happens:** SolarEdge Modbus TCP implementation allows exactly ONE simultaneous TCP connection
**How to avoid:** CONTEXT.md says configured IPs are SKIPPED. This is the primary mitigation. Additionally, scanner connections must be short-lived (connect, read, close immediately).
**Warning signs:** Connection timeouts on the configured inverter IP during scan

### Pitfall 2: Timeout Too Aggressive for Modbus Reads
**What goes wrong:** 0.5s TCP timeout works for port probe, but Modbus register read may need more time
**Why it happens:** pymodbus has handshake overhead beyond raw TCP connect
**How to avoid:** Use 0.5s for TCP port probe, but 2.0s timeout for pymodbus client (Modbus read phase). These are separate operations.
**Warning signs:** Intermittent "read timeout" errors on devices that responded to TCP probe

### Pitfall 3: `ip` Command Not Available
**What goes wrong:** `ip -j addr` fails on non-Linux systems (macOS dev)
**Why it happens:** Development machine is macOS, target is Linux LXC
**How to avoid:** Add fallback for development: try `ip -j addr` first, fall back to `ifconfig` parsing or raise clear error. In tests, mock `detect_subnet()`.
**Warning signs:** `FileNotFoundError` when running on macOS

### Pitfall 4: Non-SunSpec Devices on Port 502
**What goes wrong:** Industrial PLCs, HVAC controllers, etc. respond on port 502 but crash or hang on SunSpec-specific register reads
**Why it happens:** Port 502 is standard Modbus, not SunSpec-specific
**How to avoid:** Handle Modbus exceptions (illegal address, device failure) gracefully. Check for `resp.isError()` before accessing `.registers`. Set `retries=0` on scanner client to fail fast.
**Warning signs:** Modbus exception codes in response instead of register data

### Pitfall 5: pymodbus Client Cleanup
**What goes wrong:** Leaked connections from unclosed AsyncModbusTcpClient instances
**Why it happens:** Exception during read leaves client connected
**How to avoid:** Always `client.close()` in `finally` block. Do NOT use `reconnect_delay` for scanner (set to 0 or don't rely on auto-reconnect).
**Warning signs:** Connection pool exhaustion, SolarEdge refusing connections

## Code Examples

### Main Scanner Entry Point
```python
# Source: project patterns from webapp.py + solaredge.py
import asyncio
import structlog
from dataclasses import dataclass, asdict
from ipaddress import IPv4Network

log = structlog.get_logger()

@dataclass
class ScanConfig:
    ports: list[int] = None  # Default: [502, 1502]
    tcp_timeout: float = 0.5
    modbus_timeout: float = 2.0
    concurrency: int = 15
    scan_unit_ids: list[int] = None  # Default: [1]
    skip_ips: set[str] = None  # Configured inverter IPs to skip

    def __post_init__(self):
        if self.ports is None:
            self.ports = [502, 1502]
        if self.scan_unit_ids is None:
            self.scan_unit_ids = [1]
        if self.skip_ips is None:
            self.skip_ips = set()

async def scan_subnet(config: ScanConfig | None = None) -> list[DiscoveredDevice]:
    """Scan local subnet for SunSpec devices. Main entry point."""
    cfg = config or ScanConfig()
    subnet = detect_subnet()
    log.info("scan.start", subnet=str(subnet), ports=cfg.ports)

    # Phase 1: TCP port probe with concurrency limit
    sem = asyncio.Semaphore(cfg.concurrency)
    open_hosts = []  # list of (ip, port) tuples

    async def probe_with_sem(ip, port):
        async with sem:
            if await _probe_port(str(ip), port, cfg.tcp_timeout):
                open_hosts.append((str(ip), port))

    tasks = []
    for ip in subnet.hosts():
        ip_str = str(ip)
        if ip_str in cfg.skip_ips:
            continue
        for port in cfg.ports:
            tasks.append(probe_with_sem(ip, port))

    await asyncio.gather(*tasks)
    log.info("scan.probe_complete", open_count=len(open_hosts))

    # Phase 2: SunSpec verify (sequential per host, parallel across hosts)
    devices = []
    verify_sem = asyncio.Semaphore(cfg.concurrency)

    async def verify_host(ip, port):
        async with verify_sem:
            for uid in cfg.scan_unit_ids:
                device = await _verify_sunspec(ip, port, uid, cfg.modbus_timeout)
                if device:
                    devices.append(device)

    await asyncio.gather(*[verify_host(ip, port) for ip, port in open_hosts])
    log.info("scan.complete", devices_found=len(devices))
    return devices
```

### REST API Endpoint
```python
# Source: webapp.py patterns (config_save_handler, status_handler)
async def scanner_discover_handler(request: web.Request) -> web.Response:
    """POST /api/scanner/discover -- trigger subnet scan."""
    shared_ctx = request.app["shared_ctx"]

    # Build skip list from current config
    config: Config = request.app["config"]
    skip_ips = {config.inverter.host}

    scan_config = ScanConfig(skip_ips=skip_ips)

    try:
        devices = await scan_subnet(scan_config)
        return web.json_response({
            "success": True,
            "devices": [asdict(d) for d in devices],
        })
    except Exception as e:
        return web.json_response(
            {"success": False, "error": str(e)},
            status=500,
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `netifaces` for interface detection | `ip -j addr` + stdlib json | netifaces unmaintained since 2021 | No extra dependency needed |
| pymodbus 2.x sync client | pymodbus 3.x async client | pymodbus 3.0 (2023) | Project already on 3.8.6, use `AsyncModbusTcpClient` |
| SunSpec header at register 0 | SunSpec header at register 40000 | SunSpec spec always at 40000 for TCP | Common misconception: some docs show register 0, always use 40000 for Modbus TCP |

**Deprecated/outdated:**
- `netifaces` package: unmaintained, wheels fail on modern Python. Use `ip` command or `ifaddr` instead.
- pymodbus `ModbusTcpClient` (sync): still exists but project is fully async, use `AsyncModbusTcpClient`.

## Open Questions

1. **Unit ID scan range default**
   - What we know: Always scan unit_id=1. CONTEXT says "optionally 2-10"
   - What's unclear: Should the default include 2-10 or only 1? Time impact: 10x more Modbus reads per host
   - Recommendation: Default to unit_id=[1] only. Add `extended_scan: bool` parameter for 2-10. Most residential setups have single inverter per IP.

2. **WebSocket progress during scan**
   - What we know: CONTEXT references WebSocket broadcast for progress, existing ws infrastructure
   - What's unclear: Is progress reporting in scope for Phase 17 or Phase 20 (DISC-05)?
   - Recommendation: Phase 17 builds the scanner with a progress callback parameter. Phase 20 (DISC-05) wires it to WebSocket. Keep scanner decoupled from WebSocket.

3. **macOS development fallback for subnet detection**
   - What we know: Target is Linux LXC, `ip` command not available on macOS
   - What's unclear: How important is local development vs. direct LXC development
   - Recommendation: CONTEXT says "develop directly on production LXC". Still, add a try/except with clear error message for macOS, and mock in tests.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.23+ |
| Config file | `pyproject.toml` ([tool.pytest.ini_options]) |
| Quick run command | `pytest tests/test_scanner.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DISC-01 | TCP port probing across subnet | unit | `pytest tests/test_scanner.py::TestPortProbe -x` | -- Wave 0 |
| DISC-02 | SunSpec "SunS" magic verification | unit | `pytest tests/test_scanner.py::TestSunSpecVerify -x` | -- Wave 0 |
| DISC-03 | Common Block parsing (mfr, model, serial, fw) | unit | `pytest tests/test_scanner.py::TestCommonBlockParse -x` | -- Wave 0 |
| DISC-04 | Unit ID 1 + optional 2-10 scanning | unit | `pytest tests/test_scanner.py::TestUnitIdScan -x` | -- Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_scanner.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_scanner.py` -- covers DISC-01 through DISC-04 (all scanner tests)
- [ ] Mock helpers for `AsyncModbusTcpClient` responses (reuse pattern from `test_solaredge_plugin.py::_make_mock_response`)
- [ ] Mock for `subprocess.run` (ip -j addr output)

## Sources

### Primary (HIGH confidence)
- Existing codebase: `sunspec_models.py` -- SunSpec constants, `encode_string()` helper
- Existing codebase: `plugins/solaredge.py` -- `AsyncModbusTcpClient` usage pattern, `read_holding_registers()` with `device_id` parameter
- Existing codebase: `config.py` -- dataclass patterns, validation functions
- Existing codebase: `webapp.py` -- REST endpoint pattern, `shared_ctx`, WebSocket broadcast
- [pymodbus 3.6.9 docs](https://pymodbus.readthedocs.io/en/v3.6.9/source/client.html) -- `AsyncModbusTcpClient` constructor: `host`, `port`, `timeout`, `retries`, `reconnect_delay` parameters
- [Python ipaddress docs](https://docs.python.org/3/library/ipaddress.html) -- `IPv4Network.hosts()` for subnet enumeration

### Secondary (MEDIUM confidence)
- [pymodbus timeout discussion](https://github.com/pymodbus-dev/pymodbus/discussions/2171) -- unified `timeout` parameter for connect + read
- [asyncio TCP scanner gist](https://gist.github.com/0xpizza/dd5e005a0efeb1edfc939d3a409e22d9) -- pattern for `asyncio.open_connection` with `wait_for` timeout

### Tertiary (LOW confidence)
- None -- all findings verified with primary sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in project, patterns proven
- Architecture: HIGH -- two-phase scan (TCP probe then Modbus verify) is well-established
- Pitfalls: HIGH -- SolarEdge single-connection constraint documented in STATE.md and verified in existing code
- Subnet detection: MEDIUM -- `ip -j addr` approach verified for Linux but macOS fallback is an edge case

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (stable domain, no fast-moving dependencies)
