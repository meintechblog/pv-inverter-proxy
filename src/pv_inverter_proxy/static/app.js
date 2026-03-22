/* PV-Inverter-Proxy - Frontend Application
   Device-centric navigation, WebSocket live dashboard, per-device pages */

var POLL_INTERVAL = 10000;
var previousRegValues = {};
var ws = null;
var sparklineData = [];
var CAPACITY_W = 800;
var GAUGE_ARC_LENGTH = 251.3;
var TEMP_WARNING_C = 75;
var venusLockRemaining = null;
var venusLockSnapshotTs = null;
var venusCountdownInterval = null;

// ===== Device-centric state =====
var _devices = [];
var _activeDeviceId = null;
var _activeDeviceTab = null;
var _activeDeviceContainer = null;
var _activeDeviceType = null;
var _lastVirtualSnapshot = null;
var _regPollInterval = null;

// ===== MQTT Publisher State =====
var _mqttPubConnected = false;
var _mqttPubStats = null;
var _lastDeviceList = [];

// ===== Discovery / Scan State =====
var _scanRunning = false;
var _autoScanDone = false;
var _configuredInverters = [];

// ===== Animation Guards =====
var prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
var entranceAnimated = false;

// ===== Hash Router =====

function _firstInverterId() {
    for (var i = 0; i < _devices.length; i++) {
        if (_devices[i].type !== 'venus' && _devices[i].type !== 'virtual') return _devices[i].id;
    }
    return 'virtual';
}

function parseRoute() {
    var hash = (window.location.hash || '').replace('#', '');
    var parts = hash.split('/');
    if (parts[0] === 'device' && parts.length >= 3) {
        return { type: 'device', id: parts[1], tab: parts[2] };
    }
    // Legacy redirects
    if (hash === 'dashboard' || hash === '') return { type: 'device', id: 'virtual', tab: 'dashboard' };
    if (hash === 'config') return { type: 'device', id: _firstInverterId(), tab: 'config' };
    if (hash === 'registers') return { type: 'device', id: _firstInverterId(), tab: 'registers' };
    return { type: 'device', id: 'virtual', tab: 'dashboard' };
}

function navigateTo(deviceId, tab) {
    window.location.hash = 'device/' + deviceId + '/' + (tab || 'dashboard');
}

window.addEventListener('hashchange', function() {
    var route = parseRoute();
    showDevicePage(route.id, route.tab);
});

function esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function gaugeColor(pct) {
    return pct < 0.5 ? 'var(--ve-green)' : pct < 0.8 ? 'var(--ve-orange)' : 'var(--ve-red)';
}

function dotColorForState(state) {
    if (state === 'connected') return '--ve-green';
    if (state === 'reconnecting') return '--ve-orange';
    if (state === 'disconnected') return '--ve-red';
    return '--ve-text-dim';
}

// ===== Sidebar Rendering =====

function renderSidebar(devices) {
    if (devices) _devices = devices;
    var container = document.getElementById('device-sidebar');
    if (!container) return;
    container.innerHTML = '';

    var inverters = [];
    var venusDevice = null;
    var virtualDevice = null;
    var mqttPubDevice = null;

    for (var i = 0; i < _devices.length; i++) {
        var d = _devices[i];
        if (d.type === 'venus') venusDevice = d;
        else if (d.type === 'virtual') virtualDevice = d;
        else if (d.type === 'mqtt_pub') mqttPubDevice = d;
        else inverters.push(d);
    }

    // INVERTERS group
    if (inverters.length > 0) {
        container.appendChild(createSidebarGroup('INVERTERS', inverters));
    }

    // VENUS OS group
    if (venusDevice) {
        container.appendChild(createSidebarGroup('VENUS OS', [venusDevice]));
    }

    // VIRTUAL PV group (always visible)
    if (virtualDevice) {
        container.appendChild(createSidebarGroup('VIRTUAL PV', [virtualDevice]));
    }

    // MQTT PUBLISH group
    if (mqttPubDevice) {
        container.appendChild(createSidebarGroup('MQTT PUBLISH', [mqttPubDevice]));
    }

    // Update active highlight
    highlightActiveSidebar();
}

function createSidebarGroup(label, devices) {
    var group = document.createElement('div');
    group.className = 've-sidebar-group';

    var header = document.createElement('div');
    header.className = 've-sidebar-group-header';
    header.innerHTML = '<span>' + label + '</span><span class="ve-chevron">&#9660;</span>';
    header.addEventListener('click', function() {
        var items = group.querySelector('.ve-sidebar-group-items');
        var chevron = header.querySelector('.ve-chevron');
        if (items.classList.contains('ve-sidebar-group-items--collapsed')) {
            items.classList.remove('ve-sidebar-group-items--collapsed');
            chevron.classList.remove('ve-chevron--collapsed');
        } else {
            items.classList.add('ve-sidebar-group-items--collapsed');
            chevron.classList.add('ve-chevron--collapsed');
        }
    });
    group.appendChild(header);

    var itemsContainer = document.createElement('div');
    itemsContainer.className = 've-sidebar-group-items';

    for (var i = 0; i < devices.length; i++) {
        itemsContainer.appendChild(createSidebarDevice(devices[i]));
    }

    group.appendChild(itemsContainer);
    return group;
}

function createSidebarDevice(device) {
    var entry = document.createElement('a');
    entry.className = 've-sidebar-device';
    entry.setAttribute('data-device-id', device.id);

    if (!device.enabled && device.type !== 'virtual') {
        entry.classList.add('ve-sidebar-device--disabled');
    }

    var dotColor = dotColorForState(device.connection_state);

    var powerStr = '';
    if (device.power_w != null && device.type !== 'venus') {
        powerStr = formatW(device.power_w);
    } else if (device.type === 'venus') {
        powerStr = device.connection_state === 'connected' ? 'Connected' : '';
    }

    entry.innerHTML =
        '<span class="ve-dot" style="background:var(' + dotColor + ')"></span>' +
        '<span class="ve-sidebar-device-name">' + esc(device.name || device.id) + '</span>' +
        '<span class="ve-sidebar-device-power">' + powerStr + '</span>';

    if (!device.enabled && device.type !== 'virtual') {
        entry.innerHTML += '<span class="ve-sidebar-disabled-label">Disabled</span>';
    }

    entry.addEventListener('click', function(e) {
        e.preventDefault();
        navigateTo(device.id, 'dashboard');
        // Close mobile sidebar
        document.getElementById('sidebar').classList.remove('open');
        var overlay = document.getElementById('sidebar-overlay');
        if (overlay) overlay.classList.remove('active');
    });

    return entry;
}

function highlightActiveSidebar() {
    var entries = document.querySelectorAll('.ve-sidebar-device');
    for (var i = 0; i < entries.length; i++) {
        if (entries[i].getAttribute('data-device-id') === _activeDeviceId) {
            entries[i].classList.add('ve-sidebar-device--active');
        } else {
            entries[i].classList.remove('ve-sidebar-device--active');
        }
    }
}

// ===== Page Dispatcher =====

function showDevicePage(deviceId, tab) {
    if (_regPollInterval) { clearInterval(_regPollInterval); _regPollInterval = null; }
    _activeDeviceId = deviceId;
    _activeDeviceTab = tab || 'dashboard';
    _activeDeviceContainer = null;

    var content = document.getElementById('device-content');
    if (!content) return;
    content.innerHTML = '';

    // Find device info
    var device = null;
    for (var i = 0; i < _devices.length; i++) {
        if (_devices[i].id === deviceId) { device = _devices[i]; break; }
    }

    highlightActiveSidebar();

    if (deviceId === 'mqtt_pub' || (device && device.type === 'mqtt_pub')) {
        _activeDeviceType = 'mqtt_pub';
        renderMqttPubPage(content);
    } else if (deviceId === 'venus' || (device && device.type === 'venus')) {
        _activeDeviceType = 'venus';
        renderVenusPage(content);
    } else if (deviceId === 'virtual' || (device && device.type === 'virtual')) {
        _activeDeviceType = 'virtual';
        renderVirtualPVPage(content);
    } else {
        _activeDeviceType = device ? device.type : 'solaredge';
        renderInverterPage(content, deviceId, _activeDeviceType, tab);
    }
}

// ===== Inverter Page =====

function renderInverterPage(content, deviceId, deviceType, tab) {
    tab = tab || 'dashboard';

    // Sub-tabs
    var tabs = document.createElement('div');
    tabs.className = 've-device-tabs';
    var tabNames = ['Dashboard', 'Registers', 'Config'];
    var tabKeys = ['dashboard', 'registers', 'config'];
    for (var i = 0; i < tabNames.length; i++) {
        var btn = document.createElement('button');
        btn.className = 've-device-tab' + (tabKeys[i] === tab ? ' ve-device-tab--active' : '');
        btn.textContent = tabNames[i];
        btn.setAttribute('data-tab', tabKeys[i]);
        btn.addEventListener('click', (function(key) {
            return function() {
                navigateTo(deviceId, key);
            };
        })(tabKeys[i]));
        tabs.appendChild(btn);
    }
    content.appendChild(tabs);

    // Tab content container
    var tabContent = document.createElement('div');
    tabContent.className = 've-device-tab-content';
    content.appendChild(tabContent);
    _activeDeviceContainer = tabContent;

    if (tab === 'dashboard') {
        renderInverterDashboard(tabContent, deviceId, deviceType);
    } else if (tab === 'registers') {
        renderInverterRegisters(tabContent, deviceId);
    } else if (tab === 'config') {
        renderInverterConfig(tabContent, deviceId);
    }
}

// ===== Hamburger Toggle (Mobile) =====

document.getElementById('hamburger').addEventListener('click', function() {
    document.getElementById('sidebar').classList.toggle('open');
    var overlay = document.getElementById('sidebar-overlay');
    if (overlay) overlay.classList.toggle('active');
});

var sidebarOverlay = document.getElementById('sidebar-overlay');
if (sidebarOverlay) {
    sidebarOverlay.addEventListener('click', function() {
        document.getElementById('sidebar').classList.remove('open');
        sidebarOverlay.classList.remove('active');
    });
}

// ===== WebSocket Connection =====

