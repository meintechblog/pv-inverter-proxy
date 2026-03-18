/* Venus OS Fronius Proxy - Frontend Application
   Navigation, WebSocket live dashboard, config form, register viewer */

const POLL_INTERVAL = 10000; // Fallback polling interval (WebSocket provides live data)
let previousRegValues = {};
let ws = null;
let sparklineData = [];
const CAPACITY_W = 30000;

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

// ===== WebSocket Connection =====

function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(protocol + '//' + location.host + '/ws');
    let reconnectDelay = 1000;

    ws.onopen = function() {
        reconnectDelay = 1000;
        updateConnectionIndicator('connected');
    };

    ws.onmessage = function(event) {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'snapshot') handleSnapshot(msg.data);
            if (msg.type === 'history') handleHistory(msg.data);
            if (msg.type === 'override_event') handleOverrideEvent(msg.data);
        } catch (e) {
            console.error('WebSocket message parse error:', e);
        }
    };

    ws.onclose = function() {
        updateConnectionIndicator('disconnected');
        setTimeout(function() {
            reconnectDelay = Math.min(reconnectDelay * 2, 30000);
            connectWebSocket();
        }, reconnectDelay);
    };

    ws.onerror = function() {
        ws.close();
    };

    return ws;
}

// ===== Snapshot Handler =====

function handleSnapshot(data) {
    const inv = data.inverter;
    if (!inv) return;

    // Update gauge
    updateGauge(inv.ac_power_w || 0);
    updateGaugeStatus(inv.status || '--');

    // Update phase cards
    updatePhaseCard('l1', inv.ac_voltage_an_v, inv.ac_current_l1_a);
    updatePhaseCard('l2', inv.ac_voltage_bn_v, inv.ac_current_l2_a);
    updatePhaseCard('l3', inv.ac_voltage_cn_v, inv.ac_current_l3_a);

    // Append to sparkline data
    sparklineData.push(inv.ac_power_w || 0);
    if (sparklineData.length > 3600) sparklineData.shift();
    renderSparkline();

    // Update connection/health from snapshot data
    if (data.connection) {
        updateConnectionStatus(data.connection);
    }

    // Update power control section
    updatePowerControl(data);

    // Update top-bar dots from connection state
    if (data.connection && data.connection.state) {
        const seDot = document.getElementById('se-dot');
        const seDotDetail = document.getElementById('se-dot-detail');
        const seLabel = document.getElementById('se-label');
        if (data.connection.state === 'connected') {
            if (seDot) seDot.className = 've-dot ve-dot--ok';
            if (seDotDetail) seDotDetail.className = 've-dot ve-dot--ok';
            if (seLabel) seLabel.textContent = 'SolarEdge: Connected';
        } else {
            if (seDot) seDot.className = 've-dot ve-dot--err';
            if (seDotDetail) seDotDetail.className = 've-dot ve-dot--err';
            if (seLabel) seLabel.textContent = 'SolarEdge: ' + data.connection.state;
        }
    }
}

// ===== History Handler =====

function handleHistory(data) {
    if (data.ac_power_w && Array.isArray(data.ac_power_w)) {
        sparklineData = data.ac_power_w.map(function(p) { return p[1]; });
        renderSparkline();
    }
}

// ===== Gauge Update =====

function updateGauge(powerW) {
    var pct = Math.min(powerW / CAPACITY_W, 1.0);
    var arcLength = 251.3;
    var offset = arcLength * (1 - pct);

    var gaugeFill = document.getElementById('gauge-fill');
    var gaugeValue = document.getElementById('gauge-value');

    if (gaugeFill) {
        gaugeFill.style.strokeDashoffset = offset;
        // Color: green < 50%, orange 50-80%, red > 80%
        var color = pct < 0.5 ? 'var(--ve-green)' : pct < 0.8 ? 'var(--ve-orange)' : 'var(--ve-red)';
        gaugeFill.style.stroke = color;
    }

    if (gaugeValue) {
        gaugeValue.textContent = (powerW / 1000).toFixed(1);
    }
}

