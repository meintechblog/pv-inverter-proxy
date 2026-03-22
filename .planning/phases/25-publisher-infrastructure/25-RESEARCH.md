# Phase 25: Publisher Infrastructure & Broker Connectivity - Research

**Researched:** 2026-03-22
**Domain:** MQTT publishing infrastructure (aiomqtt), mDNS broker discovery (zeroconf), asyncio task lifecycle
**Confidence:** HIGH

## Summary

Phase 25 builds the MQTT publishing plumbing: an aiomqtt-based client that connects to a configurable broker, maintains a resilient connection with LWT, and exposes mDNS broker discovery. No telemetry payloads are published yet (Phase 26). The core architecture is a queue-based decoupled publisher task that runs alongside the existing poll/broadcast pipeline without blocking it.

The codebase has strong established patterns for everything this phase needs: dataclass configs (VenusConfig), asyncio task lifecycle (venus_task), hot-reload via cancel/recreate (config_save_handler), and AppContext state tracking. The implementation follows these patterns exactly, adding aiomqtt and zeroconf as the only new dependencies.

**Primary recommendation:** Use aiomqtt 2.5.x with asyncio.Queue(maxsize=100) decoupling, follow the venus_task lifecycle pattern exactly, and keep mDNS discovery as a manual REST endpoint only.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Use `aiomqtt` (>=2.3) for the publisher -- native asyncio, QoS 1, LWT, retain, auto-reconnect. Do NOT extend venus_reader.py raw socket client.
- **D-02:** Use `zeroconf` (>=0.140) for mDNS broker discovery -- AsyncZeroconf, discovers `_mqtt._tcp.local.` services.
- **D-03:** Leave venus_reader.py completely untouched -- existing Venus OS MQTT subscriber is a separate concern.
- **D-04:** Topic prefix `pvproxy` as default, configurable via `topic_prefix` in config.
- **D-05:** Topic layout: `{prefix}/{device_id}/state`, `{prefix}/{device_id}/availability`, `{prefix}/virtual/state`, `{prefix}/status`
- **D-06:** Availability topic uses LWT: "online" on connect, "offline" as Will message.
- **D-07:** New top-level key `mqtt_publish:` in config.yaml (separate from venus MQTT).
- **D-08:** Fields: `enabled` (bool, default false), `host` (str, default "mqtt-master.local"), `port` (int, default 1883), `topic_prefix` (str, default "pvproxy"), `interval_s` (int, default 5), `client_id` (str, default "pv-proxy-pub").
- **D-09:** New `MqttPublishConfig` dataclass in config.py following established pattern.
- **D-10:** Queue-based decoupling: asyncio.Queue (maxsize=100) between broadcast chain and publisher. Publisher task consumes from queue, never blocks poll loop.
- **D-11:** Publisher is a single asyncio.Task stored in AppContext as `mqtt_pub_task`.
- **D-12:** Hot-reload follows venus_reader pattern: cancel old task, create new task with new config on config save.
- **D-13:** Reconnect with exponential backoff (1s -> 2s -> 4s -> ... -> 30s cap) handled by aiomqtt.
- **D-14:** mDNS scan is manual only -- triggered via REST endpoint `POST /api/mqtt/discover`, no auto-scan at startup.
- **D-15:** Scan runs for 3 seconds, returns list of found brokers with hostname + port.
- **D-16:** mDNS scan logic in new module `mdns_discovery.py`, wired as webapp endpoint.

### Claude's Discretion
- Exact aiomqtt Client wrapper structure
- Queue overflow strategy (drop oldest vs block)
- Exact mDNS response format
- Error logging detail level
- Whether client_id includes hostname for uniqueness

