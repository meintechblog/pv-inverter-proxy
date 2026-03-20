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

// ===== Discovery / Scan State =====
var _scanRunning = false;
var _autoScanDone = false;
var _configuredInverters = [];

// ===== Navigation =====

function navigateTo(page) {
    // Hide all pages, show selected
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    var pageEl = document.getElementById('page-' + page);
    if (pageEl) pageEl.classList.add('active');
    // Update nav active state
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    var navItem = document.querySelector('.nav-item[data-page="' + page + '"]');
    if (navItem) navItem.classList.add('active');
    // Persist in URL hash
    window.location.hash = page;
    // When navigating to config page, reset auto-scan flag
    if (page === 'config') _autoScanDone = false;
    // Close mobile sidebar
    document.getElementById('sidebar').classList.remove('open');
    const overlay = document.getElementById('sidebar-overlay');
    if (overlay) overlay.classList.remove('active');
}

document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        navigateTo(item.dataset.page);
    });
});

// Restore page from URL hash on load
(function() {
    var hash = window.location.hash.replace('#', '');
    if (hash && document.getElementById('page-' + hash)) {
        navigateTo(hash);
    }
})();

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
            if (msg.type === 'scan_progress') handleScanProgress(msg.data);
            if (msg.type === 'scan_complete') handleScanComplete(msg.data);
            if (msg.type === 'scan_error') handleScanError(msg.data);
            if (msg.type === 'no_inverter') handleNoInverter();
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

// ===== MQTT Gate & Config Bobbles =====

function updateMqttGate(snapshot) {
    var mqttConnected = snapshot.venus_mqtt_connected;
    var gatedEls = document.querySelectorAll('.venus-dependent');
    for (var i = 0; i < gatedEls.length; i++) {
        if (mqttConnected) {
            gatedEls[i].classList.remove('mqtt-gated');
            gatedEls[i].removeAttribute('aria-disabled');
        } else {
            gatedEls[i].classList.add('mqtt-gated');
            gatedEls[i].setAttribute('aria-disabled', 'true');
        }
    }

    // ESS gate: MQTT connected but no VE.Bus (MultiPlus) → ESS unavailable
    var essPanel = document.getElementById('venus-ess-panel');
    if (essPanel) {
        var vs = snapshot.venus_settings;
        var essDown = mqttConnected && vs && !vs.ess_available;
        if (essDown) {
            essPanel.classList.remove('mqtt-gated');
            essPanel.classList.add('ess-gated');
        } else {
            essPanel.classList.remove('ess-gated');
        }
    }
}

function updateConfigBobbles(snapshot) {
    // SolarEdge bobble on config page
    var seDot = document.getElementById('cfg-se-dot');
    if (seDot) {
        var seState = snapshot.connection ? snapshot.connection.state : 'disconnected';
        seDot.className = 've-dot ' + (seState === 'connected' ? 've-dot--ok' : seState === 'reconnecting' ? 've-dot--warn' : 've-dot--err');
    }
    // Venus OS bobble on config page
    var venusDot = document.getElementById('cfg-venus-dot');
    if (venusDot) {
        var venusHost = document.getElementById('venus-host');
        var hostConfigured = venusHost && venusHost.value.trim() !== '';
        if (!hostConfigured) {
            venusDot.className = 've-dot ve-dot--dim';
        } else if (snapshot.venus_mqtt_connected) {
            venusDot.className = 've-dot ve-dot--ok';
        } else {
            venusDot.className = 've-dot ve-dot--err';
        }
    }
}

function updateSetupGuide(snapshot) {
    var guide = document.getElementById('mqtt-setup-guide');
    if (!guide) return;
    // Use SAVED config value (not current input which may be mid-typing)
    var savedHost = _cfgOriginal.venus && _cfgOriginal.venus['venus-host'];
    var hostConfigured = savedHost && savedHost.trim() !== '';
    if (!snapshot.venus_mqtt_connected && hostConfigured) {
        guide.style.display = '';
    } else {
        guide.style.display = 'none';
    }
}

function updateAutoDetectBanner(snapshot) {
    var banner = document.getElementById('venus-auto-detect-banner');
    if (!banner) return;
    window._lastVenusDetected = snapshot.venus_os_detected;
    var venusHost = document.getElementById('venus-host');
    var hostConfigured = venusHost && venusHost.value.trim() !== '';
    var shouldShow = snapshot.venus_os_detected && !hostConfigured;
    if (shouldShow && banner.style.display === 'none') {
        // Auto-fill Venus OS IP from detected client connection
        if (snapshot.venus_os_client_ip && venusHost && !venusHost.value.trim()) {
            venusHost.value = snapshot.venus_os_client_ip;
        }
        banner.style.display = '';
        banner.classList.add('ve-card--entering');
        setTimeout(function() { banner.classList.remove('ve-card--entering'); }, 300);
    } else if (!shouldShow) {
        banner.style.display = 'none';
    }
}

