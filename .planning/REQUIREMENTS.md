# Requirements: PV-Inverter-Master v8.0 — Auto-Update System

**Defined:** 2026-04-10
**Core Value:** Venus OS muss alle PV-Inverter als einen virtuellen Fronius-Inverter erkennen und steuern koennen

## Milestone Goal

Professionelle In-Webapp Update-Experience — User kann neue Versionen aus dem GitHub-Repo direkt aus der Webapp installieren, ohne SSH-Zugriff, mit automatischer Verfuegbarkeits-Pruefung, Backup, Health-Check und Rollback-Sicherheit.

## Product Decisions

- **Auto-Install Default:** OFF — Scheduler prueft nur und zeigt Badge, User klickt bewusst auf Install
- **Release Retention:** 3 Releases im Blue-Green-Layout (current + 2 Rollback-Kandidaten)
- **GPG Signing:** Optional in v8.0 (config flag `updates.allow_unsigned`), required in v8.1
- **Update Source:** Nur getaggte GitHub Releases (`/releases/latest`), NIE main branch
- **Rollback Distance:** Max N-1 (one release back), Multi-hop manuell
- **Config Kompatibilitaet:** v7.x config.py tolerieren unknown keys bereits (verified) — kein v7.1.x compat release noetig

## v8.0 Requirements

### Safety Foundation (SAFETY-xx)

- [ ] **SAFETY-01**: Blue-Green-Verzeichnis-Layout: `/opt/pv-inverter-proxy-releases/<version>-<sha>/` mit `current` Symlink; `/opt/pv-inverter-proxy` zeigt auf `releases/current`
- [ ] **SAFETY-02**: Retention-Policy haelt genau 3 Release-Verzeichnisse (konfigurierbar via `updates.keep_releases`, Default 3); aelteste werden bei erfolgreichem Update geloescht (nie das aktuelle oder vorherige)
- [ ] **SAFETY-03**: One-Time Migration beim ersten v8.0 Start: alte flat Layout wird erkannt, `git status --porcelain` auf Dirty geprueft, Baum ins Release-Verzeichnis kopiert, Symlink erstellt, Dienst neu gestartet; bei Dirty-Tree Migration verweigert und Banner mit Diff angezeigt
- [ ] **SAFETY-04**: Boot-Time Recovery Hook: `pv-inverter-proxy-recovery.service` (Type=oneshot, Before=pv-inverter-proxy.service) liest PENDING-Marker; wenn letzter Boot ohne SUCCESS-Marker endete, flippt Symlink auf vorheriges Release zurueck
- [ ] **SAFETY-05**: Systemd-Unit-Hardening: `StartLimitBurst=10`, `StartLimitIntervalSec=120`, `TimeoutStopSec=15`, `KillMode=mixed`
- [ ] **SAFETY-06**: `RuntimeDirectory=pv-inverter-proxy` in Main-Service-Unit (erzeugt tmpfs `/run/pv-inverter-proxy/` fuer healthy-Flag)
- [ ] **SAFETY-07**: `/var/lib/pv-inverter-proxy/backups/` Verzeichnis fuer venv-Tarball-Snapshots und Config-Backups; via install.sh erstellt, Owner `root:pv-proxy`, Mode 2775
- [ ] **SAFETY-08**: Pre-Flight-Disk-Space-Check vor jedem Update: mindestens 500 MB frei auf `/opt` und `/var/cache`; bei weniger Abbruch mit klarer Fehlermeldung
- [x] **SAFETY-09**: Persistenter State-File fuer SE30K Power Limit + Nachtmodus-State in `/etc/pv-inverter-proxy/state.json`; wird bei Boot restauriert wenn `now - set_at < CommandTimeout/2`

### Version Check & Discovery (CHECK-xx)

