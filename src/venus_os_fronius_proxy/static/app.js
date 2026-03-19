/* Venus OS Fronius Proxy - Frontend Application
   Navigation, WebSocket live dashboard, config form, register viewer */

const POLL_INTERVAL = 10000; // Fallback polling interval (WebSocket provides live data)
let previousRegValues = {};
let ws = null;
let sparklineData = [];
var CAPACITY_W = 30000;
var previousSnapshot = null;
var TEMP_WARNING_C = 75; // Heatsink temperature warning threshold for SE30K
var venusLockRemaining = null;
var venusLockSnapshotTs = null;
var venusCountdownInterval = null;

// ===== Navigation =====

document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        const page = item.dataset.page;
        // Hide all pages, show selected
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        var pageEl = document.getElementById('page-' + page);
        if (pageEl) pageEl.classList.add('active');
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

// ===== Animation Guards =====

var prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
var entranceAnimated = false;

// ===== WebSocket Connection =====

function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(protocol + '//' + location.host + '/ws');
    let reconnectDelay = 1000;

    ws.onopen = function() {
        reconnectDelay = 1000;
        updateConnectionIndicator('connected');
        if (!entranceAnimated && !prefersReducedMotion.matches) {
            var cards = document.querySelectorAll('#page-dashboard .ve-card');
            for (var i = 0; i < cards.length; i++) {
                cards[i].classList.add('ve-card--entering');
            }
            entranceAnimated = true;
            setTimeout(function() {
                var entering = document.querySelectorAll('.ve-card--entering');
                for (var j = 0; j < entering.length; j++) {
                    entering[j].classList.remove('ve-card--entering');
                }
            }, 800);
        }
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

    // Update rated power from snapshot (dynamic per inverter)
    if (data.rated_power_w && data.rated_power_w > 0) {
        var newRated = Math.round(data.rated_power_w / 1000);
        if (newRated !== RATED_KW) {
            RATED_KW = newRated;
            CAPACITY_W = newRated * 1000;
            dropdownPopulated = false;  // Rebuild dropdown
        }
        if (!dropdownPopulated) {
            populatePowerDropdowns(newRated);
            dropdownPopulated = true;
        }
    }

    // Smart notifications: detect events from snapshot diff
    if (previousSnapshot) {
        detectEvents(previousSnapshot, data);
    }

    // Update gauge
    updateGauge(inv.ac_power_w || 0);
    updateGaugeStatus(data.inverter_name || '--');

    // Update inverter status panel and daily energy
    updateStatusPanel(inv);
    updateDailyEnergy(inv);
    updatePeakStats(inv);

    // Update phase cards
    updatePhaseCard('l1', inv.ac_voltage_an_v, inv.ac_current_l1_a);
    updatePhaseCard('l2', inv.ac_voltage_bn_v, inv.ac_current_l2_a);
    updatePhaseCard('l3', inv.ac_voltage_cn_v, inv.ac_current_l3_a);

    // Append to sparkline data
    sparklineData.push(inv.ac_power_w || 0);
    if (sparklineData.length > 300) sparklineData.shift();
    renderSparkline();

    // Update connection/health from snapshot data
    if (data.connection) {
        updateConnectionStatus(data.connection);
    }

    // Update power control section
    updatePowerControl(data);

    // Update Venus OS info widget
    updateVenusInfo(data);

    // Update Venus OS ESS settings
    updateVenusESS(data);

    previousSnapshot = data;

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

// ===== Smart Notifications =====

function detectEvents(prev, curr) {
    if (!prev || !curr) return;
    var prevInv = prev.inverter || {};
    var currInv = curr.inverter || {};
    var prevCtrl = prev.control || {};
    var currCtrl = curr.control || {};

    // NOTIF-02: Venus OS override detection
    // Trigger when last_source transitions TO venus_os from any other source
    if (prevCtrl.last_source !== 'venus_os' && currCtrl.last_source === 'venus_os') {
        var limitStr = currCtrl.limit_pct != null ? ' at ' + currCtrl.limit_pct.toFixed(1) + '%' : '';
        showToast('Venus OS took control' + limitStr, 'warning');
    }

    // NOTIF-03: Inverter fault detection
    // Trigger when status transitions TO FAULT from any other status
    if (prevInv.status !== 'FAULT' && currInv.status === 'FAULT') {
        showToast('Inverter FAULT detected!', 'error');
    }

    // NOTIF-03: Temperature warning
    // Trigger when heatsink temp crosses threshold upward
    var prevTemp = prevInv.temperature_sink_c;
    var currTemp = currInv.temperature_sink_c;
    if (prevTemp != null && currTemp != null) {
        if (prevTemp < TEMP_WARNING_C && currTemp >= TEMP_WARNING_C) {
            showToast('Heatsink temperature warning: ' + currTemp.toFixed(1) + '\u00B0C', 'warning');
        }
    }

    // NOTIF-04: Night mode transition (sleep)
    // Trigger when status transitions TO SLEEPING from MPPT or THROTTLED (active states)
    var activeStates = ['MPPT', 'THROTTLED', 'STARTING'];
    if (activeStates.indexOf(prevInv.status) !== -1 && currInv.status === 'SLEEPING') {
        showToast('Inverter entering night mode', 'info');
    }

    // NOTIF-04: Wake transition
    // Trigger when status transitions FROM SLEEPING to MPPT
    if (prevInv.status === 'SLEEPING' && currInv.status === 'MPPT') {
        showToast('Inverter waking up - producing power', 'success');
    }

    // Note: auto-unlock detection removed — the toggle UI update is sufficient,
    // and the manual unlock already shows its own toast.
}

// ===== History Handler =====

function handleHistory(data) {
    if (data.ac_power_w && Array.isArray(data.ac_power_w)) {
        sparklineData = data.ac_power_w.map(function(p) { return p[1]; });
        renderSparkline();
    }
}

// ===== Gauge Update =====

var lastGaugePower = -1;
var GAUGE_DEADBAND_W = 50;

function updateGauge(powerW) {
    if (lastGaugePower >= 0 && Math.abs(powerW - lastGaugePower) < GAUGE_DEADBAND_W) return;
    lastGaugePower = powerW;
    var pct = Math.min(powerW / CAPACITY_W, 1.0);
    var arcLength = 251.3;
    var offset = arcLength * (1 - pct);

    var gaugeFill = document.getElementById('gauge-fill');
    var gaugeValue = document.getElementById('gauge-value');

    if (gaugeFill) {
        gaugeFill.style.strokeDashoffset = offset;
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

// ===== Inverter Status Panel =====

function updateStatusPanel(inv) {
    var dot = document.getElementById('inv-status-dot');
    var text = document.getElementById('inv-status-text');
    var tempCab = document.getElementById('inv-temp-cab');
    var tempSink = document.getElementById('inv-temp-sink');
    var dcV = document.getElementById('inv-dc-voltage');
    var dcA = document.getElementById('inv-dc-current');
    var dcW = document.getElementById('inv-dc-power');

    // Status with color mapping
    var status = inv.status || '--';
    if (text) text.textContent = status;

    if (dot) {
        var statusMap = {
            'MPPT': 'operating', 'OFF': 'off', 'SLEEPING': 'sleeping',
            'STARTING': 'starting', 'THROTTLED': 'throttled',
            'SHUTTING_DOWN': 'off', 'FAULT': 'fault', 'STANDBY': 'sleeping'
        };
        var mod = statusMap[status] || '';
        dot.className = 've-status-indicator' + (mod ? ' ve-status-indicator--' + mod : '');
    }

    // Temperature values
    if (tempCab) {
        var newCab = inv.temperature_cab_c != null ? inv.temperature_cab_c.toFixed(1) + ' \u00B0C' : '-- \u00B0C';
        if (tempCab.textContent !== newCab) { tempCab.textContent = newCab; flashValue(tempCab, 'temperature'); }
    }
    if (tempSink) {
        var newSink = inv.temperature_sink_c != null ? inv.temperature_sink_c.toFixed(1) + ' \u00B0C' : '-- \u00B0C';
        if (tempSink.textContent !== newSink) { tempSink.textContent = newSink; flashValue(tempSink, 'temperature'); }
    }

    // DC values
    if (dcV) {
        var newDcV = inv.dc_voltage_v != null ? inv.dc_voltage_v.toFixed(1) + ' V' : '-- V';
        if (dcV.textContent !== newDcV) { dcV.textContent = newDcV; flashValue(dcV, 'voltage'); }
    }
    if (dcA) {
        var newDcA = inv.dc_current_a != null ? inv.dc_current_a.toFixed(2) + ' A' : '-- A';
        if (dcA.textContent !== newDcA) { dcA.textContent = newDcA; flashValue(dcA, 'current'); }
    }
    if (dcW) {
        var newDcW = inv.dc_power_w != null ? (inv.dc_power_w / 1000).toFixed(2) + ' kW' : '-- kW';
        if (dcW.textContent !== newDcW) { dcW.textContent = newDcW; flashValue(dcW, 'power'); }
    }
}

// ===== Daily Energy =====

function updateDailyEnergy(inv) {
    var el = document.getElementById('daily-energy');
    if (!el) return;
    var wh = inv.daily_energy_wh || 0;
    var kwh = (wh / 1000).toFixed(1) + ' kWh';
    if (el.textContent !== kwh) {
        el.textContent = kwh;
        flashValue(el);
    }
}

// ===== Peak Stats Update =====

function updatePeakStats(inv) {
    var peakEl = document.getElementById('peak-power');
    var hoursEl = document.getElementById('operating-hours');
    var effEl = document.getElementById('efficiency-pct');

    if (peakEl) {
        var newPeak = inv.peak_power_w != null ? (inv.peak_power_w / 1000).toFixed(1) + ' kW' : '-- kW';
        if (peakEl.textContent !== newPeak) { peakEl.textContent = newPeak; flashValue(peakEl, 'power'); }
    }
    if (hoursEl) {
        var newHours = inv.operating_hours != null ? inv.operating_hours.toFixed(1) + 'h' : '--';
        if (hoursEl.textContent !== newHours) { hoursEl.textContent = newHours; flashValue(hoursEl); }
    }
    if (effEl) {
        var newEff = inv.efficiency_pct != null ? inv.efficiency_pct.toFixed(0) + '%' : '--%';
        if (effEl.textContent !== newEff) { effEl.textContent = newEff; flashValue(effEl); }
    }
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
            flashValue(voltageEl, 'voltage');
        }
    }

    if (currentEl) {
        var newA = (current != null) ? current.toFixed(2) + ' A' : '-- A';
        if (currentEl.textContent !== newA) {
            currentEl.textContent = newA;
            flashValue(currentEl, 'current');
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
            flashValue(powerEl, 'power');
        }
    }
}

var FLASH_THRESHOLDS = {
    'voltage': 2,
    'current': 0.5,
    'power': 100,
    'temperature': 1,
    'default': 0
};
var lastFlashValues = {};

function flashValue(el, metricType) {
    var numericValue = parseFloat(el.textContent);
    if (metricType && !isNaN(numericValue)) {
        var threshold = FLASH_THRESHOLDS[metricType] || FLASH_THRESHOLDS['default'];
        var key = el.id || el.textContent;
        if (lastFlashValues[key] !== undefined && Math.abs(numericValue - lastFlashValues[key]) < threshold) {
            lastFlashValues[key] = numericValue;
            return;
        }
        lastFlashValues[key] = numericValue;
    }
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

        if (seDot) seDot.className = seClass + (seDotMod ? ' ' + seDotMod : '');
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

        if (vosDot) vosDot.className = seClass + (vosDotMod ? ' ' + vosDotMod : '');
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

let RATED_KW = 30;  // Updated dynamically from snapshot.rated_power_w
let dropdownPopulated = false;

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

var toastContainer = null;
var MAX_TOASTS = 4;

function getToastContainer() {
    if (!toastContainer) {
        toastContainer = document.getElementById('toast-container');
    }
    return toastContainer;
}

function showToast(message, type) {
    var container = getToastContainer();
    if (!container) return;

    // Duplicate suppression: skip if same message already showing
    var existing = container.querySelectorAll('.ve-toast:not(.ve-toast--exiting)');
    for (var i = 0; i < existing.length; i++) {
        if (existing[i].textContent === message) return;
    }

    // Enforce max visible: dismiss oldest non-error toast
    while (container.querySelectorAll('.ve-toast:not(.ve-toast--exiting)').length >= MAX_TOASTS) {
        var toasts = container.querySelectorAll('.ve-toast:not(.ve-toast--exiting)');
        var oldest = null;
        for (var k = toasts.length - 1; k >= 0; k--) {
            if (!toasts[k].classList.contains('ve-toast--error')) { oldest = toasts[k]; break; }
        }
        if (!oldest) oldest = toasts[toasts.length - 1];
        dismissToast(oldest);
    }

    // Tiered auto-dismiss duration by severity
    var duration = (type === 'error') ? 8000 : (type === 'warning') ? 5000 : 3000;

    var toast = document.createElement('div');
    toast.className = 've-toast ve-toast--' + (type || 'info');
    toast.textContent = message;
    toast.setAttribute('role', 'alert');

    // Newest at top (prepend)
    container.prepend(toast);

    // Auto-dismiss timer
    var timer = setTimeout(function() { dismissToast(toast); }, duration);

    // Click to dismiss
    toast.addEventListener('click', function() {
        clearTimeout(timer);
        dismissToast(toast);
    });
}

function dismissToast(toast) {
    if (!toast || toast.classList.contains('ve-toast--exiting')) return;
    toast.classList.add('ve-toast--exiting');
    toast.addEventListener('animationend', function() {
        toast.remove();
    });
}

// --- Apply Power Limit ---

// --- Populate kW Dropdown dynamically ---

var clampMin = 0;   // Current floor in kW (0 = no floor)
var clampMax = null; // Current ceiling in kW (null = no ceiling = rated)

function populatePowerDropdowns(maxKw) {
    var minDD = document.getElementById('ctrl-min');
    var maxDD = document.getElementById('ctrl-max');
    if (!minDD || !maxDD) return;

    var minVal = minDD.value;
    var maxVal = maxDD.value;

    function kwLabel(pct) {
        var kw = maxKw * pct / 100;
        return kw === Math.floor(kw) ? kw.toFixed(0) + ' kW' : kw.toFixed(1) + ' kW';
    }

    // Both dropdowns: 100% down to 0% in 1% steps, shown as kW
    minDD.innerHTML = '';
    maxDD.innerHTML = '';
    for (var pct = 100; pct >= 0; pct--) {
        var optMin = document.createElement('option');
        optMin.value = pct;
        optMin.textContent = kwLabel(pct);
        minDD.appendChild(optMin);

        var optMax = document.createElement('option');
        optMax.value = pct;
        optMax.textContent = kwLabel(pct);
        maxDD.appendChild(optMax);
    }
    minDD.value = '0';   // Default: no floor
    maxDD.value = '100'; // Default: no ceiling

    // Restore
    if (minDD.querySelector('option[value="' + minVal + '"]')) minDD.value = minVal;
    if (maxDD.querySelector('option[value="' + maxVal + '"]')) maxDD.value = maxVal;
}

function getClampPct() {
    var minDD = document.getElementById('ctrl-min');
    var maxDD = document.getElementById('ctrl-max');
    var minPct = minDD ? parseInt(minDD.value) || 0 : 0;
    var maxPct = maxDD ? parseInt(maxDD.value) || 100 : 100;
    return { min: minPct, max: maxPct };
}

// --- Min/Max clamp dropdowns ---

async function sendClamp(minPct, maxPct) {
    try {
        var res = await fetch('/api/power-clamp', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ min_pct: minPct, max_pct: maxPct })
        });
        var data = await res.json();
        if (data.success) {
            var minKw = (minPct / 100 * RATED_KW);
            var maxKw = (maxPct / 100 * RATED_KW);
            var minStr = minKw === Math.floor(minKw) ? minKw.toFixed(0) : minKw.toFixed(1);
            var maxStr = maxKw === Math.floor(maxKw) ? maxKw.toFixed(0) : maxKw.toFixed(1);
            showToast('Range: ' + minStr + ' – ' + maxStr + ' kW', 'success');
        } else {
            showToast(data.error || 'Failed', 'error');
        }
    } catch (e) {
        showToast('Request failed: ' + e.message, 'error');
    }
}