// Register viewer: hide empty toggle
(function() {
    var toggle = document.getElementById('reg-hide-empty');
    if (toggle) {
        toggle.addEventListener('change', function() {
            var rows = document.querySelectorAll('.ve-reg-row.ve-empty');
            for (var i = 0; i < rows.length; i++) {
                if (toggle.checked) {
                    rows[i].classList.remove('ve-show-empty');
                } else {
                    rows[i].classList.add('ve-show-empty');
                }
            }
        });
    }
})();

// Hide auto-detect banner as soon as user types a Venus OS IP
(function() {
    var venusHostInput = document.getElementById('venus-host');
    if (venusHostInput) {
        venusHostInput.addEventListener('input', function() {
            var banner = document.getElementById('venus-auto-detect-banner');
            if (banner && this.value.trim() !== '') {
                banner.style.display = 'none';
            } else if (banner && this.value.trim() === '' && window._lastVenusDetected) {
                banner.style.display = '';
            }
        });
    }
})();

// ===== No Inverter Handler =====

var _noInverterActive = false;
function handleNoInverter() {
    _noInverterActive = true;
    var page = document.getElementById('page-dashboard');
    if (!page) return;

    // Hide all dashboard content
    Array.from(page.children).forEach(function(child) {
        if (!child.classList.contains('ve-no-inverter-hint')) {
            child.style.display = 'none';
        }
    });

    // Show hint card if not already present
    if (!page.querySelector('.ve-no-inverter-hint')) {
        var hint = document.createElement('div');
        hint.className = 've-no-inverter-hint';
        hint.innerHTML =
            '<div class="ve-hint-card" style="max-width:420px;margin:80px auto;text-align:center;padding:32px">' +
            '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" style="margin-bottom:16px;opacity:0.5">' +
            '<path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="var(--ve-text-dim)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>' +
            '</svg>' +
            '<h3 style="margin:0 0 8px;color:var(--ve-text)">Kein Inverter konfiguriert</h3>' +
            '<p style="margin:0;color:var(--ve-text-dim);font-size:0.9rem">Gehe zu <a href="#config" style="color:var(--ve-blue)">Config</a> um einen Inverter hinzuzufuegen oder Auto-Discover zu starten.</p>' +
            '</div>';
        page.appendChild(hint);
    }

    previousSnapshot = null;
}

function handleInverterRestored() {
    _noInverterActive = false;
    var page = document.getElementById('page-dashboard');
    if (!page) return;

    // Show all dashboard content again
    Array.from(page.children).forEach(function(child) {
        if (child.classList.contains('ve-no-inverter-hint')) {
            child.remove();
        } else {
            child.style.display = '';
        }
    });
}

// ===== Snapshot Handler =====