- [x] **CHECK-01**: Webapp zeigt aktuelle Version im Footer (aus `importlib.metadata.version`), zusammen mit short commit hash
- [x] **CHECK-02**: Background-Scheduler laeuft als asyncio-Task im Main-Event-Loop, pollt GitHub Releases API stuendlich (konfigurierbar via `updates.check_interval_hours`, Default 1)
- [x] **CHECK-03**: GitHub API Client verwendet aiohttp mit erforderlichem `User-Agent`-Header, `Accept: application/vnd.github+json`, 10s Timeout; ETag-Caching reduziert Bandbreite
- [x] **CHECK-04**: Bei verfuegbarem Update: Badge (orange `ve-dot`) an Sidebar-Eintrag `System`, Release-Notes aus `body`-Feld der GitHub-API-Response — _Phase 44 ships Badge + GitHub link; release_notes Markdown rendering deferred to Phase 46 per phase scope (T-44-17 avoidance)_
- [x] **CHECK-05**: `GET /api/update/available` liefert `{current_version, latest_version, release_notes, published_at, tag_name}` oder `null`
- [x] **CHECK-06**: Scheduler ist fehlertolerant: Netzwerkfehler, GitHub unreachable oder 5xx fuehrt nicht zum Crash, nur Log-Warnung; UI zeigt `last_check_failed_at` Timestamp
- [x] **CHECK-07**: Scheduler schiebt Check auf naechste Stunde wenn WebSocket-Client verbunden ist (User aktiv = keine Hintergrund-Aktion)

### Update Execution (EXEC-xx)

- [x] **EXEC-01**: `POST /api/update/start` liefert HTTP 202 mit `{update_id, status_url}` innerhalb <100ms und schreibt Trigger-File atomar (tempfile + `os.replace`) nach `/etc/pv-inverter-proxy/update-trigger.json`
- [x] **EXEC-02**: Trigger-File-Schema enthaelt `{op, target_sha, requested_at, requested_by, nonce}`; nonce wird vom Updater gegen `/var/lib/pv-inverter-proxy/processed-nonces.json` (letzte 50) geprueft, Duplikate werden ignoriert
- [x] **EXEC-03**: Privilegierter Updater (`pv-inverter-proxy-updater.service`, `Type=oneshot`, `User=root`) wird via Path-Unit (`pv-inverter-proxy-updater.path`, `PathModified=/etc/.../update-trigger.json`) getriggert
- [x] **EXEC-04**: Updater validiert `target_sha` gegen `refs/remotes/origin/main` via `git merge-base --is-ancestor`; SHAs ausserhalb der main-History werden abgelehnt (Security Root of Trust)
- [x] **EXEC-05**: Updater erstellt Backup vor Update: venv-Tarball nach `/var/lib/pv-inverter-proxy/backups/venv-<timestamp>.tar.gz`, Kopie von `config.yaml`, Snapshot von `pyproject.toml`
- [x] **EXEC-06**: Neuer Release wird in neues Verzeichnis `/opt/pv-inverter-proxy-releases/<version>-<sha>/` extrahiert; `git clone --shared` oder tarball extract; neue isolierte `.venv/` wird dort erstellt und `pip install -e .` laeuft gegen den neuen venv (nicht den laufenden)
- [x] **EXEC-07**: Updater fuehrt `pip install --dry-run` als Pre-Flight aus und bricht ab falls neue Dependencies nicht beschaffbar (Netzwerkfehler, fehlende Build-Tools)
- [x] **EXEC-08**: Post-Install Smoke-Import: `<new_venv>/bin/python -c "import pv_inverter_proxy"` und ein Config-Dry-Run `load_config('/etc/pv-inverter-proxy/config.yaml')` laeuft gegen den neuen Code; bei Fehler Abbruch OHNE Symlink-Flip und OHNE Restart
- [x] **EXEC-09**: `python -m compileall -q <release>/src` wird nach Install ausgefuehrt (pre-compile pyc, vermeidet Runtime-Schreibversuche unter `ProtectSystem=strict`)
- [x] **EXEC-10**: Release-Integrity via Git-SHA-Validation: Updater verwendet `git fetch` + `git checkout --detach <target_sha>` statt Tarball-Download. Git-SHAs sind kryptografische Content-Hashes (SHA-1, Phase 47 upgrade auf SHA-256 via `git config extensions.objectFormat sha256`), d.h. `git merge-base --is-ancestor origin/main <target_sha>` ist die Integritaets- UND Authentizitaets-Pruefung in einem Schritt. Separate `SHA256SUMS`-Verifikation ist bei git-basiertem Install redundant. Optional GPG tag signature verification via `git tag -v` unter SEC-05 (Phase 45 optional, Phase 47 required)