function connectWebSocket() {
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(protocol + '//' + location.host + '/ws');
    var reconnectDelay = 1000;

    ws.onopen = function() {
        reconnectDelay = 1000;
    };

    ws.onmessage = function(event) {
        try {
            var msg = JSON.parse(event.data);
            if (msg.type === 'snapshot') handleSnapshot(msg.data);
            if (msg.type === 'device_snapshot') handleDeviceSnapshot(msg);
            if (msg.type === 'virtual_snapshot') handleVirtualSnapshot(msg.data);
            if (msg.type === 'device_list') {
                _lastDeviceList = msg.data.devices || [];
                // Extract mqtt_pub connection state + stats from device list
                for (var di = 0; di < _lastDeviceList.length; di++) {
                    if (_lastDeviceList[di].type === 'mqtt_pub') {
                        _mqttPubConnected = _lastDeviceList[di].connection_state === 'connected';
                        _mqttPubStats = _lastDeviceList[di].stats || null;
                        break;
                    }
                }
                renderSidebar(msg.data.devices);
                updateMqttPubStatusDot();
                updateMqttPubStats();
                renderMqttTopicPreview();
            }
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

// ===== Device Snapshot WS Handler =====

function handleDeviceSnapshot(msg) {
    var deviceId = msg.device_id;
    var data = msg.data;

    // Update sidebar power and dot
    updateSidebarPower(deviceId, data);

    // If this device's dashboard is active, update it
    if (deviceId === _activeDeviceId && _activeDeviceContainer && _activeDeviceTab === 'dashboard') {
        updateActiveDeviceDashboard(data);
    }
}

function handleVirtualSnapshot(data) {
    _lastVirtualSnapshot = data;

    // Update sidebar power for virtual
    var entry = document.querySelector('.ve-sidebar-device[data-device-id="virtual"]');
    if (entry) {
        var pwrEl = entry.querySelector('.ve-sidebar-device-power');
        if (pwrEl && data.total_power_w != null) {
            pwrEl.textContent = formatW(data.total_power_w);
        }
    }

    // If virtual page is showing, update it
    if (_activeDeviceId === 'virtual' && _activeDeviceContainer) {
        updateVirtualPVPage(data);
    }
}

function updateSidebarPower(deviceId, data) {
    var entry = document.querySelector('.ve-sidebar-device[data-device-id="' + deviceId + '"]');
    if (!entry) return;

    // Update power
    var pwrEl = entry.querySelector('.ve-sidebar-device-power');
    if (pwrEl) {
        var inv = data.inverter || data;
        var pw = inv.ac_power_w || data.power_w;
        if (pw != null) {
            pwrEl.textContent = formatW(pw);
        }
    }

    var dot = entry.querySelector('.ve-dot');
    if (dot) {
        var connState = data.connection ? data.connection.state : data.connection_state;
        dot.style.background = 'var(' + dotColorForState(connState) + ')';
    }
}

// ===== Inverter Dashboard Renderer =====

function renderInverterDashboard(container, deviceId, deviceType) {
    container.innerHTML =
        '<div class="ve-spinner-wrap"><div class="ve-spinner"></div><span class="ve-spinner-label">Loading device data...</span></div>';

    fetch('/api/devices/' + deviceId + '/snapshot')
        .then(function(res) { return res.json(); })
        .then(function(data) {
            container.innerHTML = '';
            buildInverterDashboard(container, data, deviceType);
        })
        .catch(function(err) {
            container.innerHTML = '<div class="ve-hint-card"><div class="ve-hint-header">Failed to load device data</div><p class="ve-hint-subtext">' + err.message + '</p></div>';
        });
}

function buildInverterDashboard(container, data, deviceType) {
    var inv = data.inverter || {};

    // Check disabled state
    if (data.enabled === false) {
        container.style.position = 'relative';
        var overlay = document.createElement('div');
        overlay.className = 've-device-disabled-overlay';
        overlay.textContent = 'Device deaktiviert';
        container.appendChild(overlay);
    }

    // Row 1: Gauge + Type-specific data
    var topRow = document.createElement('div');
    topRow.className = 've-dashboard-top';

    // Gauge card
    var gaugeCard = document.createElement('div');
    gaugeCard.className = 've-card ve-gauge-card';
    var ratedW = data.rated_power_w || CAPACITY_W;
    var acPower = inv.ac_power_w || 0;
    var pct = Math.min(acPower / ratedW, 1.0);
    var arcLength = GAUGE_ARC_LENGTH;
    var offset = arcLength * (1 - pct);
    var gc = gaugeColor(pct);

    gaugeCard.innerHTML =
        '<h2 class="ve-card-title">Power Output</h2>' +
        '<svg viewBox="0 0 200 130" class="ve-gauge-svg">' +
        '  <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="var(--ve-border)" stroke-width="12" stroke-linecap="round"/>' +
        '  <path class="ve-gauge-fill" d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="' + gc + '" stroke-width="12" stroke-linecap="round" stroke-dasharray="' + arcLength + '" stroke-dashoffset="' + offset + '"/>' +
        '  <text x="100" y="76" text-anchor="middle" fill="var(--ve-text)" font-size="32" font-weight="700" class="ve-gauge-value-text">' + formatW(acPower) + '</text>' +
        '  <text x="100" y="94" text-anchor="middle" fill="var(--ve-text-dim)" font-size="11">' + formatW(ratedW) + ' max</text>' +
        '  <text x="100" y="122" text-anchor="middle" fill="var(--ve-text-dim)" font-size="11" class="ve-gauge-status-text">' + esc(data.display_name || data.inverter_name || '--') + '</text>' +
        '</svg>';
    topRow.appendChild(gaugeCard);

    // Type-specific card
    if (deviceType === 'opendtu') {
        topRow.appendChild(buildDCChannelCard(data));
    } else {
        topRow.appendChild(buildPhaseCard(data));
    }
    container.appendChild(topRow);

    // Row 2: Connection + Performance
    var row2 = document.createElement('div');
    row2.className = 've-dashboard-info-row';

    // Connection card
    var connCard = document.createElement('div');
    connCard.className = 've-card';
    var connState = data.connection ? data.connection.state : 'unknown';
    var connDotClass = connState === 'connected' ? 've-dot--ok' : connState === 'reconnecting' ? 've-dot--warn' : connState === 'night_mode' ? 've-dot--dim' : 've-dot--err';
    connCard.innerHTML =
        '<h2 class="ve-card-title">Connection</h2>' +
        '<div class="ve-status-row"><span class="ve-dot ' + connDotClass + '"></span><span>Inverter: ' + (connState === 'night_mode' ? 'sleeping' : connState) + '</span></div>';
    row2.appendChild(connCard);

    // Performance card
    var perfCard = document.createElement('div');
    perfCard.className = 've-card';
    perfCard.innerHTML =
        '<h2 class="ve-card-title">Today\'s Performance</h2>' +
        '<div class="ve-grid">' +
        '  <div><label>Energy</label><span class="ve-live-value ve-daily-energy">' + ((inv.daily_energy_wh || 0) / 1000).toFixed(1) + ' kWh</span></div>' +
        '  <div><label>Peak Power</label><span class="ve-live-value ve-peak-power">' + (inv.peak_power_w != null ? formatW(inv.peak_power_w) : '--') + '</span></div>' +
        '  <div><label>Status</label><span class="ve-live-value ve-inv-status">' + (inv.status || '--') + '</span></div>' +
        '  <div><label>Heatsink</label><span class="ve-live-value ve-inv-temp">' + (inv.temperature_sink_c != null ? inv.temperature_sink_c.toFixed(1) + ' \u00B0C' : '--') + '</span></div>' +
        '</div>';
    row2.appendChild(perfCard);
    container.appendChild(row2);
}

function buildPhaseCard(data) {
    var inv = data.inverter || {};
    var card = document.createElement('div');
    card.className = 've-card ve-phases-card';

    var l1v = inv.ac_voltage_an_v, l1a = inv.ac_current_l1_a;
    var l2v = inv.ac_voltage_bn_v, l2a = inv.ac_current_l2_a;
    var l3v = inv.ac_voltage_cn_v, l3a = inv.ac_current_l3_a;

    function fmtV(v) { return v != null ? v.toFixed(1) + ' V' : '-- V'; }
    function fmtA(a) { return a != null ? a.toFixed(2) + ' A' : '-- A'; }
    function fmtW(v, a) { return (v != null && a != null) ? formatW(v * a) : '--'; }

    card.innerHTML =
        '<h2 class="ve-card-title">3-Phase AC</h2>' +
        '<table class="ve-phase-table"><thead><tr><th></th><th>Voltage</th><th>Current</th><th>Power</th></tr></thead>' +
        '<tbody>' +
        '<tr><td class="ve-phase-label">L1</td><td class="ve-live-value ve-l1-voltage">' + fmtV(l1v) + '</td><td class="ve-live-value ve-l1-current">' + fmtA(l1a) + '</td><td class="ve-live-value ve-l1-power">' + fmtW(l1v, l1a) + '</td></tr>' +
        '<tr><td class="ve-phase-label">L2</td><td class="ve-live-value ve-l2-voltage">' + fmtV(l2v) + '</td><td class="ve-live-value ve-l2-current">' + fmtA(l2a) + '</td><td class="ve-live-value ve-l2-power">' + fmtW(l2v, l2a) + '</td></tr>' +
        '<tr><td class="ve-phase-label">L3</td><td class="ve-live-value ve-l3-voltage">' + fmtV(l3v) + '</td><td class="ve-live-value ve-l3-current">' + fmtA(l3a) + '</td><td class="ve-live-value ve-l3-power">' + fmtW(l3v, l3a) + '</td></tr>' +
        '</tbody></table>';

    return card;
}

function buildDCChannelCard(data) {
    var card = document.createElement('div');
    card.className = 've-card';
    var channels = data.dc_channels || [];
    var inv = data.inverter || {};

    card.innerHTML = '<h2 class="ve-card-title">DC Channels</h2>';

    if (channels.length === 0) {
        // Fallback: show single DC from inverter data
        card.innerHTML +=
            '<table class="ve-dc-channel-table"><thead><tr><th>Channel</th><th>Voltage</th><th>Current</th><th>Power</th></tr></thead>' +
            '<tbody><tr><td>DC</td>' +
            '<td>' + (inv.dc_voltage_v != null ? inv.dc_voltage_v.toFixed(1) + ' V' : '--') + '</td>' +
            '<td>' + (inv.dc_current_a != null ? inv.dc_current_a.toFixed(2) + ' A' : '--') + '</td>' +
            '<td>' + (inv.dc_power_w != null ? formatW(inv.dc_power_w) : '--') + '</td>' +
            '</tr></tbody></table>';
    } else {
        var rows = '';
        for (var i = 0; i < channels.length; i++) {
            var ch = channels[i];
            rows += '<tr><td>' + (ch.name || 'Ch ' + (i + 1)) + '</td>' +
                '<td>' + (ch.voltage_v != null ? ch.voltage_v.toFixed(1) + ' V' : '--') + '</td>' +
                '<td>' + (ch.current_a != null ? ch.current_a.toFixed(2) + ' A' : '--') + '</td>' +
                '<td>' + (ch.power_w != null ? formatW(ch.power_w) : '--') + '</td>' +
                '</tr>';
        }
        card.innerHTML +=
            '<table class="ve-dc-channel-table"><thead><tr><th>Channel</th><th>Voltage</th><th>Current</th><th>Power</th></tr></thead>' +
            '<tbody>' + rows + '</tbody></table>';
    }

    return card;
}

// ===== Update Active Device Dashboard =====

function updateActiveDeviceDashboard(data) {
    if (!_activeDeviceContainer) return;
    var inv = data.inverter || {};
    var ratedW = data.rated_power_w || CAPACITY_W;
    var acPower = inv.ac_power_w || 0;
    var pct = Math.min(acPower / ratedW, 1.0);
    var arcLength = GAUGE_ARC_LENGTH;
    var offset = arcLength * (1 - pct);
    var gc = gaugeColor(pct);

    // Update gauge
    var gaugeFill = _activeDeviceContainer.querySelector('.ve-gauge-fill');
    if (gaugeFill) {
        gaugeFill.style.strokeDashoffset = offset;
        gaugeFill.style.stroke = gc;
    }
    var gaugeVal = _activeDeviceContainer.querySelector('.ve-gauge-value-text');
    if (gaugeVal) gaugeVal.textContent = formatW(acPower);

    // Update phase values (SolarEdge)
    function updatePhaseVal(cls, val) {
        var el = _activeDeviceContainer.querySelector('.' + cls);
        if (el && val != null) el.textContent = val;
    }
    if (inv.ac_voltage_an_v != null) {
        updatePhaseVal('ve-l1-voltage', inv.ac_voltage_an_v.toFixed(1) + ' V');
        updatePhaseVal('ve-l1-current', inv.ac_current_l1_a != null ? inv.ac_current_l1_a.toFixed(2) + ' A' : '-- A');
        var l1w = (inv.ac_voltage_an_v != null && inv.ac_current_l1_a != null) ? formatW(inv.ac_voltage_an_v * inv.ac_current_l1_a) : '--';
        updatePhaseVal('ve-l1-power', l1w);
    }
    if (inv.ac_voltage_bn_v != null) {
        updatePhaseVal('ve-l2-voltage', inv.ac_voltage_bn_v.toFixed(1) + ' V');
        updatePhaseVal('ve-l2-current', inv.ac_current_l2_a != null ? inv.ac_current_l2_a.toFixed(2) + ' A' : '-- A');
        var l2w = (inv.ac_voltage_bn_v != null && inv.ac_current_l2_a != null) ? formatW(inv.ac_voltage_bn_v * inv.ac_current_l2_a) : '--';
        updatePhaseVal('ve-l2-power', l2w);
    }
    if (inv.ac_voltage_cn_v != null) {
        updatePhaseVal('ve-l3-voltage', inv.ac_voltage_cn_v.toFixed(1) + ' V');
        updatePhaseVal('ve-l3-current', inv.ac_current_l3_a != null ? inv.ac_current_l3_a.toFixed(2) + ' A' : '-- A');
        var l3w = (inv.ac_voltage_cn_v != null && inv.ac_current_l3_a != null) ? formatW(inv.ac_voltage_cn_v * inv.ac_current_l3_a) : '--';
        updatePhaseVal('ve-l3-power', l3w);
    }

    // Update performance values
    var energyEl = _activeDeviceContainer.querySelector('.ve-daily-energy');
    if (energyEl) energyEl.textContent = ((inv.daily_energy_wh || 0) / 1000).toFixed(1) + ' kWh';
    var peakEl = _activeDeviceContainer.querySelector('.ve-peak-power');
    if (peakEl && inv.peak_power_w != null) peakEl.textContent = formatW(inv.peak_power_w);
    var statusEl = _activeDeviceContainer.querySelector('.ve-inv-status');
    if (statusEl) statusEl.textContent = inv.status || '--';
    var tempEl = _activeDeviceContainer.querySelector('.ve-inv-temp');
    if (tempEl && inv.temperature_sink_c != null) tempEl.textContent = inv.temperature_sink_c.toFixed(1) + ' \u00B0C';
}

// ===== Inverter Registers Renderer =====

function renderInverterRegisters(container, deviceId) {
    container.innerHTML = '';

    // Toolbar
    var toolbar = document.createElement('div');
    toolbar.className = 've-panel';
    toolbar.innerHTML =
        '<div class="ve-reg-toolbar">' +
        '  <h2>Register Viewer' +
        '    <a href="https://knowledge-center.solaredge.com/sites/kc/files/sunspec-implementation-technical-note.pdf" target="_blank" rel="noopener" class="ve-doc-link" title="SolarEdge SunSpec Register Map (PDF)">SE</a>' +
        '    <a href="https://github.com/victronenergy/dbus-fronius" target="_blank" rel="noopener" class="ve-doc-link" title="Victron dbus-fronius">VE</a>' +
        '    <a href="https://files.sma.de/downloads/SunSpecModbus-TI-en-11.pdf" target="_blank" rel="noopener" class="ve-doc-link" title="SunSpec Modbus Register Reference (PDF)">SunSpec</a>' +
        '  </h2>' +
        '  <label class="ve-toggle-label">' +
        '    <span>Hide empty</span>' +
        '    <input type="checkbox" class="ve-reg-hide-toggle" checked>' +
        '    <span class="ve-switch"><span class="ve-switch-knob"></span></span>' +
        '  </label>' +
        '</div>' +
        '<div class="ve-spinner-wrap ve-reg-spinner"><div class="ve-spinner"></div><span class="ve-spinner-label">Loading registers...</span></div>' +
        '<div class="ve-reg-models"></div>';
    container.appendChild(toolbar);

    // Hide empty toggle
    var toggle = toolbar.querySelector('.ve-reg-hide-toggle');
    toggle.addEventListener('change', function() {
        var rows = container.querySelectorAll('.ve-reg-row.ve-empty');
        for (var i = 0; i < rows.length; i++) {
            if (toggle.checked) {
                rows[i].classList.remove('ve-show-empty');
            } else {
                rows[i].classList.add('ve-show-empty');
            }
        }
    });

    // Fetch registers for this specific device
    var regUrl = '/api/devices/' + encodeURIComponent(deviceId) + '/registers';
    var regSpinner = container.querySelector('.ve-reg-spinner');
    fetch(regUrl)
        .then(function(res) { return res.json(); })
        .then(function(models) {
            if (regSpinner) regSpinner.style.display = 'none';
            var modelsContainer = container.querySelector('.ve-reg-models');
            buildRegisterViewer(modelsContainer, models);
        })
        .catch(function(err) {
            if (regSpinner) regSpinner.innerHTML = '<span class="ve-hint-subtext">Failed to load registers</span>';
            console.error('Register load failed:', err);
        });

    // Poll registers while this tab is active
    if (_regPollInterval) clearInterval(_regPollInterval);
    _regPollInterval = setInterval(function() {
        if (_activeDeviceTab !== 'registers' || _activeDeviceId !== deviceId) {
            clearInterval(_regPollInterval);
            _regPollInterval = null;
            return;
        }
        fetch(regUrl)
            .then(function(res) { return res.json(); })
            .then(function(models) {
                updateRegisterValues(models);
            })
            .catch(function() {});
    }, POLL_INTERVAL);
}

// ===== Inverter Config Renderer =====

function renderInverterConfig(container, deviceId) {
    container.innerHTML =
        '<div class="ve-spinner-wrap"><div class="ve-spinner"></div><span class="ve-spinner-label">Loading config...</span></div>';

    fetch('/api/devices')
        .then(function(res) { return res.json(); })
        .then(function(data) {
            var device = null;
            var devices = data.devices || [];
            for (var i = 0; i < devices.length; i++) {
                if (devices[i].id === deviceId) { device = devices[i]; break; }
            }
            if (!device) {
                container.innerHTML = '<div class="ve-hint-card"><div class="ve-hint-header">Device not found</div></div>';
                return;
            }
            container.innerHTML = '';
            buildInverterConfigForm(container, device);
        })
        .catch(function(err) {
            container.innerHTML = '<div class="ve-hint-card"><div class="ve-hint-header">Failed to load config</div><p class="ve-hint-subtext">' + err.message + '</p></div>';
        });
}

function buildInverterConfigForm(container, device) {
    var panel = document.createElement('div');
    panel.className = 've-panel';

    var identity = ((device.manufacturer || '') + ' ' + (device.model || '')).trim();

    panel.innerHTML =
        '<div class="ve-panel-header">' +
        '  <h2>Device Configuration</h2>' +
        '  <span class="ve-btn-pair ve-cfg-save-pair" style="display:none">' +
        '    <button type="button" class="ve-btn ve-btn--sm ve-btn--cancel ve-cfg-cancel">Cancel</button>' +
        '    <button type="button" class="ve-btn ve-btn--sm ve-btn--save ve-cfg-save">Save</button>' +
        '  </span>' +
        '</div>' +
        '<div class="ve-ess-row" style="margin-bottom:12px">' +
        '  <label>Enabled</label>' +
        '  <label class="ve-toggle"><input type="checkbox" class="ve-cfg-enabled" ' + (device.enabled ? 'checked' : '') + '><span class="ve-toggle-track"></span></label>' +
        '</div>' +
        '<div class="ve-form-group"><label>Display Name</label><input type="text" class="ve-input ve-cfg-name" value="' + esc(device.name || '') + '" placeholder="e.g. SE30K"></div>' +
        '<div class="ve-form-group"><label>Host</label><input type="text" class="ve-input ve-cfg-host" value="' + esc(device.host || '') + '" placeholder="192.168.1.100"></div>' +
        '<div class="ve-form-group"><label>Port</label><input type="number" class="ve-input ve-cfg-port" value="' + (device.port || 1502) + '" min="1" max="65535"></div>' +
        '<div class="ve-form-group"><label>Unit ID</label><input type="number" class="ve-input ve-cfg-unit" value="' + (device.unit_id || 1) + '" min="1" max="247"></div>' +
        '<div class="ve-form-group"><label>Type</label><input type="text" class="ve-input" value="' + (device.type || '') + '" readonly style="opacity:0.6"></div>' +
        (identity ? '<div class="ve-form-group"><label>Identity</label><input type="text" class="ve-input" value="' + esc(identity) + '" readonly style="opacity:0.6"></div>' : '') +
        '<div class="ve-form-group"><label>Throttle Order</label><input type="number" class="ve-input ve-cfg-throttle-order" value="' + (device.throttle_order || 1) + '" min="1" max="99"></div>' +
        '<div class="ve-ess-row" style="margin-top:10px">' +
        '  <label>Throttle Enabled</label>' +
        '  <label class="ve-toggle"><input type="checkbox" class="ve-cfg-throttle-enabled" ' + (device.throttle_enabled !== false ? 'checked' : '') + '><span class="ve-toggle-track"></span></label>' +
        '</div>' +
        '<div style="margin-top:24px;padding-top:16px;border-top:1px solid var(--ve-border)">' +
        '  <button type="button" class="ve-btn ve-btn--danger ve-cfg-delete">Delete Device</button>' +
        '</div>';

    container.appendChild(panel);

    // Store originals for dirty tracking
    var originals = {
        name: device.name || '',
        host: device.host || '',
        port: String(device.port || 1502),
        unit_id: String(device.unit_id || 1),
        throttle_order: String(device.throttle_order || 1),
        throttle_enabled: device.throttle_enabled !== false,
        enabled: device.enabled !== false
    };

    var nameInput = panel.querySelector('.ve-cfg-name');
    var hostInput = panel.querySelector('.ve-cfg-host');
    var portInput = panel.querySelector('.ve-cfg-port');
    var unitInput = panel.querySelector('.ve-cfg-unit');
    var toInput = panel.querySelector('.ve-cfg-throttle-order');
    var teToggle = panel.querySelector('.ve-cfg-throttle-enabled');
    var enabledToggle = panel.querySelector('.ve-cfg-enabled');
    var savePair = panel.querySelector('.ve-cfg-save-pair');
    var saveBtn = panel.querySelector('.ve-cfg-save');
    var cancelBtn = panel.querySelector('.ve-cfg-cancel');
    var deleteBtn = panel.querySelector('.ve-cfg-delete');

    function checkDirty() {
        var dirty = nameInput.value !== originals.name ||
                    hostInput.value !== originals.host ||
                    portInput.value !== originals.port ||
                    unitInput.value !== originals.unit_id ||
                    toInput.value !== originals.throttle_order ||
                    teToggle.checked !== originals.throttle_enabled;
        savePair.style.display = dirty ? '' : 'none';
        // Highlight dirty fields
        [nameInput, hostInput, portInput, unitInput, toInput].forEach(function(el) {
            var orig = el === nameInput ? originals.name : el === hostInput ? originals.host : el === portInput ? originals.port : el === unitInput ? originals.unit_id : originals.throttle_order;
            if (el.value !== orig) el.classList.add('ve-input--dirty');
            else el.classList.remove('ve-input--dirty');
        });
    }

    [nameInput, hostInput, portInput, unitInput, toInput].forEach(function(el) {
        el.addEventListener('input', checkDirty);
    });
    teToggle.addEventListener('change', checkDirty);

    cancelBtn.addEventListener('click', function() {
        nameInput.value = originals.name;
        hostInput.value = originals.host;
        portInput.value = originals.port;
        unitInput.value = originals.unit_id;
        toInput.value = originals.throttle_order;
        teToggle.checked = originals.throttle_enabled;
        checkDirty();
    });

    saveBtn.addEventListener('click', function() {
        var payload = {
            name: nameInput.value.trim(),
            host: hostInput.value.trim(),
            port: parseInt(portInput.value),
            unit_id: parseInt(unitInput.value),
            throttle_order: parseInt(toInput.value),
            throttle_enabled: teToggle.checked
        };

        fetch('/api/devices/' + device.id, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.error) {
                showToast('Update failed: ' + data.error, 'error');
                return;
            }
            showToast('Device updated', 'success');
            originals.name = payload.name;
            originals.host = payload.host;
            originals.port = String(payload.port);
            originals.unit_id = String(payload.unit_id);
            originals.throttle_order = String(payload.throttle_order);
            originals.throttle_enabled = payload.throttle_enabled;
            checkDirty();
        })
        .catch(function(e) { showToast('Update failed: ' + e.message, 'error'); });
    });

    // Enabled toggle -- instant save
    enabledToggle.addEventListener('change', function() {
        fetch('/api/devices/' + device.id, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabledToggle.checked })
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.error) {
                showToast('Toggle failed: ' + data.error, 'error');
                enabledToggle.checked = !enabledToggle.checked;
                return;
            }
            showToast(enabledToggle.checked ? 'Device enabled' : 'Device disabled', 'success');
        })
        .catch(function(e) {
            showToast('Toggle failed: ' + e.message, 'error');
            enabledToggle.checked = !enabledToggle.checked;
        });
    });

    // Delete button
    deleteBtn.addEventListener('click', function() {
        deleteDeviceWithUndo(device.id, device.name || device.host || device.id);
    });
}