(function() {
    var minDD = document.getElementById('ctrl-min');
    var maxDD = document.getElementById('ctrl-max');
    if (!minDD || !maxDD) return;

    minDD.addEventListener('change', function() {
        var clamp = getClampPct();
        if (clamp.min > clamp.max) {
            maxDD.value = clamp.min;
            clamp.max = clamp.min;
        }
        sendClamp(clamp.min, clamp.max);
    });

    maxDD.addEventListener('change', function() {
        var clamp = getClampPct();
        if (clamp.max < clamp.min) {
            minDD.value = clamp.max;
            clamp.min = clamp.max;
        }
        sendClamp(clamp.min, clamp.max);
    });
})();

// --- Update Power Control from Snapshot ---

function updatePowerControl(data) {
    var ctrl = data.control;
    if (!ctrl) return;

    lastControlState = ctrl;

    var dot = document.getElementById('ctrl-dot');
    var label = document.getElementById('ctrl-label');

    // Status dot and label (between min/max dropdowns)
    var source = ctrl.last_source || 'none';
    var enabled = ctrl.enabled;
    var limitKw = (ctrl.limit_pct / 100 * RATED_KW).toFixed(1);
    if (source === 'venus_os' && ctrl.limit_pct < 100) {
        if (dot) dot.className = 've-dot ve-dot--ok';  // Green = Venus OS actively regulating
        if (label) label.textContent = limitKw + ' kW';
    } else if (enabled && source === 'webapp') {
        if (dot) dot.className = 've-dot ve-dot--warn';
        if (label) label.textContent = limitKw + ' kW';
    } else {
        if (dot) dot.className = 've-dot ve-dot--dim';  // Grey = no active regulation
        if (label) label.textContent = limitKw + ' kW';
    }

    // Sync dropdown selections from snapshot (restored clamp values)
    var minDD = document.getElementById('ctrl-min');
    var maxDD = document.getElementById('ctrl-max');
    if (minDD && ctrl.clamp_min_pct != null && !minDD.matches(':focus')) {
        minDD.value = ctrl.clamp_min_pct;
    }
    if (maxDD && ctrl.clamp_max_pct != null && !maxDD.matches(':focus')) {
        maxDD.value = ctrl.clamp_max_pct;
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

    var countEl = document.getElementById('override-log-count');
    if (countEl) {
        countEl.textContent = (events && events.length) ? events.length : 0;
    }

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

// --- Override Log Toggle (Collapsible) ---
(function() {
    var toggleBtn = document.getElementById('override-log-toggle');
    var logContainer = document.getElementById('override-log');
    if (!toggleBtn || !logContainer) return;

    toggleBtn.addEventListener('click', function() {
        logContainer.classList.toggle('ve-override-log--collapsed');
    });
})();

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

// ===== Venus OS Info Widget =====

function updateVenusInfo(snapshot) {
    var venus = snapshot.venus_os;
    if (!venus) return;

    var dot = document.getElementById('venus-status-dot');
    var statusText = document.getElementById('venus-status-text');
    var overrideEl = document.getElementById('venus-override');
    var lastContactEl = document.getElementById('venus-last-contact');
    var toggle = document.getElementById('venus-lock-toggle');
    var countdownDiv = document.getElementById('lock-countdown');
    var countdownTime = document.getElementById('lock-countdown-time');

    // Venus OS connection status: "Online" if last_source=="venus_os" AND last_change_ts within 120s
    var isOnline = false;
    if (venus.last_source === 'venus_os' && venus.last_change_ts > 0) {
        var age = (snapshot.ts - venus.last_change_ts);
        isOnline = age < 120;
    }

    if (dot) dot.className = 've-status-dot ' + (isOnline ? 'online' : 'offline');
    if (statusText) statusText.textContent = isOnline ? 'Online' : 'Offline';

    // Override status (elements may not exist if Venus OS card removed)
    if (overrideEl) {
        var ctrl = snapshot.control;
        if (isOnline && ctrl && ctrl.enabled && ctrl.last_source === 'venus_os') {
            overrideEl.textContent = ctrl.limit_pct.toFixed(1) + '%';
        } else if (isOnline) {
            overrideEl.textContent = 'No override';
        } else {
            overrideEl.textContent = '--';
        }
    }

    if (lastContactEl) {
        if (venus.last_change_ts > 0) {
            var ageSec = Math.floor(snapshot.ts - venus.last_change_ts);
            if (ageSec < 60) lastContactEl.textContent = ageSec + 's ago';
            else if (ageSec < 3600) lastContactEl.textContent = Math.floor(ageSec / 60) + 'm ago';
            else lastContactEl.textContent = Math.floor(ageSec / 3600) + 'h ago';
        } else {
            lastContactEl.textContent = 'Never';
        }
    }

    // Venus OS toggle: checked = allowed, unchecked = blocked (inverted from lock)
    // Skip update if user just changed it (debounce)
    var now = Date.now();
    if ((now - (toggle._userChangedAt || 0)) > 8000) {
        toggle.checked = !venus.is_locked;
    }
    toggle.disabled = false;

    // Countdown
    if (venus.is_locked && venus.lock_remaining_s != null) {
        countdownDiv.style.display = '';
        venusLockRemaining = venus.lock_remaining_s;
        venusLockSnapshotTs = Date.now() / 1000;
        updateCountdownDisplay();
        startCountdownInterval();
    } else {
        countdownDiv.style.display = 'none';
        venusLockRemaining = null;
        stopCountdownInterval();
        var timerEl = document.getElementById('lock-timer');
        if (timerEl) timerEl.textContent = '';
    }
}

function updateCountdownDisplay() {
    var el = document.getElementById('lock-timer');
    var oldEl = document.getElementById('lock-countdown-time');
    if (venusLockRemaining == null) {
        if (el) el.textContent = '';
        return;
    }
    var elapsed = Date.now() / 1000 - venusLockSnapshotTs;
    var remaining = Math.max(0, venusLockRemaining - elapsed);
    var min = Math.floor(remaining / 60);
    var sec = Math.floor(remaining % 60);
    var text = min + ':' + (sec < 10 ? '0' : '') + sec;
    if (el) el.textContent = text;
    if (oldEl) oldEl.textContent = text;
}

function startCountdownInterval() {
    if (venusCountdownInterval) return;
    venusCountdownInterval = setInterval(updateCountdownDisplay, 1000);
}

function stopCountdownInterval() {
    if (venusCountdownInterval) {
        clearInterval(venusCountdownInterval);
        venusCountdownInterval = null;
    }
}

// --- Venus OS Lock Toggle Handler ---

(function() {
    var toggle = document.getElementById('venus-lock-toggle');
    if (!toggle) return;
    var lastDisableTs = 0;
    var isCurrentlyLocked = false;

    toggle.addEventListener('change', function() {
        toggle._userChangedAt = Date.now();
        var now = Date.now();
        var wantAllow = toggle.checked;
        if (!wantAllow) {
            // Disable: if toggled off again within 5s of last disable = permanent
            var permanent = (now - lastDisableTs) < 5000 && lastDisableTs > 0;
            lastDisableTs = now;
            sendLockCommand(true, permanent);
        } else {
            // Enable: only reset if it's been > 5s since last disable
            if ((now - lastDisableTs) > 5000) {
                lastDisableTs = 0;
            }
            sendLockCommand(false, false);
        }
    });
})();

async function sendLockCommand(lock, permanent) {
    try {
        var body = { action: lock ? 'lock' : 'unlock' };
        if (permanent) body.permanent = true;
        var res = await fetch('/api/venus-lock', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        var data = await res.json();
        if (data.success) {
            if (lock && permanent) {
                showToast('Venus OS control disabled (permanent)', 'warning');
            } else if (lock) {
                showToast('Venus OS control disabled (15 min)', 'warning');
            } else {
                showToast('Venus OS control enabled', 'success');
            }
        } else {
            showToast(data.error || 'Failed', 'error');
        }
    } catch (e) {
        showToast('Request failed: ' + e.message, 'error');
    }
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

// --- Venus OS ESS Settings ---

var essFeedInPopulated = false;

function populateESSFeedIn() {
    var dd = document.getElementById('ess-feed-in');
    if (!dd || essFeedInPopulated) return;
    dd.innerHTML = '';
    for (var kw = 30; kw >= 0; kw--) {
        var opt = document.createElement('option');
        opt.value = kw * 1000;
        opt.textContent = kw + ' kW';
        dd.appendChild(opt);
    }
    essFeedInPopulated = true;
}

function formatKw(watts) {
    if (watts == null) return '--';
    var kw = watts / 1000;
    return (kw === Math.floor(kw) ? kw.toFixed(0) : kw.toFixed(1)) + ' kW';
}

function updateVenusESS(snapshot) {
    var vs = snapshot.venus_settings;
    if (!vs) return;

    var acToggle = document.getElementById('ess-ac-excess');
    var dcToggle = document.getElementById('ess-dc-excess');
    var maxRow = document.getElementById('ess-max-feedin-row');
    var feedInDD = document.getElementById('ess-feed-in');
    var feedInActual = document.getElementById('ess-feed-in-actual');
    var limiterEl = document.getElementById('ess-limiter-value');

    populateESSFeedIn();

    var now = Date.now();
    function notCooling(el) { return (now - (el._userChangedAt || 0)) > 8000; }

    // 1. AC PV Excess (PreventFeedback: 0=allow, inverted)
    var acOn = !vs.prevent_feedback;
    if (acToggle && notCooling(acToggle)) acToggle.checked = acOn;

    // 2. DC PV Excess (OvervoltageFeedIn: 1=feed)
    var dcOn = vs.overvoltage_feed_in;
    if (dcToggle && notCooling(dcToggle)) dcToggle.checked = dcOn;

    // 3. Show "Limit Feed-in" when AC OR DC is on
    var excessActive = acOn || dcOn;
    var limitRow = document.getElementById('ess-limit-row');
    var limitToggle = document.getElementById('ess-limit-feedin');
    if (limitRow) limitRow.style.display = excessActive ? '' : 'none';

    // 4. Limit Feed-in toggle
    var feedInLimited = vs.max_feed_in_w >= 0;
    if (limitToggle && notCooling(limitToggle)) limitToggle.checked = feedInLimited;

    // 5. Show Max Feed-in when limit is active AND excess is on
    if (maxRow) maxRow.style.display = (excessActive && feedInLimited) ? '' : 'none';

    // 6. Feed-in actual (current grid export)
    if (feedInActual) {
        feedInActual.textContent = formatKw(vs.grid_feed_in_w);
        if (vs.max_feed_in_w > 0 && vs.grid_feed_in_w > vs.max_feed_in_w) {
            feedInActual.style.color = 'var(--ve-red)';
        } else if (vs.grid_feed_in_w > 0) {
            feedInActual.style.color = 'var(--ve-green)';
        } else {
            feedInActual.style.color = '';
        }
    }

    // 7. Feed-in dropdown (target value)
    if (feedInDD && !feedInDD.matches(':focus') && vs.max_feed_in_w > 0) {
        var closest = Math.round(vs.max_feed_in_w / 1000) * 1000;
        feedInDD.value = closest;
    }

    // 8. Limit Inverter Power
    var invLimitToggle = document.getElementById('ess-limit-inverter');
    var invLimitRow = document.getElementById('ess-max-inverter-row');
    var invLimitDD = document.getElementById('ess-max-inverter');

    // Limited = dbus value is not -1 (any value >= 0 including 30kW is a valid limit)
    var invLimited = vs.max_inverter_w >= 0;
    if (invLimitToggle && notCooling(invLimitToggle)) invLimitToggle.checked = invLimited;
    if (invLimitRow) invLimitRow.style.display = invLimited ? '' : 'none';

    if (invLimitDD && invLimitDD.options.length <= 1) {
        invLimitDD.innerHTML = '';
        for (var kw = 30; kw >= 1; kw--) {
            var opt = document.createElement('option');
            opt.value = kw * 1000;
            opt.textContent = kw + ' kW';
            invLimitDD.appendChild(opt);
        }
    }
    if (invLimitDD && !invLimitDD.matches(':focus') && invLimited) {
        var closest = Math.round(vs.max_inverter_w / 1000) * 1000;
        invLimitDD.value = closest;
    }

    // 9. Feed-in Limiting status
    if (limiterEl) {
        if (vs.limiter_active) {
            limiterEl.textContent = 'Active';
            limiterEl.style.color = 'var(--ve-green)';
        } else {
            limiterEl.textContent = 'Inactive';
            limiterEl.style.color = 'var(--ve-text-dim)';
        }
    }
}

// --- ESS Write Handler ---

async function writeVenusDbus(path, value) {
    try {
        var res = await fetch('/api/venus-dbus', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: path, value: value })
        });
        var data = await res.json();
        if (!data.success) showToast(data.error || 'Write failed', 'error');
    } catch (e) {
        showToast('Request failed: ' + e.message, 'error');
    }
}

async function writeESSSetting(register, value) {
    try {
        var res = await fetch('/api/venus-write', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ register: register, value: value })
        });
        var data = await res.json();
        if (!data.success) showToast(data.error || 'Write failed', 'error');
    } catch (e) {
        showToast('Request failed: ' + e.message, 'error');
    }
}