### Restart Safety (RESTART-xx)

- [x] **RESTART-01**: Vor jedem Restart: Main-Service geht in Maintenance-Mode (`app_ctx.maintenance_mode = True`), Modbus-Server antwortet auf Writes mit `SlaveBusy` (Exception Code 0x06), Reads weiter aus Cache
- [x] **RESTART-02**: Mindestens 3 Sekunden Drain-Zeit nach Maintenance-Mode (laenger als Venus OS Poll-Zyklus) bevor Prozess beendet wird; in-flight pymodbus-Transaktionen werden via `asyncio.wait_for(drain(), 2.0)` abgewartet
- [x] **RESTART-03**: Pre-Shutdown WebSocket-Broadcast `update_in_progress` an alle verbundenen Clients ("Update laeuft — Rekonnekt in ~10s") bevor Shutdown
- [x] **RESTART-04**: Updater fuehrt Symlink-Flip atomar aus (`ln -sfn <new_release> current.new && mv -T current.new current`), dann `systemctl restart pv-inverter-proxy.service`
- [x] **RESTART-05**: Updater ueberlebt Main-Service-Restart, polled `/api/health` und `/run/pv-inverter-proxy/healthy` nach Restart bis zu 60 Sekunden
- [x] **RESTART-06**: pymodbus-Server bindet mit `SO_REUSEADDR` (verifizieren, ggf. patchen) — verhindert Bind-Fehler beim schnellen Restart

### Health Check & Rollback (HEALTH-xx)

- [x] **HEALTH-01**: `GET /api/health` liefert JSON mit `{status, version, commit, uptime_seconds, webapp, modbus_server, devices, venus_os}`; jede Komponente ist `ok | starting | degraded | failed`
- [x] **HEALTH-02**: Required-Health-Kriterien fuer Update-Erfolg: `webapp=ok`, `modbus_server=ok`, mindestens 1 Device in `devices` mit `ok` (hat erfolgreichen Poll produziert)
- [x] **HEALTH-03**: Warn-Only (kein Rollback-Trigger): `venus_os` MQTT noch nicht connected — MQTT-Reconnect kann laenger dauern und sollte Update-Erfolg nicht blockieren
- [x] **HEALTH-04**: Main-Service schreibt `/run/pv-inverter-proxy/healthy` (tmpfs, via `RuntimeDirectory`) sobald DeviceRegistry ersten erfolgreichen Poll abgeschlossen hat
- [x] **HEALTH-05**: Updater verlangt 3 aufeinanderfolgende erfolgreiche Health-Polls ueber 15 Sekunden (Stabilitaets-Check) bevor Update als erfolgreich markiert wird
- [x] **HEALTH-06**: Rollback-Trigger: `systemctl is-active` liefert `failed`, Version-Mismatch im Health-Response (alter Code laeuft noch), 5xx/unreachable > 45s, oder kein `healthy`-Flag nach 60s
- [x] **HEALTH-07**: Rollback-Mechanismus: Symlink zurueck auf vorheriges Release-Verzeichnis, `systemctl restart`, Health-Check gegen rolled-back Version
- [x] **HEALTH-08**: Maximal 1 automatischer Rollback pro Update-Versuch; wenn rolled-back Version auch Health-Check failed, schreibt Updater `phase=rollback_failed` mit CRITICAL-State, belaesst Symlink wie ist, User muss SSH
- [x] **HEALTH-09**: Status-File `/etc/pv-inverter-proxy/update-status.json` mit Phase-Progression (`trigger_received, backup, extract, pip_install, config_dryrun, restarting, healthcheck, done | rollback | rollback_failed`) und History-Array

### UI & User Experience (UI-xx)