// ===== Venus OS Page =====

function renderVenusPage(container) {
    container.innerHTML =
        '<div class="ve-spinner-wrap"><div class="ve-spinner"></div><span class="ve-spinner-label">Loading Venus OS...</span></div>';

    // Load config + use last snapshot for status
    Promise.all([
        fetch('/api/config').then(function(r) { return r.json(); }),
        fetch('/api/devices').then(function(r) { return r.json(); })
    ])
    .then(function(results) {
        var config = results[0];
        var deviceData = results[1];
        var venusDevice = null;
        if (deviceData.devices) {
            for (var i = 0; i < deviceData.devices.length; i++) {
                if (deviceData.devices[i].type === 'venus') { venusDevice = deviceData.devices[i]; break; }
            }
        }
        container.innerHTML = '';
        buildVenusPage(container, config, venusDevice);
    })
    .catch(function(err) {
        container.innerHTML = '<div class="ve-hint-card"><div class="ve-hint-header">Failed to load Venus OS data</div><p class="ve-hint-subtext">' + err.message + '</p></div>';
    });
}

function updateMqttPubStatusDot() {
    var dot = document.querySelector('.ve-mqtt-pub-status-dot');
    if (dot) dot.style.background = _mqttPubConnected ? 'var(--ve-green)' : 'var(--ve-red)';
    // Page-level dot (on MQTT Pub page)
    var pageDot = document.querySelector('.ve-mqtt-pub-page-dot');
    if (pageDot) {
        pageDot.className = 've-dot ' + (_mqttPubConnected ? 've-dot--ok' : 've-dot--err') + ' ve-mqtt-pub-page-dot';
    }
    var pageText = document.querySelector('.ve-mqtt-pub-page-text');
    if (pageText) pageText.textContent = _mqttPubConnected ? 'Connected' : 'Disconnected';
}

