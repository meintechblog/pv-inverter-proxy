# Technology Stack

**Project:** Venus OS Fronius Proxy -- v4.0 Multi-Source Virtual Inverter
**Researched:** 2026-03-20
**Scope:** Stack additions for OpenDTU integration, virtual inverter aggregation, device registry
**Overall confidence:** HIGH

## Existing Stack (DO NOT CHANGE)

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.12 | Runtime |
| pymodbus | >=3.6,<4.0 | Modbus TCP server + SolarEdge client |
| aiohttp | >=3.10,<4.0 | HTTP server, WebSocket, REST API |
| paho-mqtt | (installed) | Venus OS MQTT integration |
| structlog | >=24.0 | Structured JSON logging |
| PyYAML | >=6.0,<7.0 | Configuration files |
| Vanilla JS | -- | Frontend (zero dependencies, no build) |

## Stack Additions for v4.0

### ZERO new Python dependencies needed

The key finding: **aiohttp already includes `aiohttp.ClientSession`**, which is the HTTP client needed for OpenDTU REST API polling. No new library is required.

### OpenDTU REST API Client

| Decision | Choice | Rationale |
|----------|--------|-----------|
| HTTP client library | `aiohttp.ClientSession` | Already a dependency. Async-native. Supports GET for polling and POST for limit control. No reason to add `httpx` or `requests`. |
| Authentication | HTTP Basic Auth via `aiohttp.BasicAuth` | OpenDTU uses Basic Auth (admin:password). `aiohttp.BasicAuth` is built-in to aiohttp -- no dependency needed. |
| Polling pattern | Async loop with `asyncio.sleep` | Same pattern as SolarEdge Modbus polling. Reuse `ConnectionManager` for reconnection/backoff. |

**OpenDTU API endpoints used:**

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/api/livedata/status` | GET | No (readonly) | Poll all inverter data (AC power, DC strings, temperature, yields) |
| `/api/livedata/status?inv=<serial>` | GET | No | Detailed per-inverter data with all DC string channels |
| `/api/limit/status` | GET | No | Current power limit percentage and set status |
| `/api/limit/config` | POST | Yes (Basic) | Set power limit: `{"serial": "...", "limit_type": 1, "limit_value": 50}` |

**Response data mapping (OpenDTU -> InverterPlugin interface):**

| OpenDTU field | SunSpec equivalent | Notes |
|---------------|-------------------|-------|
| `inverters[].AC.0.Power.v` | `ac_power` (W) | Direct map |
| `inverters[].AC.0.Voltage.v` | `ac_voltage_an` (V) | Single-phase micro-inverter |
| `inverters[].AC.0.Current.v` | `ac_current` (A) | Direct map |
| `inverters[].AC.0.Frequency.v` | `ac_frequency` (Hz) | Direct map |
| `inverters[].DC.{0,1,2,3}.Power.v` | `dc_power` (W) | Sum all DC strings |
| `inverters[].DC.{0,1,2,3}.Voltage.v` | `dc_voltage` (V) | Average or per-string |
| `inverters[].DC.{0,1,2,3}.YieldTotal.v` | `ac_energy` (Wh) | Cumulative |
| `inverters[].DC.{0,1,2,3}.YieldDay.v` | `daily_energy_wh` | Daily yield |
| `inverters[].INV.0.Temperature.v` | `temperature_cab` (C) | Inverter temperature |
| `inverters[].limit_relative` | Power limit % | Current active limit |
| `inverters[].reachable` | Connection state | Maps to ConnectionState |
| `inverters[].producing` | Operating status | MPPT vs SLEEPING |

### Plugin Architecture Extension

**No changes to `InverterPlugin` ABC needed.** The existing 6-method interface (`connect`, `poll`, `get_static_common_overrides`, `get_model_120_registers`, `write_power_limit`, `reconfigure`, `close`) covers the OpenDTU use case:

| Method | OpenDTU Implementation |
|--------|----------------------|
| `connect()` | Create `aiohttp.ClientSession`, verify `/api/livedata/status` is reachable |
| `poll()` | GET `/api/livedata/status`, transform JSON to `PollResult` (common_registers + inverter_registers as uint16 arrays) |
| `get_static_common_overrides()` | Manufacturer="Fronius", Model from OpenDTU inverter name |
| `get_model_120_registers()` | Synthesize Model 120 from Hoymiles specs (e.g., HM-800 = 800W rated) |
| `write_power_limit()` | POST `/api/limit/config` with `{"serial": "...", "limit_type": 1, "limit_value": pct}` |
| `reconfigure()` | Close session, update host/port/credentials |
| `close()` | Close `aiohttp.ClientSession` |

**Key difference from SolarEdge:** OpenDTU returns JSON (not Modbus registers). The plugin must synthesize uint16 register arrays from JSON fields to match the `PollResult` format. This is a translation layer inside the plugin, invisible to the rest of the system.

### Virtual Inverter Aggregation

**No new library needed.** Aggregation is pure arithmetic on `PollResult` data:

| Aggregation | Method | Notes |
|-------------|--------|-------|
| AC Power | Sum all active inverters' `ac_power` | Straightforward addition |
| AC Current | Sum all inverters' `ac_current` | Currents add in parallel |
| AC Voltage | Average (or use primary inverter) | Voltage should be same across grid-tied inverters |
| Frequency | Average (or use primary inverter) | Same grid = same frequency |
| Energy Total | Sum all `ac_energy` values | Each inverter tracks independently |
| Temperature | Max across all inverters | Report hottest for safety |
| Status | Worst-case (FAULT > THROTTLED > MPPT > SLEEPING) | Conservative reporting |

**Implementation pattern:** A new `VirtualInverterAggregator` class that:
1. Holds references to multiple `InverterPlugin` instances
2. Polls all in parallel via `asyncio.gather`
3. Merges results into a single `PollResult` for the Modbus server
4. Distributes power limit commands according to priority rules

### Device Registry Pattern

**No new library needed.** Pure Python dataclasses + dict registry:

```python
@dataclass
class DeviceEntry:
    id: str                    # UUID-based, like existing InverterEntry.id
    type: str                  # "solaredge" | "opendtu" | "venus"
    name: str                  # User-defined display name
    enabled: bool
    config: dict               # Type-specific configuration
    plugin: InverterPlugin | None  # Runtime reference (not persisted)
