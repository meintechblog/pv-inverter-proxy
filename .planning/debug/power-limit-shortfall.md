---
status: awaiting_human_verify
trigger: "Fronius PV Inverter Max Limit regelt nicht weit genug runter — graduell ja, aber nicht bis zum Zielwert"
created: 2026-03-26T00:00:00Z
updated: 2026-03-26T00:00:00Z
---

## Current Focus

hypothesis: CONFIRMED -- distribute() includes monitoring-only devices in total_rated but waterfall only distributes to throttle-eligible devices, so allowed_watts budget is not reduced by monitoring devices' production
test: Code trace confirmed mismatch between total_rated (includes monitoring-only) and waterfall eligible (excludes monitoring-only)
expecting: Fix by subtracting monitoring-only rated power from allowed_watts before waterfall
next_action: Implement fix in distributor.py distribute() method

## Symptoms

expected: When Venus OS writes a power limit (e.g. 50%) via Modbus WMaxLimPct register, the distributor should distribute that limit across all devices via the waterfall algorithm, and each device should throttle to its assigned percentage of rated power.
actual: Devices throttle gradually (so the path works partially) but don't reach the target — they stop short of the requested limit. E.g. if 50% is requested, devices might only throttle to 70-80%.
errors: No error messages reported — the system appears to function, just not to the correct magnitude.
reproduction: Set WMaxLimPct via Venus OS to a low value (e.g. 30-50%), observe that devices don't throttle far enough.
started: After v6.0 deployment. Distributor heavily modified in phases 33-37.

## Eliminated

- hypothesis: Refactoring commit 86f9d9b broke convergence params or waterfall algorithm
  evidence: Diff shows only cosmetic changes (extract get_throttle_caps, add get_device_display_state). No algorithmic changes.
  timestamp: 2026-03-26

- hypothesis: auto_throttle accidentally enabled by default
  evidence: Config dataclass shows auto_throttle: bool = False. Confirmed correct default.
  timestamp: 2026-03-26

- hypothesis: SolarEdge register addresses are wrong
  evidence: Web search confirms 0xF142 (61762) = AdvancedPwrControlEn and 0xF001 (61441) = ActivePowerLimit. Both correct.
  timestamp: 2026-03-26

- hypothesis: Per-device clamps interfere with distribution
  evidence: _send_limit() does not apply device clamps. Only global clamp in _handle_local_control_write.
  timestamp: 2026-03-26

- hypothesis: Dead-time or startup grace period blocking writes
  evidence: Dead-time only buffers (latest wins), doesn't reduce percentage. Startup only excludes binary devices.
  timestamp: 2026-03-26

## Evidence

- timestamp: 2026-03-26
  checked: distribute() total_rated calculation (distributor.py lines 122-127)
  found: total_rated sums ALL enabled devices including throttle_enabled=False (monitoring-only) ones
  implication: allowed_watts includes budget for devices that can't be controlled

- timestamp: 2026-03-26
  checked: _waterfall() eligible list (distributor.py lines 187-190)
  found: Waterfall only distributes to throttle_enabled=True devices
  implication: Monitoring-only devices' share of budget is given to controllable devices, making them throttle LESS than intended

- timestamp: 2026-03-26
  checked: Example calculation with monitoring-only device
  found: With 30kW controllable + 5kW monitoring-only, 50% limit -> allowed=17.9kW -> waterfall gives 17.9kW to controllable (59.7%) -> fleet total ~22.9kW instead of target 17.9kW
  implication: Controllable devices get ~10pp too little throttling due to monitoring device budget not being subtracted

- timestamp: 2026-03-26
  checked: SolarEdge commit register (61696 / 0xF100) skipped
  found: Code intentionally skips commit with comment "SE30K does not respond to writes on this register via TCP, but the limit takes effect without commit." Web sources say commit IS needed for full effect.
  implication: Secondary issue -- missing commit may cause limits to not fully take effect on SolarEdge hardware. Needs live testing to confirm.

## Resolution

root_cause: distribute() computes allowed_watts from total_rated (which includes monitoring-only devices) but _waterfall() only distributes to throttle-eligible devices. The monitoring-only devices' share of the budget is incorrectly allocated to controllable devices, resulting in higher-than-intended percentages. Additionally, the SolarEdge commit register write is skipped, which may cause limits to partially rather than fully apply.
fix: (1) Subtract non-throttle-eligible devices' rated power from allowed_watts before calling _waterfall(). (2) Add SolarEdge commit register write (61696) with error tolerance.
verification: 77 tests pass (37 distributor + 40 control). New test_monitoring_only_budget_deduction verifies corrected percentages. Needs live device verification.
files_changed: [src/pv_inverter_proxy/distributor.py, src/pv_inverter_proxy/plugins/solaredge.py, tests/test_distributor.py]