function _formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function _timeAgo(ts) {
    if (!ts) return 'never';
    var secs = Math.floor(Date.now() / 1000 - ts);
    if (secs < 5) return 'just now';
    if (secs < 60) return secs + 's ago';
    if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
    return Math.floor(secs / 3600) + 'h ago';
}

function updateMqttPubStats() {
    var el = document.querySelector('.ve-mqtt-pub-stats');
    if (!el) return;
    if (!_mqttPubStats) { el.innerHTML = ''; return; }
    var s = _mqttPubStats;
    el.innerHTML =
        '<div class="ve-mqtt-pub-stat"><span class="ve-text-dim">Messages</span><span>' + s.messages.toLocaleString() + '</span></div>' +
        '<div class="ve-mqtt-pub-stat"><span class="ve-text-dim">Data sent</span><span>' + _formatBytes(s.bytes) + '</span></div>' +
        '<div class="ve-mqtt-pub-stat"><span class="ve-text-dim">Skipped (dedup)</span><span>' + s.skipped.toLocaleString() + '</span></div>' +
        '<div class="ve-mqtt-pub-stat"><span class="ve-text-dim">Last publish</span><span>' + _timeAgo(s.last_ts) + '</span></div>';
}

function renderMqttTopicPreview() {
    var list = document.querySelector('.ve-mqtt-pub-topic-list');
    if (!list) return;
    var prefixInput = document.querySelector('.ve-mqtt-pub-prefix');
    var prefix = prefixInput ? prefixInput.value.trim() : 'pv-inverter-proxy';
    if (!prefix) prefix = 'pv-inverter-proxy';
    var html = '';
    // Device topics
    for (var i = 0; i < _lastDeviceList.length; i++) {
        var dev = _lastDeviceList[i];
        if (dev.type === 'venus' || dev.type === 'virtual' || dev.type === 'mqtt_pub') continue;
        html += '<div class="ve-mqtt-pub-topic-item">' +
            '<span class="ve-mqtt-pub-topic-label">' + (dev.name || dev.id) + '</span>' +
            '<code class="ve-mqtt-pub-topic-path">' + prefix + '/device/' + dev.id + '/state</code>' +
            '</div>';
    }
    // Virtual PV
    html += '<div class="ve-mqtt-pub-topic-item">' +
        '<span class="ve-mqtt-pub-topic-label">Virtual PV</span>' +
        '<code class="ve-mqtt-pub-topic-path">' + prefix + '/virtual/state</code>' +
        '</div>';
    // LWT / availability
    html += '<div class="ve-mqtt-pub-topic-item">' +
        '<span class="ve-mqtt-pub-topic-label">Availability (LWT)</span>' +
        '<code class="ve-mqtt-pub-topic-path">' + prefix + '/status</code>' +
        '</div>';
    list.innerHTML = html;
}

function buildVenusPage(container, config, venusDevice) {
    var connState = venusDevice ? venusDevice.connection_state : 'disconnected';
    var connDotClass = connState === 'connected' ? 've-dot--ok' : 've-dot--err';
    var connText = connState === 'connected' ? 'Connected' : 'Disconnected';

    // Section 1: MQTT Status
    var statusCard = document.createElement('div');
    statusCard.className = 've-card';
    statusCard.innerHTML =
        '<h2 class="ve-card-title">MQTT Connection</h2>' +
        '<div class="ve-status-row"><span class="ve-dot ' + connDotClass + ' ve-venus-mqtt-dot"></span><span class="ve-venus-mqtt-text">' + connText + '</span></div>';
    container.appendChild(statusCard);

    // Section 2: ESS Settings (placeholder -- updated via WS)
    var essCard = document.createElement('div');
    essCard.className = 've-card venus-dependent';
    essCard.id = 'venus-ess-panel-device';
    essCard.innerHTML =
        '<h2 class="ve-card-title">Venus OS ESS</h2>' +
        '<div class="ve-ess-group">' +
        '  <div class="ve-ess-row"><label>AC PV Excess</label><label class="ve-toggle"><input type="checkbox" class="ve-ess-ac-excess"><span class="ve-toggle-track"></span></label></div>' +
        '  <div class="ve-ess-row"><label>DC PV Excess</label><label class="ve-toggle"><input type="checkbox" class="ve-ess-dc-excess"><span class="ve-toggle-track"></span></label></div>' +
        '  <div class="ve-ess-row ve-ess-sub ve-ess-limit-row" style="display:none"><label>Limit Feed-in</label><label class="ve-toggle"><input type="checkbox" class="ve-ess-limit-feedin"><span class="ve-toggle-track"></span></label></div>' +
        '  <div class="ve-ess-row ve-ess-sub2 ve-ess-max-feedin-row" style="display:none">' +
        '    <label>Max Feed-in</label>' +
        '    <div class="ve-ess-value-control"><span class="ve-live-value ve-ess-feed-in-actual">--</span><span class="ve-text-dim">/</span><select class="ve-ctrl-dropdown ve-ess-dropdown ve-ess-feed-in-dd"></select></div>' +
        '  </div>' +
        '  <div class="ve-ess-row"><label>Feed-in Limiting</label><span class="ve-live-value ve-ess-limiter-value">--</span></div>' +
        '</div>' +
        '<div class="ve-ess-row" style="margin-top:0.75rem;padding-top:0.5rem;border-top:1px solid var(--ve-border)"><label>Limit Inverter Power</label><label class="ve-toggle"><input type="checkbox" class="ve-ess-limit-inverter"><span class="ve-toggle-track"></span></label></div>' +
        '<div class="ve-ess-row ve-ess-sub ve-ess-max-inverter-row" style="display:none"><label>Max Inverter Power</label><select class="ve-ctrl-dropdown ve-ess-dropdown ve-ess-max-inverter-dd"></select></div>';
    container.appendChild(essCard);

    // Populate ESS dropdowns
    var feedInDD = essCard.querySelector('.ve-ess-feed-in-dd');
    var invLimitDD = essCard.querySelector('.ve-ess-max-inverter-dd');
    for (var kw = 30; kw >= 0; kw--) {
        var watts = kw * 1000;
        var opt1 = document.createElement('option');
        opt1.value = watts;
        opt1.textContent = formatW(watts);
        feedInDD.appendChild(opt1);
        if (kw > 0) {
            var opt2 = document.createElement('option');
            opt2.value = watts;
            opt2.textContent = formatW(watts);
            invLimitDD.appendChild(opt2);
        }
    }

    // Wire ESS toggle events
    wireESSToggles(essCard);

    // Section 3: Portal ID
    var portalCard = document.createElement('div');
    portalCard.className = 've-card';
    portalCard.innerHTML =
        '<h2 class="ve-card-title">Venus OS Info</h2>' +
        '<div class="ve-grid">' +
        '  <div><label>Portal ID</label><span>' + (config.venus.portal_id || 'Auto') + '</span></div>' +
        '</div>';
    container.appendChild(portalCard);

    // Section 4: Config form
    var cfgPanel = document.createElement('div');
    cfgPanel.className = 've-panel';

    var origVenus = {
        host: config.venus.host || '',
        port: String(config.venus.port || 1883),
        portal_id: config.venus.portal_id || ''
    };

    cfgPanel.innerHTML =
        '<div class="ve-panel-header">' +
        '  <h2>Venus OS Configuration</h2>' +
        '  <span class="ve-btn-pair ve-venus-save-pair" style="display:none">' +
        '    <button type="button" class="ve-btn ve-btn--sm ve-btn--cancel ve-venus-cancel">Cancel</button>' +
        '    <button type="button" class="ve-btn ve-btn--sm ve-btn--save ve-venus-save">Save</button>' +
        '  </span>' +
        '</div>' +
        '<div class="ve-form-group"><label>Venus OS IP</label><input type="text" class="ve-input ve-venus-host" value="' + origVenus.host + '" placeholder="e.g. 192.168.1.1"></div>' +
        '<div class="ve-form-group"><label>MQTT Port</label><input type="number" class="ve-input ve-venus-port" value="' + origVenus.port + '" placeholder="1883" min="1" max="65535"></div>' +
        '<div class="ve-form-group"><label>Portal ID</label><input type="text" class="ve-input ve-venus-portal-id" value="' + origVenus.portal_id + '" placeholder="leave blank for auto-discovery"></div>';
    container.appendChild(cfgPanel);

    // Dirty tracking for Venus config
    var vHost = cfgPanel.querySelector('.ve-venus-host');
    var vPort = cfgPanel.querySelector('.ve-venus-port');
    var vPortalId = cfgPanel.querySelector('.ve-venus-portal-id');
    var vSavePair = cfgPanel.querySelector('.ve-venus-save-pair');

    function checkVenusDirty() {
        var dirty = vHost.value !== origVenus.host || vPort.value !== origVenus.port || vPortalId.value !== origVenus.portal_id;
        vSavePair.style.display = dirty ? '' : 'none';
        [vHost, vPort, vPortalId].forEach(function(el) {
            var orig = el === vHost ? origVenus.host : el === vPort ? origVenus.port : origVenus.portal_id;
            if (el.value !== orig) el.classList.add('ve-input--dirty');
            else el.classList.remove('ve-input--dirty');
        });
    }
    [vHost, vPort, vPortalId].forEach(function(el) { el.addEventListener('input', checkVenusDirty); });

    cfgPanel.querySelector('.ve-venus-cancel').addEventListener('click', function() {
        vHost.value = origVenus.host;
        vPort.value = origVenus.port;
        vPortalId.value = origVenus.portal_id;
        checkVenusDirty();
    });

    cfgPanel.querySelector('.ve-venus-save').addEventListener('click', function() {
        var btn = cfgPanel.querySelector('.ve-venus-save');
        btn.textContent = 'Saving...';
        btn.disabled = true;

        var payload = {
            venus: {
                host: vHost.value.trim(),
                port: parseInt(vPort.value) || 1883,
                portal_id: vPortalId.value.trim()
            }
        };

        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.success) {
                showToast('Configuration saved. Reconnecting...', 'success');
                origVenus.host = payload.venus.host;
                origVenus.port = String(payload.venus.port);
                origVenus.portal_id = payload.venus.portal_id;
                checkVenusDirty();
            } else {
                showToast('Save failed: ' + data.error, 'error');
            }
        })
        .catch(function(e) { showToast('Save failed: ' + e.message, 'error'); })
        .finally(function() {
            btn.textContent = 'Save';
            btn.disabled = false;
        });
    });

}