// ===== Gauge Status =====

function updateGaugeStatus(status) {
    var el = document.getElementById('gauge-status');
    if (el) el.textContent = status;
}

// ===== Phase Card Update =====

function updatePhaseCard(phase, voltage, current) {
    var voltageEl = document.getElementById(phase + '-voltage');
    var currentEl = document.getElementById(phase + '-current');
    var powerEl = document.getElementById(phase + '-power');

    if (voltageEl) {
        var newV = (voltage != null) ? voltage.toFixed(1) + ' V' : '-- V';
        if (voltageEl.textContent !== newV) {
            voltageEl.textContent = newV;
            flashValue(voltageEl);
        }
    }

    if (currentEl) {
        var newA = (current != null) ? current.toFixed(2) + ' A' : '-- A';
        if (currentEl.textContent !== newA) {
            currentEl.textContent = newA;
            flashValue(currentEl);
        }
    }

    if (powerEl) {
        var newW;
        if (voltage != null && current != null) {
            newW = (voltage * current).toFixed(0) + ' W';
        } else {
            newW = '-- W';
        }
        if (powerEl.textContent !== newW) {
            powerEl.textContent = newW;
            flashValue(powerEl);
        }
    }
}

function flashValue(el) {
    el.classList.add('ve-value-flash');
    setTimeout(function() {
        el.classList.remove('ve-value-flash');
    }, 300);
}

// ===== Sparkline Renderer =====

function renderSparkline() {
    var svgEl = document.getElementById('sparkline-power');
    if (!svgEl || sparklineData.length < 2) return;

    var W = 600;
    var H = 80;
    var data = sparklineData;
    var min = Math.min.apply(null, data);
    var max = Math.max.apply(null, data);
    var range = max - min || 1;
    var dx = W / (data.length - 1);

    var points = [];
    for (var i = 0; i < data.length; i++) {
        var x = i * dx;
        var y = H - ((data[i] - min) / range) * (H * 0.9);
        points.push(x.toFixed(1) + ',' + y.toFixed(1));
    }
    var pointsStr = points.join(' ');

    // Line polyline
    var polyline = svgEl.querySelector('.sparkline-line');
    if (!polyline) {
        polyline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        polyline.classList.add('sparkline-line');
        polyline.setAttribute('fill', 'none');
        polyline.setAttribute('stroke', 'var(--ve-blue)');
        polyline.setAttribute('stroke-width', '1.5');
        svgEl.appendChild(polyline);
    }
    polyline.setAttribute('points', pointsStr);

    // Fill polygon
    var fillPoly = svgEl.querySelector('.sparkline-fill');
    if (!fillPoly) {
        fillPoly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
        fillPoly.classList.add('sparkline-fill');
        fillPoly.setAttribute('fill', 'var(--ve-blue)');
        fillPoly.setAttribute('opacity', '0.15');
        svgEl.appendChild(fillPoly);
    }
    var fillPoints = '0,' + H + ' ' + pointsStr + ' ' + W + ',' + H;
    fillPoly.setAttribute('points', fillPoints);

    // Update min/max labels
    var minEl = document.getElementById('sparkline-min');
    var maxEl = document.getElementById('sparkline-max');
    if (minEl) minEl.textContent = (min / 1000).toFixed(1) + ' kW';
    if (maxEl) maxEl.textContent = (max / 1000).toFixed(1) + ' kW';
}

// ===== Connection Indicator =====

function updateConnectionIndicator(state) {
    var dot = document.getElementById('ws-dot');
    var label = document.getElementById('ws-label');
    if (state === 'connected') {
        if (dot) dot.className = 've-dot ve-dot--ok';
        if (label) label.textContent = 'WebSocket: Connected';
    } else {
        if (dot) dot.className = 've-dot ve-dot--err';
        if (label) label.textContent = 'WebSocket: Disconnected';
    }
}

// ===== Connection Status Update (from snapshot) =====