- [ ] **UI-01**: Neue Sidebar-Rubrik `System / Software` (konsistent mit bestehendem Style)
- [ ] **UI-02**: Software-Seite zeigt: aktuelle Version + commit hash, letzte Check-Zeit, manueller `Check now` Button, Status-Dot fuer Scheduler (ok / failed)
- [ ] **UI-03**: Bei verfuegbarem Update: prominente Card mit Version from/to, Release-Notes gerendert (minimaler Markdown-Subset: headings, lists, bold, code, links), Install-Button, "View on GitHub"-Link
- [ ] **UI-04**: Confirmation-Modal vor Install: Default-Focus auf Cancel, KEINE Type-to-Confirm (Update ist via Rollback reversibel), klare Risiko-Aufklaerung
- [ ] **UI-05**: Progress-View mit Phase-Checklist, angetrieben von WebSocket `update_progress` Nachrichten (eine Nachricht pro Phase-Transition)
- [ ] **UI-06**: Success-/Failure-Toast nach Abschluss, reuseed existing Toast-Stacking-System (v2.1) mit `ve-toast--success` / `ve-toast--error`
- [ ] **UI-07**: Rollback-Button sichtbar nach erfolgreichem Update (fuer X Minuten nach Restart oder via Update-History-Eintrag); triggert POST /api/update/rollback mit target=previous_release
- [ ] **UI-08**: Browser-Tab-Stale-Version-Reload: WebSocket-Reconnect pollt `/api/version`; wenn Version != gespeicherte, `location.reload()` forcen (verhindert Stale-UI nach Update)
- [ ] **UI-09**: UI-State-Machine: Buttons disabled waehrend `state != idle`; konkurrierende Update-Versuche zeigen klare "Update already in progress"-Meldung

### Security & Rate Limiting (SEC-xx)

- [ ] **SEC-01**: CSRF-Token auf allen POST-Endpunkten fuer Update-Operationen; Token wird bei Seiten-Load generiert und an Session gebunden
- [ ] **SEC-02**: Rate Limit: maximal 1 Update-Versuch pro 60 Sekunden; zweiter Versuch liefert HTTP 429 mit `Retry-After` Header
- [ ] **SEC-03**: Concurrent-Update-Guard: wenn Phase != `idle | done | failed`, liefert POST /api/update/start HTTP 409 Conflict
- [ ] **SEC-04**: Update-Audit-Log in `/var/lib/pv-inverter-proxy/update-audit.log`: jede Anfrage mit Timestamp, Source-IP, User-Agent, Outcome (accepted / rejected / failed)
- [x] **SEC-05**: Optional GPG-Signatur-Pruefung: wenn `updates.allow_unsigned: false` (Default in v8.0: true), lehnt Updater Releases ohne gueltige `SHA256SUMS.asc`-Signatur ab
- [x] **SEC-06**: Updater akzeptiert ausschliesslich Releases mit `tag_name` matching `^v\d+\.\d+(\.\d+)?$`; main branch / unreleased commits werden nie installiert
- [x] **SEC-07**: Trigger-File-Verzeichnis-Permissions: `/etc/pv-inverter-proxy/update-trigger.json` mode 0664 owner `root:pv-proxy` (pv-proxy kann schreiben, Updater liest); `update-status.json` mode 0644 owner `root:root` (nur Updater schreibt)

### Helper Service & Monitoring (HELPER-xx)

- [ ] **HELPER-01**: Helper-Heartbeat: Main-Service schreibt alle 60 Sekunden einen `ping`-Trigger, Updater antwortet mit Timestamp in einem Status-File
- [ ] **HELPER-02**: Helper-Silent-Detection: wenn letzte Heartbeat-Antwort > 3 Minuten alt, rote Banner-Warnung in UI "Auto-Update helper not responding — SSH required"
- [ ] **HELPER-03**: Install-Time Smoke-Test: `install.sh` triggert einen `self-test` Trigger nach Installation; schlaegt laut fehl wenn End-to-End-Plumbing nicht funktioniert
- [ ] **HELPER-04**: Strukturiertes Logging fuer Updater via structlog: eine JSON-Zeile pro Update-Attempt mit `{attempt_id, from_version, to_version, outcome, duration_ms, error?}`
- [ ] **HELPER-05**: Journal-Filter: Updater verwendet `SyslogIdentifier=pv-inverter-proxy-updater`, separiert vom Main-Service, einfach via `journalctl -t pv-inverter-proxy-updater` filterbar
- [ ] **HELPER-06**: Journal-Rate-Limit auf Helper-Unit: `LogRateLimitIntervalSec=30`, `LogRateLimitBurst=10` um Log-Flood bei Retry-Loop zu verhindern

