---
phase: 16-install-script-readme
verified: 2026-03-19T21:35:00Z
status: passed
score: 9/9 must-haves verified
re_verification: false
---

# Phase 16: Install Script & README Verification Report

**Phase Goal:** A new user can install and configure the proxy with a single curl command and clear documentation
**Verified:** 2026-03-19T21:35:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth                                                                      | Status     | Evidence                                                                                  |
|----|----------------------------------------------------------------------------|------------|-------------------------------------------------------------------------------------------|
| 1  | Install script generates YAML with `inverter:` key (not `solaredge:`)     | VERIFIED   | `install.sh` line 106: `inverter:` in YAML template; `solaredge:` only in migration grep |
| 2  | Install script generates YAML with `venus:` config section                | VERIFIED   | `install.sh` line 116: `venus:` in YAML template                                         |
| 3  | Install script warns if port 502 is in use before install                 | VERIFIED   | `install.sh` lines 45-54: `ss -tlnp` check with warning output                          |
| 4  | Install script warns if existing config has old `solaredge:` key          | VERIFIED   | `install.sh` lines 134-141: `grep -q '^solaredge:'` with RED WARNING message             |
| 5  | Install script curl usage has secure `-f` flag                            | VERIFIED   | `install.sh` line 5 (header) and line 186 (footer): both use `curl -fsSL`                |
| 6  | README documents the correct `inverter:` config key                       | VERIFIED   | `README.md` line 40: `inverter:` in config example under `## Configuration`              |
| 7  | README documents Venus OS >= 3.7 as prerequisite                          | VERIFIED   | `README.md` line 11: `- **Venus OS >= 3.7** (required for MQTT on LAN feature)`          |
| 8  | README documents the Venus OS MQTT setup flow                             | VERIFIED   | `README.md` line 78: `Settings > Services > MQTT on LAN` under `## Setup Flow`          |
| 9  | config.example.yaml includes venus section                                | VERIFIED   | `config/config.example.yaml` line 18: `venus:` with host, port, portal_id fields        |

**Score:** 9/9 truths verified

### Required Artifacts

| Artifact                    | Expected                                     | Status     | Details                                                                                          |
|-----------------------------|----------------------------------------------|------------|--------------------------------------------------------------------------------------------------|
| `install.sh`                | Fixed YAML template with inverter: + venus:, pre-flight checks | VERIFIED | Contains `inverter:`, `venus:`, port 502 check, migration warning, `-fsSL` flags. `bash -n` syntax check passes. |
| `config/config.example.yaml` | Reference config with venus section         | VERIFIED   | Line 18: `venus:` section with `host`, `port`, `portal_id` fields                              |
| `README.md`                 | Updated documentation with full setup flow   | VERIFIED   | Has `## Prerequisites`, `## Setup Flow`, `## Installation` with correct curl command, all v3.0 features |

### Key Link Verification

| From                        | To                                          | Via                                          | Status   | Details                                                                                    |
|-----------------------------|---------------------------------------------|----------------------------------------------|----------|--------------------------------------------------------------------------------------------|
| `install.sh`                | `src/venus_os_fronius_proxy/config.py`      | YAML keys match dataclass field names        | VERIFIED | `config.py` defines `inverter:` (line 55) and `venus:` (line 59) fields; install.sh YAML template uses identical keys |
| `config/config.example.yaml` | `src/venus_os_fronius_proxy/config.py`     | YAML keys match dataclass field names        | VERIFIED | `portal_id` in example.yaml matches `VenusConfig.portal_id` (config.py line 50)          |
| `README.md`                 | `install.sh`                                | curl command must match script header        | VERIFIED | `README.md` lines 17 and 32: `curl -fsSL ...install.sh` matches `install.sh` line 5 header exactly |

### Requirements Coverage

| Requirement | Source Plan | Description                                                                                       | Status    | Evidence                                                                             |
|-------------|-------------|---------------------------------------------------------------------------------------------------|-----------|--------------------------------------------------------------------------------------|
| DOCS-01     | 16-01-PLAN  | Install Script fix — YAML key mismatch (solaredge: -> inverter:), venus config section, secure curl flags | SATISFIED | install.sh: `inverter:` in template, `venus:` section, `-fsSL` flags (2 occurrences), migration warning |
| DOCS-02     | 16-01-PLAN  | README update — setup flow, Venus OS >= 3.7 prerequisite, badges, screenshots                    | SATISFIED | README.md: `## Prerequisites` (line 7), `## Setup Flow` (line 61), `>= 3.7` (line 11), paho-mqtt in tech stack (line 134) |

Both requirements mapped to Phase 16 in REQUIREMENTS.md are satisfied. No orphaned requirements found.

### Anti-Patterns Found

| File       | Line | Pattern              | Severity | Impact |
|------------|------|----------------------|----------|--------|
| (none)     | —    | —                    | —        | —      |

No TODO/FIXME/placeholder comments, empty implementations, or stub patterns found in the modified files.

### Human Verification Required

#### 1. Install Script End-to-End

**Test:** On a fresh Debian 12+ system, run `curl -fsSL https://raw.githubusercontent.com/meintechblog/pv-inverter-proxy/main/install.sh | bash`
**Expected:** Service installs cleanly, generates `/etc/fronius-proxy/config.yaml` with `inverter:` and `venus:` sections, systemd unit starts, dashboard accessible on port 80
**Why human:** Cannot execute the install script in a live environment from this verification context

#### 2. Port 502 Warning Visibility

**Test:** With port 502 already in use, run the install script and observe output
**Expected:** Blue "Note: Port 502 is currently in use" warning printed before Step 1 proceeds
**Why human:** Requires a live environment with a process holding port 502

#### 3. Migration Warning for Old Config

**Test:** Place a config with `solaredge:` key at the expected config path, then run the install script
**Expected:** Red "WARNING: Your config uses the old 'solaredge:' key" message appears
**Why human:** Requires simulating a pre-existing old config in a live install environment

#### 4. README Readability and Completeness

**Test:** Follow the README as a new user with no prior knowledge of the project
**Expected:** User can complete install, connect SolarEdge, and optionally connect Venus OS MQTT without needing to consult source code
**Why human:** UX clarity and completeness of prose cannot be verified programmatically

### Test Results

- `bash -n install.sh`: passes (syntax valid)
- `pytest tests/test_config.py -x -q`: 7 passed — config loading unaffected
- Commit hashes `650a225` and `6c6bc76` verified present in git history

### Gaps Summary

No gaps. All 9 must-have truths are verified. The install script YAML template uses the correct `inverter:` key matching the `ProxyConfig` dataclass, includes the `venus:` section, carries `-fsSL` curl flags in both the header comment and the update reminder footer, and implements both pre-flight checks (port 502 and old config migration warning). The README has all required sections (`## Prerequisites`, `## Installation`, `## Configuration`, `## Setup Flow`) with Venus OS >= 3.7 stated as a prerequisite and MQTT on LAN setup instructions. `config/config.example.yaml` is consistent with the install script template and the config.py dataclasses.

---

_Verified: 2026-03-19T21:35:00Z_
_Verifier: Claude (gsd-verifier)_
