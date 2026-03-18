# Phase 11: Venus OS Widget & Lock Toggle - Research

**Researched:** 2026-03-18
**Domain:** Safety-critical UI lock toggle, Venus OS connection info widget, pymodbus server internals
**Confidence:** HIGH

## Summary

This phase adds a Venus OS info widget and a safety-critical lock toggle to the dashboard. The lock toggle blocks Venus OS Modbus writes from reaching the inverter while silently accepting them (so Venus OS does not retry aggressively). An auto-unlock timer (max 15 minutes) ensures Venus OS is never permanently locked out -- this is a grid compliance safety requirement.

The backend changes are small: add `is_locked` and `lock_expires_at` to `ControlState`, add a lock check in `_handle_control_write()`, add a lock expiry check in `edpc_refresh_loop()`, and add a `POST /api/venus-lock` endpoint. The frontend adds an Apple-style CSS toggle (already researched in STACK.md) with confirmation dialog (reusing existing `showConfirmDialog()` pattern) and a countdown timer.

**Primary recommendation:** Implement lock state entirely in `ControlState` (backend-authoritative). Lock check goes in `_handle_control_write()` before the `write_power_limit()` call. Auto-unlock check goes in `edpc_refresh_loop()` alongside the existing webapp revert check. Venus OS IP display should be skipped -- pymodbus 3.x does not expose client IP through its public API.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
None -- all implementation decisions delegated to Claude's discretion.

### Claude's Discretion
All implementation decisions for this phase are delegated to Claude. Key areas:

**Venus OS Info Widget:**
- What info to display (connection status, last contact timestamp, current override value)
- How to determine Venus OS connection status (passive tracking via last_change_ts from ControlState, NOT active Modbus polling to Venus OS)
- IP display: use configured SolarEdge IP as proxy for "system is working" or skip IP entirely if pymodbus server doesn't expose client IP
- Widget styling consistent with existing ve-card pattern