```

**Config schema extension (YAML):**

```yaml
# Existing format (backward compatible):
inverters:
  - id: "abc123def456"
    host: "192.168.3.18"
    port: 1502
    unit_id: 1
    type: "solaredge"        # NEW field, default "solaredge" for migration
    enabled: true

  - id: "789xyz012345"
    host: "192.168.3.98"
    port: 80                 # OpenDTU web port
    type: "opendtu"          # NEW field
    serial: "114184835288"   # Hoymiles serial (for limit commands)
    auth_user: "admin"       # OpenDTU credentials
    auth_pass: "openDTU42"   # Default OpenDTU password
    enabled: true

# NEW section:
virtual_inverter:
  name: "PV Gesamtanlage"    # Display name for Venus OS
  rated_power_w: 30800       # Sum of all inverter ratings (30000 + 800)
```

### Power Limit Distribution

**No new library needed.** Priority-based distribution using a simple strategy pattern:

| Strategy | Description | Use Case |
|----------|-------------|----------|
| Proportional | Distribute limit proportionally by rated power | Default, fair distribution |
| Priority | Limit lowest-priority inverter first | Protect primary inverter |
| Exclude | Skip specific inverters from limiting | Micro-inverters exempt |

### Frontend Additions

**No new JS libraries.** Existing patterns cover all needs:

| Need | Existing Pattern |
|------|-----------------|
| Device list/cards | `ve-card` + `ve-panel` components |
| Per-device dashboard | Reuse gauge, sparkline, phase table |
| Device type icons | CSS-only (SVG in CSS or unicode) |
| Tab navigation per device | Hash routing (`#device/<id>/dashboard`) |
| Add device flow | Modal pattern from config page |

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| HTTP client | aiohttp.ClientSession | httpx | Already have aiohttp; adding httpx means a new dependency for zero benefit |
| HTTP client | aiohttp.ClientSession | urllib3/requests | Not async-native; would need run_in_executor, adds complexity |
| Config format | Extended YAML | SQLite/JSON | YAML is established pattern, migration path is clean |
| Aggregation | In-process Python | Message broker (Redis) | Massive overkill for 2-5 inverters on same LAN |
| Device registry | Dict + dataclasses | SQLAlchemy/TinyDB | Out-of-scope complexity; in-memory + YAML persistence is sufficient |
| Plugin discovery | Explicit dict mapping | pluggy/entry_points | Only 2 plugin types; dynamic discovery is premature abstraction |