### Deferred Ideas (OUT OF SCOPE)
- Actual telemetry payload format and publishing -- Phase 26
- Home Assistant MQTT Auto-Discovery config payloads -- Phase 26
- Webapp MQTT config UI -- Phase 27
- MQTT username/password auth -- Future
- TLS for MQTT -- Future
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CONN-01 | MQTT Broker Host/Port ist konfigurierbar (Default: mqtt-master.local:1883) | MqttPublishConfig dataclass with host/port fields, loaded from `mqtt_publish:` YAML section following established VenusConfig pattern |
| CONN-02 | Publisher reconnected automatisch mit Exponential Backoff bei Verbindungsverlust | aiomqtt's built-in reconnect via context manager re-entry pattern with 1s->30s backoff loop |
| CONN-03 | mDNS Autodiscovery findet MQTT Broker im LAN | zeroconf AsyncZeroconf + AsyncServiceBrowser for `_mqtt._tcp.local.`, manual trigger via `POST /api/mqtt/discover` |
| CONN-04 | Broker-Konfiguration ist hot-reloadable ohne Service-Restart | Cancel old mqtt_pub_task, create new task -- follows venus_task cancel/recreate pattern in config_save_handler |
| PUB-03 | Publish-Intervall ist konfigurierbar (Default: 5s) | `interval_s` field in MqttPublishConfig, used by publisher loop sleep |
| PUB-05 | Publisher nutzt LWT fuer Online/Offline-Availability-Tracking | aiomqtt `Will(topic, payload, qos=1, retain=True)` on Client constructor, explicit "online" publish on connect |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiomqtt | >=2.3,<3.0 (latest 2.5.1) | Async MQTT client for publisher | Native asyncio (`async with`), wraps paho-mqtt, QoS 0/1/2, LWT, retain. Only idiomatic asyncio MQTT client. |
| zeroconf | >=0.140,<1.0 (latest 0.148.0) | mDNS `_mqtt._tcp.local.` discovery | AsyncZeroconf, AsyncServiceBrowser. Pure Python, used by Home Assistant. Only real option for Python mDNS. |

### Supporting (transitive)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| paho-mqtt | >=2.0 (auto-installed) | Underlying MQTT protocol implementation | Never used directly -- aiomqtt wraps it |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| aiomqtt | Extend venus_reader.py raw sockets | Would need QoS 1 PUBACK, LWT, reconnect -- essentially reimplementing paho-mqtt. Decision D-01 explicitly forbids this. |
| aiomqtt | paho-mqtt directly | Callback-based, needs thread bridging with asyncio. aiomqtt wraps it cleanly. |
| zeroconf | avahi-browse subprocess | External dep on avahi-daemon, fragile output parsing, not async |

**Installation:**
```bash
pip install "aiomqtt>=2.3,<3.0" "zeroconf>=0.140,<1.0"
```

**Version verification:** aiomqtt 2.5.1 released 2026-03-05. zeroconf 0.148.0 released Oct 2025. Both actively maintained.

## Architecture Patterns

### Recommended Project Structure
```
src/venus_os_fronius_proxy/
├── mqtt_publisher.py     # NEW: Publisher loop, queue consumer, aiomqtt client
├── mdns_discovery.py     # NEW: mDNS broker scan via zeroconf
├── config.py             # MODIFIED: Add MqttPublishConfig dataclass
├── context.py            # MODIFIED: Add mqtt_pub_task, mqtt_pub_connected fields
├── __main__.py           # MODIFIED: Conditional publisher task creation + shutdown
└── webapp.py             # MODIFIED: Hot-reload in config_save_handler + POST /api/mqtt/discover
```

### Pattern 1: Queue-Decoupled Publisher (D-10)
**What:** asyncio.Queue sits between the broadcast chain and the MQTT publisher task. The broadcast chain (in `_on_aggregation_broadcast`) pushes snapshots to the queue without blocking. The publisher task consumes from the queue at its own pace.
**When to use:** Always -- this is the core architecture decision.
**Why:** If the MQTT broker is slow or unreachable, the poll loop and WebSocket broadcasts must not be affected. The queue absorbs the difference.