**Lock Toggle (Safety-Critical):**
- Apple-style CSS toggle (checkbox hack with opacity:0, ::before pseudo-element)
- Confirmation dialog REQUIRED before locking (same pattern as power control confirmation)
- Lock semantics: when locked, Venus OS Modbus writes to Model 123 are silently accepted but NOT forwarded to inverter
- Auto-unlock timer: max 15 minutes, countdown visible in UI
- Backend: add is_locked flag to ControlState, check in StalenessAwareSlaveContext.setValues() before forwarding writes
- Lock state persisted only in-memory (resets to unlocked on restart -- safe default)
- Toast notification when lock activates/deactivates and when auto-unlock triggers
- Lock toggle disabled when Venus OS is not active (no point locking what isn't controlling)

**Backend Integration:**
- Extend ControlState with lock fields (is_locked, lock_expires_at)
- Extend snapshot with lock state for WebSocket push
- POST /api/venus-lock endpoint for toggling
- Lock expiry checked in poll loop or EDPC refresh loop

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| VENUS-01 | Venus OS Info Widget shows connection status (Online/Offline), IP address, and last contact | Passive tracking via `control_state.last_change_ts` and `last_source`; IP skipped (see pymodbus findings); connection status derived from recency of last Venus OS write |
| VENUS-02 | Widget shows current override status (whether Venus OS has control and at what value) | Already in snapshot: `control.last_source`, `control.limit_pct`, `control.enabled` |
| VENUS-03 | Apple-style Lock Toggle with confirmation dialog | CSS toggle pattern from STACK.md; confirmation dialog reuses `showConfirmDialog()`; POST /api/venus-lock endpoint |
| VENUS-04 | Lock Toggle has auto-unlock timer (max 15 minutes) as safety feature | `lock_expires_at` in ControlState checked by `edpc_refresh_loop()` every 30s; countdown displayed in UI from snapshot |
</phase_requirements>

## Standard Stack

### Core (No New Dependencies)

| Technology | Version | Purpose | Notes |
|------------|---------|---------|-------|
| Python | 3.12 | Backend runtime | Unchanged |
| pymodbus | >=3.6,<4.0 | Modbus TCP server | Lock check in _handle_control_write |
| aiohttp | >=3.10,<4.0 | REST endpoint + WebSocket | New POST /api/venus-lock |
| CSS3 | Modern | Apple-style toggle | Checkbox hack pattern |
| Vanilla JS | ES6+ | Lock toggle handler, countdown | No new deps |

**Installation:** No changes. Zero new dependencies.

## Architecture Patterns

### Recommended Project Structure (Changes Only)

```
src/venus_os_fronius_proxy/
  control.py          # ADD: is_locked, lock_expires_at, lock/unlock methods
  proxy.py            # MODIFY: _handle_control_write lock check
  webapp.py           # ADD: POST /api/venus-lock endpoint
  dashboard.py        # MODIFY: add venus_os section to snapshot
  static/
    index.html        # ADD: Venus OS widget card with lock toggle
    style.css         # ADD: .ve-toggle, .ve-lock-countdown, .ve-venus-card styles
    app.js            # ADD: updateVenusInfo(), lock toggle handler, countdown timer
```

### Pattern 1: Backend-Authoritative Lock State

**What:** Lock state lives in `ControlState` (Python). Frontend reflects state from snapshot. All lock decisions are backend-enforced.

**When to use:** Always. Safety-critical state must be backend-authoritative.

**Example (control.py additions):**
```python
class ControlState:
    def __init__(self) -> None:
        # ... existing fields ...
        self.is_locked: bool = False
        self.lock_expires_at: float | None = None  # time.monotonic() deadline

    def lock(self, duration_s: float = 900.0) -> None:
        """Lock Venus OS control for duration_s seconds (max 900)."""
        duration_s = min(duration_s, 900.0)  # hard cap at 15 min
        self.is_locked = True
        self.lock_expires_at = time.monotonic() + duration_s

    def unlock(self) -> None:
        """Unlock Venus OS control."""
        self.is_locked = False
        self.lock_expires_at = None

    def check_lock_expiry(self) -> bool:
        """Check and auto-unlock if expired. Returns True if unlock happened."""
        if self.is_locked and self.lock_expires_at is not None:
            if time.monotonic() >= self.lock_expires_at:
                self.unlock()
                return True
        return False

    @property
    def lock_remaining_s(self) -> float | None:
        """Seconds until lock expires, or None if not locked."""
        if self.is_locked and self.lock_expires_at is not None:
            return max(0.0, self.lock_expires_at - time.monotonic())
        return None
```

### Pattern 2: Lock Check in _handle_control_write

**What:** When locked, Venus OS writes are accepted (stored in local registers for readback) but NOT forwarded to the inverter via `plugin.write_power_limit()`. Venus OS sees a successful write response, preventing aggressive retries.

**When to use:** Every Venus OS Model 123 write.

**Where exactly (proxy.py):** In `_handle_control_write()`, AFTER validation but BEFORE `plugin.write_power_limit()`.

**Example (proxy.py modification):**
```python
async def _handle_control_write(self, abs_addr: int, values: list[int]) -> None:
    offset = abs_addr - MODEL_123_START

    if offset == WMAXLIMPCT_OFFSET and len(values) >= 1:
        error = validate_wmaxlimpct(values[0])
        if error:
            # ... existing rejection ...
            raise Exception(f"ILLEGAL_VALUE: {error}")

        self._control.update_wmaxlimpct(values[0])

        # --- LOCK CHECK: accept write but skip inverter forwarding ---
        if self._control.is_locked:
            control_log.info(
                "power_limit_write",
                wmaxlimpct=values[0], result="locked",
                detail="Venus OS write accepted, not forwarded to inverter",
            )
            # Still update readback registers so Venus OS sees its value
            self._update_model_123_readback()
            # Do NOT call set_from_venus_os() -- don't update source tracking
            return

        # ... existing forwarding logic (unchanged) ...
```

**Critical design decision:** When locked, we do NOT call `self._control.set_from_venus_os()`. This means:
1. The `last_source` stays at whatever it was before (not "venus_os")
2. The Venus OS priority window check in `power_limit_handler` is not triggered
3. The webapp can still control the inverter while Venus OS is locked out
4. Venus OS's readback registers still show the value it wrote (no error response)

### Pattern 3: Lock Expiry in edpc_refresh_loop

**What:** Add lock expiry check alongside existing webapp revert check.

**Where:** `edpc_refresh_loop()` in control.py, which already runs every 30 seconds.

**Example:**
```python
async def edpc_refresh_loop(...) -> None:
    while True:
        await asyncio.sleep(interval)

        # Check lock expiry (BEFORE other checks)
        if control_state.check_lock_expiry():
            override_log.append("system", "unlock", None, "auto-unlock after timeout")
            if broadcast_fn is not None:
                await broadcast_fn()

        # ... existing auto-revert and refresh logic ...
```

**Timing:** Lock expiry is checked every 30s (edpc refresh interval). This means the actual unlock may happen up to 30s late. This is acceptable for a 15-minute timer. The UI countdown is cosmetic -- it shows the intended expiry time, not synced to the backend check cycle.

### Pattern 4: Extend Snapshot (Not New Message Types)

**What:** Add `venus_os` section to existing snapshot dict.

**Where:** `DashboardCollector.collect()` in dashboard.py.

**Example:**
```python
# In collect(), after building control section:
venus_os = {}
if control_state is not None:
    venus_os = {
        "last_source": getattr(control_state, "last_source", "none"),
        "last_change_ts": getattr(control_state, "last_change_ts", 0.0),
        "is_locked": getattr(control_state, "is_locked", False),
        "lock_remaining_s": getattr(control_state, "lock_remaining_s", None),
    }

snapshot = {
    "ts": time.time(),
    "inverter": inverter,
    "control": control,
    "connection": connection,
    "venus_os": venus_os,  # NEW
    "override_log": ...,
}
```

### Anti-Patterns to Avoid

- **Frontend-only lock state:** Lock MUST be in ControlState. A JavaScript-only lock provides zero safety guarantee.
- **Returning Modbus error when locked:** Venus OS will retry aggressively if it gets an error response. Accept the write silently.
- **Permanent lock (no auto-unlock):** Violates grid compliance. The 15-minute cap is non-negotiable.
- **Polling Venus OS for connection status:** Use passive tracking from existing writes. No new Modbus connections.
- **New WebSocket message type for lock state:** Extend the snapshot, follow established pattern.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Confirmation dialog | New dialog system | Existing `showConfirmDialog()` | Already proven, consistent UX |
| Toast notifications | New notification system | Existing `showToast()` | Already has stacking, dedup, auto-dismiss |
| Toggle CSS | JS toggle library | CSS checkbox hack from STACK.md | Zero-dep, accessible by default |
| Timer precision | High-precision countdown | Cosmetic countdown from snapshot | Backend is authoritative, UI is display-only |
| Venus OS connection tracking | Active Modbus polling to Venus OS | Passive tracking via ControlState.last_change_ts | Zero overhead, data already available |

## Common Pitfalls

### Pitfall 1: Lock Bypass During WMaxLim_Ena Write

**What goes wrong:** The lock check is only added for `WMAXLIMPCT_OFFSET` writes but not for `WMAXLIM_ENA_OFFSET` writes. Venus OS could enable/disable power limiting even while "locked."

**Why it happens:** `_handle_control_write()` has two separate code paths -- one for WMaxLimPct (offset 5) and one for WMaxLim_Ena (offset 9). A lock check in only one path leaves the other open.

**How to avoid:** Add the same lock check pattern in BOTH code paths. When locked, both WMaxLimPct and WMaxLim_Ena writes should be accepted locally but not forwarded.

### Pitfall 2: Lock Expiry During Active EDPC Refresh

**What goes wrong:** The EDPC refresh loop writes the current power limit to the inverter every 30s. If the lock expires mid-cycle, and immediately after, Venus OS sends a new write, there's a brief window where the old (pre-lock) limit gets refreshed to the inverter AND then Venus OS's new value also gets forwarded.

**Why it happens:** The lock expiry check and the EDPC refresh happen in the same loop iteration. After unlock, the `is_enabled` check in edpc_refresh_loop will attempt to refresh the current limit.

**How to avoid:** After auto-unlock, do NOT refresh the old limit. Just unlock and let the next Venus OS write (or webapp action) establish a new limit. The auto-unlock should simply clear the lock flag, not trigger any inverter write.

### Pitfall 3: Lock Toggle Disabled State Stale After Venus OS Stops Writing

**What goes wrong:** The lock toggle should be disabled when Venus OS is "not active." But Venus OS connection status is derived from `last_change_ts` recency. If Venus OS wrote 2 minutes ago and then stopped, `last_source` is still "venus_os" -- the toggle stays enabled. But if Venus OS wrote 30 minutes ago, the status should show "Offline" and the toggle should be disabled.

**How to avoid:** Define a clear timeout for "Venus OS is active": if `last_source == "venus_os"` AND `last_change_ts` is within the last N seconds (suggest 120s = 2 minutes, which is generous since Venus OS writes every ~3s when active). Outside this window, show Venus OS as "Offline" and disable the lock toggle.

### Pitfall 4: Race Between Webapp Power Limit and Lock State

**What goes wrong:** User locks Venus OS, then sets a power limit via webapp. The webapp power limit has a 5-minute auto-revert. When the lock expires (up to 15 min), Venus OS can write again. But the webapp's revert timer might have already fired, disabling the limit. Now Venus OS takes control immediately after unlock.

**Why it happens:** Lock and webapp power limit are independent timers on the same `ControlState`.

**How to avoid:** This is actually correct behavior -- when the lock expires, Venus OS SHOULD be able to take control again. Document this interaction for the user: "After lock expires, Venus OS will resume control if it is still actively writing."

### Pitfall 5: Countdown Display Drift

**What goes wrong:** The UI countdown shows `lock_remaining_s` from the snapshot, which updates every 1 second (poll interval). But between snapshots, the displayed countdown is stale. If the user watches closely, the countdown appears to "jump" every second rather than counting smoothly.

**How to avoid:** Use JavaScript `setInterval()` to decrement the countdown locally between snapshots. Store the `lock_remaining_s` and `snapshot_ts` on each update, then interpolate: `displayed = lock_remaining_s - (Date.now()/1000 - snapshot_ts)`. Reset on each new snapshot.

## Code Examples

### Venus OS Info Widget HTML

```html
<!-- In ve-dashboard-bottom grid -->
<div class="ve-card" id="venus-os-panel">
  <h2 class="ve-card-title">Venus OS Control</h2>
  <div class="ve-status-row">
    <span class="ve-status-indicator" id="venus-status-dot"></span>
    <span id="venus-status-text">--</span>
  </div>
  <div class="ve-grid">
    <div><label>Override</label><span class="ve-live-value" id="venus-override">--</span></div>
    <div><label>Last Contact</label><span class="ve-live-value" id="venus-last-contact">--</span></div>
  </div>
  <!-- Lock Toggle -->
  <div class="ve-venus-lock" id="venus-lock-section">
    <div class="ve-venus-lock-row">
      <span class="ve-venus-lock-label">Lock Venus OS</span>
      <label class="ve-toggle" id="venus-lock-container">
        <input type="checkbox" id="venus-lock-toggle" disabled>
        <span class="ve-toggle-track"></span>
      </label>
    </div>
    <div class="ve-lock-countdown" id="lock-countdown" style="display:none">
      Auto-unlock in: <span id="lock-countdown-time">15:00</span>
    </div>
  </div>
</div>
```

### Apple-Style Toggle CSS (from STACK.md, verified)

```css
/* Source: .planning/research/STACK.md */
.ve-toggle {
    position: relative;
    display: inline-block;
    width: 52px;
    height: 28px;
}

.ve-toggle input {
    opacity: 0;
    width: 0;
    height: 0;
    position: absolute;
}

.ve-toggle-track {
    position: absolute;
    cursor: pointer;
    top: 0; left: 0; right: 0; bottom: 0;
    background: var(--ve-border);
    border-radius: 28px;
    transition: background var(--ve-duration-normal) var(--ve-easing-default);
}

.ve-toggle-track::before {
    content: '';
    position: absolute;
    height: 22px;
    width: 22px;
    left: 3px;
    bottom: 3px;
    background: var(--ve-text);
    border-radius: 50%;
    transition: transform var(--ve-duration-normal) cubic-bezier(0.34, 1.56, 0.64, 1);
}

.ve-toggle input:checked + .ve-toggle-track {
    background: var(--ve-red);  /* Red = locked (danger state) */
}

.ve-toggle input:checked + .ve-toggle-track::before {
    transform: translateX(24px);
}

.ve-toggle input:disabled + .ve-toggle-track {
    opacity: 0.4;
    cursor: not-allowed;
}
```

### Lock Toggle JavaScript Handler

```javascript
// Lock toggle click handler (with confirmation dialog)
(function() {
    var toggle = document.getElementById('venus-lock-toggle');
    if (!toggle) return;

    toggle.addEventListener('change', function(e) {
        e.preventDefault();
        var wantLock = toggle.checked;

        if (wantLock) {
            // Revert toggle visually until confirmed
            toggle.checked = false;
            showConfirmDialog(
                'Lock Venus OS control for <strong>15 minutes</strong>?<br>' +
                'Venus OS will not be able to limit inverter power during this time.<br>' +
                'Auto-unlock at ' + formatAutoUnlockTime() + '.',
                function() { sendLockCommand(true); }
            );
        } else {
            sendLockCommand(false);
        }
    });
})();

async function sendLockCommand(lock) {
    try {
        var res = await fetch('/api/venus-lock', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: lock ? 'lock' : 'unlock' })
        });
        var data = await res.json();
        if (data.success) {
            showToast(lock ? 'Venus OS control locked' : 'Venus OS control unlocked',
                      lock ? 'warning' : 'success');
        } else {
            showToast(data.error || 'Failed to change lock state', 'error');
        }
    } catch (e) {
        showToast('Request failed: ' + e.message, 'error');
    }
}
```

### POST /api/venus-lock Endpoint

```python
async def venus_lock_handler(request: web.Request) -> web.Response:
    """Toggle Venus OS control lock."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"success": False, "error": "Invalid JSON body"}, status=400,
        )

    action = body.get("action")
    if action not in ("lock", "unlock"):
        return web.json_response(
            {"success": False, "error": f"Unknown action: {action}"}, status=400,
        )

    shared_ctx = request.app["shared_ctx"]
    control = shared_ctx["control_state"]
    override_log = shared_ctx.get("override_log")

    if action == "lock":
        control.lock(duration_s=900.0)  # 15 min hard cap
        if override_log:
            override_log.append("webapp", "lock", None, "Venus OS control locked")
    else:
        control.unlock()
        if override_log:
            override_log.append("webapp", "unlock", None, "Venus OS control unlocked")

    return web.json_response({"success": True})
```

## Research Findings: Key Technical Questions

### Q1: Can pymodbus server expose Venus OS client IP?

**Answer: No (not through public API). Confidence: HIGH.**

pymodbus 3.x `ModbusTcpServer` has a `trace_connect` callback, but its signature is `Callable[[bool], None]` -- it only receives a boolean (connected/disconnected), not client address information. The internal `ModbusProtocol` class has an `active_connections` dict and each protocol has a `transport` (asyncio), which theoretically supports `transport.get_extra_info('peername')`. However, this is internal API, not documented, and version-dependent.

**Decision:** Skip Venus OS IP display. Show connection status derived from `last_change_ts` recency instead. The CONTEXT.md explicitly allows this: "skip IP entirely if pymodbus server doesn't expose client IP."

**Sources:**
- [pymodbus issue #2159](https://github.com/pymodbus-dev/pymodbus/issues/2159) -- maintainer confirmed no public API for client IP
- [pymodbus 3.8.1 server docs](https://pymodbus.readthedocs.io/en/v3.8.1/source/server.html) -- trace_connect signature is `Callable[[bool], None]`

### Q2: Exact code path for lock check in setValues

**Answer: `_handle_control_write()` in proxy.py, lines 128-228. Confidence: HIGH.**

The write interception happens in `StalenessAwareSlaveContext.async_setValues()` (line 104), which delegates to `_handle_control_write()` (line 128) for Model 123 addresses. The lock check must go in `_handle_control_write()` at TWO points:
1. After `validate_wmaxlimpct()` passes but before `plugin.write_power_limit()` (WMaxLimPct path, around line 148)
2. After `ena_value in (0, 1)` check passes but before `plugin.write_power_limit()` (WMaxLim_Ena path, around line 198)

In both cases: accept the write (update local registers for readback), log it as "locked", skip the `plugin.write_power_limit()` call, and skip `set_from_venus_os()`.

### Q3: Auto-unlock expiry mechanism

**Answer: Use `edpc_refresh_loop()` in control.py. Confidence: HIGH.**

The `edpc_refresh_loop()` already runs every 30 seconds and checks `webapp_revert_at` for auto-revert. Adding `control_state.check_lock_expiry()` at the top of the loop is the natural place. This reuses the existing async loop infrastructure with zero new tasks or timers.

**Why not a separate asyncio task?** Unnecessary complexity. The 30s check granularity is fine for a 15-minute timer. The UI countdown is cosmetically interpolated in JavaScript.

### Q4: Venus OS connection status without active polling

**Answer: Derive from `last_source` and `last_change_ts` in ControlState. Confidence: HIGH.**

Venus OS writes to Model 123 approximately every 3 seconds when DVCC is active. If `last_source == "venus_os"` AND `time.time() - last_change_ts < 120`, Venus OS is "Online." Otherwise "Offline."

This is already tracked in `ControlState.set_from_venus_os()` (called on every Venus OS write). No new tracking needed -- just expose it in the snapshot.

Note: Venus OS also READS registers (getValues) every ~3s. Currently this is not tracked. For a more accurate "Online" indicator, we could track last read time in `StalenessAwareSlaveContext.getValues()`. However, writes are sufficient for the Venus OS widget since we mainly care about whether Venus OS is actively controlling the inverter.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No Venus OS visibility | Passive tracking via ControlState | Phase 7 (v2.0) | last_source and last_change_ts already exist |
| No lock mechanism | Lock with auto-unlock timer | This phase (v2.1) | Safety-critical addition |
| Power control on separate page | Inline on dashboard | Phase 12 (planned) | Lock toggle goes in Venus OS widget now, not power control page |

## Open Questions

1. **Venus OS write frequency when DVCC disabled**
   - What we know: When DVCC is active, Venus OS writes Model 123 every ~3s
   - What's unclear: When DVCC is disabled, Venus OS may not write at all -- the "Online/Offline" indicator would always show "Offline"
   - Recommendation: Display "No control activity" rather than "Offline" when last_source is never "venus_os", to avoid confusion

2. **Lock toggle visual semantics**
   - What we know: Toggle ON = locked (danger), Toggle OFF = unlocked (normal)
   - What's unclear: Should the toggle label say "Lock Venus OS" or "Venus OS Control Allowed"? Former makes ON=lock intuitive; latter makes ON=good
   - Recommendation: Use "Lock Venus OS" with toggle OFF by default (unlocked). Red track when checked (locked). This matches the danger-action paradigm.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.23+ |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_control.py tests/test_webapp.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| VENUS-01 | Venus OS status in snapshot | unit | `pytest tests/test_dashboard.py -x -k venus` | Needs new tests |
| VENUS-02 | Override status in snapshot | unit | `pytest tests/test_dashboard.py -x -k override` | Partially exists |
| VENUS-03 | Lock toggle endpoint + lock check in write path | unit+integration | `pytest tests/test_control.py tests/test_webapp.py tests/test_proxy.py -x -k lock` | Needs new tests |
| VENUS-04 | Auto-unlock timer + lock expiry | unit | `pytest tests/test_control.py -x -k lock_expiry` | Needs new tests |

### Sampling Rate

- **Per task commit:** `pytest tests/test_control.py tests/test_webapp.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before verify

### Wave 0 Gaps

- [ ] `tests/test_control.py` -- add tests for ControlState.lock(), unlock(), check_lock_expiry(), lock_remaining_s
- [ ] `tests/test_proxy.py` -- add tests for _handle_control_write with is_locked=True (both WMaxLimPct and WMaxLim_Ena paths)
- [ ] `tests/test_webapp.py` -- add tests for POST /api/venus-lock endpoint
- [ ] `tests/test_dashboard.py` -- add tests for venus_os section in snapshot

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis of `control.py`, `proxy.py`, `webapp.py`, `dashboard.py`, `app.js`, `style.css`, `index.html`
- `.planning/research/STACK.md` -- Apple-style toggle CSS pattern (verified)
- `.planning/research/PITFALLS.md` -- Safety requirements for lock toggle (Pitfall 2)
- `.planning/research/ARCHITECTURE.md` -- Venus OS passive tracking approach

### Secondary (MEDIUM confidence)
- [pymodbus issue #2159](https://github.com/pymodbus-dev/pymodbus/issues/2159) -- maintainer confirmed no public API for client IP
- [pymodbus 3.8.1 server docs](https://pymodbus.readthedocs.io/en/v3.8.1/source/server.html) -- trace_connect callback signature

### Tertiary (LOW confidence)
- pymodbus internal `active_connections` dict and `transport.get_extra_info('peername')` -- exists in source but undocumented, version-dependent

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new deps, all patterns verified in existing code
- Architecture: HIGH - extends proven ControlState + snapshot pattern, all insertion points identified in source
- Lock safety: HIGH - auto-unlock in edpc_refresh_loop follows existing webapp_revert_at pattern exactly
- Venus OS IP: HIGH (negative finding) - confirmed pymodbus does not expose client IP through public API
- Pitfalls: HIGH - based on direct code analysis of write paths and timing

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable domain, no fast-moving deps)
