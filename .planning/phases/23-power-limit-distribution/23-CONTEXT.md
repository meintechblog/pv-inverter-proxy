# Phase 23: Power Limit Distribution - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Venus OS power limit commands (WMaxLimPct) are distributed across multiple inverters based on user-defined Throttling Order. Supports heterogeneous latencies, monitoring-only mode, and offline failover. No UI changes (Phase 24), no per-device API (Phase 24).

</domain>

<decisions>
## Implementation Decisions

### Throttling Order (TO)
- Begriff: "Throttling Order" (TO) statt "Prioritaet" — klarer und unmissverstaendlich
- TO = Nummernfeld pro Inverter: TO 1 = wird als ERSTES gedrosselt, TO 2 = danach, etc.
- Gleiche TO-Nummer erlaubt: Inverter mit gleicher TO werden gleichmaessig aufgeteilt (50/50)
- Default fuer neue Inverter: naechste freie TO-Nummer
- UI-Label: "Throttling Order (TO)" mit Erklaerung "TO 1 = first to throttle, TO 2 = next, ..."
- Config-Feld: `throttle_order: int` in InverterEntry

### Verteilungs-Algorithmus
- Wasserfall-Prinzip: TO 1 wird komplett runtergedreht (bis 0% wenn noetig). Erst wenn TO 1 am Minimum, wird TO 2 gedrosselt
- Minimum pro Inverter: 0% (komplett aus) — kein Hardware-Minimum-Clamp
- Umrechnung: Venus OS WMaxLimPct (Prozent der Gesamtnennleistung) → absolute Watt → Wasserfall-Verteilung auf einzelne Inverter → pro Inverter Prozentwert berechnen und senden
- Beispiel: 50% von 31kW Gesamt = 15.5kW erlaubt. TO 1 (SE30K, 30kW) wird auf 15.5kW / 30kW = 51.7% gedrosselt. TO 2 bleibt auf 100%
- Bei Offline eines Inverters waehrend aktivem Limit: Anteil wird sofort auf naechste in TO-Reihenfolge umverteilt

### Exclude-/Monitoring-Modus
- 3 Zustaende pro Inverter: Enabled (voll) / Monitoring-Only / Disabled
- UI: Toggle = Enabled/Disabled (wie bisher). Zusaetzliche Checkbox "Throttle" = ob Inverter gedrosselt werden darf
- Monitoring-Only = Throttle-Checkbox unchecked: Polling ja, Daten fliessen in Aggregation, aber KEIN Limit-Befehl wird gesendet
- Monitoring-Only Inverter traegt zur aggregierten Leistung bei die Venus OS sieht (Leistung zaehlt mit)
- Default fuer neue Inverter: Throttle AN (steuerbar)
- Config-Feld: `throttle_enabled: bool` in InverterEntry (default: true)

### Latenz-Handling
- Dead-Time pro Device konfigurierbar: Default = 0s (kein Warten, da SolarEdge + Hoymiles via OpenDTU near-instant)
- Config-Feld: `throttle_dead_time_s: float` in InverterEntry (default: 0.0)
- Waehrend Dead-Time: neue Venus OS Befehle werden zwischengespeichert und nach Ablauf angewandt (latest wins)
- Zukunftssicher fuer Hardware mit echten Latenzproblemen (z.B. Hoymiles mit WLAN statt OpenDTU)

### Claude's Discretion
- Internes Datenmodell fuer Limit-State pro Device
- Wie die Umrechnung Prozent→Watt→pro-Device exakt implementiert wird
- Error-Handling bei fehlgeschlagenem Limit-Write
- Ob Limit-Aenderungen geloggt werden (empfohlen: ja, structlog)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Power Limit Control
- `src/venus_os_fronius_proxy/control.py` — Existing ControlState, WMaxLimPct validation, clamp logic
- `src/venus_os_fronius_proxy/proxy.py` — StalenessAwareSlaveContext._handle_control_write() and _handle_local_control_write() — current single-plugin limit forwarding that must be replaced

### Plugin Interface
- `src/venus_os_fronius_proxy/plugin.py` — InverterPlugin ABC with write_power_limit(enable, limit_pct) method
- `src/venus_os_fronius_proxy/plugins/solaredge.py` — SolarEdge implementation of write_power_limit
- `src/venus_os_fronius_proxy/plugins/opendtu.py` — OpenDTU implementation of write_power_limit

### Device Registry
- `src/venus_os_fronius_proxy/device_registry.py` — DeviceRegistry managing N ManagedDevices with poll loops
- `src/venus_os_fronius_proxy/config.py` — InverterEntry dataclass (needs throttle_order, throttle_enabled, throttle_dead_time_s fields)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ControlState` in control.py: already tracks WMaxLimPct, clamp values, and venus_os flag. Can be reused as-is
- `validate_wmaxlimpct()`: validation function for raw register values. Reuse in distributor
- `InverterPlugin.write_power_limit(enable, limit_pct)`: all plugins implement this interface consistently

### Established Patterns
- `StalenessAwareSlaveContext._handle_control_write()`: current entry point for Venus OS writes. Must be rewired to call PowerLimitDistributor instead of single plugin
- `_handle_local_control_write()`: already stores control state locally. Phase 22 added "deferred to Phase 23" logging stubs here — replace with actual distribution

### Integration Points
- `StalenessAwareSlaveContext.__init__` receives `plugin` parameter — needs to receive PowerLimitDistributor instead (or in addition)
- `DeviceRegistry` provides access to all ManagedDevices and their plugins
- `AggregationLayer.recalculate()` knows total rated power — needed for Prozent→Watt conversion

</code_context>

<specifics>
## Specific Ideas

- "Ausserdem koennen wir das Regelverhalten auch mal gemeinsam testen... also wie lange das dauert" — Live-Test auf dem LXC mit echten Invertern nach Deploy geplant
- Begrifflichkeit "Throttling Order" statt "Prioritaet" war User-Feedback: klarer, unmissverstaendlich

</specifics>

<deferred>
## Deferred Ideas

- Live-Test des Regelverhaltens mit echten Invertern — nach Deploy auf LXC (manuelle Session)
- UI-Darstellung der Throttling Order und Throttle-Checkbox — Phase 24

</deferred>

---

*Phase: 23-power-limit-distribution*
*Context gathered: 2026-03-20*