// ===== MQTT Publishing Page =====

function renderMqttPubPage(container) {
    container.innerHTML =
        '<div class="ve-spinner-wrap"><div class="ve-spinner"></div><span class="ve-spinner-label">Loading MQTT config...</span></div>';

    fetch('/api/config')
        .then(function(r) { return r.json(); })
        .then(function(config) {
            container.innerHTML = '';
            buildMqttPubPage(container, config);
        })
        .catch(function(err) {
            container.innerHTML = '<div class="ve-hint-card"><div class="ve-hint-header">Failed to load MQTT config</div><p class="ve-hint-subtext">' + esc(err.message) + '</p></div>';
        });
}

function buildMqttPubPage(container, config) {
    // Connection status card
    var statusCard = document.createElement('div');
    statusCard.className = 've-card';
    var mqttConn = _mqttPubConnected ? 'Connected' : 'Disconnected';
    var mqttDotClass = _mqttPubConnected ? 've-dot--ok' : 've-dot--err';
    statusCard.innerHTML =
        '<h2 class="ve-card-title">Broker Connection</h2>' +
        '<div class="ve-status-row"><span class="ve-dot ' + mqttDotClass + ' ve-mqtt-pub-page-dot"></span><span class="ve-mqtt-pub-page-text">' + mqttConn + '</span></div>' +
        '<div class="ve-mqtt-pub-stats"></div>';
    container.appendChild(statusCard);
    updateMqttPubStats();

    // Config panel
    var mqttPubPanel = document.createElement('div');
    mqttPubPanel.className = 've-panel ve-mqtt-pub-panel';

    var mqttPub = config.mqtt_publish || {};
    var origMqttPub = {
        host: mqttPub.host || '',
        port: String(mqttPub.port || 1883),
        topic_prefix: mqttPub.topic_prefix || 'pv-inverter-proxy',
        interval_s: String(mqttPub.interval_s || 5)
    };

    mqttPubPanel.innerHTML =
        '<div class="ve-panel-header">' +
        '  <h2><span class="ve-dot ve-mqtt-pub-status-dot"></span> MQTT Publishing</h2>' +
        '  <span class="ve-btn-pair ve-mqtt-pub-save-pair" style="display:none">' +
        '    <button type="button" class="ve-btn ve-btn--sm ve-btn--cancel ve-mqtt-pub-cancel">Cancel</button>' +
        '    <button type="button" class="ve-btn ve-btn--sm ve-btn--save ve-mqtt-pub-save">Save</button>' +
        '  </span>' +
        '</div>' +
        '<div class="ve-form-group"><label>Enable</label><label class="ve-toggle"><input type="checkbox" class="ve-mqtt-pub-enabled"><span class="ve-toggle-track"></span></label></div>' +
        '<div class="ve-form-group"><label>Broker Host</label>' +
        '  <div class="ve-mqtt-pub-discover-row">' +
        '    <input type="text" class="ve-input ve-mqtt-pub-host" value="' + origMqttPub.host + '" placeholder="e.g. mqtt-master.local">' +
        '    <button type="button" class="ve-mqtt-pub-discover-btn">Discover</button>' +
        '  </div>' +
        '  <select class="ve-mqtt-pub-broker-select" style="display:none"></select>' +
        '</div>' +
        '<div class="ve-form-group"><label>Port</label><input type="number" class="ve-input ve-mqtt-pub-port" value="' + origMqttPub.port + '" placeholder="1883" min="1" max="65535"></div>' +
        '<div class="ve-form-group"><label>Topic Prefix</label><input type="text" class="ve-input ve-mqtt-pub-prefix" value="' + origMqttPub.topic_prefix + '" placeholder="pv-inverter-proxy"></div>' +
        '<div class="ve-form-group"><label>Publish Interval (s)</label><input type="number" class="ve-input ve-mqtt-pub-interval" value="' + origMqttPub.interval_s + '" placeholder="5" min="1" max="3600"></div>';
    container.appendChild(mqttPubPanel);

    // MQTT Publishing: enable toggle (instant-save)
    var mqttPubEnabled = mqttPubPanel.querySelector('.ve-mqtt-pub-enabled');
    mqttPubEnabled.checked = !!mqttPub.enabled;
    mqttPubEnabled.addEventListener('change', function() {
        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mqtt_publish: { enabled: mqttPubEnabled.checked } })
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.success) {
                showToast('MQTT Publishing: ' + (mqttPubEnabled.checked ? 'On' : 'Off'), 'success');
            } else {
                showToast('Failed: ' + data.error, 'error');
                mqttPubEnabled.checked = !mqttPubEnabled.checked;
            }
        })
        .catch(function(e) {
            showToast('Failed: ' + e.message, 'error');
            mqttPubEnabled.checked = !mqttPubEnabled.checked;
        });
    });

    // MQTT Publishing: dirty tracking
    var mpHost = mqttPubPanel.querySelector('.ve-mqtt-pub-host');
    var mpPort = mqttPubPanel.querySelector('.ve-mqtt-pub-port');
    var mpPrefix = mqttPubPanel.querySelector('.ve-mqtt-pub-prefix');
    var mpInterval = mqttPubPanel.querySelector('.ve-mqtt-pub-interval');
    var mpSavePair = mqttPubPanel.querySelector('.ve-mqtt-pub-save-pair');

    function checkMqttPubDirty() {
        var dirty = mpHost.value !== origMqttPub.host ||
                    mpPort.value !== origMqttPub.port ||
                    mpPrefix.value !== origMqttPub.topic_prefix ||
                    mpInterval.value !== origMqttPub.interval_s;
        mpSavePair.style.display = dirty ? '' : 'none';
        var fields = [
            { el: mpHost, orig: origMqttPub.host },
            { el: mpPort, orig: origMqttPub.port },
            { el: mpPrefix, orig: origMqttPub.topic_prefix },
            { el: mpInterval, orig: origMqttPub.interval_s }
        ];
        fields.forEach(function(f) {
            if (f.el.value !== f.orig) f.el.classList.add('ve-input--dirty');
            else f.el.classList.remove('ve-input--dirty');
        });
    }
    [mpHost, mpPort, mpPrefix, mpInterval].forEach(function(el) {
        el.addEventListener('input', checkMqttPubDirty);
    });

    // MQTT Publishing: cancel
    mqttPubPanel.querySelector('.ve-mqtt-pub-cancel').addEventListener('click', function() {
        mpHost.value = origMqttPub.host;
        mpPort.value = origMqttPub.port;
        mpPrefix.value = origMqttPub.topic_prefix;
        mpInterval.value = origMqttPub.interval_s;
        checkMqttPubDirty();
    });

    // MQTT Publishing: save
    mqttPubPanel.querySelector('.ve-mqtt-pub-save').addEventListener('click', function() {
        var btn = mqttPubPanel.querySelector('.ve-mqtt-pub-save');
        btn.textContent = 'Saving...';
        btn.disabled = true;

        var payload = {
            mqtt_publish: {
                host: mpHost.value.trim(),
                port: parseInt(mpPort.value) || 1883,
                topic_prefix: mpPrefix.value.trim(),
                interval_s: parseInt(mpInterval.value) || 5
            }
        };

        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.success) {
                showToast('MQTT config saved', 'success');
                origMqttPub.host = payload.mqtt_publish.host;
                origMqttPub.port = String(payload.mqtt_publish.port);
                origMqttPub.topic_prefix = payload.mqtt_publish.topic_prefix;
                origMqttPub.interval_s = String(payload.mqtt_publish.interval_s);
                checkMqttPubDirty();
            } else {
                showToast('Save failed: ' + data.error, 'error');
            }
        })
        .catch(function(e) { showToast('Save failed: ' + e.message, 'error'); })
        .finally(function() {
            btn.textContent = 'Save';
            btn.disabled = false;
        });
    });

    // MQTT Publishing: discover button
    var discoverBtn = mqttPubPanel.querySelector('.ve-mqtt-pub-discover-btn');
    var brokerSelect = mqttPubPanel.querySelector('.ve-mqtt-pub-broker-select');

    discoverBtn.addEventListener('click', function() {
        discoverBtn.textContent = 'Scanning...';
        discoverBtn.disabled = true;
        brokerSelect.style.display = 'none';

        fetch('/api/mqtt/discover', { method: 'POST' })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (!data.success) {
                showToast('Discovery failed: ' + (data.error || 'unknown'), 'error');
                return;
            }
            var brokers = data.brokers || [];
            if (brokers.length === 0) {
                showToast('No MQTT brokers found', 'warning');
            } else if (brokers.length === 1) {
                mpHost.value = brokers[0].host;
                if (brokers[0].port) mpPort.value = String(brokers[0].port);
                checkMqttPubDirty();
                showToast('Found broker: ' + brokers[0].host, 'success');
            } else {
                // Multiple brokers: show dropdown
                brokerSelect.innerHTML = '';
                brokers.forEach(function(b) {
                    var opt = document.createElement('option');
                    opt.value = b.host + ':' + (b.port || 1883);
                    opt.textContent = (b.name || b.host) + ' (' + b.host + ':' + (b.port || 1883) + ')';
                    brokerSelect.appendChild(opt);
                });
                brokerSelect.style.display = '';
                // Auto-select first
                var parts = brokerSelect.value.split(':');
                mpHost.value = parts[0];
                mpPort.value = parts[1] || '1883';
                checkMqttPubDirty();
                showToast('Found ' + brokers.length + ' brokers — select one', 'success');

                brokerSelect.addEventListener('change', function() {
                    var p = brokerSelect.value.split(':');
                    mpHost.value = p[0];
                    mpPort.value = p[1] || '1883';
                    checkMqttPubDirty();
                });
            }
        })
        .catch(function(e) { showToast('Discovery failed: ' + e.message, 'error'); })
        .finally(function() {
            discoverBtn.textContent = 'Discover';
            discoverBtn.disabled = false;
        });
    });

    // Section 6: MQTT Topic Preview card
    var topicCard = document.createElement('div');
    topicCard.className = 've-card ve-mqtt-pub-topic-card';
    topicCard.innerHTML =
        '<h2 class="ve-card-title">MQTT Topics</h2>' +
        '<div class="ve-mqtt-pub-topic-list"></div>';
    container.appendChild(topicCard);

    // Re-render topic preview when prefix input changes
    mpPrefix.addEventListener('input', renderMqttTopicPreview);

    // Initial renders: status dot + topic preview
    // Seed _lastDeviceList from config.inverters if no WS data yet
    if (_lastDeviceList.length === 0 && config.inverters) {
        _lastDeviceList = config.inverters.map(function(inv) {
            return { id: inv.id, name: inv.name || inv.id, type: inv.type || 'sunspec', enabled: inv.enabled };
        });
        // Add venus + virtual placeholders
        _lastDeviceList.push({ id: 'venus', name: 'Venus OS', type: 'venus' });
        _lastDeviceList.push({ id: 'virtual', name: config.virtual_inverter ? config.virtual_inverter.name : 'Virtual PV', type: 'virtual' });
    }
    updateMqttPubStatusDot();
    renderMqttTopicPreview();
}