```python
# In mqtt_publisher.py
import asyncio
import json
import aiomqtt
import structlog

log = structlog.get_logger(component="mqtt_publisher")

async def mqtt_publish_loop(ctx, config):
    """Background task: consume from queue, publish to MQTT broker.

    Reconnects with exponential backoff on connection loss.
    Publishes LWT 'offline' via Will message on unexpected disconnect.
    """
    queue = ctx.mqtt_pub_queue  # asyncio.Queue(maxsize=100)
    backoff = 1.0
    max_backoff = 30.0

    while not ctx.shutdown_event.is_set():
        try:
            will = aiomqtt.Will(
                topic=f"{config.topic_prefix}/status",
                payload="offline",
                qos=1,
                retain=True,
            )
            async with aiomqtt.Client(
                hostname=config.host,
                port=config.port,
                identifier=config.client_id,
                will=will,
            ) as client:
                # Announce online
                await client.publish(
                    f"{config.topic_prefix}/status",
                    payload="online",
                    qos=1,
                    retain=True,
                )
                ctx.mqtt_pub_connected = True
                backoff = 1.0  # reset on success
                log.info("mqtt_pub_connected", host=config.host, port=config.port)

                # Consume from queue and publish
                while not ctx.shutdown_event.is_set():
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=config.interval_s)
                        topic = msg["topic"]
                        payload = msg["payload"]
                        await client.publish(topic, payload=json.dumps(payload), qos=0)
                    except asyncio.TimeoutError:
                        pass  # No messages in interval -- loop continues (keepalive handled by aiomqtt)

        except aiomqtt.MqttError as e:
            ctx.mqtt_pub_connected = False
            log.warning("mqtt_pub_disconnected", error=str(e), backoff=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        except asyncio.CancelledError:
            break

    ctx.mqtt_pub_connected = False
    log.info("mqtt_pub_stopped")
```

### Pattern 2: Config Dataclass (D-09, follows VenusConfig)
**What:** `MqttPublishConfig` dataclass added to config.py, loaded from YAML `mqtt_publish:` section.
**When to use:** For all MQTT publishing configuration.

```python
# In config.py
@dataclass
class MqttPublishConfig:
    enabled: bool = False
    host: str = "mqtt-master.local"
    port: int = 1883
    topic_prefix: str = "pvproxy"
    interval_s: int = 5
    client_id: str = "pv-proxy-pub"
```

Added to Config dataclass:
```python
mqtt_publish: MqttPublishConfig = field(default_factory=MqttPublishConfig)
```

Loaded in `load_config()` with same filtered-kwargs pattern:
```python
mqtt_publish=MqttPublishConfig(**{
    k: v for k, v in data.get("mqtt_publish", {}).items()
    if k in MqttPublishConfig.__dataclass_fields__
}),
```

### Pattern 3: AppContext Extension (D-11)
**What:** Add publisher state fields to AppContext.

```python
# In context.py, add to AppContext:
mqtt_pub_task: object = None           # asyncio.Task
mqtt_pub_connected: bool = False
mqtt_pub_queue: object = None          # asyncio.Queue
```

### Pattern 4: Conditional Task Creation (follows venus_task)
**What:** Start publisher task in `__main__.py` only if enabled.

```python
# In __main__.py run_with_shutdown(), after venus task creation:
if config.mqtt_publish.enabled:
    app_ctx.mqtt_pub_queue = asyncio.Queue(maxsize=100)
    app_ctx.mqtt_pub_task = asyncio.create_task(
        mqtt_publish_loop(app_ctx, config.mqtt_publish)
    )
else:
    log.info("mqtt_publish_skipped", reason="mqtt_publish.enabled is false")
```

### Pattern 5: Hot-Reload (D-12, follows venus_task cancel/recreate)
**What:** In `config_save_handler`, cancel old publisher task and start new one.

```python
# In webapp.py config_save_handler, after venus reload block:
if mqtt_publish_changed:
    old_task = app_ctx.mqtt_pub_task
    if old_task is not None and not old_task.done():
        old_task.cancel()
        try:
            await old_task
        except asyncio.CancelledError:
            pass

    if config.mqtt_publish.enabled:
        app_ctx.mqtt_pub_queue = asyncio.Queue(maxsize=100)
        app_ctx.mqtt_pub_task = asyncio.create_task(
            mqtt_publish_loop(app_ctx, config.mqtt_publish)
        )
    else:
        app_ctx.mqtt_pub_connected = False
        app_ctx.mqtt_pub_task = None
```

### Pattern 6: Graceful Shutdown with LWT
**What:** Cancel publisher task during shutdown, let LWT handle offline notification.