function updateConnectionStatus(conn) {
    if (conn.poll_success != null && conn.poll_total != null && conn.poll_total > 0) {
        var rate = (conn.poll_success / conn.poll_total * 100).toFixed(1);
        var pollRateEl = document.getElementById('poll-rate');
        if (pollRateEl) pollRateEl.textContent = rate + '%';
    }
    var cacheEl = document.getElementById('cache-status');
    if (cacheEl && conn.cache_stale != null) {
        cacheEl.textContent = conn.cache_stale ? 'STALE' : 'Fresh';
        cacheEl.style.color = conn.cache_stale ? 'var(--ve-red)' : 'var(--ve-green)';
    }
}

// ===== Status Polling (fallback) =====

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

// ===== Health Polling (fallback) =====

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
    // Only poll when register page is active
    if (!document.querySelector('#page-registers.active')) return;
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

// ===== Power Control =====

const RATED_KW = 30;
let ctrlSliderDragging = false;
let lastControlState = null;

// --- Confirmation Dialog ---

function showConfirmDialog(message, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 've-modal-overlay';
    overlay.innerHTML =
        '<div class="ve-modal">' +
        '  <div class="ve-modal-body">' + message + '</div>' +
        '  <div class="ve-modal-actions">' +
        '    <button class="ve-btn" id="modal-cancel">Cancel</button>' +
        '    <button class="ve-btn ve-btn--danger" id="modal-confirm">Confirm</button>' +
        '  </div>' +
        '</div>';
    document.body.appendChild(overlay);

    function closeDialog() {
        overlay.remove();
        document.removeEventListener('keydown', escHandler);
    }

    function escHandler(e) {
        if (e.key === 'Escape') closeDialog();
    }

    document.addEventListener('keydown', escHandler);
    overlay.querySelector('#modal-cancel').onclick = closeDialog;
    overlay.querySelector('#modal-confirm').onclick = function() {
        closeDialog();
        onConfirm();
    };
    // Close on overlay background click
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) closeDialog();
    });
}

// --- Toast Notifications ---

function showToast(message, type) {
    var toast = document.createElement('div');
    toast.className = 've-toast ve-toast--' + (type || 'info');
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(function() {
        toast.remove();
    }, 3000);
}

// --- Slider Preview ---

(function() {
    var slider = document.getElementById('ctrl-slider');
    var sliderValue = document.getElementById('ctrl-slider-value');
    if (!slider || !sliderValue) return;

    slider.addEventListener('input', function() {
        var pct = parseInt(slider.value);
        var kw = (pct / 100 * RATED_KW).toFixed(1);
        sliderValue.textContent = pct + '% = ' + kw + ' kW';
    });

    slider.addEventListener('mousedown', function() { ctrlSliderDragging = true; });
    slider.addEventListener('touchstart', function() { ctrlSliderDragging = true; });
    document.addEventListener('mouseup', function() { ctrlSliderDragging = false; });
    document.addEventListener('touchend', function() { ctrlSliderDragging = false; });
})();

// --- Apply Power Limit ---

async function applyPowerLimit(pct) {
    try {
        var res = await fetch('/api/power-limit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'set', limit_pct: pct })
        });
        var data = await res.json();
        if (data.success) {
            showToast('Power limit set to ' + pct + '%', 'success');
        } else if (res.status === 409) {
            showToast('Venus OS is controlling -- manual override blocked', 'error');
        } else {
            showToast(data.error || 'Failed to set power limit', 'error');
        }
    } catch (e) {
        showToast('Request failed: ' + e.message, 'error');
    }
}

// --- Apply Button ---

(function() {
    var applyBtn = document.getElementById('ctrl-apply');
    var slider = document.getElementById('ctrl-slider');
    if (!applyBtn || !slider) return;

    applyBtn.addEventListener('click', function() {
        var pct = parseInt(slider.value);
        var kw = (pct / 100 * RATED_KW).toFixed(1);
        showConfirmDialog(
            'Set power limit to <strong>' + pct + '% (' + kw + ' kW)</strong>?<br>' +
            'This limit will auto-revert after 5 minutes.',
            function() { applyPowerLimit(pct); }
        );
    });
})();