function handleSnapshot(data) {
    const inv = data.inverter;
    if (!inv) return;

    // Restore dashboard if it was hidden
    if (_noInverterActive) handleInverterRestored();

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

    // Update MQTT gate, config bobbles, setup guide
    updateMqttGate(data);
    updateConfigBobbles(data);
    updateSetupGuide(data);
    updateAutoDetectBanner(data);

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

        if (data.venus_os === 'connected') {
            vosDotMod = 've-dot--ok';
            vosText = 'Venus OS: Connected';
        } else if (data.venus_os === 'disconnected') {
            vosDotMod = 've-dot--err';
            vosText = 'Venus OS: Disconnected';
        } else {
            vosDotMod = 've-dot--dim';
            vosText = 'Venus OS: Not Configured';
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

// Track original config values for dirty-checking (Venus only)
var _cfgOriginal = { venus: {} };

var _cfgFields = {
    venus: ['venus-host', 'venus-port', 'venus-portal-id']
};

function _cfgIsDirty(section) {
    var fields = _cfgFields[section];
    if (!fields) return false;
    for (var i = 0; i < fields.length; i++) {
        var el = document.getElementById(fields[i]);
        if (el && el.value !== _cfgOriginal[section][fields[i]]) return true;
    }
    return false;
}

function _cfgUpdateSaveBtn(section) {
    var pair = document.getElementById('btn-pair-venus');
    if (!pair) return;
    var dirty = _cfgIsDirty(section);
    pair.style.display = dirty ? '' : 'none';
    // Per-field dirty highlight
    var fields = _cfgFields[section];
    if (!fields) return;
    for (var i = 0; i < fields.length; i++) {
        var el = document.getElementById(fields[i]);
        if (el) {
            if (el.value !== _cfgOriginal[section][fields[i]]) {
                el.classList.add('ve-input--dirty');
            } else {
                el.classList.remove('ve-input--dirty');
            }
        }
    }
}

function _cfgCancel(section) {
    var fields = _cfgFields[section];
    if (!fields) return;
    for (var i = 0; i < fields.length; i++) {
        var el = document.getElementById(fields[i]);
        if (el) el.value = _cfgOriginal[section][fields[i]];
    }
    _cfgUpdateSaveBtn(section);
}

function _cfgStoreOriginals() {
    for (var section in _cfgFields) {
        var fields = _cfgFields[section];
        for (var i = 0; i < fields.length; i++) {
            var el = document.getElementById(fields[i]);
            if (el) _cfgOriginal[section][fields[i]] = el.value;
        }
    }
}

// Attach input listeners for dirty-checking (Venus fields only)
(function() {
    _cfgFields.venus.forEach(function(fieldId) {
        var el = document.getElementById(fieldId);
        if (el) {
            el.addEventListener('input', function() { _cfgUpdateSaveBtn('venus'); });
        }
    });
})();

async function loadConfig() {
    try {
        var res = await fetch('/api/config');
        var data = await res.json();
        // Populate Venus fields
        document.getElementById('venus-host').value = data.venus.host;
        document.getElementById('venus-port').value = data.venus.port;
        document.getElementById('venus-portal-id').value = data.venus.portal_id;
        _cfgStoreOriginals();
        _cfgUpdateSaveBtn('venus');
        // Load inverter list from same response (avoids second HTTP call)
        loadInverters(data.inverters);
        // Load scanner ports
        fetch('/api/scanner/config').then(function(r) { return r.json(); }).then(function(scanData) {
            var input = document.getElementById('scan-ports-input');
            if (input && scanData.ports) input.value = scanData.ports.join(', ');
        }).catch(function() {});
    } catch (e) {
        console.error('Config load failed:', e);
    }
}

// ===== Inverter List CRUD =====

async function loadInverters(invertersData) {
    var inverters;
    if (invertersData) {
        inverters = invertersData;
    } else {
        try {
            var res = await fetch('/api/inverters');
            var data = await res.json();
            inverters = data.inverters;
        } catch (e) {
            console.error('Inverter list load failed:', e);
            return;
        }
    }

    var container = document.getElementById('inverter-list');
    container.innerHTML = '';

    if (!inverters || inverters.length === 0) {
        _configuredInverters = [];
        container.innerHTML = '<div class="ve-inv-empty"><div class="ve-hint-card">' +
            '<div class="ve-hint-header">' +
            '<svg width="20" height="20" viewBox="0 0 20 20" fill="none">' +
            '<circle cx="10" cy="10" r="9" stroke="currentColor" stroke-width="1.5" fill="none"/>' +
            '<path d="M10 9v5M10 6.5v.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>' +
            '</svg>' +
            '<h3>No Inverter Configured</h3></div>' +
            '<p>Add an inverter manually or use Auto-Discover.</p>' +
            '</div></div>';
        // Auto-scan: only on page navigation, not after mutations
        if (!_scanRunning && !_autoScanDone) {
            _autoScanDone = true;
            triggerScan();
        }
        return;
    }

    inverters.forEach(function(inv) {
        container.appendChild(createInverterRow(inv));
    });

    // Cache for duplicate detection
    _configuredInverters = inverters;
}

function createInverterRow(inv) {
    var row = document.createElement('div');
    row.className = 've-inv-row';
    if (inv.active) row.classList.add('ve-inv-row--active');
    if (!inv.enabled) row.classList.add('ve-inv-row--disabled');
    row.setAttribute('data-id', inv.id);

    var identity = ((inv.manufacturer || '') + ' ' + (inv.model || '')).trim();

    row.innerHTML =
        '<span class="ve-dot" style="background:var(' + (inv.enabled ? '--ve-green' : '--ve-text-dim') + ')"></span>' +
        '<span class="ve-inv-host">' + inv.host + ':' + inv.port + '</span>' +
        '<span class="ve-inv-identity">' + identity + '</span>' +
        '<div class="ve-inv-actions">' +
            '<label class="ve-toggle"><input type="checkbox" ' + (inv.enabled ? 'checked' : '') + '><span class="ve-toggle-track"></span></label>' +
            '<button class="ve-inv-edit" title="Edit"><svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M11.5 1.5l3 3L5 14H2v-3L11.5 1.5z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg></button>' +
            '<button class="ve-inv-delete" title="Delete"><svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M2 4h12M5.33 4V2.67h5.34V4M6 7v5M10 7v5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M3.33 4l.67 9.33h8l.67-9.33" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg></button>' +
        '</div>';

    // Toggle event
    var toggleLabel = row.querySelector('.ve-toggle');
    var toggleInput = row.querySelector('.ve-toggle input');
    toggleLabel.addEventListener('click', function(e) { e.stopPropagation(); });
    toggleInput.addEventListener('change', function() {
        toggleInverter(inv.id, toggleInput.checked);
    });

    // Edit button event
    var editBtn = row.querySelector('.ve-inv-edit');
    editBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        expandEditForm(row, inv);
    });

    // Delete button event
    var deleteBtn = row.querySelector('.ve-inv-delete');
    deleteBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        showDeleteConfirm(row, inv.id);
    });

    // Row click — open edit form
    row.addEventListener('click', function() {
        expandEditForm(row, inv);
    });

    return row;
}

async function toggleInverter(id, enabled) {
    try {
        var res = await fetch('/api/inverters/' + id, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabled })
        });
        var data = await res.json();
        if (data.error) {
            showToast('Toggle failed: ' + data.error, 'error');
            loadInverters();
            return;
        }
        showToast(enabled ? 'Inverter enabled' : 'Inverter disabled', 'success');
        // Prevent auto-scan when disabling the last inverter
        _autoScanDone = true;
        loadInverters();
    } catch (e) {
        showToast('Toggle failed: ' + e.message, 'error');
        loadInverters();
    }
}