```python
# In __main__.py shutdown sequence, before device registry stop:
if app_ctx.mqtt_pub_task is not None:
    app_ctx.mqtt_pub_task.cancel()
    try:
        await app_ctx.mqtt_pub_task
    except asyncio.CancelledError:
        pass
    log.info("mqtt_publisher_stopped")
```

### Pattern 7: mDNS Discovery Endpoint (D-14, D-15, D-16)
**What:** `POST /api/mqtt/discover` triggers a 3-second mDNS scan, returns broker list.

```python
# In mdns_discovery.py
import asyncio
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf, AsyncServiceInfo

async def discover_mqtt_brokers(timeout: float = 3.0) -> list[dict]:
    """Scan LAN for _mqtt._tcp.local. services. Returns list of {host, port, name}."""
    found = []

    def on_state_change(zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Added:
            found.append(name)

    aiozc = AsyncZeroconf()
    browser = AsyncServiceBrowser(aiozc.zeroconf, "_mqtt._tcp.local.", handlers=[on_state_change])

    await asyncio.sleep(timeout)
    await browser.async_cancel()

    results = []
    for name in found:
        info = AsyncServiceInfo("_mqtt._tcp.local.", name)
        await info.async_request(aiozc.zeroconf, timeout=1000)
        if info.server and info.port:
            results.append({
                "host": info.server.rstrip("."),
                "port": info.port,
                "name": name.replace("._mqtt._tcp.local.", ""),
            })

    await aiozc.async_close()
    return results
```

### Anti-Patterns to Avoid
- **Publishing inside the poll loop hot path:** Never `await client.publish()` in the aggregation/broadcast chain. Use the queue.
- **Extending venus_reader.py:** Decision D-03 explicitly forbids this. The two MQTT connections are separate concerns.
- **Auto-scanning mDNS at startup:** Decision D-14 says manual-only. Startup mDNS can race with broker boot.
- **Blocking event loop with DNS resolution:** `mqtt-master.local` resolution can take seconds. aiomqtt handles this internally.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MQTT protocol (CONNECT, PUBLISH, PUBACK, LWT) | Raw socket MQTT packets | aiomqtt | QoS 1 needs PUBACK tracking, LWT needs Will flag in CONNECT, session persistence needs clean_session management |
| mDNS service discovery | Raw multicast UDP sockets | zeroconf AsyncZeroconf | mDNS is complex (multicast groups, DNS record types, caching). zeroconf handles all edge cases. |
| Reconnect with backoff | Custom retry loop around raw sockets | aiomqtt `MqttError` catch + sleep loop | aiomqtt raises `MqttError` on disconnect, making the reconnect loop trivial |
| Queue overflow handling | Custom ring buffer | asyncio.Queue with `put_nowait` + drop on `QueueFull` | stdlib Queue is battle-tested for this pattern |

## Common Pitfalls

### Pitfall 1: Queue Overflow When Broker is Unreachable
**What goes wrong:** If the broker is down for extended time, the queue fills up (maxsize=100). New messages from the broadcast chain get rejected.
**Why it happens:** Queue is bounded to prevent unbounded memory growth.
**How to avoid:** Use `try: queue.put_nowait(msg) except asyncio.QueueFull: pass` in the producer (broadcast chain). Dropping oldest is not needed -- the newest data supersedes old data for telemetry. Simply dropping when full is correct.
**Warning signs:** Log message "mqtt_pub_queue_full" appearing frequently.

### Pitfall 2: Client ID Collision with Venus Reader
**What goes wrong:** If both MQTT connections use the same client ID and happen to connect to the same broker, the broker disconnects the first client.
**Why it happens:** MQTT spec requires unique client IDs per broker.
**How to avoid:** Venus reader uses "pv-proxy-sub" (in venus_reader.py). Publisher uses "pv-proxy-pub" (from config). Different IDs by default.
**Warning signs:** Venus reader disconnects repeatedly after publisher starts.

