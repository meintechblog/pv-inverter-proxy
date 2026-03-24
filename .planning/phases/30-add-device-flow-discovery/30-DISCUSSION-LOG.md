# Phase 30: Add-Device Flow & Discovery - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-24

## Areas Discussed

### 1. Shelly Form Fields

**Q: What fields should the Shelly add-form show?**
- Options: Minimal (Host only) | Host + Name | Host + Name + Rated Power
- **Selected:** Host + Name + Rated Power
- Rationale: Rated power needed for WRtg aggregation when Shelly monitors micro-inverter

**Q: Should rated_power have a default value?**
- Options: Empty (0W default) | Pre-filled from device
- **Selected:** Empty (0W default)

### 2. Generation Probe UX

**Q: How should generation probe work?**
- Options: Auto-probe on Add click | Probe on IP blur | Separate Test button
- **Selected:** Probe bei Add-Klick (auto-probe on Add click, single-click flow)

**Q: How should probe failure display?**
- Options: Rote Hint-Card im Formular | Toast Meldung
- **Selected:** Claude's discretion — chose Hint-Card in form (consistent with existing OpenDTU auth-test pattern)

### 3. Shelly Discovery Method

**Q: How should Shelly discovery work?**
- Options: mDNS | HTTP scan | Both
- **Selected:** "So wie es am besten funktioniert" — Claude chose mDNS (_shelly._tcp) as primary

**Q: Should Discover button scan all types or only selected?**
- Options: Only Shelly when Shelly selected | Everything at once | Claude decides
- **Selected:** Only Shelly when Shelly selected (type-filtered)

### 4. Config Page Readonly Fields

**Q: Which Shelly-specific fields on config page?**
- Options: Host + Gen | Host + Gen + Model + MAC | Host + Gen + Rated Power
- **Selected:** "Du entscheidest" — Claude chose Host + Gen + Rated Power

## Deferred Ideas

- Plugin Deployment Runbook (user suggestion mid-discussion)
