/* PV-Inverter-Master - Frontend Application
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
        container.appendChild(createSidebarGroup('INVERTERS', inverters, true));
    }

    // VENUS OS group (includes Virtual PV as sub-entry)
    if (venusDevice) {
        var venusGroup = [venusDevice];
        if (virtualDevice) venusGroup.push(virtualDevice);
        container.appendChild(createSidebarGroup('VENUS OS', venusGroup));
    } else if (virtualDevice) {
        container.appendChild(createSidebarGroup('VENUS OS', [virtualDevice]));
    }

    // MQTT PUBLISH group
    if (mqttPubDevice) {
        container.appendChild(createSidebarGroup('MQTT PUBLISH', [mqttPubDevice]));
    }

    // Update active highlight
    highlightActiveSidebar();
}

function createSidebarGroup(label, devices, showAddBtn) {
    var group = document.createElement('div');
    group.className = 've-sidebar-group';

    var header = document.createElement('div');
    header.className = 've-sidebar-group-header';
    var addBtnHtml = showAddBtn ? '<button class="ve-sidebar-add-btn" id="btn-add-device" title="Add Inverter">+</button>' : '';
    header.innerHTML = '<span>' + label + '</span><span class="ve-sidebar-header-right">' + addBtnHtml + '<span class="ve-chevron">&#9660;</span></span>';
    header.addEventListener('click', function(e) {
        // Don't toggle collapse when clicking the add button
        if (e.target.closest('.ve-sidebar-add-btn')) return;
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

    // Wire add button if present
    if (showAddBtn) {
        var addBtn = header.querySelector('.ve-sidebar-add-btn');
        if (addBtn) addBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            showAddDeviceModal();
        });
    }

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
        renderInverterRegisters(tabContent, deviceId, deviceType);
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

    // Power limit dropdowns
    var clampHtml = '';
    if (ratedW > 0) {
        var isBinary = deviceType === 'shelly';
        var ctrl = data.control || {};
        var curMinPct = ctrl.clamp_min_pct || 0;
        var curMaxPct = ctrl.clamp_max_pct != null ? ctrl.clamp_max_pct : 100;

        var zeroLabel = ratedW >= 2000 ? '0 kW' : '0 W';
        var maxLabel = ratedW >= 2000 ? (ratedW / 1000) + ' kW' : ratedW + ' W';
        var minOpts, maxOpts;

        if (isBinary) {
            // Binary: only 0 and Max (on/off)
            minOpts = '<option value="max"' + (curMinPct >= 100 ? ' selected' : '') + '>Max</option>' +
                '<option value="0"' + (curMinPct === 0 ? ' selected' : '') + '>' + zeroLabel + '</option>';
            maxOpts = '<option value="max"' + (curMaxPct >= 100 ? ' selected' : '') + '>Max</option>' +
                '<option value="0"' + (curMaxPct === 0 ? ' selected' : '') + '>' + zeroLabel + '</option>';
        } else {
            // Proportional: full step list
            // ≥ 2kW: 1kW steps, < 2kW: 50W steps
            var steps = [];
            if (ratedW >= 2000) {
                var maxKw = Math.round(ratedW / 1000);
                for (var kw = maxKw - 1; kw >= 1; kw--) steps.push({w: kw * 1000, label: kw + ' kW'});
            } else {
                var stepW = 50;
                for (var w = ratedW - stepW; w >= stepW; w -= stepW) steps.push({w: w, label: w + ' W'});
            }
            var w1pct = Math.round(ratedW * 0.01);
            var label1pct = w1pct >= 1000 ? (w1pct / 1000).toFixed(1) + ' kW' : w1pct + ' W';

            var curMinW = Math.round(curMinPct * ratedW / 100);
            var curMaxW = curMaxPct >= 100 ? ratedW : Math.round(curMaxPct * ratedW / 100);

            function _closestStep(watts) {
                if (watts <= w1pct) return watts === 0 ? '0' : 'min';
                var best = steps[0]; var bestD = 99999;
                for (var i = 0; i < steps.length; i++) {
                    var d = Math.abs(steps[i].w - watts);
                    if (d < bestD) { bestD = d; best = steps[i]; }
                }
                return String(best.w);
            }

            minOpts = '';
            for (var i = 0; i < steps.length; i++) {
                var s = steps[i];
                minOpts += '<option value="' + s.w + '"' + (_closestStep(curMinW) === String(s.w) ? ' selected' : '') + '>' + s.label + '</option>';
            }
            minOpts += '<option value="min"' + (curMinPct === 1 ? ' selected' : '') + '>' + label1pct + '</option>';
            minOpts += '<option value="0"' + (curMinPct === 0 ? ' selected' : '') + '>' + zeroLabel + '</option>';

            maxOpts = '<option value="max"' + (curMaxPct >= 100 ? ' selected' : '') + '>Max</option>';
            for (var i = 0; i < steps.length; i++) {
                var s = steps[i];
                maxOpts += '<option value="' + s.w + '"' + (curMaxPct < 100 && curMaxPct > 1 && _closestStep(curMaxW) === String(s.w) ? ' selected' : '') + '>' + s.label + '</option>';
            }
            maxOpts += '<option value="min"' + (curMaxPct === 1 ? ' selected' : '') + '>' + label1pct + '</option>';
            maxOpts += '<option value="0"' + (curMaxPct === 0 ? ' selected' : '') + '>' + zeroLabel + '</option>';
        }

        clampHtml =
            '<div class="ve-gauge-clamp">' +
            '  <select class="ve-ctrl-dropdown ve-clamp-min" title="Minimum power (floor)">' + minOpts + '</select>' +
            '  <span class="ve-text-dim ve-clamp-label">Limit</span>' +
            '  <select class="ve-ctrl-dropdown ve-clamp-max" title="Maximum power (ceiling)">' + maxOpts + '</select>' +
            '</div>';
    }

    gaugeCard.innerHTML =
        '<h2 class="ve-card-title">Power Output</h2>' +
        '<svg viewBox="0 0 200 130" class="ve-gauge-svg">' +
        '  <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="var(--ve-border)" stroke-width="12" stroke-linecap="round"/>' +
        '  <path class="ve-gauge-fill" d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="' + gc + '" stroke-width="12" stroke-linecap="round" stroke-dasharray="' + arcLength + '" stroke-dashoffset="' + offset + '"/>' +
        '  <text x="100" y="76" text-anchor="middle" fill="var(--ve-text)" font-size="32" font-weight="700" class="ve-gauge-value-text">' + formatW(acPower) + '</text>' +
        '  <text x="100" y="94" text-anchor="middle" fill="var(--ve-text-dim)" font-size="11">' + formatW(ratedW) + ' max</text>' +
        '  <text x="100" y="122" text-anchor="middle" fill="var(--ve-text-dim)" font-size="11" class="ve-gauge-status-text">' + esc(data.display_name || data.inverter_name || '--') + '</text>' +
        '</svg>' + clampHtml;
    topRow.appendChild(gaugeCard);

    // Wire up power limit dropdown events
    var clampMinDD = gaugeCard.querySelector('.ve-clamp-min');
    var clampMaxDD = gaugeCard.querySelector('.ve-clamp-max');
    if (clampMinDD && clampMaxDD) {
        var _ratedW = ratedW;
        function _ddPct(dd) {
            if (dd.value === 'max') return 100;
            if (dd.value === 'min') return 1;
            if (dd.value === '0') return 0;
            return Math.round(parseInt(dd.value) / _ratedW * 100);
        }
        function _ddLabel(dd) {
            if (dd.value === 'max') return 'Max';
            return dd.options[dd.selectedIndex].text;
        }
        function sendClamp() {
            var minPct = _ddPct(clampMinDD);
            var maxPct = _ddPct(clampMaxDD);
            if (minPct > maxPct) { clampMinDD.value = clampMaxDD.value; minPct = maxPct; }
            fetch('/api/power-clamp', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_id: _activeDeviceId, min_pct: minPct, max_pct: maxPct })
            }).then(function(r) { return r.json(); }).then(function(d) {
                if (d.success) showToast('Limit: ' + _ddLabel(clampMinDD) + ' – ' + _ddLabel(clampMaxDD), 'success');
                else showToast(d.error || 'Failed', 'error');
            }).catch(function(e) { showToast('Error: ' + e.message, 'error'); });
        }
        clampMinDD.addEventListener('change', function() {
            if (_ddPct(clampMinDD) > _ddPct(clampMaxDD)) clampMaxDD.value = clampMinDD.value;
            sendClamp();
        });
        clampMaxDD.addEventListener('change', function() {
            if (_ddPct(clampMinDD) > _ddPct(clampMaxDD)) clampMinDD.value = clampMaxDD.value;
            sendClamp();
        });
    }

    // Type-specific card
    if (deviceType === 'opendtu' || deviceType === 'shelly') {
        topRow.appendChild(buildDCChannelCard(data));
    } else {
        topRow.appendChild(buildPhaseCard(data));
    }

    // Throttle info card (only for devices with throttle capabilities)
    if (data.throttle_mode && data.throttle_mode !== 'none') {
        var throttleInfoCard = document.createElement('div');
        throttleInfoCard.className = 've-card';
        var tiScore = (data.throttle_score || 0).toFixed(1);
        var tiMode = data.throttle_mode.charAt(0).toUpperCase() + data.throttle_mode.slice(1);
        var tiResp = data.measured_response_time_s != null
            ? '<span style="font-family:var(--ve-mono)">' + data.measured_response_time_s.toFixed(1) + 's</span>'
            : 'Measuring...';
        throttleInfoCard.innerHTML =
            '<h2 class="ve-card-title">Throttle Info</h2>' +
            '<div class="ve-throttle-info-grid">' +
            '  <span class="ve-text-dim">Score</span><span style="font-family:var(--ve-mono)">' + tiScore + '</span>' +
            '  <span class="ve-text-dim">Mode</span><span>' + tiMode + '</span>' +
            '  <span class="ve-text-dim">Reaktion</span><span>' + tiResp + '</span>' +
            '</div>';
        topRow.appendChild(throttleInfoCard);
    }

    container.appendChild(topRow);

    // Row 2: Connection + Performance
    var row2 = document.createElement('div');
    row2.className = 've-dashboard-info-row';

    // Connection card
    var connCard = document.createElement('div');
    connCard.className = 've-card ve-conn-card';
    var connState = data.connection ? data.connection.state : 'unknown';
    var connDotClass = connState === 'connected' ? 've-dot--ok' : connState === 'reconnecting' ? 've-dot--warn' : connState === 'night_mode' ? 've-dot--dim' : 've-dot--err';
    connCard.innerHTML =
        '<h2 class="ve-card-title">Connection</h2>' +
        '<div class="ve-status-row"><span class="ve-dot ' + connDotClass + '"></span><span>Inverter: ' + (connState === 'night_mode' ? 'sleeping' : connState) + '</span></div>';

    if (deviceType === 'shelly') {
        var relayStatus = inv.status === 'MPPT' ? 'On' : 'Off';
        var relayDot = inv.status === 'MPPT' ? 've-dot' : 've-dot ve-dot--dim';
        connCard.innerHTML +=
            '<div style="margin-top:10px">' +
            '  <div class="ve-status-row"><span class="ve-text-dim">Relay:</span><span class="' + relayDot + '" style="display:inline-block;width:8px;height:8px;border-radius:50%;margin:0 6px;background:' + (inv.status === 'MPPT' ? 'var(--ve-green)' : 'var(--ve-text-dim)') + '"></span><span class="ve-shelly-relay-state">' + relayStatus + '</span></div>' +
            '</div>' +
            '<div class="ve-shelly-actions" style="margin-top:12px;display:flex;gap:6px;flex-wrap:wrap">' +
            '  <button class="ve-btn ve-btn--sm ve-shelly-on">Switch On</button>' +
            '  <button class="ve-btn ve-btn--sm ve-btn--cancel ve-shelly-off">Switch Off</button>' +
            '</div>';

        var _shellyDevId = data.device_id || _activeDeviceId;
        function _sendShellySwitch(on) {
            fetch('/api/devices/' + _shellyDevId + '/shelly/switch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ on: on })
            }).then(function(r) { return r.json(); }).then(function(d) {
                if (d.success) {
                    showToast('Relay ' + (on ? 'On' : 'Off'), 'success');
                    var stateEl = connCard.querySelector('.ve-shelly-relay-state');
                    if (stateEl) stateEl.textContent = on ? 'On' : 'Off';
                } else {
                    showToast(d.error || 'Failed', 'error');
                }
            }).catch(function(e) { showToast('Error: ' + e.message, 'error'); });
        }
        var shellyOnBtn = connCard.querySelector('.ve-shelly-on');
        var shellyOffBtn = connCard.querySelector('.ve-shelly-off');
        if (shellyOnBtn) shellyOnBtn.addEventListener('click', function() { _sendShellySwitch(true); });
        if (shellyOffBtn) shellyOffBtn.addEventListener('click', function() { _sendShellySwitch(false); });
    }

    if (deviceType === 'opendtu') {
        var dtuCached = data.opendtu_status || null;
        connCard.innerHTML +=
            '<div class="ve-opendtu-status" style="margin-top:10px">' +
            '  <div class="ve-status-row"><span class="ve-text-dim">Producing:</span><span class="ve-opendtu-producing">' + (dtuCached ? (dtuCached.producing ? 'Yes' : 'No') : '...') + '</span></div>' +
            '  <div class="ve-status-row"><span class="ve-text-dim">Reachable:</span><span class="ve-opendtu-reachable">' + (dtuCached ? (dtuCached.reachable ? 'Yes' : 'No') : '...') + '</span></div>' +
            '  <div class="ve-status-row"><span class="ve-text-dim">Limit:</span><span class="ve-opendtu-limit">' + (dtuCached ? dtuCached.limit_relative + '% (' + dtuCached.limit_absolute + ' W)' : '...') + '</span></div>' +
            '</div>' +
            '<div class="ve-opendtu-actions" style="margin-top:12px;display:flex;gap:6px;flex-wrap:wrap">' +
            '  <button class="ve-btn ve-btn--sm ve-opendtu-restart">Restart</button>' +
            '  <button class="ve-btn ve-btn--sm ve-opendtu-on">Power On</button>' +
            '  <button class="ve-btn ve-btn--sm ve-btn--cancel ve-opendtu-off">Power Off</button>' +
            '</div>';

        // Fetch live OpenDTU status (periodic refresh every 10s)
        var _devId = data.device_id || _activeDeviceId;
        var _dtuInterval = null;
        function _refreshDtuStatus() {
            // Stop if card is no longer in DOM (page navigated away)
            if (!connCard.parentNode) { if (_dtuInterval) clearInterval(_dtuInterval); return; }
            fetch('/api/devices/' + _devId + '/opendtu/status')
                .then(function(r) { return r.json(); })
                .then(function(s) {
                    var prodEl = connCard.querySelector('.ve-opendtu-producing');
                    var reachEl = connCard.querySelector('.ve-opendtu-reachable');
                    var limEl = connCard.querySelector('.ve-opendtu-limit');
                    if (s.error) {
                        if (prodEl) prodEl.textContent = '--';
                        if (reachEl) reachEl.textContent = '--';
                        if (limEl) limEl.textContent = s.error;
                        return;
                    }
                    if (prodEl) prodEl.textContent = s.producing ? 'Yes' : 'No';
                    if (reachEl) reachEl.textContent = s.reachable ? 'Yes' : 'No';
                    if (limEl) limEl.textContent = s.limit_relative + '% (' + s.limit_absolute + ' W)';
                }).catch(function() {});
        }
        _refreshDtuStatus();
        _dtuInterval = setInterval(_refreshDtuStatus, 10000);

        // Wire power buttons
        function _sendPower(action) {
            fetch('/api/devices/' + _devId + '/opendtu/power', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: action })
            }).then(function(r) { return r.json(); }).then(function(d) {
                if (d.success) { showToast('Inverter: ' + action, 'success'); setTimeout(_refreshDtuStatus, 3000); }
                else showToast(d.error || 'Failed', 'error');
            }).catch(function(e) { showToast('Error: ' + e.message, 'error'); });
        }
        var restartBtn = connCard.querySelector('.ve-opendtu-restart');
        var onBtn = connCard.querySelector('.ve-opendtu-on');
        var offBtn = connCard.querySelector('.ve-opendtu-off');
        if (restartBtn) restartBtn.addEventListener('click', function() { _sendPower('restart'); });
        if (onBtn) onBtn.addEventListener('click', function() { _sendPower('on'); });
        if (offBtn) offBtn.addEventListener('click', function() { _sendPower('off'); });
    }

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

    function fmtV(v) { return v != null ? v.toFixed(1) + ' V' : '--'; }
    function fmtA(a) { return a != null ? a.toFixed(2) + ' A' : '--'; }
    function fmtW(v, a) { return (v != null && a != null) ? formatW(v * a) : '--'; }
    function fmtHz(f) { return f != null ? f.toFixed(1) + ' Hz' : '--'; }

    // AC summary row
    var eff = inv.efficiency_pct;
    var freq = inv.ac_frequency_hz;
    var dcV = inv.dc_voltage_v, dcA = inv.dc_current_a, dcW = inv.dc_power_w;
    var temp = inv.temperature_sink_c;

    card.innerHTML =
        '<h2 class="ve-card-title">AC Output' +
        '  <span class="ve-card-subtitle">' + fmtHz(freq) +
            ' · <span class="ve-se-eff">' + (eff != null ? eff.toFixed(1) + '%' : '--') + '</span> eff' +
            ' · <span class="ve-se-temp">' + (temp != null ? temp.toFixed(1) + '°C' : '--') + '</span>' +
        '</span></h2>' +
        ((!l2v && !l2a && !l3v && !l3a) ?
        '<table class="ve-phase-table"><thead><tr><th>Voltage</th><th>Current</th><th>Power</th></tr></thead>' +
        '<tbody>' +
        '<tr><td class="ve-live-value ve-l1-voltage">' + fmtV(l1v) + '</td><td class="ve-live-value ve-l1-current">' + fmtA(l1a) + '</td><td class="ve-live-value ve-l1-power">' + fmtW(l1v, l1a) + '</td></tr>' +
        '</tbody></table>'
        :
        '<table class="ve-phase-table"><thead><tr><th></th><th>Voltage</th><th>Current</th><th>Power</th></tr></thead>' +
        '<tbody>' +
        '<tr><td class="ve-phase-label">L1</td><td class="ve-live-value ve-l1-voltage">' + fmtV(l1v) + '</td><td class="ve-live-value ve-l1-current">' + fmtA(l1a) + '</td><td class="ve-live-value ve-l1-power">' + fmtW(l1v, l1a) + '</td></tr>' +
        '<tr><td class="ve-phase-label">L2</td><td class="ve-live-value ve-l2-voltage">' + fmtV(l2v) + '</td><td class="ve-live-value ve-l2-current">' + fmtA(l2a) + '</td><td class="ve-live-value ve-l2-power">' + fmtW(l2v, l2a) + '</td></tr>' +
        '<tr><td class="ve-phase-label">L3</td><td class="ve-live-value ve-l3-voltage">' + fmtV(l3v) + '</td><td class="ve-live-value ve-l3-current">' + fmtA(l3a) + '</td><td class="ve-live-value ve-l3-power">' + fmtW(l3v, l3a) + '</td></tr>' +
        '</tbody></table>') +
        ((dcV || dcA || dcW) ?
        '<h2 class="ve-card-title" style="margin-top:12px">DC Input' +
        '  <span class="ve-card-subtitle"><span class="ve-se-dc-v">' + (dcV != null ? dcV.toFixed(0) + 'V' : '--') + '</span>' +
            ' · <span class="ve-se-dc-a">' + (dcA != null ? dcA.toFixed(1) + 'A' : '--') + '</span>' +
            ' · <span class="ve-se-dc-w">' + (dcW != null ? formatW(dcW) : '--') + '</span></span></h2>'
        : '');

    return card;
}

function buildDCChannelCard(data) {
    var card = document.createElement('div');
    card.className = 've-card ve-ac-dc-card';
    var channels = data.dc_channels || [];
    var inv = data.inverter || {};

    // AC section
    var acV = inv.ac_voltage_an_v, acA = inv.ac_current_l1_a, acW = inv.ac_power_w;
    var acFreq = inv.ac_frequency_hz, eff = inv.efficiency_pct;
    card.innerHTML =
        '<h2 class="ve-card-title">AC Output</h2>' +
        '<table class="ve-phase-table"><thead><tr><th>Voltage</th><th>Current</th><th>Power</th><th>Frequency</th></tr></thead>' +
        '<tbody><tr>' +
        '<td class="ve-live-value ve-ac-voltage">' + (acV != null ? acV.toFixed(1) + ' V' : '--') + '</td>' +
        '<td class="ve-live-value ve-ac-current">' + (acA != null ? acA.toFixed(2) + ' A' : '--') + '</td>' +
        '<td class="ve-live-value ve-ac-power">' + (acW != null ? formatW(acW) : '--') + '</td>' +
        '<td class="ve-live-value ve-ac-freq">' + (acFreq != null ? acFreq.toFixed(1) + ' Hz' : '--') + '</td>' +
        '</tr></tbody></table>' +
        (eff != null ? '<div style="margin-top:6px" class="ve-text-dim ve-live-value ve-ac-eff">Efficiency: ' + eff.toFixed(1) + '%</div>' : '');

    // DC Strings section
    if (channels.length > 0) {
        var dcRows = '';
        for (var i = 0; i < channels.length; i++) {
            var ch = channels[i];
            dcRows += '<tr>' +
                '<td>' + esc(ch.name || 'String ' + (i + 1)) + '</td>' +
                '<td class="ve-live-value ve-dc' + i + '-voltage">' + (ch.voltage_v != null ? ch.voltage_v.toFixed(1) + ' V' : '--') + '</td>' +
                '<td class="ve-live-value ve-dc' + i + '-current">' + (ch.current_a != null ? ch.current_a.toFixed(2) + ' A' : '--') + '</td>' +
                '<td class="ve-live-value ve-dc' + i + '-power">' + (ch.power_w != null ? formatW(ch.power_w) : '--') + '</td>' +
                '<td class="ve-live-value ve-dc' + i + '-yield">' + (ch.yield_day_wh != null ? ch.yield_day_wh + ' Wh' : '--') + '</td>' +
                '</tr>';
        }
        card.innerHTML +=
            '<h2 class="ve-card-title" style="margin-top:16px">DC Strings</h2>' +
            '<table class="ve-phase-table"><thead><tr><th>String</th><th>Voltage</th><th>Current</th><th>Power</th><th>Today</th></tr></thead>' +
            '<tbody>' + dcRows + '</tbody></table>';
    } else if (inv.dc_voltage_v || inv.dc_current_a || inv.dc_power_w) {
        // Fallback: single DC from inverter data (only if DC data exists)
        card.innerHTML +=
            '<h2 class="ve-card-title" style="margin-top:16px">DC Input</h2>' +
            '<table class="ve-phase-table"><thead><tr><th>Voltage</th><th>Current</th><th>Power</th></tr></thead>' +
            '<tbody><tr>' +
            '<td class="ve-live-value">' + (inv.dc_voltage_v != null ? inv.dc_voltage_v.toFixed(1) + ' V' : '--') + '</td>' +
            '<td class="ve-live-value">' + (inv.dc_current_a != null ? inv.dc_current_a.toFixed(2) + ' A' : '--') + '</td>' +
            '<td class="ve-live-value">' + (inv.dc_power_w != null ? formatW(inv.dc_power_w) : '--') + '</td>' +
            '</tr></tbody></table>';
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

    // Update SolarEdge AC summary + DC input
    updatePhaseVal('ve-se-freq', inv.ac_frequency_hz != null ? inv.ac_frequency_hz.toFixed(1) + ' Hz' : null);
    updatePhaseVal('ve-se-eff', inv.efficiency_pct != null ? inv.efficiency_pct.toFixed(1) + '%' : null);
    updatePhaseVal('ve-se-temp', inv.temperature_sink_c != null ? inv.temperature_sink_c.toFixed(1) + ' \u00B0C' : null);
    updatePhaseVal('ve-se-total-a', inv.ac_current_a != null ? inv.ac_current_a.toFixed(1) + ' A' : null);
    updatePhaseVal('ve-se-dc-v', inv.dc_voltage_v != null ? inv.dc_voltage_v.toFixed(1) + ' V' : null);
    updatePhaseVal('ve-se-dc-a', inv.dc_current_a != null ? inv.dc_current_a.toFixed(2) + ' A' : null);
    updatePhaseVal('ve-se-dc-w', inv.dc_power_w != null ? formatW(inv.dc_power_w) : null);

    // Update performance values
    var energyEl = _activeDeviceContainer.querySelector('.ve-daily-energy');
    if (energyEl) energyEl.textContent = ((inv.daily_energy_wh || 0) / 1000).toFixed(1) + ' kWh';
    var peakEl = _activeDeviceContainer.querySelector('.ve-peak-power');
    if (peakEl && inv.peak_power_w != null) peakEl.textContent = formatW(inv.peak_power_w);
    var statusEl = _activeDeviceContainer.querySelector('.ve-inv-status');
    if (statusEl) statusEl.textContent = inv.status || '--';
    var tempEl = _activeDeviceContainer.querySelector('.ve-inv-temp');
    if (tempEl && inv.temperature_sink_c != null) tempEl.textContent = inv.temperature_sink_c.toFixed(1) + ' \u00B0C';

    // Update AC/DC values for OpenDTU
    updatePhaseVal('ve-ac-voltage', inv.ac_voltage_an_v != null ? inv.ac_voltage_an_v.toFixed(1) + ' V' : null);
    updatePhaseVal('ve-ac-current', inv.ac_current_l1_a != null ? inv.ac_current_l1_a.toFixed(2) + ' A' : null);
    updatePhaseVal('ve-ac-power', inv.ac_power_w != null ? formatW(inv.ac_power_w) : null);
    updatePhaseVal('ve-ac-freq', inv.ac_frequency_hz != null ? inv.ac_frequency_hz.toFixed(1) + ' Hz' : null);
    updatePhaseVal('ve-ac-eff', inv.efficiency_pct != null ? 'Efficiency: ' + inv.efficiency_pct.toFixed(1) + '%' : null);
    var dcs = data.dc_channels || [];
    for (var di = 0; di < dcs.length; di++) {
        updatePhaseVal('ve-dc' + di + '-voltage', dcs[di].voltage_v != null ? dcs[di].voltage_v.toFixed(1) + ' V' : null);
        updatePhaseVal('ve-dc' + di + '-current', dcs[di].current_a != null ? dcs[di].current_a.toFixed(2) + ' A' : null);
        updatePhaseVal('ve-dc' + di + '-power', dcs[di].power_w != null ? formatW(dcs[di].power_w) : null);
        updatePhaseVal('ve-dc' + di + '-yield', dcs[di].yield_day_wh != null ? dcs[di].yield_day_wh + ' Wh' : null);
    }

    // Update OpenDTU status from cached snapshot data (instant, no extra fetch)
    var dtuS = data.opendtu_status;
    if (dtuS) {
        var prodEl = _activeDeviceContainer.querySelector('.ve-opendtu-producing');
        var reachEl = _activeDeviceContainer.querySelector('.ve-opendtu-reachable');
        var limEl = _activeDeviceContainer.querySelector('.ve-opendtu-limit');
        if (prodEl) prodEl.textContent = dtuS.producing ? 'Yes' : 'No';
        if (reachEl) reachEl.textContent = dtuS.reachable ? 'Yes' : 'No';
        if (limEl) limEl.textContent = dtuS.limit_relative + '% (' + dtuS.limit_absolute + ' W)';
    }
}

// ===== Inverter Registers Renderer =====

function renderInverterRegisters(container, deviceId, deviceType) {
    container.innerHTML = '';

    // Doc links per device type
    var docLinks = {
        solaredge:
            '<a href="https://github.com/nmakel/solaredge_modbus" target="_blank" rel="noopener" class="ve-doc-link" title="SolarEdge Modbus Register Reference">SE</a>',
        opendtu:
            '<a href="https://www.opendtu.solar/" target="_blank" rel="noopener" class="ve-doc-link" title="OpenDTU Documentation">DTU</a>',
        shelly:
            '<a href="https://shelly-api-docs.shelly.cloud/" target="_blank" rel="noopener" class="ve-doc-link" title="Shelly API Documentation">Shelly</a>',
        sungrow:
            '<a href="https://github.com/bohdan-s/SunGather" target="_blank" rel="noopener" class="ve-doc-link" title="Sungrow Modbus Register Map (SunGather)">SG</a>'
    };
    var typeLink = docLinks[deviceType] || '';

    // Toolbar
    var toolbar = document.createElement('div');
    toolbar.className = 've-panel';
    toolbar.innerHTML =
        '<div class="ve-reg-toolbar">' +
        '  <h2>Register Viewer' +
        '    ' + typeLink +
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
        (device.type !== 'shelly' ?
            '<div class="ve-form-group"><label>Port</label><input type="number" class="ve-input ve-cfg-port" value="' + (device.port || 1502) + '" min="1" max="65535"></div>' +
            '<div class="ve-form-group"><label>Unit ID</label><input type="number" class="ve-input ve-cfg-unit" value="' + (device.unit_id || 1) + '" min="1" max="247"></div>'
        : '') +
        (device.type === 'shelly' ?
            '<div class="ve-form-group"><label>Generation</label><span class="ve-gen-badge">' + esc(device.shelly_gen === 'gen2' ? 'Gen2' : (device.shelly_gen === 'gen3' ? 'Gen3' : 'Gen1')) + '</span></div>' +
            '<div class="ve-form-group"><label>Rated Power (W)</label><input type="number" class="ve-input ve-cfg-rated-power" value="' + (device.rated_power || 0) + '" min="0"></div>'
        : '') +
        (device.type === 'opendtu' ?
            '<div class="ve-form-group"><label>Gateway User</label><input type="text" class="ve-input ve-cfg-gw-user" value="' + esc(device.gateway_user || '') + '" placeholder="admin (default)"></div>' +
            '<div class="ve-form-group"><label>Gateway Password</label><input type="password" class="ve-input ve-cfg-gw-pass" value="' + esc(device.gateway_password || '') + '" placeholder="openDTU42 (default)"></div>'
        : '') +
        '<div class="ve-form-group"><label>Type</label><input type="text" class="ve-input" value="' + (device.type || '') + '" readonly style="opacity:0.6"></div>' +
        (identity ? '<div class="ve-form-group"><label>Identity</label><input type="text" class="ve-input" value="' + esc(identity) + '" readonly style="opacity:0.6"></div>' : '') +
        '<div class="ve-ess-row" style="margin-top:10px">' +
        '  <label>Fronius Aggregation</label>' +
        '  <label class="ve-toggle"><input type="checkbox" class="ve-cfg-aggregate" ' + (device.aggregate !== false ? 'checked' : '') + '><span class="ve-toggle-track"></span></label>' +
        '</div>' +
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
        aggregate: device.aggregate !== false,
        throttle_enabled: device.throttle_enabled !== false,
        enabled: device.enabled !== false,
        gateway_user: device.gateway_user || '',
        gateway_password: device.gateway_password || '',
        rated_power: String(device.rated_power || 0)
    };

    var nameInput = panel.querySelector('.ve-cfg-name');
    var hostInput = panel.querySelector('.ve-cfg-host');
    var portInput = panel.querySelector('.ve-cfg-port');
    var unitInput = panel.querySelector('.ve-cfg-unit');
    var gwUserInput = panel.querySelector('.ve-cfg-gw-user');
    var gwPassInput = panel.querySelector('.ve-cfg-gw-pass');
    var rpInput = panel.querySelector('.ve-cfg-rated-power');
    var agToggle = panel.querySelector('.ve-cfg-aggregate');
    var teToggle = panel.querySelector('.ve-cfg-throttle-enabled');
    var enabledToggle = panel.querySelector('.ve-cfg-enabled');
    var savePair = panel.querySelector('.ve-cfg-save-pair');
    var saveBtn = panel.querySelector('.ve-cfg-save');
    var cancelBtn = panel.querySelector('.ve-cfg-cancel');
    var deleteBtn = panel.querySelector('.ve-cfg-delete');

    function checkDirty() {
        var dirty = nameInput.value !== originals.name ||
                    hostInput.value !== originals.host ||
                    (portInput && portInput.value !== originals.port) ||
                    (unitInput && unitInput.value !== originals.unit_id) ||
                    agToggle.checked !== originals.aggregate ||
                    teToggle.checked !== originals.throttle_enabled ||
                    (gwUserInput && gwUserInput.value !== originals.gateway_user) ||
                    (gwPassInput && gwPassInput.value !== originals.gateway_password) ||
                    (rpInput && rpInput.value !== originals.rated_power);
        savePair.style.display = dirty ? '' : 'none';
        // Highlight dirty fields
        var trackFields = [nameInput, hostInput];
        if (portInput) trackFields.push(portInput);
        if (unitInput) trackFields.push(unitInput);
        if (gwUserInput) trackFields.push(gwUserInput);
        if (gwPassInput) trackFields.push(gwPassInput);
        if (rpInput) trackFields.push(rpInput);
        trackFields.forEach(function(el) {
            var orig = el === nameInput ? originals.name : el === hostInput ? originals.host : el === portInput ? originals.port : el === unitInput ? originals.unit_id : el === gwUserInput ? originals.gateway_user : el === gwPassInput ? originals.gateway_password : el === rpInput ? originals.rated_power : '';
            if (el.value !== orig) el.classList.add('ve-input--dirty');
            else el.classList.remove('ve-input--dirty');
        });
    }

    var inputFields = [nameInput, hostInput];
    if (portInput) inputFields.push(portInput);
    if (unitInput) inputFields.push(unitInput);
    if (gwUserInput) inputFields.push(gwUserInput);
    if (gwPassInput) inputFields.push(gwPassInput);
    if (rpInput) inputFields.push(rpInput);
    inputFields.forEach(function(el) {
        el.addEventListener('input', checkDirty);
    });
    agToggle.addEventListener('change', checkDirty);
    teToggle.addEventListener('change', checkDirty);

    cancelBtn.addEventListener('click', function() {
        nameInput.value = originals.name;
        hostInput.value = originals.host;
        if (portInput) portInput.value = originals.port;
        if (unitInput) unitInput.value = originals.unit_id;
        agToggle.checked = originals.aggregate;
        teToggle.checked = originals.throttle_enabled;
        if (gwUserInput) gwUserInput.value = originals.gateway_user;
        if (gwPassInput) gwPassInput.value = originals.gateway_password;
        if (rpInput) rpInput.value = originals.rated_power;
        checkDirty();
    });

    saveBtn.addEventListener('click', function() {
        var payload = {
            name: nameInput.value.trim(),
            host: hostInput.value.trim(),
            aggregate: agToggle.checked,
            throttle_enabled: teToggle.checked
        };
        if (portInput) payload.port = parseInt(portInput.value);
        if (unitInput) payload.unit_id = parseInt(unitInput.value);
        if (gwUserInput) payload.gateway_user = gwUserInput.value.trim();
        if (gwPassInput) payload.gateway_password = gwPassInput.value.trim();
        if (rpInput) payload.rated_power = parseInt(rpInput.value) || 0;

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
            if (portInput) originals.port = String(payload.port);
            if (unitInput) originals.unit_id = String(payload.unit_id);
            originals.aggregate = payload.aggregate;
            originals.throttle_enabled = payload.throttle_enabled;
            if (gwUserInput) originals.gateway_user = payload.gateway_user || '';
            if (gwPassInput) originals.gateway_password = payload.gateway_password || '';
            if (rpInput) originals.rated_power = String(payload.rated_power || 0);
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
        name: config.venus.name || '',
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
        '<div class="ve-form-group"><label>Display Name</label><input type="text" class="ve-input ve-venus-name" value="' + esc(origVenus.name) + '" placeholder="e.g. Hallbude"></div>' +
        '<div class="ve-form-group"><label>Venus OS IP</label><input type="text" class="ve-input ve-venus-host" value="' + origVenus.host + '" placeholder="e.g. 192.168.1.1"></div>' +
        '<div class="ve-form-group"><label>MQTT Port</label><input type="number" class="ve-input ve-venus-port" value="' + origVenus.port + '" placeholder="1883" min="1" max="65535"></div>' +
        '<div class="ve-form-group"><label>Portal ID</label><input type="text" class="ve-input ve-venus-portal-id" value="' + origVenus.portal_id + '" placeholder="leave blank for auto-discovery"></div>';
    container.appendChild(cfgPanel);

    // Dirty tracking for Venus config
    var vName = cfgPanel.querySelector('.ve-venus-name');
    var vHost = cfgPanel.querySelector('.ve-venus-host');
    var vPort = cfgPanel.querySelector('.ve-venus-port');
    var vPortalId = cfgPanel.querySelector('.ve-venus-portal-id');
    var vSavePair = cfgPanel.querySelector('.ve-venus-save-pair');

    function checkVenusDirty() {
        var dirty = vName.value !== origVenus.name || vHost.value !== origVenus.host || vPort.value !== origVenus.port || vPortalId.value !== origVenus.portal_id;
        vSavePair.style.display = dirty ? '' : 'none';
        [vName, vHost, vPort, vPortalId].forEach(function(el) {
            var orig = el === vName ? origVenus.name : el === vHost ? origVenus.host : el === vPort ? origVenus.port : origVenus.portal_id;
            if (el.value !== orig) el.classList.add('ve-input--dirty');
            else el.classList.remove('ve-input--dirty');
        });
    }
    [vName, vHost, vPort, vPortalId].forEach(function(el) { el.addEventListener('input', checkVenusDirty); });

    cfgPanel.querySelector('.ve-venus-cancel').addEventListener('click', function() {
        vName.value = origVenus.name;
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
                name: vName.value.trim(),
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
                origVenus.name = payload.venus.name;
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
        '<div class="ve-form-group"><label>Publish Interval</label><select class="ve-input ve-mqtt-pub-interval">' +
        '<option value="1"' + (origMqttPub.interval_s === '1' ? ' selected' : '') + '>1s (debug)</option>' +
        '<option value="2"' + (origMqttPub.interval_s === '2' ? ' selected' : '') + '>2s</option>' +
        '<option value="5"' + (origMqttPub.interval_s === '5' ? ' selected' : '') + '>5s (default)</option>' +
        '<option value="10"' + (origMqttPub.interval_s === '10' ? ' selected' : '') + '>10s</option>' +
        '<option value="30"' + (origMqttPub.interval_s === '30' ? ' selected' : '') + '>30s</option>' +
        '<option value="60"' + (origMqttPub.interval_s === '60' ? ' selected' : '') + '>60s</option>' +
        '</select></div>';
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

    _activeDeviceContainer = container;

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
var THROTTLE_STATE_COLORS = {
    active: 'var(--ve-green)',
    throttled: 'var(--ve-orange)',
    disabled: 'var(--ve-text-dim)',
    cooldown: 'var(--ve-blue)',
    startup: 'var(--ve-blue-light)'
};

function buildVirtualPVPage(container, data) {
    var totalW = data.total_power_w || 0;
    var totalRated = data.total_rated_w || 0;
    var contributions = data.contributions || [];

    // Gauge card (same style as inverter pages)
    var gaugeCard = document.createElement('div');
    gaugeCard.className = 've-card ve-gauge-card';
    var ratedW = totalRated > 0 ? totalRated : (totalW > 0 ? totalW * 1.2 : 30000);
    var pct = Math.min(totalW / ratedW, 1.0);
    var arcLength = GAUGE_ARC_LENGTH;
    var offset = arcLength * (1 - pct);
    var gc = gaugeColor(pct);

    // Build power limit dropdowns for virtual inverter
    var clampHtml = '';
    if (ratedW > 0) {
        var ctrl = data.control || {};
        var curMinPct = ctrl.clamp_min_pct || 0;
        var curMaxPct = ctrl.clamp_max_pct != null ? ctrl.clamp_max_pct : 100;
        var steps = [];
        var maxKw = Math.round(ratedW / 1000);
        for (var kw = maxKw - 1; kw >= 1; kw--) steps.push({w: kw * 1000, label: kw + ' kW'});
        var w1pct = Math.round(ratedW * 0.01);
        var label1pct = w1pct >= 1000 ? (w1pct / 1000).toFixed(1) + ' kW' : w1pct + ' W';
        var curMinW = Math.round(curMinPct * ratedW / 100);
        var curMaxW = curMaxPct >= 100 ? ratedW : Math.round(curMaxPct * ratedW / 100);
        function _vClosestStep(watts) {
            if (watts <= w1pct) return watts === 0 ? '0' : 'min';
            var best = steps[0]; var bestD = 99999;
            for (var i = 0; i < steps.length; i++) { var d = Math.abs(steps[i].w - watts); if (d < bestD) { bestD = d; best = steps[i]; } }
            return String(best.w);
        }
        var minOpts = '';
        for (var si = 0; si < steps.length; si++) {
            var s = steps[si];
            minOpts += '<option value="' + s.w + '"' + (_vClosestStep(curMinW) === String(s.w) ? ' selected' : '') + '>' + s.label + '</option>';
        }
        minOpts += '<option value="min"' + (curMinPct === 1 ? ' selected' : '') + '>' + label1pct + '</option>';
        minOpts += '<option value="0"' + (curMinPct === 0 ? ' selected' : '') + '>0 kW</option>';
        var maxOpts = '<option value="max"' + (curMaxPct >= 100 ? ' selected' : '') + '>Max</option>';
        for (var si2 = 0; si2 < steps.length; si2++) {
            var s2 = steps[si2];
            maxOpts += '<option value="' + s2.w + '"' + (curMaxPct < 100 && curMaxPct > 1 && _vClosestStep(curMaxW) === String(s2.w) ? ' selected' : '') + '>' + s2.label + '</option>';
        }
        maxOpts += '<option value="min"' + (curMaxPct === 1 ? ' selected' : '') + '>' + label1pct + '</option>';
        maxOpts += '<option value="0"' + (curMaxPct === 0 ? ' selected' : '') + '>0 kW</option>';
        clampHtml =
            '<div class="ve-gauge-clamp">' +
            '  <select class="ve-ctrl-dropdown ve-clamp-min" title="Minimum power (floor)">' + minOpts + '</select>' +
            '  <span class="ve-text-dim ve-clamp-label">Limit</span>' +
            '  <select class="ve-ctrl-dropdown ve-clamp-max" title="Maximum power (ceiling)">' + maxOpts + '</select>' +
            '</div>';
    }

    gaugeCard.innerHTML =
        '<h2 class="ve-card-title">Total Power Output</h2>' +
        '<svg viewBox="0 0 200 130" class="ve-gauge-svg">' +
        '  <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="var(--ve-border)" stroke-width="12" stroke-linecap="round"/>' +
        '  <path class="ve-gauge-fill ve-virtual-gauge-fill" d="M 20 100 A 80 80 0 0 1 180 100" fill="none" stroke="' + gc + '" stroke-width="12" stroke-linecap="round" stroke-dasharray="' + arcLength + '" stroke-dashoffset="' + offset + '"/>' +
        '  <text x="100" y="76" text-anchor="middle" fill="var(--ve-text)" font-size="32" font-weight="700" class="ve-virtual-gauge-value">' + formatW(totalW) + '</text>' +
        '  <text x="100" y="94" text-anchor="middle" fill="var(--ve-text-dim)" font-size="11">' + formatW(ratedW) + ' max</text>' +
        '  <text x="100" y="122" text-anchor="middle" fill="var(--ve-text-dim)" font-size="11">' + esc(data.virtual_name || 'Virtual PV') + '</text>' +
        '</svg>' + clampHtml;
    container.appendChild(gaugeCard);

    // Throttle info card (collapsible)
    var atCard = document.createElement('div');
    atCard.className = 've-card';
    atCard.innerHTML =
        '<details class="ve-auto-throttle-info">' +
        '  <summary>Wie funktioniert die Leistungsverteilung?</summary>' +
        '  <div class="ve-auto-throttle-info-body">' +
        '    <p>Das System verteilt das Leistungslimit automatisch auf alle Inverter \u2014 basierend auf deren Throttle-Score. H\u00f6herer Score = wird zuerst gedrosselt (reagiert am schnellsten).</p>' +
        '    <ul>' +
        '      <li><strong>Schnelle Inverter zuerst drosseln:</strong> Ger\u00e4te mit hohem Score reagieren am schnellsten und werden daher priorisiert gedrosselt</li>' +
        '      <li><strong>Proportional vs. Binary:</strong> Proportionale Inverter (z.B. SolarEdge) k\u00f6nnen stufenlos gedrosselt werden. Binary-Ger\u00e4te (z.B. Shelly) werden nur ein-/ausgeschaltet</li>' +
        '      <li><strong>Selbstlernend:</strong> Das System misst die tats\u00e4chliche Reaktionszeit jedes Inverters und optimiert die Reihenfolge automatisch</li>' +
        '      <li><strong>Cooldown-Schutz:</strong> Binary-Ger\u00e4te werden nicht zu schnell hintereinander geschaltet</li>' +
        '    </ul>' +
        '    <p style="margin-top:12px"><strong>Score-Formel (0\u201310):</strong></p>' +
        '    <p style="font-family:var(--ve-mono);font-size:0.8rem;color:var(--ve-text-secondary);margin:4px 0">Score = Basis + Reaktionsbonus \u2212 Cooldown-Abzug \u2212 Startup-Abzug</p>' +
        '    <ul>' +
        '      <li><strong>Basis:</strong> 7.0 (proportional) oder 3.0 (binary)</li>' +
        '      <li><strong>Reaktionsbonus:</strong> 0\u20133.0 \u2014 je schneller der Inverter reagiert, desto h\u00f6her (3.0 \u00d7 (1 \u2212 Reaktionszeit / 10s))</li>' +
        '      <li><strong>Cooldown-Abzug:</strong> 0\u20132.0 \u2014 l\u00e4ngerer Cooldown = gr\u00f6\u00dferer Abzug (nur binary)</li>' +
        '      <li><strong>Startup-Abzug:</strong> 0\u20131.0 \u2014 l\u00e4ngere Startverz\u00f6gerung = gr\u00f6\u00dferer Abzug (nur binary)</li>' +
        '    </ul>' +
        '    <p style="color:var(--ve-text-dim);margin-top:4px;font-size:0.8rem">Klicke auf eine Zeile in der Throttle-Tabelle um den Score-Breakdown zu sehen.</p>' +
        '  </div>' +
        '</details>';
    container.appendChild(atCard);

    // Wire up virtual power limit dropdown events
    var vClampMin = gaugeCard.querySelector('.ve-clamp-min');
    var vClampMax = gaugeCard.querySelector('.ve-clamp-max');
    if (vClampMin && vClampMax) {
        var _vRatedW = ratedW;
        function _vDdPct(dd) { if (dd.value === 'max') return 100; if (dd.value === 'min') return 1; if (dd.value === '0') return 0; return Math.round(parseInt(dd.value) / _vRatedW * 100); }
        function _vDdLabel(dd) { if (dd.value === 'max') return 'Max'; return dd.options[dd.selectedIndex].text; }
        function vSendClamp() {
            var minPct = _vDdPct(vClampMin); var maxPct = _vDdPct(vClampMax);
            if (minPct > maxPct) { vClampMin.value = vClampMax.value; minPct = maxPct; }
            fetch('/api/power-clamp', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device_id: 'virtual', min_pct: minPct, max_pct: maxPct })
            }).then(function(r) { return r.json(); }).then(function(d) {
                if (d.success) showToast('Limit: ' + _vDdLabel(vClampMin) + ' – ' + _vDdLabel(vClampMax), 'success');
                else showToast(d.error || 'Failed', 'error');
            }).catch(function(e) { showToast('Error: ' + e.message, 'error'); });
        }
        vClampMin.addEventListener('change', function() { if (_vDdPct(vClampMin) > _vDdPct(vClampMax)) vClampMax.value = vClampMin.value; vSendClamp(); });
        vClampMax.addEventListener('change', function() { if (_vDdPct(vClampMin) > _vDdPct(vClampMax)) vClampMin.value = vClampMax.value; vSendClamp(); });
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
        var color = THROTTLE_STATE_COLORS[c.throttle_state] || CONTRIBUTION_COLORS[i % CONTRIBUTION_COLORS.length];

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

    // Throttle table (enhanced 6-column)
    if (contributions.length > 0) {
        var throttleCard = document.createElement('div');
        throttleCard.className = 've-card';
        throttleCard.innerHTML = '<h2 class="ve-card-title">Throttle Overview</h2>';

        var table = document.createElement('table');
        table.className = 've-throttle-table';
        var thead = '<thead><tr><th>Name</th><th>Score</th><th>Modus</th><th>Reaktion</th><th>Limit</th><th>Status</th></tr></thead>';
        var tbody = '<tbody>';
        for (var j = 0; j < contributions.length; j++) {
            var ct = contributions[j];
            var scoreVal = ct.throttle_score != null ? '<span style="font-family:var(--ve-mono)">' + ct.throttle_score.toFixed(1) + '</span>' : '--';
            var modeVal = ct.throttle_mode || '--';
            var respVal = ct.measured_response_time_s != null ? '<span style="font-family:var(--ve-mono)">' + ct.measured_response_time_s.toFixed(1) + 's</span>' : '--';
            var limitVal = ct.current_limit_pct != null ? '<span style="font-family:var(--ve-mono)">' + ct.current_limit_pct.toFixed(1) + '%</span>' : '--';
            var stateColor = THROTTLE_STATE_COLORS[ct.throttle_state] || 'var(--ve-text-dim)';
            var stateDot = '<span class="ve-throttle-state-dot" style="background:' + stateColor + '"></span>';
            tbody += '<tr>' +
                '<td>' + esc(ct.name || ct.device_id) + '</td>' +
                '<td>' + scoreVal + '</td>' +
                '<td>' + modeVal + '</td>' +
                '<td>' + respVal + '</td>' +
                '<td>' + limitVal + '</td>' +
                '<td>' + stateDot + '</td>' +
                '</tr>';
            // Score breakdown row (collapsed by default)
            var sb = ct.score_breakdown;
            if (sb) {
                var formula = '<span class="ve-mono">' + sb.base.toFixed(1) + '</span> Basis (' + ct.throttle_mode + ')';
                if (sb.response_bonus > 0) formula += ' + <span class="ve-mono">' + sb.response_bonus.toFixed(1) + '</span> Reaktionsbonus (' + sb.response_time_s.toFixed(1) + 's)';
                if (sb.cooldown_penalty > 0) formula += ' \u2212 <span class="ve-mono">' + sb.cooldown_penalty.toFixed(1) + '</span> Cooldown (' + sb.cooldown_s + 's)';
                if (sb.startup_penalty > 0) formula += ' \u2212 <span class="ve-mono">' + sb.startup_penalty.toFixed(1) + '</span> Startup (' + sb.startup_delay_s + 's)';
                formula += ' = <strong>' + ct.throttle_score.toFixed(1) + '</strong>';
                tbody += '<tr class="ve-score-breakdown-row"><td colspan="6">' + formula + '</td></tr>';
            }
        }
        tbody += '</tbody>';
        table.innerHTML = thead + tbody;

        // Toggle breakdown rows on score cell click
        table.addEventListener('click', function(e) {
            var row = e.target.closest('tr');
            if (!row || row.classList.contains('ve-score-breakdown-row')) return;
            var next = row.nextElementSibling;
            if (next && next.classList.contains('ve-score-breakdown-row')) {
                next.classList.toggle('ve-score-breakdown-row--open');
            }
        });

        throttleCard.appendChild(table);
        container.appendChild(throttleCard);
    }
}

function updateVirtualPVPage(data) {
    if (!_activeDeviceContainer) return;

    var el = _activeDeviceContainer;

    var totalW = data.total_power_w || 0;
    var totalRated = data.total_rated_w || 0;
    var contributions = data.contributions || [];

    // Update gauge
    var gaugeFill = el.querySelector('.ve-virtual-gauge-fill');
    var gaugeVal = el.querySelector('.ve-virtual-gauge-value');
    if (gaugeFill && totalRated > 0) {
        var pct = Math.min(totalW / totalRated, 1.0);
        gaugeFill.style.strokeDashoffset = GAUGE_ARC_LENGTH * (1 - pct);
        gaugeFill.style.stroke = gaugeColor(pct);
    }
    if (gaugeVal) gaugeVal.textContent = formatW(totalW);

    // Check if contribution count changed -- rebuild if so
    var segments = el.querySelectorAll('.ve-contribution-segment');
    if (segments.length !== contributions.length) {
        // Rebuild entire page
        el.innerHTML = '';
        buildVirtualPVPage(el, data);
        return;
    }

    // Update bar segments with throttle state colors
    for (var i = 0; i < segments.length && i < contributions.length; i++) {
        var pct = totalW > 0 ? (contributions[i].power_w / totalW * 100) : 0;
        segments[i].style.width = pct.toFixed(1) + '%';
        var segColor = THROTTLE_STATE_COLORS[contributions[i].throttle_state] || CONTRIBUTION_COLORS[i % CONTRIBUTION_COLORS.length];
        segments[i].style.background = segColor;
    }

    // Update legend powers and dot colors
    var legendItems = el.querySelectorAll('.ve-contribution-legend-item');
    for (var j = 0; j < legendItems.length && j < contributions.length; j++) {
        var pwrEl = legendItems[j].querySelector('.ve-contribution-legend-power');
        if (pwrEl) pwrEl.textContent = formatW(contributions[j].power_w);
        var dotEl = legendItems[j].querySelector('.ve-contribution-legend-dot');
        if (dotEl) {
            var dotColor = THROTTLE_STATE_COLORS[contributions[j].throttle_state] || CONTRIBUTION_COLORS[j % CONTRIBUTION_COLORS.length];
            dotEl.style.background = dotColor;
        }
    }

    // Update enhanced throttle table (6 columns)
    var tds = el.querySelectorAll('.ve-throttle-table tbody tr');
    for (var k = 0; k < tds.length && k < contributions.length; k++) {
        var cells = tds[k].querySelectorAll('td');
        var ck = contributions[k];
        if (cells.length >= 6) {
            cells[1].innerHTML = ck.throttle_score != null ? '<span style="font-family:var(--ve-mono)">' + ck.throttle_score.toFixed(1) + '</span>' : '--';
            cells[2].textContent = ck.throttle_mode || '--';
            cells[3].innerHTML = ck.measured_response_time_s != null ? '<span style="font-family:var(--ve-mono)">' + ck.measured_response_time_s.toFixed(1) + 's</span>' : '--';
            cells[4].innerHTML = ck.current_limit_pct != null ? '<span style="font-family:var(--ve-mono)">' + ck.current_limit_pct.toFixed(1) + '%</span>' : '--';
            var stColor = THROTTLE_STATE_COLORS[ck.throttle_state] || 'var(--ve-text-dim)';
            var stDot = cells[5].querySelector('.ve-throttle-state-dot');
            if (stDot) stDot.style.background = stColor;
        }
    }
}

// ===== Add Device Flow =====

// Add device button is now inline in the INVERTERS sidebar group header

function showAddDeviceModal() {
    var modal = document.createElement('div');
    modal.className = 've-add-modal';
    modal.innerHTML =
        '<div class="ve-add-modal-content">' +
        '  <div class="ve-add-modal-title">Add Device</div>' +
        '  <div class="ve-add-type-picker">' +
        '    <div class="ve-add-type-card" data-type="solaredge">SolarEdge Inverter</div>' +
        '    <div class="ve-add-type-card" data-type="opendtu">OpenDTU Inverter</div>' +
        '    <div class="ve-add-type-card" data-type="shelly">Shelly Device</div>' +
        '    <div class="ve-add-type-card" data-type="sungrow">Sungrow Inverter</div>' +
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
            '<div class="ve-form-group"><label>Gateway Host</label><input type="text" class="ve-input ve-add-host" placeholder="192.168.1.100"></div>' +
            '<div class="ve-form-group"><label>Username</label><input type="text" class="ve-input ve-add-gw-user" placeholder="admin (default)"></div>' +
            '<div class="ve-form-group"><label>Password</label><input type="password" class="ve-input ve-add-gw-pass" placeholder="openDTU42 (default)"></div>' +
            '<div class="ve-hint-card ve-add-auth-hint" style="display:none"></div>';
    } else if (type === 'shelly') {
        formArea.innerHTML =
            '<div class="ve-form-group"><label>Name (optional)</label><input type="text" class="ve-input ve-add-name" placeholder="e.g. Shelly Plus 1PM"></div>' +
            '<div class="ve-form-group"><label>Host IP</label><input type="text" class="ve-input ve-add-host" placeholder="192.168.1.50"></div>' +
            '<div class="ve-form-group"><label>Rated Power (W)</label><input type="number" class="ve-input ve-add-rated-power" value="" min="0" placeholder="0 (optional)"></div>' +
            '<div class="ve-hint-card ve-add-probe-hint" style="display:none"></div>';
    } else if (type === 'sungrow') {
        formArea.innerHTML =
            '<div class="ve-form-group"><label>Name (optional)</label><input type="text" class="ve-input ve-add-name" placeholder="e.g. Sungrow SG-RT"></div>' +
            '<div class="ve-form-group"><label>Host IP</label><input type="text" class="ve-input ve-add-host" placeholder="192.168.2.151"></div>' +
            '<div class="ve-form-group"><label>Port</label><input type="number" class="ve-input ve-add-port" value="502" min="1" max="65535"></div>' +
            '<div class="ve-form-group"><label>Unit ID</label><input type="number" class="ve-input ve-add-unit" value="1" min="1" max="247"></div>' +
            '<div class="ve-form-group"><label>Rated Power (W)</label><input type="number" class="ve-input ve-add-rated-power" value="8000" min="0"></div>' +
            '<div class="ve-hint-card ve-add-probe-hint" style="display:none"></div>';
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

        // OpenDTU: include gateway credentials
        if (type === 'opendtu') {
            var gwUser = formArea.querySelector('.ve-add-gw-user');
            var gwPass = formArea.querySelector('.ve-add-gw-pass');
            payload.gateway_host = host.value.trim();
            if (gwUser && gwUser.value.trim()) payload.gateway_user = gwUser.value.trim();
            if (gwPass && gwPass.value.trim()) payload.gateway_password = gwPass.value.trim();
        }

        function _doAdd() {
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
        }

        // OpenDTU: auto-test credentials before adding
        if (type === 'opendtu') {
            var authHint = formArea.querySelector('.ve-add-auth-hint');
            addBtn.disabled = true;
            addBtn.textContent = 'Testing...';
            fetch('/api/opendtu/test-auth', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    host: payload.gateway_host || payload.host,
                    user: payload.gateway_user || 'admin',
                    password: payload.gateway_password || 'openDTU42'
                })
            }).then(function(r) { return r.json(); }).then(function(result) {
                addBtn.disabled = false;
                addBtn.textContent = 'Add';
                if (result.success) {
                    if (authHint) { authHint.style.display = 'block'; authHint.className = 've-hint-card ve-hint-card--success ve-add-auth-hint'; authHint.innerHTML = '<div class="ve-hint-header">Connected — ' + result.inverters.length + ' inverter(s) found</div>'; }
                    _doAdd();
                } else {
                    if (authHint) { authHint.style.display = 'block'; authHint.className = 've-hint-card ve-add-auth-hint'; authHint.innerHTML = '<div class="ve-hint-header">' + esc(result.error) + '</div><p class="ve-hint-subtext">Please enter valid username and password.</p>'; }
                }
            }).catch(function(e) {
                addBtn.disabled = false;
                addBtn.textContent = 'Add';
                if (authHint) { authHint.style.display = 'block'; authHint.className = 've-hint-card ve-add-auth-hint'; authHint.innerHTML = '<div class="ve-hint-header">Connection failed: ' + esc(e.message) + '</div>'; }
            });
        } else if (type === 'shelly') {
            var probeHint = formArea.querySelector('.ve-add-probe-hint');
            var ratedPower = formArea.querySelector('.ve-add-rated-power');
            addBtn.disabled = true;
            addBtn.textContent = 'Probing...';
            fetch('/api/shelly/probe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ host: host.value.trim() })
            }).then(function(r) { return r.json(); }).then(function(result) {
                addBtn.disabled = false;
                addBtn.textContent = 'Add';
                if (result.success) {
                    if (probeHint) {
                        probeHint.style.display = 'block';
                        probeHint.className = 've-hint-card ve-hint-card--success ve-add-probe-hint';
                        var probeTitle = 'Detected ' + esc(result.gen_display) + ' — ' + esc(result.model);
                        if (result.switch_name) probeTitle += ' (' + esc(result.switch_name) + ')';
                        probeHint.innerHTML = '<div class="ve-hint-header">' + probeTitle + '</div>';
                    }
                    payload.shelly_gen = result.generation;
                    if (ratedPower && ratedPower.value) payload.rated_power = parseInt(ratedPower.value) || 0;
                    _doAdd();
                } else {
                    if (probeHint) {
                        probeHint.style.display = 'block';
                        probeHint.className = 've-hint-card ve-add-probe-hint';
                        probeHint.innerHTML = '<div class="ve-hint-header">Could not reach device</div><p class="ve-hint-subtext">' + esc(result.error) + '</p>';
                    }
                }
            }).catch(function(e) {
                addBtn.disabled = false;
                addBtn.textContent = 'Add';
                if (probeHint) {
                    probeHint.style.display = 'block';
                    probeHint.className = 've-hint-card ve-add-probe-hint';
                    probeHint.innerHTML = '<div class="ve-hint-header">Connection failed: ' + esc(e.message) + '</div>';
                }
            });
        } else if (type === 'sungrow') {
            var sgProbeHint = formArea.querySelector('.ve-add-probe-hint');
            var sgRatedPower = formArea.querySelector('.ve-add-rated-power');
            addBtn.disabled = true;
            addBtn.textContent = 'Probing...';
            payload.port = parseInt(port.value) || 502;
            payload.unit_id = parseInt(unit.value) || 1;
            if (sgRatedPower && sgRatedPower.value) payload.rated_power = parseInt(sgRatedPower.value) || 0;
            fetch('/api/sungrow/probe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ host: host.value.trim(), port: payload.port, unit_id: payload.unit_id })
            }).then(function(r) { return r.json(); }).then(function(result) {
                addBtn.disabled = false;
                addBtn.textContent = 'Add';
                if (result.success) {
                    if (sgProbeHint) {
                        sgProbeHint.style.display = 'block';
                        sgProbeHint.className = 've-hint-card ve-hint-card--success ve-add-probe-hint';
                        sgProbeHint.innerHTML = '<div class="ve-hint-header">Connected — ' + esc(result.model) + '</div>';
                    }
                    payload.manufacturer = result.manufacturer;
                    payload.model = result.model;
                    _doAdd();
                } else {
                    if (sgProbeHint) {
                        sgProbeHint.style.display = 'block';
                        sgProbeHint.className = 've-hint-card ve-add-probe-hint';
                        sgProbeHint.innerHTML = '<div class="ve-hint-header">Could not reach inverter</div><p class="ve-hint-subtext">' + esc(result.error) + '</p>';
                    }
                }
            }).catch(function(e) {
                addBtn.disabled = false;
                addBtn.textContent = 'Add';
                if (sgProbeHint) {
                    sgProbeHint.style.display = 'block';
                    sgProbeHint.className = 've-hint-card ve-add-probe-hint';
                    sgProbeHint.innerHTML = '<div class="ve-hint-header">Connection failed: ' + esc(e.message) + '</div>';
                }
            });
        } else {
            _doAdd();
        }
    });

    // Discover button handler
    discoverBtn.addEventListener('click', function() {
        if (type === 'shelly') {
            triggerShellyDiscover(formArea);
        } else {
            triggerAddModalScan(formArea);
        }
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

function triggerShellyDiscover(formArea) {
    var scanArea = formArea.querySelector('.ve-add-scan-area');
    var progress = formArea.querySelector('.ve-scan-progress');
    var fill = formArea.querySelector('.ve-add-scan-fill');
    var status = formArea.querySelector('.ve-add-scan-status');
    var results = formArea.querySelector('.ve-add-scan-results');

    scanArea.style.display = '';
    progress.style.display = '';
    fill.style.width = '50%';
    status.textContent = 'Scanning for Shelly devices via mDNS...';
    results.innerHTML = '';

    fetch('/api/shelly/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        progress.style.display = 'none';
        if (!data.success) {
            results.innerHTML = '<div class="ve-hint-card"><div class="ve-hint-header">' + esc(data.error) + '</div></div>';
            return;
        }
        if (data.devices.length === 0) {
            results.innerHTML = '<div class="ve-hint-card"><div class="ve-hint-header">No Shelly devices found</div><p class="ve-hint-subtext">Gen1 devices may not support mDNS discovery — enter the IP manually.</p></div>';
            return;
        }
        var html = '';
        data.devices.forEach(function(dev) {
            var genLabel = dev.generation === 'gen2' ? 'Gen2' : (dev.generation === 'gen3' ? 'Gen3' : 'Gen1');
            var displayName = dev.switch_name || dev.name || dev.model || 'Shelly';
            var subtitle = dev.switch_name ? (dev.model || dev.name) : '';
            html += '<div class="ve-scan-result">' +
                '<span class="ve-scan-result-check"><input type="checkbox" class="ve-scan-result-cb" data-host="' + esc(dev.host) + '" data-name="' + esc(displayName) + '" data-gen="' + esc(dev.generation) + '"></span>' +
                '<span class="ve-scan-result-identity">' + esc(displayName) + (subtitle ? ' <span style="color:var(--ve-text-dim);font-size:0.8rem">(' + esc(subtitle) + ')</span>' : '') + '</span>' +
                '<span class="ve-scan-result-host">' + esc(dev.host) + '</span>' +
                '<span class="ve-scan-result-unit">' + genLabel + '</span>' +
                '</div>';
        });
        results.innerHTML = html;

        // Selecting a result fills in the form
        results.querySelectorAll('.ve-scan-result-cb').forEach(function(cb) {
            cb.addEventListener('change', function() {
                if (cb.checked) {
                    // Uncheck others
                    results.querySelectorAll('.ve-scan-result-cb').forEach(function(other) {
                        if (other !== cb) other.checked = false;
                    });
                    // Fill form fields
                    var hostInput = formArea.querySelector('.ve-add-host');
                    var nameInput = formArea.querySelector('.ve-add-name');
                    if (hostInput) hostInput.value = cb.getAttribute('data-host');
                    if (nameInput && !nameInput.value) nameInput.value = cb.getAttribute('data-name');
                }
            });
        });
    })
    .catch(function(e) {
        progress.style.display = 'none';
        results.innerHTML = '<div class="ve-hint-card"><div class="ve-hint-header">Discovery failed: ' + esc(e.message) + '</div></div>';
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
        var sourceLabel = 'Device Source';
        var targetLabel = 'Proxy Output';
        if (_activeDeviceType === 'solaredge') { sourceLabel = 'SE30K Source'; targetLabel = 'Fronius Target'; }
        else if (_activeDeviceType === 'opendtu') { sourceLabel = 'OpenDTU Source'; targetLabel = 'Proxy Output'; }
        else if (_activeDeviceType === 'shelly') { sourceLabel = 'Shelly Source'; targetLabel = 'Proxy Output'; }
        headerRow.innerHTML = '<span>Addr</span><span>Name</span><span class="ve-reg-se-value">' + sourceLabel + '</span><span class="ve-reg-fronius-value">' + targetLabel + '</span><span class="ve-reg-decoded">Decoded</span>';
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

    // Config Export
    document.getElementById('btn-config-export').addEventListener('click', function() {
        window.location.href = '/api/config/export';
    });

    // Config Import
    var importBtn = document.getElementById('btn-config-import');
    var fileInput = document.getElementById('config-file-input');
    importBtn.addEventListener('click', function() { fileInput.click(); });
    fileInput.addEventListener('change', function() {
        var file = fileInput.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.onload = function(e) {
            fetch('/api/config/import', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-yaml' },
                body: e.target.result
            }).then(function(r) { return r.json(); }).then(function(d) {
                if (d.success) {
                    showToast('Config imported — restart recommended', 'success');
                    setTimeout(function() { location.reload(); }, 1500);
                } else {
                    showToast('Import failed: ' + d.error, 'error');
                }
            }).catch(function(err) { showToast('Import error: ' + err.message, 'error'); });
        };
        reader.readAsText(file);
        fileInput.value = '';  // Reset for re-import of same file
    });
});
