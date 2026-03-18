/* Venus OS Fronius Proxy - Frontend Application
   Navigation, polling, config form, register viewer */

const POLL_INTERVAL = 2000;
let previousRegValues = {};

// ===== Navigation =====

document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        const page = item.dataset.page;
        // Hide all pages, show selected
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.getElementById('page-' + page).classList.add('active');
        // Update nav active state
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        item.classList.add('active');
        // Close mobile sidebar
        document.getElementById('sidebar').classList.remove('open');
        const overlay = document.getElementById('sidebar-overlay');
        if (overlay) overlay.classList.remove('active');
    });
});

// ===== Hamburger Toggle (Mobile) =====

document.getElementById('hamburger').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('open');
    const overlay = document.getElementById('sidebar-overlay');
    if (overlay) overlay.classList.toggle('active');
});

// Close sidebar when clicking overlay
const sidebarOverlay = document.getElementById('sidebar-overlay');
if (sidebarOverlay) {
    sidebarOverlay.addEventListener('click', () => {
        document.getElementById('sidebar').classList.remove('open');
        sidebarOverlay.classList.remove('active');
    });
}

// ===== Status Polling =====

async function pollStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();

        // Update top-bar dots
        const seDot = document.getElementById('se-dot');
        const seDotDetail = document.getElementById('se-dot-detail');
        const seLabel = document.getElementById('se-label');

        const seClass = 've-dot';
        let seDotMod = '';
        let seText = 'SolarEdge: --';

        if (data.reconfiguring) {
            seDotMod = 've-dot--warn';
            seText = 'SolarEdge: Reconnecting...';
        } else if (data.solaredge === 'connected') {
            seDotMod = 've-dot--ok';
            seText = 'SolarEdge: Connected';
        } else if (data.solaredge === 'night_mode') {
            seDotMod = 've-dot--warn';
            seText = 'SolarEdge: Night Mode';
        } else {
            seDotMod = 've-dot--err';
            seText = 'SolarEdge: ' + (data.solaredge || 'Disconnected');
        }

        seDot.className = seClass + (seDotMod ? ' ' + seDotMod : '');
        if (seDotDetail) seDotDetail.className = seClass + (seDotMod ? ' ' + seDotMod : '');
        if (seLabel) seLabel.textContent = seText;

        // Venus OS dot
        const vosDot = document.getElementById('vos-dot');
        const vosDotDetail = document.getElementById('vos-dot-detail');
        const vosLabel = document.getElementById('vos-label');

        let vosDotMod = '';
        let vosText = 'Venus OS: --';

        if (data.venus_os === 'active') {
            vosDotMod = 've-dot--ok';
            vosText = 'Venus OS: Active';
        } else {
            vosDotMod = 've-dot--warn';
            vosText = 'Venus OS: ' + (data.venus_os || 'Unknown');
        }

        vosDot.className = seClass + (vosDotMod ? ' ' + vosDotMod : '');
        if (vosDotDetail) vosDotDetail.className = seClass + (vosDotMod ? ' ' + vosDotMod : '');
        if (vosLabel) vosLabel.textContent = vosText;
    } catch (e) {
        console.error('Status poll failed:', e);
    }
}

// ===== Health Polling =====

async function pollHealth() {
    try {
        const res = await fetch('/api/health');
        const data = await res.json();

        const hrs = Math.floor(data.uptime_seconds / 3600);
        const mins = Math.floor((data.uptime_seconds % 3600) / 60);
        document.getElementById('uptime').textContent = hrs + 'h ' + mins + 'm';
        document.getElementById('poll-rate').textContent = data.poll_success_rate.toFixed(1) + '%';

        if (data.last_poll_age !== null) {
            document.getElementById('last-poll').textContent = data.last_poll_age.toFixed(0) + 's ago';
        } else {
            document.getElementById('last-poll').textContent = 'No data';
        }

        const cacheEl = document.getElementById('cache-status');
        cacheEl.textContent = data.cache_stale ? 'STALE' : 'Fresh';
        cacheEl.style.color = data.cache_stale ? 'var(--ve-red)' : 'var(--ve-green)';
    } catch (e) {
        console.error('Health poll failed:', e);
    }
}

// ===== Config Loading =====

async function loadConfig() {
    try {
        const res = await fetch('/api/config');
        const data = await res.json();
        document.getElementById('se-host').value = data.host;
        document.getElementById('se-port').value = data.port;
        document.getElementById('se-unit').value = data.unit_id;
    } catch (e) {
        console.error('Config load failed:', e);
    }
}

// ===== Test Connection =====

document.getElementById('btn-test').addEventListener('click', async () => {
    const msg = document.getElementById('config-message');
    msg.className = 've-message';
    msg.style.display = 'block';
    msg.textContent = 'Testing connection...';
    msg.style.color = 'var(--ve-text-dim)';
    msg.style.background = 'var(--ve-bg)';

    try {
        const res = await fetch('/api/config/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                host: document.getElementById('se-host').value,
                port: parseInt(document.getElementById('se-port').value),
                unit_id: parseInt(document.getElementById('se-unit').value)
            })
        });
        const data = await res.json();
        msg.className = 've-message ' + (data.success ? 'success' : 'error');
        msg.textContent = data.success ? 'Connection successful!' : 'Connection failed: ' + data.error;
    } catch (e) {
        msg.className = 've-message error';
        msg.textContent = 'Test request failed: ' + e.message;
    }
});