### Pitfall 3: aiomqtt Context Manager Exit on CancelledError
**What goes wrong:** When cancelling the publisher task for hot-reload, `aiomqtt.Client.__aexit__` sends DISCONNECT to the broker. But if the broker is unreachable, the DISCONNECT may hang.
**Why it happens:** aiomqtt's context manager is designed for clean disconnect.
**How to avoid:** The cancel + await pattern with `except asyncio.CancelledError: pass` handles this. aiomqtt internally handles CancelledError in its cleanup.
**Warning signs:** Hot-reload takes >5 seconds.

### Pitfall 4: mDNS Scan Holds Resources After Timeout
**What goes wrong:** If `AsyncZeroconf` is not properly closed, it leaks multicast sockets and background threads.
**Why it happens:** zeroconf opens multicast UDP sockets and starts listener threads.
**How to avoid:** Always call `await aiozc.async_close()` in a finally block.
**Warning signs:** "Address already in use" errors on repeated scans, resource warnings.

### Pitfall 5: Stale "online" Status After Ungraceful Shutdown
**What goes wrong:** If the proxy crashes (SIGKILL, power loss), the "online" retained message stays on the broker until LWT fires after keepalive timeout.
**Why it happens:** LWT fires after broker detects client gone (1.5x keepalive interval).
**How to avoid:** Set aiomqtt keepalive to 30s (default 60s). This means broker detects crash within ~45 seconds and publishes "offline" LWT.
**Warning signs:** HA shows device as "online" for a minute after proxy crash.

## Code Examples

### aiomqtt Will Message (LWT)
```python
# Source: aiomqtt documentation + paho-mqtt Will interface
import aiomqtt

will = aiomqtt.Will(
    topic="pvproxy/status",
    payload="offline",
    qos=1,
    retain=True,
)

async with aiomqtt.Client(
    hostname="mqtt-master.local",
    port=1883,
    identifier="pv-proxy-pub",
    will=will,
    keepalive=30,
) as client:
    # Publish "online" on successful connect
    await client.publish("pvproxy/status", payload="online", qos=1, retain=True)
```

### Queue Producer in Broadcast Chain
```python
# In __main__.py _on_aggregation_broadcast, after WebSocket broadcasts:
queue = app_ctx.mqtt_pub_queue
if queue is not None:
    msg = {"topic": f"{config.mqtt_publish.topic_prefix}/{device_id}/state", "payload": snapshot}
    try:
        queue.put_nowait(msg)
    except asyncio.QueueFull:
        log.debug("mqtt_pub_queue_full", device_id=device_id)
```

### mDNS Discovery with Timeout
```python
# Source: python-zeroconf async API
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf, AsyncServiceInfo

async def discover_mqtt_brokers(timeout: float = 3.0) -> list[dict]:
    found_names = []

    def handler(zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Added:
            found_names.append(name)

    aiozc = AsyncZeroconf()
    try:
        browser = AsyncServiceBrowser(aiozc.zeroconf, "_mqtt._tcp.local.", handlers=[handler])
        await asyncio.sleep(timeout)
        await browser.async_cancel()

        results = []
        for name in found_names:
            info = AsyncServiceInfo("_mqtt._tcp.local.", name)
            await info.async_request(aiozc.zeroconf, timeout=1000)
            if info.server and info.port:
                results.append({
                    "host": info.server.rstrip("."),
                    "port": info.port,
                    "name": name.replace("._mqtt._tcp.local.", ""),
                })
        return results
    finally:
        await aiozc.async_close()
```