## What NOT to Add

| Library | Why Not |
|---------|---------|
| `httpx` | aiohttp already has a capable async HTTP client |
| `requests` | Not async; would block the event loop |
| `pydantic` | Dataclasses are sufficient for config validation; pydantic adds 5MB+ |
| `fastapi` | Already using aiohttp; no benefit to switching |
| `sqlalchemy` / `tinydb` | No database needed; YAML config + in-memory state is the pattern |
| `celery` / `dramatiq` | No task queue needed; asyncio.gather handles parallel polling |
| `pluggy` | Only 2 plugin types; dict-based dispatch is simpler and debuggable |
| Any JS framework | Zero-dependency vanilla JS is a core project constraint |

## Installation

```bash
# No new packages needed for v4.0
# Existing pyproject.toml dependencies cover everything:
pip install -e .
```

The only code additions are:
1. `src/venus_os_fronius_proxy/plugins/opendtu.py` -- new plugin file using `aiohttp.ClientSession`
2. Device registry logic in existing `config.py` (extend `InverterEntry` with `type` field)
3. Virtual inverter aggregation module (new file, pure Python)
4. Frontend: extend existing `app.js` / `index.html` / `style.css`

## Key Integration Points

### aiohttp.ClientSession Lifecycle

The `aiohttp.ClientSession` for OpenDTU polling must be created within an async context and properly closed on shutdown. Pattern:

```python
class OpenDTUPlugin(InverterPlugin):
    def __init__(self, host: str, port: int = 80, serial: str = "",
                 auth_user: str = "admin", auth_pass: str = "openDTU42"):
        self.host = host
        self.port = port
        self.serial = serial
        self._auth = aiohttp.BasicAuth(auth_user, auth_pass)
        self._session: aiohttp.ClientSession | None = None
        self._base_url = f"http://{host}:{port}"

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        # Verify connectivity
        async with self._session.get(f"{self._base_url}/api/livedata/status") as resp:
            resp.raise_for_status()

    async def poll(self) -> PollResult:
        async with self._session.get(
            f"{self._base_url}/api/livedata/status?inv={self.serial}"
        ) as resp:
            data = await resp.json()
            return self._json_to_poll_result(data)

    async def write_power_limit(self, enable: bool, limit_pct: float) -> WriteResult:
        payload = {
            "serial": self.serial,
            "limit_type": 1,  # relative (%)
            "limit_value": limit_pct if enable else 100,
        }
        async with self._session.post(
            f"{self._base_url}/api/limit/config",
            json=payload,
            auth=self._auth,
        ) as resp:
            return WriteResult(success=resp.status == 200)

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None
```

### Parallel Polling in Aggregator

```python
async def poll_all(plugins: list[InverterPlugin]) -> list[PollResult]:
    return await asyncio.gather(
        *(p.poll() for p in plugins),
        return_exceptions=True,
    )
```

### Config Migration Path

Existing `inverters:` list entries without a `type` field default to `"solaredge"`. No migration script needed -- just a default value in the dataclass.

## Sources

- OpenDTU Web API documentation: https://www.opendtu.solar/firmware/web_api/ (HIGH confidence, official docs)
- aiohttp ClientSession: https://docs.aiohttp.org/en/stable/client.html (HIGH confidence, already a dependency)
- Existing codebase: `plugin.py`, `plugins/solaredge.py`, `config.py`, `proxy.py`, `dashboard.py`, `__main__.py` (HIGH confidence, validated source)
- OpenDTU limit control: POST `/api/limit/config` with `limit_type: 1` (relative %) confirmed in official docs (HIGH confidence)