// ===== Save Config =====

document.getElementById('config-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = document.getElementById('config-message');
    msg.className = 've-message';
    msg.style.display = 'block';
    msg.textContent = 'Saving...';
    msg.style.color = 'var(--ve-text-dim)';
    msg.style.background = 'var(--ve-bg)';

    try {
        const res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                host: document.getElementById('se-host').value,
                port: parseInt(document.getElementById('se-port').value),
                unit_id: parseInt(document.getElementById('se-unit').value)
            })
        });
        const data = await res.json();
        msg.className = 've-message ' + (data.success ? 'success' : 'error');
        msg.textContent = data.success ? 'Saved and applied!' : 'Save failed: ' + data.error;
    } catch (e) {
        msg.className = 've-message error';
        msg.textContent = 'Save request failed: ' + e.message;
    }
});

// ===== Register Viewer =====

async function pollRegisters() {
    try {
        const res = await fetch('/api/registers');
        const models = await res.json();
        const container = document.getElementById('register-models');
        if (container.children.length === 0) {
            buildRegisterViewer(container, models);
        } else {
            updateRegisterValues(models);
        }
    } catch (e) {
        console.error('Register poll failed:', e);
    }
}

function buildRegisterViewer(container, models) {
    models.forEach((model) => {
        const group = document.createElement('div');
        group.className = 've-model-group';

        const header = document.createElement('div');
        header.className = 've-model-header';
        header.innerHTML = '<span>' + model.name + '</span><span>&#9660;</span>';
        header.addEventListener('click', () => {
            const fields = group.querySelector('.ve-model-fields');
            fields.classList.toggle('collapsed');
            header.querySelector('span:last-child').textContent =
                fields.classList.contains('collapsed') ? '\u25B6' : '\u25BC';
        });
        group.appendChild(header);

        const fields = document.createElement('div');
        fields.className = 've-model-fields';

        // Column header row
        const headerRow = document.createElement('div');
        headerRow.className = 've-reg-header';
        headerRow.innerHTML = '<span>Addr</span><span>Name</span><span>SE30K Source</span><span>Fronius Target</span>';
        fields.appendChild(headerRow);

        model.fields.forEach(field => {
            const row = document.createElement('div');
            row.className = 've-reg-row';
            row.id = 'reg-' + field.addr;

            const seVal = formatValue(field.se_value);
            const frVal = formatValue(field.fronius_value);
            const seClass = field.se_value === null ? 've-reg-se-value null-value' : 've-reg-se-value';

            row.innerHTML =
                '<span class="ve-reg-addr">' + field.addr + '</span>' +
                '<span class="ve-reg-name">' + field.name + '</span>' +
                '<span class="' + seClass + '" id="se-val-' + field.addr + '">' + seVal + '</span>' +
                '<span class="ve-reg-fronius-value" id="fr-val-' + field.addr + '">' + frVal + '</span>';
            fields.appendChild(row);
            previousRegValues[field.addr] = { se: field.se_value, fr: field.fronius_value };
        });

        group.appendChild(fields);
        container.appendChild(group);
    });
}

function updateRegisterValues(models) {
    models.forEach(model => {
        model.fields.forEach(field => {
            const seEl = document.getElementById('se-val-' + field.addr);
            const frEl = document.getElementById('fr-val-' + field.addr);
            let changed = false;

            if (seEl) {
                const newSeVal = formatValue(field.se_value);
                if (seEl.textContent !== newSeVal) {
                    seEl.textContent = newSeVal;
                    changed = true;
                }
                seEl.className = field.se_value === null ? 've-reg-se-value null-value' : 've-reg-se-value';
            }
            if (frEl) {
                const newFrVal = formatValue(field.fronius_value);
                if (frEl.textContent !== newFrVal) {
                    frEl.textContent = newFrVal;
                    changed = true;
                }
            }

            if (changed) {
                const row = document.getElementById('reg-' + field.addr);
                if (row) {
                    row.classList.remove('ve-changed');
                    void row.offsetWidth; // force reflow for re-animation
                    row.classList.add('ve-changed');
                }
            }
            previousRegValues[field.addr] = { se: field.se_value, fr: field.fronius_value };
        });
    });
}

function formatValue(val) {
    if (val === null || val === undefined) return '--';
    if (typeof val === 'string') return val;
    return val.toString();
}

// ===== Initialization =====

document.addEventListener('DOMContentLoaded', () => {
    loadConfig();
    pollStatus();
    pollHealth();
    pollRegisters();
    setInterval(() => {
        pollStatus();
        pollHealth();
        pollRegisters();
    }, POLL_INTERVAL);
});