(function() {
    var acToggle = document.getElementById('ess-ac-excess');
    var dcToggle = document.getElementById('ess-dc-excess');
    var limitToggle = document.getElementById('ess-limit-feedin');
    var feedInDD = document.getElementById('ess-feed-in');

    // AC PV Excess (PreventFeedback: inverted — 0=allow, 1=block)
    if (acToggle) acToggle.addEventListener('change', function() {
        acToggle._userChangedAt = Date.now();
        writeVenusDbus('/Settings/CGwacs/PreventFeedback', acToggle.checked ? 0 : 1);
        showToast('AC PV Excess: ' + (acToggle.checked ? 'On' : 'Off'), 'success');
    });

    // DC PV Excess (OvervoltageFeedIn: 1=feed, 0=don't)
    if (dcToggle) dcToggle.addEventListener('change', function() {
        dcToggle._userChangedAt = Date.now();
        writeVenusDbus('/Settings/CGwacs/OvervoltageFeedIn', dcToggle.checked ? 1 : 0);
        showToast('DC PV Excess: ' + (dcToggle.checked ? 'On' : 'Off'), 'success');
    });

    // Limit Feed-in toggle
    if (limitToggle) limitToggle.addEventListener('change', function() {
        limitToggle._userChangedAt = Date.now();
        if (limitToggle.checked) {
            writeVenusDbus('/Settings/CGwacs/MaxFeedInPower', 10000);  // Default 10 kW
            showToast('Feed-in limit: 10 kW', 'success');
        } else {
            writeVenusDbus('/Settings/CGwacs/MaxFeedInPower', -1);
            showToast('Feed-in limit: Off', 'success');
        }
    });

    // Max Feed-in value dropdown
    if (feedInDD) feedInDD.addEventListener('change', function() {
        var watts = parseInt(feedInDD.value);
        writeVenusDbus('/Settings/CGwacs/MaxFeedInPower', watts);
        showToast('Max feed-in: ' + formatKw(watts), 'success');
    });

    // Limit Inverter Power toggle
    var invLimitToggle = document.getElementById('ess-limit-inverter');
    var invLimitDD = document.getElementById('ess-max-inverter');

    if (invLimitToggle) invLimitToggle.addEventListener('change', function() {
        invLimitToggle._userChangedAt = Date.now();
        if (invLimitToggle.checked) {
            writeVenusDbus('/Settings/CGwacs/MaxDischargePower', 20000);  // Default 20 kW
            showToast('Inverter limit: 20 kW', 'success');
        } else {
            writeVenusDbus('/Settings/CGwacs/MaxDischargePower', -1);
            showToast('Inverter limit: Off', 'success');
        }
    });

    if (invLimitDD) invLimitDD.addEventListener('change', function() {
        var watts = parseInt(invLimitDD.value);
        writeVenusDbus('/Settings/CGwacs/MaxDischargePower', watts);
        showToast('Max inverter: ' + formatKw(watts), 'success');
    });
})();