function showDeleteConfirm(row, id) {
    var actions = row.querySelector('.ve-inv-actions');
    actions.innerHTML =
        '<span class="ve-inv-confirm-text">Delete?</span>' +
        '<button class="ve-btn ve-btn--sm ve-btn--cancel">No</button>' +
        '<button class="ve-inv-delete-confirm">Yes</button>';

    actions.querySelector('.ve-btn--cancel').addEventListener('click', function(e) {
        e.stopPropagation();
        loadInverters();
    });
    actions.querySelector('.ve-inv-delete-confirm').addEventListener('click', function(e) {
        e.stopPropagation();
        deleteInverter(id);
    });
}

async function deleteInverter(id) {
    try {
        var res = await fetch('/api/inverters/' + id, { method: 'DELETE' });
        var data = await res.json();
        if (data.error) {
            showToast('Delete failed: ' + data.error, 'error');
            loadInverters();
            return;
        }
        showToast('Inverter deleted', 'success');
        // Prevent auto-scan from re-adding the just-deleted inverter
        _autoScanDone = true;
        loadInverters();
    } catch (e) {
        showToast('Delete failed: ' + e.message, 'error');
        loadInverters();
    }
}

function expandEditForm(row, inv) {
    // If this row already has an edit form, close it
    var existing = row.nextElementSibling;
    if (existing && existing.classList.contains('ve-inv-edit-form')) {
        existing.remove();
        return;
    }

    // Close any other open edit forms
    document.querySelectorAll('.ve-inv-edit-form').forEach(function(f) { f.remove(); });

    var form = document.createElement('div');
    form.className = 've-inv-edit-form';
    form.innerHTML =
        '<div class="ve-form-group"><label>Host</label><input type="text" class="ve-input" value="' + inv.host + '"></div>' +
        '<div class="ve-form-group"><label>Port</label><input type="number" class="ve-input" value="' + inv.port + '" min="1" max="65535"></div>' +
        '<div class="ve-form-group"><label>Unit ID</label><input type="number" class="ve-input" value="' + inv.unit_id + '" min="1" max="247"></div>' +
        '<span class="ve-btn-pair">' +
            '<button type="button" class="ve-btn ve-btn--sm ve-btn--cancel">Cancel</button>' +
            '<button type="button" class="ve-btn ve-btn--sm ve-btn--save">Save</button>' +
        '</span>';

    // Prevent row click from triggering on form interactions
    form.addEventListener('click', function(e) { e.stopPropagation(); });

    row.after(form);

    // Animate open
    requestAnimationFrame(function() {
        form.classList.add('ve-inv-edit-form--open');
    });

    var inputs = form.querySelectorAll('.ve-input');
    var cancelBtn = form.querySelector('.ve-btn--cancel');
    var saveBtn = form.querySelector('.ve-btn--save');

    cancelBtn.addEventListener('click', function() {
        form.remove();
    });

    saveBtn.addEventListener('click', async function() {
        var host = inputs[0].value.trim();
        var port = parseInt(inputs[1].value);
        var unitId = parseInt(inputs[2].value);

        if (!host) {
            showToast('Host is required', 'error');
            return;
        }

        try {
            var res = await fetch('/api/inverters/' + inv.id, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ host: host, port: port, unit_id: unitId })
            });
            var data = await res.json();
            if (data.error) {
                showToast('Update failed: ' + data.error, 'error');
                return;
            }
            showToast('Inverter updated', 'success');
            loadInverters();
        } catch (e) {
            showToast('Update failed: ' + e.message, 'error');
        }
    });
}

// Add inverter form logic
document.getElementById('btn-add-inverter').addEventListener('click', function() {
    var form = document.getElementById('inverter-add-form');
    if (form.style.display === 'none') {
        form.style.display = 'block';
        document.getElementById('add-inv-host').focus();
    } else {
        form.style.display = 'none';
    }
});

document.getElementById('btn-add-inv-cancel').addEventListener('click', function() {
    var form = document.getElementById('inverter-add-form');
    form.style.display = 'none';
    document.getElementById('add-inv-host').value = '';
    document.getElementById('add-inv-port').value = '1502';
    document.getElementById('add-inv-unit').value = '1';
});