### Config YAML Example
```yaml
# In config.yaml
mqtt_publish:
  enabled: false
  host: "mqtt-master.local"
  port: 1883
  topic_prefix: "pvproxy"
  interval_s: 5
  client_id: "pv-proxy-pub"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| paho-mqtt callbacks + threading | aiomqtt async context manager | aiomqtt 2.0 (2024) | No callbacks, no thread bridging needed |
| asyncio-mqtt (old name) | aiomqtt (renamed) | 2023 | Import path changed to `aiomqtt` |
| zeroconf sync API | AsyncZeroconf async API | zeroconf 0.36+ | Native asyncio support, no executor needed |

**Deprecated/outdated:**
- `asyncio-mqtt` package name: renamed to `aiomqtt`, old name still works as redirect but use new name
- aiomqtt `Client.connect()`/`Client.disconnect()`: removed in v2.0, use `async with` context manager only

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.23+ |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_mqtt_publisher.py -x` |
| Full suite command | `python -m pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CONN-01 | MqttPublishConfig loads host/port from YAML with defaults | unit | `python -m pytest tests/test_config.py -x -k mqtt` | Extend existing |
| CONN-02 | Publisher reconnects with backoff on MqttError | unit | `python -m pytest tests/test_mqtt_publisher.py -x -k reconnect` | Wave 0 |
| CONN-03 | mDNS discovers _mqtt._tcp.local. services | unit | `python -m pytest tests/test_mdns_discovery.py -x` | Wave 0 |
| CONN-04 | Hot-reload cancels old task, creates new | unit | `python -m pytest tests/test_mqtt_publisher.py -x -k hot_reload` | Wave 0 |
| PUB-03 | interval_s config field used in publisher loop | unit | `python -m pytest tests/test_config.py -x -k mqtt_interval` | Extend existing |
| PUB-05 | Will message set on Client, "online" published on connect | unit | `python -m pytest tests/test_mqtt_publisher.py -x -k lwt` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_mqtt_publisher.py tests/test_mdns_discovery.py tests/test_config.py -x`
- **Per wave merge:** `python -m pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_mqtt_publisher.py` -- covers CONN-01, CONN-02, CONN-04, PUB-03, PUB-05 (mock aiomqtt.Client)
- [ ] `tests/test_mdns_discovery.py` -- covers CONN-03 (mock AsyncZeroconf, AsyncServiceBrowser)
- [ ] Extend `tests/test_config.py` -- MqttPublishConfig load/save/defaults

## Open Questions

1. **Queue overflow strategy: drop silently or log?**
   - What we know: Decision D-10 says maxsize=100. Dropping when full is correct for telemetry.
   - What's unclear: Whether to log every drop or only periodically.
   - Recommendation: Use `log.debug("mqtt_pub_queue_full")` -- debug level to avoid log spam when broker is down for extended time.

2. **Client ID uniqueness across multiple proxy instances**
   - What we know: D-08 sets default "pv-proxy-pub". If two proxies run on same LAN pointing to same broker, client IDs collide.
   - What's unclear: Whether multi-instance is a real use case.
   - Recommendation: Append hostname suffix for uniqueness: `pv-proxy-pub-{socket.gethostname()[:8]}`. Claude's discretion per CONTEXT.md.

3. **aiomqtt keepalive default**
   - What we know: MQTT keepalive controls how fast broker detects client death for LWT.
   - What's unclear: Whether 30s or 60s is better.
   - Recommendation: Use 30s -- LWT fires within ~45s of crash, acceptable for Home Assistant availability.

## Sources

### Primary (HIGH confidence)
- [aiomqtt GitHub (empicano)](https://github.com/empicano/aiomqtt) - v2.5.1, 2026-03-05, Will/LWT, Client API, reconnect pattern
- [aiomqtt PyPI](https://pypi.org/project/aiomqtt/) - version 2.5.1 confirmed
- [python-zeroconf GitHub](https://github.com/python-zeroconf/python-zeroconf) - v0.148.0, AsyncZeroconf API
- [python-zeroconf API docs](https://python-zeroconf.readthedocs.io/en/latest/api.html) - AsyncServiceBrowser, AsyncServiceInfo
- Existing codebase: config.py, context.py, __main__.py, webapp.py, venus_reader.py (HIGH, source of truth for patterns)
- `.planning/research/STACK.md`, `ARCHITECTURE.md`, `PITFALLS.md` (HIGH, prior milestone research)

### Secondary (MEDIUM confidence)
- [aiomqtt CHANGELOG](https://github.com/empicano/aiomqtt/blob/main/CHANGELOG.md) - v2.0 breaking changes, v2.5.1 latest

### Tertiary (LOW confidence)
- None -- all findings verified against primary sources.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - aiomqtt and zeroconf versions verified against PyPI, APIs confirmed via docs
- Architecture: HIGH - follows established codebase patterns exactly (venus_task, config dataclass, hot-reload)
- Pitfalls: HIGH - derived from prior milestone research + codebase analysis + MQTT protocol knowledge

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (30 days -- stable domain, libraries actively maintained)