function wireESSToggles(essCard) {
    var acToggle = essCard.querySelector('.ve-ess-ac-excess');
    var dcToggle = essCard.querySelector('.ve-ess-dc-excess');
    var limitToggle = essCard.querySelector('.ve-ess-limit-feedin');
    var feedInDD = essCard.querySelector('.ve-ess-feed-in-dd');
    var invLimitToggle = essCard.querySelector('.ve-ess-limit-inverter');
    var invLimitDD = essCard.querySelector('.ve-ess-max-inverter-dd');

    if (acToggle) acToggle.addEventListener('change', function() {
        acToggle._userChangedAt = Date.now();
        writeVenusDbus('/Settings/CGwacs/PreventFeedback', acToggle.checked ? 0 : 1);
        showToast('AC PV Excess: ' + (acToggle.checked ? 'On' : 'Off'), 'success');
    });
    if (dcToggle) dcToggle.addEventListener('change', function() {
        dcToggle._userChangedAt = Date.now();
        writeVenusDbus('/Settings/CGwacs/OvervoltageFeedIn', dcToggle.checked ? 1 : 0);
        showToast('DC PV Excess: ' + (dcToggle.checked ? 'On' : 'Off'), 'success');
    });
    if (limitToggle) limitToggle.addEventListener('change', function() {
        limitToggle._userChangedAt = Date.now();
        if (limitToggle.checked) {
            writeVenusDbus('/Settings/CGwacs/MaxFeedInPower', 10000);
            showToast('Feed-in limit: ' + formatW(10000), 'success');
        } else {
            writeVenusDbus('/Settings/CGwacs/MaxFeedInPower', -1);
            showToast('Feed-in limit: Off', 'success');
        }
    });
    if (feedInDD) feedInDD.addEventListener('change', function() {
        var watts = parseInt(feedInDD.value);
        writeVenusDbus('/Settings/CGwacs/MaxFeedInPower', watts);
        showToast('Max feed-in: ' + formatW(watts), 'success');
    });
    if (invLimitToggle) invLimitToggle.addEventListener('change', function() {
        invLimitToggle._userChangedAt = Date.now();
        if (invLimitToggle.checked) {
            writeVenusDbus('/Settings/CGwacs/MaxDischargePower', 20000);
            showToast('Inverter limit: ' + formatW(20000), 'success');
        } else {
            writeVenusDbus('/Settings/CGwacs/MaxDischargePower', -1);
            showToast('Inverter limit: Off', 'success');
        }
    });
    if (invLimitDD) invLimitDD.addEventListener('change', function() {
        var watts = parseInt(invLimitDD.value);
        writeVenusDbus('/Settings/CGwacs/MaxDischargePower', watts);
        showToast('Max inverter: ' + formatW(watts), 'success');
    });
}

// ===== Virtual PV Page =====

function renderVirtualPVPage(container) {
    container.innerHTML =
        '<div class="ve-spinner-wrap"><div class="ve-spinner"></div><span class="ve-spinner-label">Loading Virtual PV...</span></div>';

    fetch('/api/devices/virtual/snapshot')
        .then(function(res) { return res.json(); })
        .then(function(data) {
            _lastVirtualSnapshot = data;
            container.innerHTML = '';
            buildVirtualPVPage(container, data);
        })
        .catch(function(err) {
            container.innerHTML = '<div class="ve-hint-card"><div class="ve-hint-header">Failed to load Virtual PV data</div><p class="ve-hint-subtext">' + err.message + '</p></div>';
        });
}

var CONTRIBUTION_COLORS = ['var(--ve-blue)', 'var(--ve-orange)', 'var(--ve-green)', 'var(--ve-text-dim)', 'var(--ve-blue-light)', 'var(--ve-red)'];

function buildVirtualPVPage(container, data) {
    var totalW = data.total_power_w || 0;
    var contributions = data.contributions || [];

    // Total power
    var totalDiv = document.createElement('div');
    totalDiv.className = 've-virtual-total';
    totalDiv.innerHTML =
        '<span class="ve-virtual-total-value">' + Math.round(totalW) + '</span>' +
        '<span class="ve-virtual-total-unit">W</span>';
    container.appendChild(totalDiv);

    // Virtual name
    if (data.virtual_name) {
        var nameDiv = document.createElement('div');
        nameDiv.style.cssText = 'text-align:center;color:var(--ve-text-dim);font-size:0.85rem;margin-bottom:16px';
        nameDiv.textContent = data.virtual_name;
        container.appendChild(nameDiv);
    }

    // Contribution bar
    var barCard = document.createElement('div');
    barCard.className = 've-card';
    barCard.innerHTML = '<h2 class="ve-card-title">Power Contribution</h2>';

    var bar = document.createElement('div');
    bar.className = 've-contribution-bar';

    var legend = document.createElement('div');
    legend.className = 've-contribution-legend';

    for (var i = 0; i < contributions.length; i++) {
        var c = contributions[i];
        var pct = totalW > 0 ? (c.power_w / totalW * 100) : 0;
        var color = CONTRIBUTION_COLORS[i % CONTRIBUTION_COLORS.length];

        var seg = document.createElement('div');
        seg.className = 've-contribution-segment';
        seg.style.width = pct.toFixed(1) + '%';
        seg.style.background = color;
        seg.setAttribute('data-device-id', c.device_id);
        bar.appendChild(seg);

        var legendItem = document.createElement('div');
        legendItem.className = 've-contribution-legend-item';
        legendItem.innerHTML =
            '<span class="ve-contribution-legend-dot" style="background:' + color + '"></span>' +
            '<span class="ve-contribution-legend-name">' + esc(c.name || c.device_id) + '</span>' +
            '<span class="ve-contribution-legend-power">' + formatW(c.power_w) + '</span>';
        legendItem.setAttribute('data-device-id', c.device_id);
        legend.appendChild(legendItem);
    }

    barCard.appendChild(bar);
    barCard.appendChild(legend);
    container.appendChild(barCard);

    // Throttle table
    if (contributions.length > 0) {
        var throttleCard = document.createElement('div');
        throttleCard.className = 've-card';
        throttleCard.innerHTML = '<h2 class="ve-card-title">Throttle Overview</h2>';

        var table = document.createElement('table');
        table.className = 've-throttle-table';
        var thead = '<thead><tr><th>Name</th><th>TO#</th><th>Throttle</th><th>Limit</th></tr></thead>';
        var tbody = '<tbody>';
        for (var j = 0; j < contributions.length; j++) {
            var ct = contributions[j];
            tbody += '<tr>' +
                '<td>' + esc(ct.name || ct.device_id) + '</td>' +
                '<td>' + (ct.throttle_order || '--') + '</td>' +
                '<td>' + (ct.throttle_enabled ? 'On' : 'Off') + '</td>' +
                '<td>' + (ct.current_limit_pct != null ? ct.current_limit_pct.toFixed(1) + '%' : '--') + '</td>' +
                '</tr>';
        }
        tbody += '</tbody>';
        table.innerHTML = thead + tbody;
        throttleCard.appendChild(table);
        container.appendChild(throttleCard);
    }
}

function updateVirtualPVPage(data) {
    if (!_activeDeviceContainer) return;

    var parent = _activeDeviceContainer.parentElement;
    if (!parent) return;

    var totalW = data.total_power_w || 0;
    var contributions = data.contributions || [];

    // Update total
    var totalEl = parent.querySelector('.ve-virtual-total-value');
    if (totalEl) totalEl.textContent = Math.round(totalW);

    // Update bar segments
    var segments = parent.querySelectorAll('.ve-contribution-segment');
    for (var i = 0; i < segments.length && i < contributions.length; i++) {
        var pct = totalW > 0 ? (contributions[i].power_w / totalW * 100) : 0;
        segments[i].style.width = pct.toFixed(1) + '%';
    }

    // Update legend powers
    var legendItems = parent.querySelectorAll('.ve-contribution-legend-item');
    for (var j = 0; j < legendItems.length && j < contributions.length; j++) {
        var pwrEl = legendItems[j].querySelector('.ve-contribution-legend-power');
        if (pwrEl) pwrEl.textContent = formatW(contributions[j].power_w);
    }

    // Update throttle table
    var tds = parent.querySelectorAll('.ve-throttle-table tbody tr');
    for (var k = 0; k < tds.length && k < contributions.length; k++) {
        var cells = tds[k].querySelectorAll('td');
        if (cells.length >= 4) {
            cells[2].textContent = contributions[k].throttle_enabled ? 'On' : 'Off';
            cells[3].textContent = contributions[k].current_limit_pct != null ? contributions[k].current_limit_pct.toFixed(1) + '%' : '--';
        }
    }
}

// ===== Add Device Flow =====

document.getElementById('btn-add-device').addEventListener('click', function() {
    showAddDeviceModal();
});

function showAddDeviceModal() {
    var modal = document.createElement('div');
    modal.className = 've-add-modal';
    modal.innerHTML =
        '<div class="ve-add-modal-content">' +
        '  <div class="ve-add-modal-title">Add Device</div>' +
        '  <div class="ve-add-type-picker">' +
        '    <div class="ve-add-type-card" data-type="solaredge">SolarEdge Inverter</div>' +
        '    <div class="ve-add-type-card" data-type="opendtu">OpenDTU Inverter</div>' +
        '  </div>' +
        '  <div class="ve-add-form-area"></div>' +
        '  <div class="ve-add-modal-actions">' +
        '    <button class="ve-btn ve-add-cancel">Cancel</button>' +
        '  </div>' +
        '</div>';
    document.body.appendChild(modal);

    var selectedType = null;
    var formArea = modal.querySelector('.ve-add-form-area');
    var actions = modal.querySelector('.ve-add-modal-actions');

    // Type picker
    modal.querySelectorAll('.ve-add-type-card').forEach(function(card) {
        card.addEventListener('click', function() {
            modal.querySelectorAll('.ve-add-type-card').forEach(function(c) { c.classList.remove('ve-add-type-card--selected'); });
            card.classList.add('ve-add-type-card--selected');
            selectedType = card.getAttribute('data-type');
            showAddForm(formArea, actions, selectedType, modal);
        });
    });

    // Cancel
    modal.querySelector('.ve-add-cancel').addEventListener('click', function() {
        modal.remove();
    });

    // Close on overlay click
    modal.addEventListener('click', function(e) {
        if (e.target === modal) modal.remove();
    });
}