document.getElementById('btn-add-inv-save').addEventListener('click', async function() {
    var host = document.getElementById('add-inv-host').value.trim();
    var port = parseInt(document.getElementById('add-inv-port').value);
    var unitId = parseInt(document.getElementById('add-inv-unit').value);

    if (!host) {
        showToast('Host is required', 'error');
        return;
    }

    try {
        var res = await fetch('/api/inverters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ host: host, port: port, unit_id: unitId })
        });
        var data = await res.json();
        if (res.status === 201 || data.id) {
            showToast('Inverter added', 'success');
            document.getElementById('inverter-add-form').style.display = 'none';
            document.getElementById('add-inv-host').value = '';
            document.getElementById('add-inv-port').value = '1502';
            document.getElementById('add-inv-unit').value = '1';
            loadInverters();
        } else {
            showToast('Add failed: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (e) {
        showToast('Add failed: ' + e.message, 'error');
    }
});

// ===== Save Config (Venus only) =====

async function saveConfigSection(section) {
    var btn = document.getElementById('btn-save-venus');
    var origText = btn.textContent;
    btn.textContent = 'Saving...';
    btn.disabled = true;

    var payload = {
        venus: {
            host: document.getElementById('venus-host').value.trim(),
            port: parseInt(document.getElementById('venus-port').value) || 1883,
            portal_id: document.getElementById('venus-portal-id').value.trim()
        }
    };

    try {
        var res = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        var data = await res.json();
        if (data.success) {
            showToast('Configuration saved. Reconnecting...', 'success');
            _cfgStoreOriginals();
            _cfgUpdateSaveBtn('venus');
        } else {
            showToast('Save failed: ' + data.error, 'error');
        }
    } catch (err) {
        showToast('Save failed: ' + err.message, 'error');
    } finally {
        btn.textContent = origText;
        btn.disabled = false;
    }
}

document.getElementById('btn-save-venus').addEventListener('click', function() { saveConfigSection('venus'); });
document.getElementById('btn-cancel-venus').addEventListener('click', function() { _cfgCancel('venus'); });

// Prevent form submit (no global save button anymore)
document.getElementById('config-form').addEventListener('submit', function(e) { e.preventDefault(); });

// ===== Discovery / Scan =====

function handleScanProgress(data) {
    var area = document.getElementById('scan-area');
    area.style.display = '';
    var fill = document.getElementById('scan-bar-fill');
    var statusText = document.getElementById('scan-status-text');
    var progress = document.getElementById('scan-progress');
    progress.style.display = '';

    var pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
    fill.style.width = pct + '%';

    if (data.phase === 'probe') {
        statusText.textContent = 'Scanning network (' + data.current + '/' + data.total + ')...';
    } else if (data.phase === 'verify') {
        statusText.textContent = 'Verifying SunSpec (' + data.current + '/' + data.total + ')...';
    }
}

function handleScanComplete(data) {
    _scanRunning = false;
    setScanButtonState(false);

    var progress = document.getElementById('scan-progress');
    progress.style.display = 'none';
    var resultsDiv = document.getElementById('scan-results');
    resultsDiv.innerHTML = '';

    var devices = data.devices || [];

    if (devices.length === 0) {
        resultsDiv.innerHTML =
            '<div class="ve-hint-card ve-scan-hint">' +
            '<div class="ve-hint-header">Keine Inverter gefunden</div>' +
            '<div class="ve-hint-subtext">Pruefe: Sind die Geraete eingeschaltet? Ist Modbus TCP aktiviert? Stimmen die Ports?</div>' +
            '</div>';
        return;
    }

    // Auto-scan single result: auto-add
    if (_autoScanDone && devices.length === 1 && !isAlreadyConfigured(devices[0])) {
        addDiscoveredInverters([devices[0]]);
        return;
    }

    // Build result list
    var header = document.createElement('div');
    header.className = 've-scan-results-header';
    header.innerHTML = '<span>' + devices.length + ' Inverter gefunden</span>' +
        '<button type="button" class="ve-btn ve-btn--sm ve-btn--save" id="btn-scan-add-all">Alle uebernehmen</button>';
    resultsDiv.appendChild(header);

    var hasNewDevices = false;
    devices.forEach(function(device) {
        var configured = isAlreadyConfigured(device);
        if (!configured) hasNewDevices = true;
        resultsDiv.appendChild(createScanResultRow(device, configured));
    });

    // Wire Add All button
    document.getElementById('btn-scan-add-all').addEventListener('click', function() {
        var checked = [];
        resultsDiv.querySelectorAll('.ve-scan-result').forEach(function(row) {
            if (row._device && !row.classList.contains('ve-scan-result--configured')) {
                var cb = row.querySelector('input[type="checkbox"]');
                if (cb && cb.checked) checked.push(row._device);
            }
        });
        if (checked.length > 0) addDiscoveredInverters(checked);
    });

    if (!hasNewDevices) {
        header.querySelector('#btn-scan-add-all').style.display = 'none';
    }
}

function handleScanError(data) {
    _scanRunning = false;
    setScanButtonState(false);
    var progress = document.getElementById('scan-progress');
    progress.style.display = 'none';
    showToast('Scan fehlgeschlagen: ' + (data.error || 'Unbekannter Fehler'), 'error');
}

function createScanResultRow(device, isConfigured) {
    var row = document.createElement('div');
    row.className = 've-scan-result';
    if (isConfigured) row.classList.add('ve-scan-result--configured');

    var identity = ((device.manufacturer || '') + ' ' + (device.model || '')).trim() || 'Unknown';
    var hostPort = device.ip + ':' + device.port;

    if (isConfigured) {
        row.innerHTML =
            '<span class="ve-scan-result-configured">Bereits konfiguriert</span>' +
            '<span class="ve-scan-result-host">' + hostPort + '</span>' +
            '<span class="ve-scan-result-identity">' + identity + '</span>' +
            '<span class="ve-scan-result-unit">Unit ' + device.unit_id + '</span>';
    } else {
        row.innerHTML =
            '<label class="ve-scan-result-check"><input type="checkbox" checked></label>' +
            '<span class="ve-scan-result-host">' + hostPort + '</span>' +
            '<span class="ve-scan-result-identity">' + identity + '</span>' +
            '<span class="ve-scan-result-unit">Unit ' + device.unit_id + '</span>';
    }
    row._device = device;
    return row;
}

function isAlreadyConfigured(device) {
    return _configuredInverters.some(function(inv) {
        return inv.host === device.ip &&
               inv.port === device.port &&
               inv.unit_id === device.unit_id;
    });
}

async function addDiscoveredInverters(devices) {
    var added = 0;
    for (var i = 0; i < devices.length; i++) {
        var d = devices[i];
        try {
            var res = await fetch('/api/inverters', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    host: d.ip, port: d.port, unit_id: d.unit_id,
                    manufacturer: d.manufacturer || '', model: d.model || '',
                    serial: d.serial_number || '', firmware_version: d.firmware_version || '',
                    enabled: true
                })
            });
            if (res.status === 201) added++;
        } catch (e) {
            console.error('Failed to add inverter:', d.ip, e);
        }
    }
    if (added > 0) {
        showToast(added === 1 ? 'Inverter hinzugefuegt' : added + ' Inverter hinzugefuegt', 'success');
        document.getElementById('scan-results').innerHTML = '';
        document.getElementById('scan-area').style.display = 'none';
        loadInverters();
    }
}