// --- Enable/Disable Toggle ---

(function() {
    var toggleBtn = document.getElementById('ctrl-toggle');
    if (!toggleBtn) return;

    toggleBtn.addEventListener('click', function() {
        var isEnabled = lastControlState && lastControlState.enabled;
        var action = isEnabled ? 'disable' : 'enable';
        var label = isEnabled ? 'Disable' : 'Enable';
        showConfirmDialog(
            '<strong>' + label + '</strong> power limiting?',
            async function() {
                try {
                    var res = await fetch('/api/power-limit', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ action: action })
                    });
                    var data = await res.json();
                    if (data.success) {
                        showToast('Power limiting ' + (action === 'enable' ? 'enabled' : 'disabled'), 'success');
                    } else if (res.status === 409) {
                        showToast('Venus OS is controlling -- manual override blocked', 'error');
                    } else {
                        showToast(data.error || 'Failed to ' + action + ' power limit', 'error');
                    }
                } catch (e) {
                    showToast('Request failed: ' + e.message, 'error');
                }
            }
        );
    });
})();

// --- Update Power Control from Snapshot ---

function updatePowerControl(data) {
    var ctrl = data.control;
    if (!ctrl) return;

    lastControlState = ctrl;

    var dot = document.getElementById('ctrl-dot');
    var label = document.getElementById('ctrl-label');
    var limitEl = document.getElementById('ctrl-limit');
    var sourceEl = document.getElementById('ctrl-source');
    var tsEl = document.getElementById('ctrl-ts');
    var slider = document.getElementById('ctrl-slider');
    var sliderValue = document.getElementById('ctrl-slider-value');
    var applyBtn = document.getElementById('ctrl-apply');
    var toggleBtn = document.getElementById('ctrl-toggle');
    var revertDiv = document.getElementById('ctrl-revert');
    var revertTime = document.getElementById('ctrl-revert-time');
    var banner = document.getElementById('ctrl-override-banner');

    // Status dot and label
    var source = ctrl.last_source || 'none';
    var enabled = ctrl.enabled;
    if (source === 'venus_os') {
        if (dot) dot.className = 've-dot ve-dot--err';
        if (label) label.textContent = 'Venus OS override active';
    } else if (enabled && source === 'webapp') {
        if (dot) dot.className = 've-dot ve-dot--warn';
        if (label) label.textContent = 'Limited (' + ctrl.limit_pct.toFixed(1) + '%)';
    } else if (enabled && source !== 'none') {
        if (dot) dot.className = 've-dot ve-dot--warn';
        if (label) label.textContent = 'Limited (' + ctrl.limit_pct.toFixed(1) + '%)';
    } else {
        if (dot) dot.className = 've-dot ve-dot--ok';
        if (label) label.textContent = 'No limit active';
    }

    // Readout
    if (limitEl) {
        limitEl.textContent = enabled ? ctrl.limit_pct.toFixed(1) + '%' : '--';
    }
    if (sourceEl) {
        var sourceNames = { 'none': 'None', 'webapp': 'Webapp', 'venus_os': 'Venus OS' };
        sourceEl.textContent = sourceNames[source] || source;
    }
    if (tsEl) {
        if (ctrl.last_change_ts && ctrl.last_change_ts > 0) {
            tsEl.textContent = formatRelativeTime(ctrl.last_change_ts);
        } else {
            tsEl.textContent = '--';
        }
    }

    // Slider (only update if user is not dragging)
    var isVenusOverride = source === 'venus_os';
    if (!ctrlSliderDragging && slider && sliderValue) {
        var pct = enabled ? Math.round(ctrl.limit_pct) : 100;
        slider.value = pct;
        var kw = (pct / 100 * RATED_KW).toFixed(1);
        sliderValue.textContent = pct + '% = ' + kw + ' kW';
    }

    // Disable slider and apply when Venus OS controls
    if (slider) slider.disabled = isVenusOverride;
    if (applyBtn) applyBtn.disabled = isVenusOverride;

    // Toggle button text
    if (toggleBtn) {
        toggleBtn.textContent = enabled ? 'Disable' : 'Enable';
        toggleBtn.disabled = isVenusOverride;
    }

    // Venus OS override banner
    if (banner) {
        banner.style.display = isVenusOverride ? 'block' : 'none';
    }

    // Revert countdown
    if (revertDiv && revertTime) {
        if (ctrl.revert_remaining_s != null && ctrl.revert_remaining_s > 0 && source === 'webapp') {
            var secs = Math.ceil(ctrl.revert_remaining_s);
            var mins = Math.floor(secs / 60);
            var secPart = secs % 60;
            revertTime.textContent = mins + ':' + (secPart < 10 ? '0' : '') + secPart;
            revertDiv.style.display = 'block';
        } else {
            revertDiv.style.display = 'none';
        }
    }

    // Override log
    if (data.override_log) {
        updateOverrideLog(data.override_log);
    }
}