function showAddForm(formArea, actions, type, modal) {
    formArea.innerHTML = '';

    // Remove old add/discover buttons
    actions.querySelectorAll('.ve-add-submit, .ve-add-discover').forEach(function(b) { b.remove(); });

    if (type === 'solaredge') {
        formArea.innerHTML =
            '<div class="ve-form-group"><label>Name (optional)</label><input type="text" class="ve-input ve-add-name" placeholder="e.g. SE30K"></div>' +
            '<div class="ve-form-group"><label>Host IP</label><input type="text" class="ve-input ve-add-host" placeholder="192.168.1.100"></div>' +
            '<div class="ve-form-group"><label>Port</label><input type="number" class="ve-input ve-add-port" value="1502" min="1" max="65535"></div>' +
            '<div class="ve-form-group"><label>Unit ID</label><input type="number" class="ve-input ve-add-unit" value="1" min="1" max="247"></div>';
    } else if (type === 'opendtu') {
        formArea.innerHTML =
            '<div class="ve-form-group"><label>Name (optional)</label><input type="text" class="ve-input ve-add-name" placeholder="e.g. HM-800"></div>' +
            '<div class="ve-form-group"><label>Gateway Host</label><input type="text" class="ve-input ve-add-host" placeholder="192.168.1.100"></div>';
    }

    // Discover area
    formArea.innerHTML += '<div class="ve-add-scan-area" style="display:none"><div class="ve-scan-progress" style="display:none"><div class="ve-scan-bar"><div class="ve-scan-bar-fill ve-add-scan-fill"></div></div><span class="ve-scan-status ve-add-scan-status"></span></div><div class="ve-add-scan-results"></div></div>';

    // Add buttons
    var discoverBtn = document.createElement('button');
    discoverBtn.className = 've-btn ve-btn--primary ve-add-discover';
    discoverBtn.textContent = 'Discover';
    actions.insertBefore(discoverBtn, actions.firstChild);

    var addBtn = document.createElement('button');
    addBtn.className = 've-btn ve-btn--save ve-add-submit';
    addBtn.textContent = 'Add';
    actions.insertBefore(addBtn, actions.querySelector('.ve-add-cancel'));

    // Add button handler
    addBtn.addEventListener('click', function() {
        var host = formArea.querySelector('.ve-add-host');
        var port = formArea.querySelector('.ve-add-port');
        var unit = formArea.querySelector('.ve-add-unit');
        var name = formArea.querySelector('.ve-add-name');

        if (!host || !host.value.trim()) {
            showToast('Host is required', 'error');
            return;
        }

        var payload = {
            host: host.value.trim(),
            type: type
        };
        if (name && name.value.trim()) payload.name = name.value.trim();
        if (port) payload.port = parseInt(port.value) || 1502;
        if (unit) payload.unit_id = parseInt(unit.value) || 1;

        fetch('/api/devices', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.error) {
                showToast('Add failed: ' + data.error, 'error');
                return;
            }
            showToast('Device added', 'success');
            modal.remove();
            if (data.id) navigateTo(data.id, 'dashboard');
        })
        .catch(function(e) { showToast('Add failed: ' + e.message, 'error'); });
    });

    // Discover button handler
    discoverBtn.addEventListener('click', function() {
        triggerAddModalScan(formArea);
    });
}

function triggerAddModalScan(formArea) {
    var scanArea = formArea.querySelector('.ve-add-scan-area');
    var progress = formArea.querySelector('.ve-scan-progress');
    var fill = formArea.querySelector('.ve-add-scan-fill');
    var status = formArea.querySelector('.ve-add-scan-status');
    var results = formArea.querySelector('.ve-add-scan-results');

    _scanRunning = true;
    scanArea.style.display = '';
    progress.style.display = '';
    fill.style.width = '0%';
    status.textContent = 'Starting scan...';
    results.innerHTML = '';

    fetch('/api/scanner/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ports: [502, 1502] })
    })
    .then(function(res) {
        if (res.status === 409) {
            showToast('Scan already running', 'warning');
        }
    })
    .catch(function(e) {
        showToast('Scan failed: ' + e.message, 'error');
    });
}

// ===== Delete with Undo Toast =====

function deleteDeviceWithUndo(deviceId, deviceName) {
    // Cache device data for undo
    var cachedDevice = null;
    for (var i = 0; i < _devices.length; i++) {
        if (_devices[i].id === deviceId) { cachedDevice = JSON.parse(JSON.stringify(_devices[i])); break; }
    }

    fetch('/api/devices/' + deviceId, { method: 'DELETE' })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            if (data.error) {
                showToast('Delete failed: ' + data.error, 'error');
                return;
            }
            // Navigate away
            navigateTo('virtual', 'dashboard');

            // Show undo toast
            showToast('Device geloescht', 'warning', 'Rueckgaengig', function() {
                // Undo: re-add device
                if (cachedDevice) {
                    var payload = {
                        host: cachedDevice.host,
                        port: cachedDevice.port,
                        unit_id: cachedDevice.unit_id,
                        name: cachedDevice.name,
                        type: cachedDevice.type,
                        enabled: cachedDevice.enabled
                    };
                    fetch('/api/devices', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    })
                    .then(function(res) { return res.json(); })
                    .then(function(d) {
                        if (d.id) {
                            showToast('Device wiederhergestellt', 'success');
                            navigateTo(d.id, 'dashboard');
                        }
                    })
                    .catch(function() { showToast('Undo failed', 'error'); });
                }
            }, 5000);
        })
        .catch(function(e) { showToast('Delete failed: ' + e.message, 'error'); });
}

// ===== Legacy Snapshot Handler (backward compat) =====

function handleSnapshot(data) {
    var inv = data.inverter;
    if (!inv) return;

    // Update sidebar with legacy data
    if (data.connection && data.connection.state) {
        var sidebarDevices = document.querySelectorAll('.ve-sidebar-device');
        // Try to update first inverter
        for (var i = 0; i < sidebarDevices.length; i++) {
            var did = sidebarDevices[i].getAttribute('data-device-id');
            if (did && did !== 'venus' && did !== 'virtual') {
                updateSidebarPower(did, data);
                break;
            }
        }
    }

    // If active device is an inverter and we have no device_snapshot routing yet
    if (_activeDeviceContainer && _activeDeviceTab === 'dashboard' &&
        _activeDeviceId !== 'venus' && _activeDeviceId !== 'virtual') {
        updateActiveDeviceDashboard(data);
    }

    // Update Venus MQTT status in sidebar
    if (data.venus_mqtt_connected != null) {
        var venusEntry = document.querySelector('.ve-sidebar-device[data-device-id="venus"]');
        if (venusEntry) {
            var dot = venusEntry.querySelector('.ve-dot');
            if (dot) {
                dot.style.background = data.venus_mqtt_connected ? 'var(--ve-green)' : 'var(--ve-red)';
            }
            var pwrEl = venusEntry.querySelector('.ve-sidebar-device-power');
            if (pwrEl) {
                pwrEl.textContent = data.venus_mqtt_connected ? 'Connected' : 'Disconnected';
            }
        }
    }

    // Update Venus ESS on device page if showing
    if (_activeDeviceId === 'venus' && _activeDeviceContainer) {
        updateVenusESSOnPage(data);
    }
}

function updateVenusESSOnPage(snapshot) {
    var vs = snapshot.venus_settings;
    if (!vs) return;

    var container = _activeDeviceContainer.parentElement || document.getElementById('device-content');
    if (!container) return;

    var now = Date.now();
    function notCooling(el) { return (now - (el._userChangedAt || 0)) > 8000; }

    // MQTT dot update
    var mqttDot = container.querySelector('.ve-venus-mqtt-dot');
    var mqttText = container.querySelector('.ve-venus-mqtt-text');
    if (mqttDot) {
        mqttDot.className = 've-dot ' + (snapshot.venus_mqtt_connected ? 've-dot--ok' : 've-dot--err');
    }
    if (mqttText) {
        mqttText.textContent = snapshot.venus_mqtt_connected ? 'Connected' : 'Disconnected';
    }

    // ESS toggles
    var acToggle = container.querySelector('.ve-ess-ac-excess');
    var dcToggle = container.querySelector('.ve-ess-dc-excess');
    var limitToggle = container.querySelector('.ve-ess-limit-feedin');
    var feedInDD = container.querySelector('.ve-ess-feed-in-dd');
    var feedInActual = container.querySelector('.ve-ess-feed-in-actual');
    var limiterEl = container.querySelector('.ve-ess-limiter-value');
    var limitRow = container.querySelector('.ve-ess-limit-row');
    var maxRow = container.querySelector('.ve-ess-max-feedin-row');
    var invLimitToggle = container.querySelector('.ve-ess-limit-inverter');
    var invLimitRow = container.querySelector('.ve-ess-max-inverter-row');
    var invLimitDD = container.querySelector('.ve-ess-max-inverter-dd');

    var acOn = !vs.prevent_feedback;
    if (acToggle && notCooling(acToggle)) acToggle.checked = acOn;

    var dcOn = vs.overvoltage_feed_in;
    if (dcToggle && notCooling(dcToggle)) dcToggle.checked = dcOn;

    var excessActive = acOn || dcOn;
    if (limitRow) limitRow.style.display = excessActive ? '' : 'none';

    var feedInLimited = vs.max_feed_in_w >= 0;
    if (limitToggle && notCooling(limitToggle)) limitToggle.checked = feedInLimited;
    if (maxRow) maxRow.style.display = (excessActive && feedInLimited) ? '' : 'none';

    if (feedInActual) {
        feedInActual.textContent = formatW(vs.grid_feed_in_w);
        if (vs.max_feed_in_w > 0 && vs.grid_feed_in_w > vs.max_feed_in_w) {
            feedInActual.style.color = 'var(--ve-red)';
        } else if (vs.grid_feed_in_w > 0) {
            feedInActual.style.color = 'var(--ve-green)';
        } else {
            feedInActual.style.color = '';
        }
    }

    if (feedInDD && !feedInDD.matches(':focus') && vs.max_feed_in_w > 0) {
        var closest = Math.round(vs.max_feed_in_w / 1000) * 1000;
        feedInDD.value = closest;
    }

    var invLimited = vs.max_inverter_w >= 0;
    if (invLimitToggle && notCooling(invLimitToggle)) invLimitToggle.checked = invLimited;
    if (invLimitRow) invLimitRow.style.display = invLimited ? '' : 'none';

    if (invLimitDD && !invLimitDD.matches(':focus') && invLimited) {
        var closestInv = Math.round(vs.max_inverter_w / 1000) * 1000;
        invLimitDD.value = closestInv;
    }

    if (limiterEl) {
        if (vs.limiter_active) {
            limiterEl.textContent = 'Active';
            limiterEl.style.color = 'var(--ve-green)';
        } else {
            limiterEl.textContent = 'Inactive';
            limiterEl.style.color = 'var(--ve-text-dim)';
        }
    }

    // MQTT gate
    var essPanel = container.querySelector('#venus-ess-panel-device');
    if (essPanel) {
        if (snapshot.venus_mqtt_connected) {
            essPanel.classList.remove('mqtt-gated');
        } else {
            essPanel.classList.add('mqtt-gated');
        }
    }
}

// ===== No Inverter Handler =====

function handleNoInverter() {
    // Show empty state if viewing an inverter that no longer exists
    if (_activeDeviceContainer && _activeDeviceId !== 'venus' && _activeDeviceId !== 'virtual') {
        _activeDeviceContainer.innerHTML =
            '<div class="ve-hint-card" style="max-width:420px;margin:80px auto;text-align:center;padding:32px">' +
            '<h3 style="margin:0 0 8px;color:var(--ve-text)">Kein Inverter konfiguriert</h3>' +
            '<p style="margin:0;color:var(--ve-text-dim);font-size:0.9rem">Klicke auf "+" um einen Inverter hinzuzufuegen.</p>' +
            '</div>';
    }
}

// ===== History Handler =====

function handleHistory(data) {
    if (data.ac_power_w && Array.isArray(data.ac_power_w)) {
        sparklineData = data.ac_power_w.map(function(p) { return p[1]; });
    }
}

// ===== Override Event Handler =====

function handleOverrideEvent(eventData) {
    var sourceNames = { 'webapp': 'Webapp', 'venus_os': 'Venus OS', 'system': 'System' };
    var sourceName = sourceNames[eventData.source] || eventData.source;
    var msg = sourceName + ': ' + eventData.action;
    if (eventData.value != null) msg += ' ' + eventData.value.toFixed(1) + '%';
    if (eventData.detail) msg += ' (' + eventData.detail + ')';
    var toastType = eventData.source === 'venus_os' ? 'error' : 'info';
    showToast(msg, toastType);
}