async function triggerScan() {
    if (_scanRunning) return;
    _scanRunning = true;
    setScanButtonState(true);

    // Clear previous results
    document.getElementById('scan-results').innerHTML = '';
    document.getElementById('scan-bar-fill').style.width = '0%';
    document.getElementById('scan-area').style.display = '';
    document.getElementById('scan-progress').style.display = '';
    document.getElementById('scan-status-text').textContent = 'Starting scan...';

    // Read ports from input
    var portsInput = document.getElementById('scan-ports-input');
    var portsStr = portsInput ? portsInput.value : '502, 1502';
    var ports = portsStr.split(',').map(function(p) { return parseInt(p.trim(), 10); }).filter(function(p) { return !isNaN(p) && p > 0 && p <= 65535; });
    if (ports.length === 0) ports = [502, 1502];

    try {
        var res = await fetch('/api/scanner/discover', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ports: ports })
        });
        if (res.status === 409) {
            showToast('Scan laeuft bereits', 'warning');
            _scanRunning = false;
            setScanButtonState(false);
        }
    } catch (e) {
        showToast('Scan konnte nicht gestartet werden: ' + e.message, 'error');
        _scanRunning = false;
        setScanButtonState(false);
    }
}

function setScanButtonState(scanning) {
    var btn = document.getElementById('btn-discover-inverter');
    if (!btn) return;
    if (scanning) {
        btn.classList.add('ve-scanning');
        btn.disabled = true;
        btn.title = 'Scan laeuft...';
    } else {
        btn.classList.remove('ve-scanning');
        btn.disabled = false;
        btn.title = 'Auto-Discover';
    }
}

// Wire discover button
document.getElementById('btn-discover-inverter').addEventListener('click', function() {
    _autoScanDone = false;
    triggerScan();
});

// Save scan ports on blur
document.getElementById('scan-ports-input').addEventListener('blur', function() {
    var ports = this.value.split(',').map(function(p) { return parseInt(p.trim(), 10); }).filter(function(p) { return !isNaN(p) && p > 0 && p <= 65535; });
    if (ports.length === 0) return;
    fetch('/api/scanner/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ports: ports })
    });
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
            var spinner = document.getElementById('register-spinner');
            if (spinner) spinner.style.display = 'none';
        } else {
            updateRegisterValues(models);
        }
    } catch (e) {
        console.error('Register poll failed:', e);
    }
}