function formatRelativeTime(ts) {
    var now = Date.now() / 1000;
    var diff = now - ts;
    if (diff < 0) diff = 0;
    if (diff < 60) return Math.round(diff) + 's ago';
    if (diff < 3600) return Math.round(diff / 60) + 'm ago';
    if (diff < 86400) return Math.round(diff / 3600) + 'h ago';
    return new Date(ts * 1000).toLocaleString();
}

// --- Override Log Rendering ---

function updateOverrideLog(events) {
    var container = document.getElementById('override-log');
    if (!container) return;

    if (!events || events.length === 0) {
        container.innerHTML = '<div class="ve-text-dim">No events yet</div>';
        return;
    }

    // Newest first
    var sorted = events.slice().reverse();
    var html = '';
    for (var i = 0; i < sorted.length; i++) {
        var ev = sorted[i];
        var ts = new Date(ev.ts * 1000);
        var timeStr = ts.toLocaleTimeString();
        var sourceCls = 've-source-badge ve-source-badge--' + (ev.source || 'system');
        var sourceLabel = { 'webapp': 'Webapp', 'venus_os': 'Venus OS', 'system': 'System' }[ev.source] || ev.source;
        var valueStr = ev.value != null ? ev.value.toFixed(1) + '%' : '';
        var detailStr = ev.detail ? ' (' + ev.detail + ')' : '';

        html += '<div class="ve-log-entry">' +
            '<span class="ve-log-ts">' + timeStr + '</span>' +
            '<span class="' + sourceCls + '">' + sourceLabel + '</span>' +
            '<span class="ve-log-action">' + (ev.action || '') + detailStr + '</span>' +
            '<span class="ve-log-value">' + valueStr + '</span>' +
            '</div>';
    }
    container.innerHTML = html;
}

// --- Handle override_event WebSocket message ---

function handleOverrideEvent(eventData) {
    var sourceNames = { 'webapp': 'Webapp', 'venus_os': 'Venus OS', 'system': 'System' };
    var sourceName = sourceNames[eventData.source] || eventData.source;
    var msg = sourceName + ': ' + eventData.action;
    if (eventData.value != null) msg += ' ' + eventData.value.toFixed(1) + '%';
    if (eventData.detail) msg += ' (' + eventData.detail + ')';

    var toastType = eventData.source === 'venus_os' ? 'error' : 'info';
    showToast(msg, toastType);
}

// ===== Initialization =====

document.addEventListener('DOMContentLoaded', () => {
    // Start WebSocket connection for live dashboard
    connectWebSocket();

    // Load config form values
    loadConfig();

    // Fallback polling (reduced frequency -- WebSocket provides live data)
    pollStatus();
    pollHealth();
    setInterval(() => {
        pollStatus();
        pollHealth();
        pollRegisters();
    }, POLL_INTERVAL);
});
