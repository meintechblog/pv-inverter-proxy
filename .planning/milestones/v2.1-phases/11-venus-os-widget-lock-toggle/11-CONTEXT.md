# Phase 11: Venus OS Widget & Lock Toggle - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a Venus OS info widget to the dashboard showing connection status, last contact, and override state. Add an Apple-style lock toggle to block/allow Venus OS power control, with confirmation dialog and auto-unlock safety timer. No layout changes — widget added to existing grid (Phase 12 handles layout merge).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation decisions for this phase are delegated to Claude. User trusts Claude to make good choices, including safety-critical Lock Toggle design. Key areas:

**Venus OS Info Widget:**
- What info to display (connection status, last contact timestamp, current override value)
- How to determine Venus OS connection status (passive tracking via last_change_ts from ControlState, NOT active Modbus polling to Venus OS)
- IP display: use configured SolarEdge IP as proxy for "system is working" or skip IP entirely if pymodbus server doesn't expose client IP
- Widget styling consistent with existing ve-card pattern

**Lock Toggle (Safety-Critical):**
- Apple-style CSS toggle (checkbox hack with opacity:0, ::before pseudo-element)
- Confirmation dialog REQUIRED before locking (same pattern as power control confirmation)
- Lock semantics: when locked, Venus OS Modbus writes to Model 123 are silently accepted but NOT forwarded to inverter (Venus OS doesn't see an error, but the value doesn't take effect). This prevents Venus OS from retrying aggressively.
- Auto-unlock timer: max 15 minutes, countdown visible in UI
- Backend: add `is_locked` flag to ControlState, check in StalenessAwareSlaveContext.setValues() before forwarding writes
- Lock state persisted only in-memory (resets to unlocked on restart — safe default)
- Toast notification when lock activates/deactivates and when auto-unlock triggers
- Lock toggle disabled when Venus OS is not active (no point locking what isn't controlling)

**Backend Integration:**
- Extend ControlState with lock fields (is_locked, lock_expires_at)
- Extend snapshot with lock state for WebSocket push
- POST /api/venus-lock endpoint for toggling
- Lock expiry checked in poll loop or EDPC refresh loop

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Backend — Control Flow
- `src/venus_os_fronius_proxy/control.py` — ControlState class (last_source, last_change_ts, set_from_venus_os, set_from_webapp), OverrideLog
- `src/venus_os_fronius_proxy/proxy.py` lines 170-220 — StalenessAwareSlaveContext.setValues() where Venus OS writes are detected and forwarded
- `src/venus_os_fronius_proxy/webapp.py` lines 460-510 — POST /api/power-limit with Venus OS priority window check

### Frontend — Existing Patterns
- `src/venus_os_fronius_proxy/static/app.js` — showToast, confirmation dialog pattern (confirmAction), power control toggle pattern
- `src/venus_os_fronius_proxy/static/style.css` — ve-card, ve-toggle (if exists), animation variables from Phase 9

### Research
- `.planning/research/PITFALLS.md` — Venus OS Lock Toggle safety requirements (auto-unlock, confirmation)
- `.planning/research/STACK.md` — Apple-style toggle CSS pattern (checkbox hack, spring easing)
- `.planning/research/ARCHITECTURE.md` — Venus OS info passive tracking approach

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ControlState` class: already tracks last_source ("venus_os"/"webapp"/"none") and last_change_ts — extend with is_locked, lock_expires_at
- `StalenessAwareSlaveContext.setValues()`: Venus OS write interception point — add lock check here
- `confirmAction()` in app.js: confirmation dialog pattern reusable for lock confirmation
- Power control toggle HTML/CSS: existing enable/disable toggle pattern to base lock toggle on
- Phase 9 animation variables: smooth toggle transition

### Established Patterns
- Backend state → snapshot → WebSocket → client JS update
- Confirmation dialog before destructive actions (power control)
- OverrideLog for event tracking
- Auto-revert timeout pattern (webapp_revert_at in ControlState)

### Integration Points
- `ControlState`: add is_locked, lock_expires_at fields
- `StalenessAwareSlaveContext.setValues()`: check lock before forwarding Venus OS writes
- `build_dashboard_snapshot()` in webapp.py: include lock state
- `webapp.py`: new POST /api/venus-lock endpoint
- `app.js handleSnapshot()`: update Venus OS widget from snapshot data
- EDPC refresh loop or poll loop: check lock expiry

</code_context>

<specifics>
## Specific Ideas

- Apple-style toggle: user specifically requested this look (smooth sliding circle, green/red states)
- Venus OS should never be permanently locked — auto-unlock is non-negotiable safety feature
- Lock must use existing --ve-green/--ve-red color variables for unlocked/locked states

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 11-venus-os-widget-lock-toggle*
*Context gathered: 2026-03-18*