// SunSpec human-readable decode map
// Sources: SunSpec Model 103 (inverter), 120 (nameplate), 123 (controls)
// Spec: https://sunspec.org/sunspec-modbus-specifications/
var SUNSPEC_DECODE = {
    // Model 103 — Three-Phase Inverter
    40071: { unit: 'A', sf_addr: 40075, label: 'Total AC current' },
    40072: { unit: 'A', sf_addr: 40075, label: 'Phase L1 current' },
    40073: { unit: 'A', sf_addr: 40075, label: 'Phase L2 current' },
    40074: { unit: 'A', sf_addr: 40075, label: 'Phase L3 current' },
    40075: { is_sf: true },
    40076: { unit: 'V', sf_addr: 40082, label: 'Line voltage L1-L2' },
    40077: { unit: 'V', sf_addr: 40082, label: 'Line voltage L2-L3' },
    40078: { unit: 'V', sf_addr: 40082, label: 'Line voltage L3-L1' },
    40079: { unit: 'V', sf_addr: 40082, label: 'Phase voltage L1-N' },
    40080: { unit: 'V', sf_addr: 40082, label: 'Phase voltage L2-N' },
    40081: { unit: 'V', sf_addr: 40082, label: 'Phase voltage L3-N' },
    40082: { is_sf: true },
    40083: { unit: 'W', sf_addr: 40084, label: 'AC power output', signed: true },
    40084: { is_sf: true },
    40085: { unit: 'Hz', sf_addr: 40086, label: 'Grid frequency' },
    40086: { is_sf: true },
    40087: { unit: 'VA', sf_addr: 40088, label: 'Apparent power', signed: true },
    40088: { is_sf: true },
    40089: { unit: 'var', sf_addr: 40090, label: 'Reactive power', signed: true },
    40090: { is_sf: true },
    40091: { unit: '%', sf_addr: 40092, label: 'Power factor', signed: true },
    40092: { is_sf: true },
    40093: { unit: 'Wh', sf_addr: 40095, label: 'Lifetime energy', size: 2 },
    40095: { is_sf: true },
    40096: { unit: 'A', sf_addr: 40097, label: 'DC current' },
    40097: { is_sf: true },
    40098: { unit: 'V', sf_addr: 40099, label: 'DC voltage' },
    40099: { is_sf: true },
    40100: { unit: 'W', sf_addr: 40101, label: 'DC power', signed: true },
    40101: { is_sf: true },
    40102: { unit: '°C', sf_addr: 40106, label: 'Cabinet temperature', signed: true },
    40103: { unit: '°C', sf_addr: 40106, label: 'Heatsink temperature', signed: true },
    40104: { unit: '°C', sf_addr: 40106, label: 'Transformer temperature', signed: true },
    40105: { unit: '°C', sf_addr: 40106, label: 'Other temperature', signed: true },
    40106: { is_sf: true },
    40107: { enum: { 1: 'Off', 2: 'Sleeping', 3: 'Starting', 4: 'Producing (MPPT)', 5: 'Throttled', 6: 'Shutting down', 7: 'Fault', 8: 'Standby' }, label: 'Operating state' },
    40108: { label: 'Vendor-specific status code' },
    // Model 120 — Nameplate
    40123: { enum: { 4: 'PV', 82: 'Storage', 83: 'PV+Storage' }, label: 'DER type' },
    40124: { unit: 'W', sf_addr: 40125, label: 'Max power rating' },
    40125: { is_sf: true },
    40126: { unit: 'VA', sf_addr: 40127, label: 'Max apparent power' },
    40127: { is_sf: true },
    40133: { unit: 'A', sf_addr: 40134, label: 'Max current rating' },
    40134: { is_sf: true },
    // Model 123 — Controls
    40153: { enum: { 0: 'Disconnect', 1: 'Connect' }, label: 'Connection control' },
    40154: { unit: '%', sf_fixed: -2, label: 'Power limit setpoint' },
    40158: { enum: { 0: 'Disabled', 1: 'Enabled' }, label: 'Power limit enable' },
};

// SunSpec model documentation links (GitHub model definitions)
var SUNSPEC_DOCS = {
    'Common (Model 1)': 'https://github.com/sunspec/models/blob/master/json/model_1.json',
    'Inverter (Model 103)': 'https://github.com/sunspec/models/blob/master/json/model_103.json',
    'Nameplate (Model 120)': 'https://github.com/sunspec/models/blob/master/json/model_120.json',
    'Controls (Model 123)': 'https://github.com/sunspec/models/blob/master/json/model_123.json',
};

// Cache for scale factor values (populated on first build, updated on poll)
var sfCache = {};

function decodeRegisterValue(addr, rawValue, allFields) {
    var meta = SUNSPEC_DECODE[addr];
    if (!meta || rawValue === null || rawValue === undefined) return '';
    if (meta.is_sf) return 'Scale Factor';

    // Enum lookup
    if (meta.enum) {
        var label = meta.enum[rawValue];
        return label ? label : 'Unknown (' + rawValue + ')';
    }

    // Scale factor decode
    if (meta.unit) {
        // SunSpec sentinel values: 0x7FFF/0x8000 (int16), 0xFFFF (uint16) = not implemented
        if (rawValue === 32768 || rawValue === 32767 || rawValue === 65535) return 'N/A';

        var sf = 0;
        if (meta.sf_fixed !== undefined) {
            sf = meta.sf_fixed;
        } else if (meta.sf_addr) {
            // Look up SF from cached values
            sf = sfCache[meta.sf_addr];
            if (sf === undefined || sf === null) return rawValue + ' ' + meta.unit + ' (raw)';
            // SF is stored as int16 (signed)
            if (sf > 32767) sf = sf - 65536;
        }
        // Handle large values that may be comma-formatted strings from API
        var numValue = (typeof rawValue === 'string') ? parseInt(rawValue.replace(/,/g, ''), 10) : rawValue;
        if (isNaN(numValue)) return '';
        var decoded = numValue * Math.pow(10, sf);
        // Format nicely — large values get k/M suffix
        var decimals = sf < 0 ? Math.abs(sf) : 0;
        if (Math.abs(decoded) >= 1000000) {
            return (decoded / 1000000).toFixed(1) + ' M' + meta.unit;
        } else if (Math.abs(decoded) >= 10000) {
            return (decoded / 1000).toFixed(1) + ' k' + meta.unit;
        }
        return decoded.toFixed(decimals) + ' ' + meta.unit;
    }

    return '';
}