### Update History (HIST-xx)

- [ ] **HIST-01**: Update-History gespeichert in `/var/lib/pv-inverter-proxy/update-history.json` als Ring-Buffer der letzten 20 Eintraege
- [ ] **HIST-02**: Jeder Eintrag enthaelt: `{timestamp, from_version, to_version, duration_seconds, outcome (success|rolled_back|failed), rollback_reason, triggered_by}`
- [ ] **HIST-03**: `GET /api/update/history` liefert letzte 20 Eintraege als JSON-Array
- [ ] **HIST-04**: Software-Seite zeigt History-Tabelle unter dem Version-Check mit Outcome-Badges und aufklappbaren Details

### Configuration (CFG-xx)

- [ ] **CFG-01**: Neue Config-Section `update:` in `config.yaml` mit Defaults: `enabled: true`, `auto_install: false`, `check_interval_hours: 1`, `github_repo: "meintechblog/pv-inverter-master"`, `keep_releases: 3`, `allow_unsigned: true`
- [ ] **CFG-02**: Alle Update-Config-Felder editierbar via Webapp (System / Software Settings); Save/Cancel mit Dirty-Tracking wie bestehende Config-Pages
- [ ] **CFG-03**: Hot-Reload von Update-Config: Scheduler-Task wird bei Config-Aenderung cancelled und mit neuen Werten neu gestartet (pattern wie existing VenusConfig Hot-Reload)

## Future Requirements (v8.1+)

### GPG Enforcement
- Required GPG-Signatur-Pruefung (allow_unsigned default false, dann entfernt)
- Maintainer-Key-Distribution via Dokumentation und install.sh

### Release Channels
- Pre-Release/Beta-Channel-Toggle (filter by `prerelease` flag der GitHub API)
- Power-User opt-in

### Advanced History
- Diagnostics-Page mit Journal-Tail fuer failed updates (`journalctl -u pv-inverter-proxy-updater -n 200`)
- Rollback-Loop-Guard: verhindert mehr als 2 Rollbacks in 24h

### UX Polish
- "Skip this version" Button (stoppt Badge fuer eine spezifische Version)
- Service-Health-Banner nach Update zeigt Device-Reconnect-Status
- Inline Changelog Preview im Badge-Tooltip

## Out of Scope

- **Silent Auto-Install** — Infrastruktur-Update ohne User-Consent ist inakzeptabel
- **Main-Branch Auto-Pull** — Nur getaggte Releases, keine unreleased commits via UI
- **Type-to-Confirm Dialog** — Rollback macht Update reversibel, Standard-Modal reicht
- **Hot-Reload ohne Restart** — `importlib.resources` caching verhindert das sicher
- **Multi-Hop Downgrade** — Rollback ist N-1; aeltere Versionen via manuellem git checkout
- **In-App Dependency Manager** — Dependencies werden via pyproject.toml im Release gepinnt
- **Multi-Instance Update Coordination** — Jeder LXC ist autonom, kein Central Control Plane
- **Telemetry / Update-Success-Reporting** — Kein Phone-Home, keine zentrale Metriken
- **Rollback nach mehr als 1 Stunde** — Aelteres Rollback via manuellem git checkout nicht auto

## Traceability

Requirements werden in Phasen gemappt vom gsd-roadmapper (ROADMAP.md).