// ===== Discovery / Scan =====

function handleScanProgress(data) {
    // Check for add-modal scan area
    var addFill = document.querySelector('.ve-add-scan-fill');
    var addStatus = document.querySelector('.ve-add-scan-status');
    if (addFill) {
        var pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
        addFill.style.width = pct + '%';
    }
    if (addStatus) {
        if (data.phase === 'probe') {
            addStatus.textContent = 'Scanning network (' + data.current + '/' + data.total + ')...';
        } else if (data.phase === 'verify') {
            addStatus.textContent = 'Verifying SunSpec (' + data.current + '/' + data.total + ')...';
        }
    }
}

function handleScanComplete(data) {
    _scanRunning = false;
    var devices = data.devices || [];

    // Check for add-modal scan results
    var scanResults = document.querySelector('.ve-add-scan-results');
    var scanProgress = document.querySelector('.ve-add-scan-area .ve-scan-progress');
    if (scanProgress) scanProgress.style.display = 'none';

    if (scanResults) {
        scanResults.innerHTML = '';
        if (devices.length === 0) {
            scanResults.innerHTML = '<div class="ve-hint-card ve-scan-hint"><div class="ve-hint-header">Keine Inverter gefunden</div></div>';
        } else {
            scanResults.innerHTML = '<div style="margin-top:8px;font-size:0.85rem;color:var(--ve-text-dim)">' + devices.length + ' found. Click to fill form:</div>';
            for (var i = 0; i < devices.length; i++) {
                var dev = devices[i];
                var row = document.createElement('div');
                row.className = 've-scan-result';
                row.style.cursor = 'pointer';
                var ident = ((dev.manufacturer || '') + ' ' + (dev.model || '')).trim() || 'Unknown';
                row.innerHTML = '<span class="ve-scan-result-host">' + esc(dev.ip) + ':' + esc(dev.port) + '</span><span class="ve-scan-result-identity">' + esc(ident) + '</span>';
                row._device = dev;
                row.addEventListener('click', function() {
                    var d = this._device;
                    var hostInput = document.querySelector('.ve-add-host');
                    var portInput = document.querySelector('.ve-add-port');
                    var unitInput = document.querySelector('.ve-add-unit');
                    if (hostInput) hostInput.value = d.ip;
                    if (portInput) portInput.value = d.port;
                    if (unitInput) unitInput.value = d.unit_id;
                });
                scanResults.appendChild(row);
            }
        }
    }
}

function handleScanError(data) {
    _scanRunning = false;
    showToast('Scan fehlgeschlagen: ' + (data.error || 'Unbekannter Fehler'), 'error');
}

// ===== Register Viewer =====

var SUNSPEC_DECODE = {
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
    40102: { unit: '\u00B0C', sf_addr: 40106, label: 'Cabinet temperature', signed: true },
    40103: { unit: '\u00B0C', sf_addr: 40106, label: 'Heatsink temperature', signed: true },
    40104: { unit: '\u00B0C', sf_addr: 40106, label: 'Transformer temperature', signed: true },
    40105: { unit: '\u00B0C', sf_addr: 40106, label: 'Other temperature', signed: true },
    40106: { is_sf: true },
    40107: { enum: { 1: 'Off', 2: 'Sleeping', 3: 'Starting', 4: 'Producing (MPPT)', 5: 'Throttled', 6: 'Shutting down', 7: 'Fault', 8: 'Standby' }, label: 'Operating state' },
    40108: { label: 'Vendor-specific status code' },
    40123: { enum: { 4: 'PV', 82: 'Storage', 83: 'PV+Storage' }, label: 'DER type' },
    40124: { unit: 'W', sf_addr: 40125, label: 'Max power rating' },
    40125: { is_sf: true },
    40126: { unit: 'VA', sf_addr: 40127, label: 'Max apparent power' },
    40127: { is_sf: true },
    40133: { unit: 'A', sf_addr: 40134, label: 'Max current rating' },
    40134: { is_sf: true },
    40153: { enum: { 0: 'Disconnect', 1: 'Connect' }, label: 'Connection control' },
    40154: { unit: '%', sf_fixed: -2, label: 'Power limit setpoint' },
    40158: { enum: { 0: 'Disabled', 1: 'Enabled' }, label: 'Power limit enable' }
};

var sfCache = {};

function decodeRegisterValue(addr, rawValue) {
    var meta = SUNSPEC_DECODE[addr];
    if (!meta || rawValue === null || rawValue === undefined) return '';
    if (meta.is_sf) return 'Scale Factor';
    if (meta.enum) {
        var label = meta.enum[rawValue];
        return label ? label : 'Unknown (' + rawValue + ')';
    }
    if (meta.unit) {
        if (rawValue === 32768 || rawValue === 32767 || rawValue === 65535) return 'N/A';
        var sf = 0;
        if (meta.sf_fixed !== undefined) {
            sf = meta.sf_fixed;
        } else if (meta.sf_addr) {
            sf = sfCache[meta.sf_addr];
            if (sf === undefined || sf === null) return rawValue + ' ' + meta.unit + ' (raw)';
            if (sf > 32767) sf = sf - 65536;
        }
        var numValue = (typeof rawValue === 'string') ? parseInt(rawValue.replace(/,/g, ''), 10) : rawValue;
        if (isNaN(numValue)) return '';
        var decoded = numValue * Math.pow(10, sf);
        var decimals = sf < 0 ? Math.abs(sf) : 0;
        if (Math.abs(decoded) >= 1000000) return (decoded / 1000000).toFixed(1) + ' M' + meta.unit;
        if (Math.abs(decoded) >= 10000) return (decoded / 1000).toFixed(1) + ' k' + meta.unit;
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
    buildSfCache(models);
    models.forEach(function(model) {
        var group = document.createElement('div');
        group.className = 've-model-group';

        var header = document.createElement('div');
        header.className = 've-model-header';
        header.innerHTML = '<span>' + model.name + '</span><span>\u25BC</span>';
        header.addEventListener('click', function() {
            var fields = group.querySelector('.ve-model-fields');
            fields.classList.toggle('collapsed');
            header.querySelector('span:last-child').textContent = fields.classList.contains('collapsed') ? '\u25B6' : '\u25BC';
        });
        group.appendChild(header);

        var fields = document.createElement('div');
        fields.className = 've-model-fields';

        var headerRow = document.createElement('div');
        headerRow.className = 've-reg-header';
        headerRow.innerHTML = '<span>Addr</span><span>Name</span><span class="ve-reg-se-value">SE30K Source</span><span class="ve-reg-fronius-value">Fronius Target</span><span class="ve-reg-decoded">Decoded</span>';
        fields.appendChild(headerRow);

        model.fields.forEach(function(field) {
            var row = document.createElement('div');
            row.className = 've-reg-row';
            row.id = 'reg-' + field.addr;

            var seVal = formatValue(field.se_value);
            var frVal = formatValue(field.fronius_value);
            var seClass = field.se_value === null ? 've-reg-se-value null-value' : 've-reg-se-value';
            var decoded = decodeRegisterValue(field.addr, field.fronius_value);
            var meta = SUNSPEC_DECODE[field.addr];
            var tooltip = meta && meta.label ? ' title="' + meta.label + '"' : '';

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
    buildSfCache(models);
    models.forEach(function(model) {
        model.fields.forEach(function(field) {
            var seEl = document.getElementById('se-val-' + field.addr);
            var frEl = document.getElementById('fr-val-' + field.addr);
            var decEl = document.getElementById('dec-val-' + field.addr);
            var changed = false;

            if (seEl) {
                var newSeVal = formatValue(field.se_value);
                if (seEl.textContent !== newSeVal) { seEl.textContent = newSeVal; changed = true; }
                seEl.className = field.se_value === null ? 've-reg-se-value null-value' : 've-reg-se-value';
            }
            if (frEl) {
                var newFrVal = formatValue(field.fronius_value);
                if (frEl.textContent !== newFrVal) { frEl.textContent = newFrVal; changed = true; }
            }
            if (decEl) {
                var newDec = decodeRegisterValue(field.addr, field.fronius_value);
                if (decEl.textContent !== newDec) decEl.textContent = newDec;
            }
            if (changed) {
                var row = document.getElementById('reg-' + field.addr);
                if (row) { row.classList.remove('ve-changed'); void row.offsetWidth; row.classList.add('ve-changed'); }
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

// ===== Venus OS dbus write =====

function formatW(watts) {
    if (watts == null) return '--';
    if (Math.abs(watts) >= 1000) {
        var kw = watts / 1000;
        return (kw % 1 === 0 ? kw.toFixed(0) : kw.toFixed(1)) + ' kW';
    }
    return Math.round(watts) + ' W';
}

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

// ===== Toast Notifications =====

var toastContainer = null;
var MAX_TOASTS = 4;

function getToastContainer() {
    if (!toastContainer) toastContainer = document.getElementById('toast-container');
    return toastContainer;
}

function showToast(message, type, actionLabel, actionCallback, duration) {
    var container = getToastContainer();
    if (!container) return;

    // Duplicate suppression
    var existing = container.querySelectorAll('.ve-toast:not(.ve-toast--exiting)');
    for (var i = 0; i < existing.length; i++) {
        if (existing[i]._message === message) return;
    }

    // Enforce max
    while (container.querySelectorAll('.ve-toast:not(.ve-toast--exiting)').length >= MAX_TOASTS) {
        var toasts = container.querySelectorAll('.ve-toast:not(.ve-toast--exiting)');
        var oldest = null;
        for (var k = toasts.length - 1; k >= 0; k--) {
            if (!toasts[k].classList.contains('ve-toast--error')) { oldest = toasts[k]; break; }
        }
        if (!oldest) oldest = toasts[toasts.length - 1];
        dismissToast(oldest);
    }

    if (!duration) duration = (type === 'error') ? 8000 : (type === 'warning') ? 5000 : 3000;

    var toast = document.createElement('div');
    toast.className = 've-toast ve-toast--' + (type || 'info');
    toast._message = message;

    if (actionLabel && actionCallback) {
        toast.innerHTML = '<span>' + message + '</span> <button style="margin-left:12px;padding:2px 10px;background:rgba(255,255,255,0.2);border:1px solid rgba(255,255,255,0.3);border-radius:4px;color:inherit;cursor:pointer;font-weight:600;font-size:0.85em">' + actionLabel + '</button>';
        var actionBtn = toast.querySelector('button');
        actionBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            clearTimeout(timer);
            dismissToast(toast);
            actionCallback();
        });
    } else {
        toast.textContent = message;
    }

    toast.setAttribute('role', 'alert');
    container.prepend(toast);

    var timer = setTimeout(function() { dismissToast(toast); }, duration);
    toast.addEventListener('click', function() {
        clearTimeout(timer);
        dismissToast(toast);
    });
}

function dismissToast(toast) {
    if (!toast || toast.classList.contains('ve-toast--exiting')) return;
    toast.classList.add('ve-toast--exiting');
    toast.addEventListener('animationend', function() { toast.remove(); }, { once: true });
}

// ===== Initialization =====

document.addEventListener('DOMContentLoaded', function() {
    // Fetch device list and render sidebar
    fetch('/api/devices')
        .then(function(res) { return res.json(); })
        .then(function(data) {
            renderSidebar(data.devices || []);
            // Parse route and show page
            var route = parseRoute();
            showDevicePage(route.id, route.tab);
        })
        .catch(function() {
            // No devices yet -- show virtual
            renderSidebar([]);
            var route = parseRoute();
            showDevicePage(route.id, route.tab);
        });

    // Start WebSocket
    connectWebSocket();
});