function buildSfCache(models) {
    models.forEach(function(model) {
        model.fields.forEach(function(field) {
            var meta = SUNSPEC_DECODE[field.addr];
            if (meta && meta.is_sf && field.fronius_value !== null) {
                sfCache[field.addr] = field.fronius_value;
            }
        });
    });
}

function buildRegisterViewer(container, models) {
    // Build SF cache first so decode works
    buildSfCache(models);

    models.forEach((model) => {
        const group = document.createElement('div');
        group.className = 've-model-group';

        const header = document.createElement('div');
        header.className = 've-model-header';
        header.innerHTML = '<span>' + model.name + '</span><span>&#9660;</span>';
        header.addEventListener('click', (e) => {
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
        headerRow.innerHTML = '<span>Addr</span><span>Name</span><span class="ve-reg-se-value">SE30K Source</span><span class="ve-reg-fronius-value">Fronius Target</span><span class="ve-reg-decoded">Decoded</span>';
        fields.appendChild(headerRow);

        model.fields.forEach(field => {
            const row = document.createElement('div');
            row.className = 've-reg-row';
            row.id = 'reg-' + field.addr;

            const seVal = formatValue(field.se_value);
            const frVal = formatValue(field.fronius_value);
            const seClass = field.se_value === null ? 've-reg-se-value null-value' : 've-reg-se-value';
            const decoded = decodeRegisterValue(field.addr, field.fronius_value, model.fields);
            const meta = SUNSPEC_DECODE[field.addr];
            var tooltip = meta && meta.label ? ' title="' + meta.label + '"' : '';

            // Mark rows as empty when both values are 0/null and no meaningful decode
            var isEmpty = (field.se_value === null || field.se_value === 0) &&
                          (field.fronius_value === null || field.fronius_value === 0) &&
                          (!decoded || decoded === '0 W' || decoded === '0 A' || decoded === '0 VA' ||
                           decoded === '0 var' || decoded === '0 %' || decoded === '0.00 A' ||
                           decoded === '0.0 W' || decoded === '0 V' || decoded === '' ||
                           decoded === 'N/A' || decoded === '0.00 %');
            if (isEmpty) row.classList.add('ve-empty');

            row.innerHTML =
                '<span class="ve-reg-addr">' + field.addr + '</span>' +
                '<span class="ve-reg-name"' + tooltip + '>' + field.name + '</span>' +
                '<span class="' + seClass + '" id="se-val-' + field.addr + '">' + seVal + '</span>' +
                '<span class="ve-reg-fronius-value" id="fr-val-' + field.addr + '">' + frVal + '</span>' +
                '<span class="ve-reg-decoded" id="dec-val-' + field.addr + '">' + decoded + '</span>';
            fields.appendChild(row);
            previousRegValues[field.addr] = { se: field.se_value, fr: field.fronius_value };
        });

        group.appendChild(fields);
        container.appendChild(group);
    });
}

function updateRegisterValues(models) {
    // Refresh SF cache
    buildSfCache(models);

    models.forEach(model => {
        model.fields.forEach(field => {
            const seEl = document.getElementById('se-val-' + field.addr);
            const frEl = document.getElementById('fr-val-' + field.addr);
            const decEl = document.getElementById('dec-val-' + field.addr);
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
            if (decEl) {
                var newDec = decodeRegisterValue(field.addr, field.fronius_value, model.fields);
                if (decEl.textContent !== newDec) {
                    decEl.textContent = newDec;
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
    var timerEl = document.getElementById('lock-timer');

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

    // ESS availability check
    var vs = snapshot.venus_settings;
    var essDown = snapshot.venus_mqtt_connected && vs && !vs.ess_available;
    var toggleContainer = document.querySelector('.ve-gauge-venus-toggle');

    if (essDown) {
        // ESS unavailable: disable toggle, show warning overlay
        toggle.disabled = true;
        if (toggleContainer) toggleContainer.classList.add('ess-gated');
    } else {
        toggle.disabled = false;
        if (toggleContainer) toggleContainer.classList.remove('ess-gated');

        // Venus OS toggle: checked = allowed, unchecked = blocked (inverted from lock)
        // Skip update if user just changed it (debounce)
        var now = Date.now();
        if ((now - (toggle._userChangedAt || 0)) > 8000) {
            toggle.checked = !venus.is_locked;
        }
    }

    // Countdown (only for timed locks, not permanent)
    if (venus.is_locked && venus.lock_remaining_s != null) {
        venusLockRemaining = venus.lock_remaining_s;
        venusLockSnapshotTs = Date.now() / 1000;
        updateCountdownDisplay();
        startCountdownInterval();
    } else {
        venusLockRemaining = null;
        stopCountdownInterval();
        if (timerEl) timerEl.textContent = '';
    }
}

function updateCountdownDisplay() {
    var el = document.getElementById('lock-timer');
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