| REQ-ID | Phase | Status |
|--------|-------|--------|
| SAFETY-01 | Phase 43 | Pending |
| SAFETY-02 | Phase 43 | Pending |
| SAFETY-03 | Phase 43 | Pending |
| SAFETY-04 | Phase 43 | Pending |
| SAFETY-05 | Phase 43 | Pending |
| SAFETY-06 | Phase 43 | Pending |
| SAFETY-07 | Phase 43 | Pending |
| SAFETY-08 | Phase 43 | Pending |
| SAFETY-09 | Phase 43 | Complete |
| CHECK-01 | Phase 44 | Complete |
| CHECK-02 | Phase 44 | Complete |
| CHECK-03 | Phase 44 | Complete |
| CHECK-04 | Phase 44 | Partial — badge + GitHub link complete; release_notes Markdown rendering deferred to Phase 46 |
| CHECK-05 | Phase 44 | Complete |
| CHECK-06 | Phase 44 | Complete |
| CHECK-07 | Phase 44 | Complete |
| EXEC-01 | Phase 45 | Complete (45-02) |
| EXEC-02 | Phase 45 | Complete (45-02) |
| EXEC-03 | Phase 45 | Complete |
| EXEC-04 | Phase 45 | Complete |
| EXEC-05 | Phase 45 | Complete |
| EXEC-06 | Phase 45 | Complete |
| EXEC-07 | Phase 45 | Complete |
| EXEC-08 | Phase 45 | Complete |
| EXEC-09 | Phase 45 | Complete |
| EXEC-10 | Phase 45 | Complete |
| RESTART-01 | Phase 45 | Complete |
| RESTART-02 | Phase 45 | Complete |
| RESTART-03 | Phase 45 | Complete |
| RESTART-04 | Phase 45 | Complete |
| RESTART-05 | Phase 45 | Complete |
| RESTART-06 | Phase 45 | Complete |
| HEALTH-01 | Phase 45 | Complete |
| HEALTH-02 | Phase 45 | Complete |
| HEALTH-03 | Phase 45 | Complete |
| HEALTH-04 | Phase 45 | Complete |
| HEALTH-05 | Phase 45 | Complete |
| HEALTH-06 | Phase 45 | Complete |
| HEALTH-07 | Phase 45 | Complete |
| HEALTH-08 | Phase 45 | Complete |
| HEALTH-09 | Phase 45 | Partial — reader shipped (45-02), writer ships in 45-03/04 |
| SEC-05 | Phase 45 | Complete |
| SEC-06 | Phase 45 | Complete |
| SEC-07 | Phase 45 | Complete (45-02) |
| UI-01 | Phase 46 | Pending |
| UI-02 | Phase 46 | Pending |
| UI-03 | Phase 46 | Pending |
| UI-04 | Phase 46 | Pending |
| UI-05 | Phase 46 | Pending |
| UI-06 | Phase 46 | Pending |
| UI-07 | Phase 46 | Pending |
| UI-08 | Phase 46 | Pending |
| UI-09 | Phase 46 | Pending |
| SEC-01 | Phase 46 | Pending |
| SEC-02 | Phase 46 | Pending |
| SEC-03 | Phase 46 | Pending |
| SEC-04 | Phase 46 | Pending |
| CFG-02 | Phase 46 | Pending |
| HELPER-01 | Phase 47 | Pending |
| HELPER-02 | Phase 47 | Pending |
| HELPER-03 | Phase 47 | Pending |
| HELPER-04 | Phase 47 | Pending |
| HELPER-05 | Phase 47 | Pending |
| HELPER-06 | Phase 47 | Pending |
| HIST-01 | Phase 47 | Pending |
| HIST-02 | Phase 47 | Pending |
| HIST-03 | Phase 47 | Pending |
| HIST-04 | Phase 47 | Pending |
| CFG-01 | Phase 47 | Pending |
| CFG-03 | Phase 47 | Pending |

**Coverage:** 64/64 requirements mapped to exactly one phase (no orphans, no duplicates)

## Success Criteria

Milestone ist fertig wenn:

1. User kann via Webapp ein neues Release installieren, ohne SSH-Zugriff, ohne Datenverlust, ohne Venus-OS-Disconnect laenger als 10s
2. Ein bewusst kaputter Commit als neues Release taggend fuehrt zu automatischem Rollback und funktionierendem Service ohne User-Intervention
3. Scheduler findet neue Releases innerhalb einer Stunde nach dem Tagging und zeigt Badge an
4. Config-Aenderungen in Update-Settings werden ohne Restart wirksam
5. Update-Historie ist nachvollziehbar ueber die letzten 20 Updates
6. Disk-Usage bleibt unter 1 GB zusaetzlich durch Release-Retention
