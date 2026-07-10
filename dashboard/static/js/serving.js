(function () {
  'use strict';

  var state = {
    initialized: false,
    loading: false,
    servers: {},
    details: {},
    selectedPort: null,
    search: '',
    filter: 'all',
    editPort: null,
    timer: null,
    previewTimer: null,
    detailSequence: 0
  };

  function byId(id) { return document.getElementById(id); }
  function text(id, value) { var node = byId(id); if (node) node.textContent = value == null ? '—' : String(value); }
  function make(tag, className, value) { var node = document.createElement(tag); if (className) node.className = className; if (value != null) node.textContent = value; return node; }
  function number(value) { return Number(value || 0).toLocaleString(); }
  function title(value) { return String(value || '').replace(/[_-]+/g, ' ').replace(/\b\w/g, function (char) { return char.toUpperCase(); }); }
  function isLocalBind(value) { return ['127.0.0.1', '::1', '[::1]', 'localhost'].includes(String(value || '').toLowerCase()); }
  function hasControl() { return typeof hasPermission !== 'function' || hasPermission('server.control'); }

  async function jsonRequest(url, options) {
    var response = await authFetch(url, options || {});
    var payload = await response.json().catch(function () { return {}; });
    if (!response.ok || payload.success === false) throw new Error(payload.error || 'Request failed');
    return payload;
  }

  function serverConfig(server) { return server && server.config ? server.config : {}; }
  function profileName(port, server) { var cfg = serverConfig(server); return cfg.name || ((cfg.protocol || server.protocol || 'http').toUpperCase() + ' route :' + port); }
  function profileState(server) { return server && server.running ? 'running' : 'stopped'; }
  function profileMatches(port, server) {
    var cfg = serverConfig(server);
    if (state.filter === 'running' && !server.running) return false;
    if (state.filter === 'stopped' && server.running) return false;
    if (state.filter === 'network' && isLocalBind(cfg.bind)) return false;
    var term = state.search.trim().toLowerCase();
    if (!term) return true;
    return [profileName(port, server), port, cfg.protocol, cfg.bind, cfg.use_case, cfg.rotate].join(' ').toLowerCase().includes(term);
  }

  function updateMetrics() {
    var ports = Object.keys(state.servers);
    var running = 0;
    var protectedCount = 0;
    ports.forEach(function (port) {
      var server = state.servers[port];
      var cfg = serverConfig(server);
      if (server.running) running += 1;
      if (isLocalBind(cfg.bind) || cfg.has_auth) protectedCount += 1;
    });
    text('serving-metric-profiles', ports.length);
    text('serving-metric-running', running);
    text('serving-metric-protected', protectedCount);
    var detail = state.selectedPort ? state.details[state.selectedPort] : null;
    text('serving-metric-candidates', detail && detail.candidates ? number(detail.candidates.total) : '0');
  }

  function renderProfiles() {
    var list = byId('serving-profile-list');
    if (!list) return;
    var allPorts = Object.keys(state.servers);
    var ports = allPorts.filter(function (port) { return profileMatches(port, state.servers[port]); });
    ports.sort(function (a, b) {
      var first = state.servers[a];
      var second = state.servers[b];
      if (Boolean(first.running) !== Boolean(second.running)) return first.running ? -1 : 1;
      return profileName(a, first).localeCompare(profileName(b, second));
    });
    text('serving-profile-count', ports.length + (ports.length === 1 ? ' profile' : ' profiles'));
    text('serving-profile-caption', state.search || state.filter !== 'all' ? 'Filtered from ' + allPorts.length : 'Latest runtime snapshot');
    list.replaceChildren();

    if (!ports.length) {
      var empty = make('div', 'serving-list-empty');
      empty.append(make('strong', '', allPorts.length ? 'No profiles match this view' : 'No server profiles yet'));
      empty.append(make('p', '', allPorts.length ? 'Clear the search or select another state.' : 'Create a controlled local listener after validating your candidate pool.'));
      if (!allPorts.length && hasControl()) {
        var button = make('button', 'btn btn-primary btn-sm', 'Create first server');
        button.type = 'button'; button.addEventListener('click', showAddServerForm); empty.append(button);
      }
      list.append(empty);
      state.selectedPort = null;
      renderDetail();
      return;
    }

    if (!state.selectedPort || !ports.includes(state.selectedPort)) state.selectedPort = ports[0];
    ports.forEach(function (port) {
      var server = state.servers[port];
      var cfg = serverConfig(server);
      var button = make('button', 'serving-profile-item');
      button.type = 'button'; button.setAttribute('role', 'option'); button.setAttribute('aria-selected', state.selectedPort === port ? 'true' : 'false');
      var dot = make('span', 'serving-profile-state'); dot.dataset.state = profileState(server);
      var copy = make('span', 'serving-profile-copy'); copy.append(make('strong', '', profileName(port, server)), make('span', '', (cfg.protocol || server.protocol || 'http').toUpperCase() + ' · ' + (cfg.bind || '127.0.0.1') + ':' + port));
      var meta = make('span', 'serving-profile-meta'); meta.append(make('strong', '', server.running ? 'Running' : 'Stopped'), make('span', '', title(cfg.use_case || cfg.rotate || 'custom')));
      button.append(dot, copy, meta);
      button.addEventListener('click', function () { selectProfile(port); });
      list.append(button);
    });
  }

  function actionButton(label, className, handler) {
    var button = make('button', 'btn btn-sm ' + (className || ''), label);
    button.type = 'button'; button.addEventListener('click', handler); return button;
  }

  function renderActions(port, detail) {
    var holder = byId('serving-detail-actions');
    if (!holder) return;
    holder.replaceChildren();
    if (!hasControl()) return;
    if (detail.running) {
      holder.append(actionButton('Stop server', 'btn-danger', function () { stopServer(port); }));
    } else {
      holder.append(actionButton('Start server', 'btn-primary', function () { startServer(port); }));
      holder.append(actionButton('Edit', '', function () { showServerSettings(port); }));
      holder.append(actionButton('Delete', 'btn-danger', function () { deleteServer(port); }));
    }
  }

  function definition(label, value) {
    var wrapper = make('div'); wrapper.append(make('dt', '', label), make('dd', '', value == null || value === '' ? '—' : String(value))); return wrapper;
  }

  function capability(label, enabled) {
    var node = make('span', 'serving-capability', (enabled ? '✓ ' : '— ') + label); node.dataset.enabled = enabled ? 'true' : 'false'; return node;
  }

  function renderChips(holder, values, emptyLabel) {
    if (!holder) return;
    holder.replaceChildren();
    var entries = Object.entries(values || {}).filter(function (entry) { return Number(entry[1]) > 0; });
    if (!entries.length) { holder.append(make('span', 'serving-chip', emptyLabel || 'No data')); return; }
    entries.forEach(function (entry) { var chip = make('span', 'serving-chip', title(entry[0])); chip.append(make('strong', '', number(entry[1]))); holder.append(chip); });
  }

  function renderSamples(holder, samples) {
    if (!holder) return;
    holder.replaceChildren();
    if (!samples || !samples.length) { holder.append(make('span', '', 'No candidates match this profile.')); return; }
    samples.forEach(function (proxy) {
      var row = make('div', 'serving-candidate-item');
      row.append(make('code', '', (proxy.protocol || 'http') + '://' + (proxy.ip || proxy.host || 'unknown') + ':' + proxy.port));
      row.append(make('span', '', proxy.cost != null ? 'cost ' + proxy.cost : (proxy.status || 'candidate')));
      holder.append(row);
    });
  }

  function renderDetail() {
    var empty = byId('serving-detail-empty');
    var panel = byId('serving-detail');
    var port = state.selectedPort;
    var detail = port ? state.details[port] : null;
    if (!detail) { if (empty) empty.hidden = false; if (panel) panel.hidden = true; updateMetrics(); return; }
    if (empty) empty.hidden = true;
    if (panel) panel.hidden = false;
    var cfg = detail.config || {};
    var candidates = detail.candidates || {};
    var endpoint = detail.endpoint || {};
    var stateNode = byId('serving-detail-state');
    if (stateNode) { stateNode.dataset.state = detail.running ? 'running' : 'stopped'; stateNode.textContent = detail.running ? 'Running' : 'Stopped'; }
    text('serving-detail-name', cfg.name || ((detail.protocol || 'http').toUpperCase() + ' route :' + port));
    text('serving-detail-subtitle', title(cfg.use_case || 'custom') + ' · ' + (detail.protocol || 'http').toUpperCase() + ' listener on ' + (cfg.bind || '127.0.0.1') + ':' + port);
    text('serving-endpoint', endpoint.uri || '—');
    text('serving-endpoint-note', endpoint.scope === 'network' ? (endpoint.has_auth ? 'Network listener protected by client authentication.' : 'Network listener with explicit no-auth exposure.') : 'Loopback listener available only to this host.');
    var copyButton = byId('serving-copy-endpoint'); if (copyButton) copyButton.onclick = function () { if (endpoint.uri) copyProxy(endpoint.uri); };
    text('serving-detail-candidates', number(candidates.total));
    text('serving-detail-candidate-note', candidates.total ? 'Ready for runtime selection' : 'Start will serve 503 until candidates exist');
    text('serving-detail-rotation', title(cfg.rotate || 'better_cost'));
    text('serving-detail-rotation-note', cfg.rotate === 'time' ? 'Every ' + (cfg.rotate_interval || 60) + ' sec' : (cfg.sticky_upstream ? 'Pinned upstream configured' : 'Cost-aware selection'));
    text('serving-detail-auth', cfg.has_auth ? 'Protected' : (endpoint.scope === 'local' ? 'Local only' : 'No auth'));
    text('serving-detail-auth-note', cfg.auth_required ? 'Upstream: ' + title(cfg.auth_required) : 'Any upstream authentication');
    text('serving-detail-process', detail.running ? 'PID ' + (detail.pid || '—') : 'Offline');
    text('serving-detail-process-note', detail.running ? 'Listener process is active' : 'Profile saved, process stopped');

    var policy = byId('serving-policy-list');
    if (policy) {
      policy.replaceChildren(
        definition('Listener', (detail.protocol || 'http').toUpperCase() + ' · ' + (cfg.bind || '127.0.0.1') + ':' + port),
        definition('Workers', cfg.threads || 100),
        definition('Timeout', (cfg.timeout || 10) + ' sec'),
        definition('Cost range', (cfg.min_cost || 0) + ' → ' + (cfg.cost_threshold == null ? 'unbounded' : cfg.cost_threshold)),
        definition('Candidate status', cfg.candidate_statuses || 'alive'),
        definition('Upstream protocols', cfg.upstream_protocol || 'Any'),
        definition('Runtime writes', cfg.readonly ? 'Read only' : 'Enabled'),
        definition('Header limit', number(cfg.header_limit || 65536) + ' bytes')
      );
    }
    var capabilities = byId('serving-capability-list');
    if (capabilities) { capabilities.replaceChildren(capability('HTTPS', Boolean(cfg.require_web_https)), capability('Remote DNS', Boolean(cfg.require_remote_dns)), capability('Telegram', Boolean(cfg.require_telegram))); }
    renderChips(byId('serving-protocol-mix'), candidates.by_protocol, 'No protocol data');
    renderSamples(byId('serving-candidate-samples'), candidates.samples || []);
    var log = detail.log && detail.log.lines ? detail.log.lines.join('') : '';
    text('serving-log-output', log.trim() || 'No log output yet.');
    renderActions(port, detail);
    updateMetrics();
  }

  async function loadDetail(port, options) {
    options = options || {};
    var sequence = ++state.detailSequence;
    try {
      var detail = await jsonRequest('/api/server/' + encodeURIComponent(port));
      if (sequence !== state.detailSequence) return;
      state.details[port] = detail;
      if (state.selectedPort === String(port)) renderDetail();
    } catch (error) {
      if (!options.silent) showAlert(error.message || String(error));
    }
  }

  async function selectProfile(port) {
    state.selectedPort = String(port);
    renderProfiles();
    if (state.details[state.selectedPort]) renderDetail();
    else { text('serving-detail-name', 'Loading profile…'); await loadDetail(state.selectedPort); }
  }

  async function loadServers(options) {
    options = options || {};
    if (state.loading) return;
    state.loading = true;
    try {
      var payload = await jsonRequest('/api/server');
      state.servers = payload.servers || {};
      renderProfiles(); updateMetrics();
      if (state.selectedPort && state.servers[state.selectedPort]) await loadDetail(state.selectedPort, {silent: true});
      else renderDetail();
    } catch (error) {
      if (!options.silent) showAlert(error.message || String(error));
    } finally { state.loading = false; }
  }

  function readChecks(containerId) {
    return Array.prototype.slice.call(document.querySelectorAll('#' + containerId + ' input[type="checkbox"]:checked')).map(function (input) { return input.value; });
  }
  function setChecks(containerId, values) {
    var selected = new Set(values || []);
    document.querySelectorAll('#' + containerId + ' input[type="checkbox"]').forEach(function (input) { input.checked = selected.has(input.value); });
  }
  function value(id, fallback) { var node = byId(id); return node && node.value !== '' ? node.value : (fallback == null ? '' : fallback); }
  function checked(id) { var node = byId(id); return Boolean(node && node.checked); }

  function collectFormData() {
    var statuses = readChecks('server-status-choices');
    var protocols = readChecks('server-upstream-protocol-choices');
    return {
      name: value('server-name') || (value('server-proto', 'http').toUpperCase() + ' route :' + value('server-port', '8080')),
      use_case: value('server-use-case', 'custom'),
      protocol: value('server-proto', 'http'),
      bind: value('server-bind', '127.0.0.1'),
      port: Number(value('server-port', 8080)),
      threads: Number(value('server-threads', 100)),
      timeout: Number(value('server-timeout', 10)),
      header_limit: Number(value('server-header-limit', 65536)),
      rotate: value('server-rotate', 'better_cost'),
      rotate_interval: Number(value('server-rotate-interval', 60)),
      min_cost: Number(value('server-min-cost', 0)),
      cost_threshold: value('server-cost') === '' ? null : Number(value('server-cost')),
      username: value('server-user') || null,
      password: value('server-pass') || null,
      clear_credentials: checked('server-clear-credentials'),
      allow_public_no_auth: checked('server-allow-public-no-auth'),
      auth_required: value('server-auth-required') || null,
      certfile: value('server-certfile') || null,
      keyfile: value('server-keyfile') || null,
      sticky_upstream: value('server-sticky-upstream') || null,
      insecure_upstream: checked('server-insecure-upstream'),
      readonly: checked('server-readonly'),
      upstream_protocol: protocols.join(',') || null,
      candidate_statuses: statuses.join(',') || 'alive',
      require_web_https: checked('server-require-web-https'),
      require_remote_dns: checked('server-require-remote-dns'),
      require_telegram: checked('server-require-telegram'),
      countryCodes: value('server-country') || null,
      regions: value('server-regions') || null,
      cities: value('server-cities') || null,
      orgs: value('server-orgs') || null,
      isp: value('server-isp') || null,
      asn: value('server-asn') || null,
      continentCode: value('server-continent') || null,
      zip_codes: value('server-zip') || null,
      timezones: value('server-timezones') || null,
      mobile: value('server-mobile') || null,
      proxy: value('server-proxy') || null,
      hosting: value('server-hosting') || null,
      existing_port: state.editPort ? Number(state.editPort) : null
    };
  }

  function updatePresetButtons(preset) {
    document.querySelectorAll('#serving-preset-grid [data-preset]').forEach(function (button) { button.setAttribute('aria-pressed', button.dataset.preset === preset ? 'true' : 'false'); });
    var hidden = byId('server-use-case'); if (hidden) hidden.value = preset;
  }

  function applyPreset(preset, options) {
    options = options || {};
    updatePresetButtons(preset);
    var https = byId('server-require-web-https'); var dns = byId('server-require-remote-dns'); var telegram = byId('server-require-telegram');
    if (preset !== 'custom') {
      setChecks('server-status-choices', ['alive']);
      setChecks('server-upstream-protocol-choices', ['http', 'https', 'socks4', 'socks5']);
      if (https) https.checked = preset !== 'scraping';
      if (dns) dns.checked = preset === 'telegram';
      if (telegram) telegram.checked = preset === 'telegram';
    }
    if (!options.keepName && byId('server-name') && !byId('server-name').value.trim()) {
      var labels = {web: 'Web route — local', telegram: 'Telegram route — local', scraping: 'Scraping route — local', custom: 'Custom route'};
      byId('server-name').value = labels[preset] || labels.custom;
    }
    schedulePreview();
  }

  function resetForm() {
    var form = byId('serving-profile-form'); if (form) form.reset();
    state.editPort = null;
    text('serving-editor-title', 'Create server profile');
    text('serving-editor-subtitle', 'Define the listener, candidate pool, and route policy before starting traffic.');
    text('serving-editor-status', '');
    byId('server-port').disabled = false;
    byId('server-clear-credentials-row').hidden = true;
    byId('server-clear-credentials').checked = false;
    text('server-credential-help', 'Leave both fields blank for a loopback-only no-auth listener.');
    setChecks('server-status-choices', ['alive']);
    setChecks('server-upstream-protocol-choices', ['http', 'https', 'socks4', 'socks5']);
    applyPreset('web');
    updateProtocolFields(); updateBindWarning();
  }

  function fillForm(detail) {
    var cfg = detail.config || {};
    state.editPort = String(detail.port);
    text('serving-editor-title', 'Edit server profile');
    text('serving-editor-subtitle', 'Update the stopped listener. Existing client credentials remain unless replaced or cleared.');
    byId('server-port').disabled = true;
    var fields = {
      'server-name': cfg.name || '', 'server-use-case': cfg.use_case || 'custom', 'server-proto': cfg.protocol || detail.protocol || 'http',
      'server-bind': cfg.bind || '127.0.0.1', 'server-port': detail.port, 'server-threads': cfg.threads || 100,
      'server-timeout': cfg.timeout || 10, 'server-header-limit': cfg.header_limit || 65536, 'server-rotate': cfg.rotate || 'better_cost',
      'server-rotate-interval': cfg.rotate_interval || 60, 'server-min-cost': cfg.min_cost || 0, 'server-cost': cfg.cost_threshold == null ? '' : cfg.cost_threshold,
      'server-auth-required': cfg.auth_required || '', 'server-certfile': cfg.certfile || '', 'server-keyfile': cfg.keyfile || '',
      'server-sticky-upstream': cfg.sticky_upstream || '', 'server-country': cfg.countryCodes || '', 'server-regions': cfg.regions || '',
      'server-cities': cfg.cities || '', 'server-orgs': cfg.orgs || '', 'server-isp': cfg.isp || '', 'server-asn': cfg.asn || '',
      'server-continent': cfg.continentCode || '', 'server-zip': cfg.zip_codes || '', 'server-timezones': cfg.timezones || '',
      'server-mobile': cfg.mobile || '', 'server-proxy': cfg.proxy || '', 'server-hosting': cfg.hosting || ''
    };
    Object.keys(fields).forEach(function (id) { var node = byId(id); if (node) node.value = fields[id]; });
    byId('server-user').value = ''; byId('server-pass').value = '';
    byId('server-allow-public-no-auth').checked = Boolean(cfg.allow_public_no_auth);
    byId('server-insecure-upstream').checked = Boolean(cfg.insecure_upstream);
    byId('server-readonly').checked = Boolean(cfg.readonly);
    byId('server-require-web-https').checked = Boolean(cfg.require_web_https);
    byId('server-require-remote-dns').checked = Boolean(cfg.require_remote_dns);
    byId('server-require-telegram').checked = Boolean(cfg.require_telegram);
    setChecks('server-status-choices', String(cfg.candidate_statuses || 'alive').split(','));
    setChecks('server-upstream-protocol-choices', cfg.upstream_protocol ? String(cfg.upstream_protocol).split(',') : ['http', 'https', 'socks4', 'socks5']);
    updatePresetButtons(cfg.use_case || 'custom');
    byId('server-clear-credentials-row').hidden = !cfg.has_auth;
    text('server-credential-help', cfg.has_auth ? 'Client credentials are configured. Leave blank to preserve them, or enter a replacement pair.' : 'No client credentials are currently configured.');
    updateProtocolFields(); updateBindWarning(); schedulePreview();
  }

  function updateProtocolFields() {
    var socks4 = value('server-proto') === 'socks4';
    var password = byId('server-pass');
    if (password) { password.disabled = socks4; if (socks4) password.value = ''; password.placeholder = socks4 ? 'Not supported by SOCKS4' : 'Optional'; }
  }

  function updateBindWarning() {
    var bind = value('server-bind', '127.0.0.1');
    var local = isLocalBind(bind);
    text('server-bind-help', local ? 'Loopback is safest for local clients.' : 'Network exposure requires credentials or the explicit no-auth override.');
  }

  function previewChips(holderId, values) { renderChips(byId(holderId), values, 'None'); }

  function renderPreview(payload) {
    var status = byId('serving-preview-status'); if (status) { status.textContent = 'Ready'; status.dataset.state = 'ready'; }
    text('serving-preview-total', number(payload.total));
    var data = collectFormData(); text('serving-preview-listener', data.protocol.toUpperCase() + ' :' + data.port);
    previewChips('serving-preview-protocols', payload.by_protocol);
    previewChips('serving-preview-statuses', payload.by_status);
    var warnings = byId('serving-preview-warnings'); if (warnings) { warnings.replaceChildren(); if (payload.warnings && payload.warnings.length) payload.warnings.forEach(function (item) { warnings.append(make('div', 'serving-preview-warning', item)); }); else warnings.append(make('div', 'serving-preview-ok', 'Preflight looks good.')); }
    renderSamples(byId('serving-preview-samples'), payload.samples || []);
  }

  async function refreshPreview() {
    var status = byId('serving-preview-status'); if (status) { status.textContent = 'Checking'; status.dataset.state = ''; }
    try {
      var payload = await jsonRequest('/api/server/preview-candidates', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(collectFormData())});
      renderPreview(payload);
    } catch (error) {
      if (status) { status.textContent = 'Needs attention'; status.dataset.state = 'error'; }
      text('serving-preview-total', '—');
      var warnings = byId('serving-preview-warnings'); if (warnings) { warnings.replaceChildren(make('div', 'serving-preview-warning', error.message || String(error))); }
    }
  }

  function schedulePreview() { clearTimeout(state.previewTimer); state.previewTimer = setTimeout(refreshPreview, 300); }

  function showAddServerForm() {
    if (!hasControl()) return showAlert('You do not have permission to manage server profiles.');
    resetForm(); openModal('modal-add-server'); schedulePreview();
  }

  async function showServerSettings(port) {
    if (!hasControl()) return;
    try {
      var detail = state.details[String(port)] || await jsonRequest('/api/server/' + encodeURIComponent(port));
      if (detail.running) return showAlert('Stop the server before editing its profile.');
      resetForm(); fillForm(detail); openModal('modal-add-server');
    } catch (error) { showAlert(error.message || String(error)); }
  }

  async function saveProfile(startAfter) {
    var form = byId('serving-profile-form');
    if (form && !form.reportValidity()) return;
    var saveButton = byId('serving-save-button'); var startButton = byId('serving-save-start-button');
    if (saveButton) saveButton.disabled = true; if (startButton) startButton.disabled = true;
    text('serving-editor-status', state.editPort ? 'Updating profile…' : 'Creating profile…');
    try {
      var body = collectFormData();
      var endpoint = state.editPort ? '/api/server/update' : '/api/server/create';
      var result = await jsonRequest(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      var port = String(result.port || state.editPort || body.port);
      if (startAfter) {
        text('serving-editor-status', 'Starting listener…');
        await jsonRequest('/api/server/start', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({port: Number(port)})});
      }
      closeModal('modal-add-server'); state.selectedPort = port; delete state.details[port];
      showAlert(startAfter ? 'Server profile saved and started.' : 'Server profile saved.');
      await loadServers();
    } catch (error) { text('serving-editor-status', error.message || String(error)); showAlert(error.message || String(error)); }
    finally { if (saveButton) saveButton.disabled = false; if (startButton) startButton.disabled = false; }
  }

  async function performStart(port) {
    try {
      await jsonRequest('/api/server/start', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({port: Number(port)})});
      delete state.details[String(port)]; showAlert('Server on port ' + port + ' started.'); await loadServers();
    } catch (error) { showAlert(error.message || String(error)); }
  }

  function startServer(port) {
    var detail = state.details[String(port)];
    if (detail && detail.candidates && Number(detail.candidates.total || 0) === 0) {
      showConfirm('Start without candidates?', 'This profile currently matches no upstream proxies. The listener can start, but client requests will receive 503 until the pool is ready.', function () { performStart(port); }, {confirmText: 'Start anyway', confirmClass: 'btn-primary'});
      return;
    }
    performStart(port);
  }

  function stopServer(port) {
    showConfirm('Stop server', 'Stop the listener on port ' + port + '? Existing connections will be terminated.', async function () {
      try { await jsonRequest('/api/server/stop', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({port: Number(port)})}); delete state.details[String(port)]; showAlert('Server stopped.'); await loadServers(); }
      catch (error) { showAlert(error.message || String(error)); }
    }, {confirmText: 'Stop server', confirmClass: 'btn-danger'});
  }

  function deleteServer(port) {
    showConfirm('Delete server profile', 'Delete the stopped profile on port ' + port + '? Log files are not removed.', async function () {
      try { await jsonRequest('/api/server/delete', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({port: Number(port)})}); delete state.details[String(port)]; state.selectedPort = null; showAlert('Server profile deleted.'); await loadServers(); }
      catch (error) { showAlert(error.message || String(error)); }
    });
  }

  async function refreshSelectedDetail() { if (state.selectedPort) { delete state.details[state.selectedPort]; await loadDetail(state.selectedPort); } }

  function bindEvents() {
    var search = byId('serving-search'); if (search) search.addEventListener('input', function () { state.search = search.value; renderProfiles(); });
    var filter = byId('serving-state-filter'); if (filter) filter.addEventListener('change', function () { state.filter = filter.value; renderProfiles(); });
    document.querySelectorAll('#serving-preset-grid [data-preset]').forEach(function (button) { button.addEventListener('click', function () { applyPreset(button.dataset.preset); }); });
    var form = byId('serving-profile-form'); if (form) {
      form.addEventListener('input', function (event) { if (event.target.id === 'server-bind') updateBindWarning(); if (event.target.id === 'server-proto') updateProtocolFields(); if (!event.target.closest('#serving-preset-grid')) { if (['server-require-web-https','server-require-remote-dns','server-require-telegram'].includes(event.target.id)) updatePresetButtons('custom'); schedulePreview(); } });
      form.addEventListener('change', schedulePreview);
      form.addEventListener('submit', function (event) { event.preventDefault(); saveProfile(false); });
    }
    var save = byId('serving-save-button'); if (save) save.addEventListener('click', function () { saveProfile(false); });
    var saveStart = byId('serving-save-start-button'); if (saveStart) saveStart.addEventListener('click', function () { saveProfile(true); });
    var refreshPreflight = byId('serving-refresh-preflight'); if (refreshPreflight) refreshPreflight.addEventListener('click', refreshSelectedDetail);
    var refreshLog = byId('serving-refresh-log'); if (refreshLog) refreshLog.addEventListener('click', refreshSelectedDetail);
  }

  function init() {
    if (!state.initialized) {
      state.initialized = true; bindEvents();
      if (!hasControl()) { var create = byId('serving-create-button'); if (create) create.hidden = true; }
      state.timer = window.setInterval(function () { if (window.currentTab === 'server') loadServers({silent: true}); }, 5000);
    }
    loadServers();
  }

  window.ServingWorkspace = {init: init, refresh: loadServers, openEditor: showAddServerForm, edit: showServerSettings};
  window.showAddServerForm = showAddServerForm;
  window.showServerSettings = showServerSettings;
  window.checkServerStatus = function () { return loadServers({silent: true}); };
  window.startServer = startServer;
  window.stopServer = stopServer;
  window.deleteServer = deleteServer;
}());
