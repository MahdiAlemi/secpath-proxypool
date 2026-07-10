(function () {
  'use strict';

  var STATES = ['untested', 'alive', 'soft', 'flaky', 'cooling', 'revived', 'semi-revived', 'dead'];
  var state = {
    initialized: false,
    loading: false,
    monitors: {},
    selectedId: null,
    search: '',
    filter: 'all',
    editId: null,
    statusEnabled: new Set(STATES),
    timer: null,
    previewTimer: null,
    detailSequence: 0
  };

  function byId(id) { return document.getElementById(id); }
  function text(id, value) { var node = byId(id); if (node) node.textContent = value == null ? '—' : String(value); }
  function number(value) { return Number(value || 0).toLocaleString(); }
  function clamp(value, min, max) { return Math.max(min, Math.min(max, Number(value) || 0)); }
  function title(value) { return String(value || '').replace(/[_-]+/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); }); }
  function time(value) {
    if (!value) return '—';
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return '—';
    return date.toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'});
  }
  function timeAgo(value) {
    if (!value) return 'Never';
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Unknown';
    var seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (seconds < 15) return 'Just now';
    if (seconds < 60) return seconds + 's ago';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
    if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
    return Math.floor(seconds / 86400) + 'd ago';
  }
  function make(tag, className, value) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (value != null) node.textContent = value;
    return node;
  }
  async function jsonRequest(url, options) {
    var response = await authFetch(url, options || {});
    var payload = await response.json().catch(function () { return {}; });
    if (!response.ok || payload.success === false) throw new Error(payload.error || 'Request failed');
    return payload;
  }

  function monitorState(monitor) {
    monitor = monitor || {};
    var progress = monitor.progress || {};
    if (monitor.starting) return 'starting';
    if (monitor.running) return 'running';
    if (progress.paused || monitor.session_status === 'paused' || monitor.last_state === 'paused') return 'paused';
    if (monitor.last_state === 'failed' || monitor.last_state === 'interrupted') return monitor.last_state;
    if (progress.completed || monitor.session_status === 'completed') return 'completed';
    if (progress.stopped || monitor.session_status === 'stopped') return 'stopped';
    return monitor.last_state || 'idle';
  }

  function stateLabel(value) {
    var labels = {starting: 'Starting', running: 'Running', paused: 'Paused', completed: 'Completed', stopped: 'Stopped', failed: 'Failed', interrupted: 'Interrupted', idle: 'Idle'};
    return labels[value] || title(value || 'idle');
  }

  function scheduleLabel(config) {
    config = config || {};
    var mode = config.run_mode || 'once';
    if (mode === 'once') return 'Run once';
    if (mode === 'infinite') return 'Continuous · every ' + (config.interval || 60) + ' sec';
    if (mode === 'restart') return 'Restart · every ' + (config.interval || 60) + ' sec';
    if (mode === 'schedule') return title(config.schedule_days || 'daily') + ' at ' + (config.schedule_time || '00:00');
    if (mode === 'custom') return 'Every ' + (config.custom_every || 24) + ' hours';
    return title(mode);
  }

  function profileMatches(id, monitor) {
    var term = state.search.trim().toLowerCase();
    var currentState = monitorState(monitor);
    if (state.filter === 'active' && currentState !== 'running' && currentState !== 'starting') return false;
    if (state.filter === 'paused' && currentState !== 'paused') return false;
    if (state.filter === 'idle' && !['idle', 'completed', 'stopped'].includes(currentState)) return false;
    if (state.filter === 'failed' && !['failed', 'interrupted'].includes(currentState)) return false;
    if (!term) return true;
    var cfg = monitor.config || {};
    return [monitor.name, id, cfg.protocol, cfg.status, cfg.run_mode].join(' ').toLowerCase().includes(term);
  }

  function updateMetrics() {
    var ids = Object.keys(state.monitors);
    var active = 0;
    var paused = 0;
    var targets = 0;
    ids.forEach(function (id) {
      var monitor = state.monitors[id];
      var currentState = monitorState(monitor);
      if (currentState === 'running' || currentState === 'starting') active += 1;
      if (currentState === 'paused') paused += 1;
      targets += Number(monitor.proxy_count || 0);
    });
    text('validation-metric-profiles', ids.length);
    text('validation-metric-active', active);
    text('validation-metric-paused', paused);
    text('validation-metric-targets', number(targets));
  }

  function renderProfiles() {
    var list = byId('validation-profile-list');
    if (!list) return;
    var ids = Object.keys(state.monitors).filter(function (id) { return profileMatches(id, state.monitors[id]); });
    ids.sort(function (a, b) {
      var first = state.monitors[a];
      var second = state.monitors[b];
      var priority = {running: 0, starting: 1, paused: 2, failed: 3, interrupted: 3, idle: 4, completed: 5, stopped: 6};
      return (priority[monitorState(first)] || 9) - (priority[monitorState(second)] || 9) || String(first.name || a).localeCompare(String(second.name || b));
    });
    text('validation-profile-count', ids.length + (ids.length === 1 ? ' profile' : ' profiles'));
    text('validation-profile-caption', state.search || state.filter !== 'all' ? 'Filtered from ' + Object.keys(state.monitors).length : 'Latest runtime snapshot');
    list.replaceChildren();
    if (!ids.length) {
      var empty = make('div', 'validation-list-empty');
      var icon = make('span', 'validation-empty-icon', '⌁'); icon.setAttribute('aria-hidden', 'true');
      empty.append(icon, make('strong', '', Object.keys(state.monitors).length ? 'No profiles match this view' : 'No validation profiles yet'));
      empty.append(make('p', '', Object.keys(state.monitors).length ? 'Clear the search or choose a different state filter.' : 'Create a focused profile for raw imports, HTTPS readiness, Telegram, or periodic health checks.'));
      if (!Object.keys(state.monitors).length) {
        var create = make('button', 'btn btn-primary btn-sm', 'Create first profile'); create.type = 'button'; create.addEventListener('click', showAddMonitorForm); empty.append(create);
      }
      list.append(empty);
      return;
    }
    if (!state.selectedId || !ids.includes(state.selectedId)) state.selectedId = ids[0];
    ids.forEach(function (id) {
      var monitor = state.monitors[id] || {};
      var cfg = monitor.config || {};
      var currentState = monitorState(monitor);
      var button = make('button', 'validation-profile-item');
      button.type = 'button'; button.setAttribute('role', 'option'); button.setAttribute('aria-selected', id === state.selectedId ? 'true' : 'false');
      var dot = make('span', 'validation-profile-item-state'); dot.dataset.state = currentState;
      var copy = make('span', 'validation-profile-item-copy'); copy.append(make('strong', '', monitor.name || cfg.name || id), make('span', '', (cfg.protocol ? cfg.protocol.toUpperCase() : 'ALL PROTOCOLS') + ' · ' + scheduleLabel(cfg)));
      var meta = make('span', 'validation-profile-item-meta'); meta.append(make('strong', '', number(monitor.proxy_count || 0)), make('span', '', stateLabel(currentState)));
      button.append(dot, copy, meta);
      button.addEventListener('click', function () { selectProfile(id); });
      list.append(button);
    });
  }

  function actionButton(label, className, handler) {
    var button = make('button', 'btn btn-sm ' + (className || ''), label);
    button.type = 'button'; button.addEventListener('click', handler); return button;
  }

  function renderActions(id, monitor) {
    var holder = byId('validation-detail-actions');
    if (!holder) return;
    holder.replaceChildren();
    var currentState = monitorState(monitor);
    if (currentState === 'running' || currentState === 'starting') {
      holder.append(actionButton('Pause', '', function () { pauseMonitor(id); }), actionButton('Stop', 'btn-danger', function () { stopMonitor(id); }));
    } else if (currentState === 'paused') {
      holder.append(actionButton('Resume', 'btn-primary', function () { resumeMonitor(id); }), actionButton('Stop session', 'btn-danger', function () { stopMonitor(id); }));
    } else {
      holder.append(actionButton('Start validation', 'btn-primary', function () { startMonitor(id); }));
      holder.append(actionButton('Edit', '', function () { showMonitorSettings(id); }));
      holder.append(actionButton('Delete', 'btn-danger', function () { deleteMonitor(id, Boolean(monitor.service)); }));
    }
    if (monitor.service && currentState !== 'running' && currentState !== 'starting') holder.append(actionButton('Remove service', '', function () { removeMonitorService(id); }));
  }

  function renderDetail() {
    var empty = byId('validation-detail-empty');
    var detail = byId('validation-detail');
    var id = state.selectedId;
    var monitor = id ? state.monitors[id] : null;
    if (!monitor) { if (empty) empty.hidden = false; if (detail) detail.hidden = true; return; }
    if (empty) empty.hidden = true;
    if (detail) detail.hidden = false;
    var cfg = monitor.config || {};
    var currentState = monitorState(monitor);
    var progress = monitor.progress || {};
    var total = Number(progress.total || monitor.proxy_count || 0);
    var tested = Number(progress.tested || 0);
    var percent = clamp(progress.percent != null ? progress.percent : (total ? tested / total * 100 : 0), 0, 100);
    var stateMark = byId('validation-detail-state-mark'); if (stateMark) stateMark.dataset.state = currentState;
    text('validation-detail-eyebrow', 'Profile · ' + stateLabel(currentState));
    text('validation-detail-name', monitor.name || cfg.name || id);
    text('validation-detail-summary', (cfg.protocol ? cfg.protocol.toUpperCase() : 'All protocols') + ' · ' + scheduleLabel(cfg) + ' · ' + number(monitor.proxy_count || 0) + ' candidates');
    renderActions(id, monitor);

    var ring = byId('validation-progress-ring'); if (ring) ring.style.setProperty('--progress', percent.toFixed(1));
    text('validation-progress-percent', Math.round(percent) + '%');
    text('validation-progress-state', stateLabel(progress.state || currentState));
    text('validation-progress-timing', monitor.running ? 'Started ' + timeAgo(monitor.start_time) : (monitor.end_time ? 'Finished ' + timeAgo(monitor.end_time) : 'No completed runtime'));
    var bar = byId('validation-progress-bar'); if (bar) bar.style.width = percent + '%';
    text('validation-progress-tested', number(tested) + ' / ' + number(total));
    text('validation-progress-alive', number(progress.alive || 0));
    text('validation-progress-dead', number(progress.dead || 0));
    text('validation-progress-other', number(progress.other || 0));

    text('validation-rule-protocols', cfg.protocol ? cfg.protocol.toUpperCase().replaceAll(',', ', ') : 'All protocols');
    text('validation-rule-statuses', cfg.status ? title(cfg.status.replaceAll(',', ', ')) : 'All statuses');
    text('validation-rule-targets', number(monitor.proxy_count || 0) + ' proxies');
    text('validation-rule-probes', cfg.probes || 2);
    text('validation-rule-threads', (cfg.threads || 50) + ' threads');
    text('validation-rule-timeout', (cfg.timeout || 5) + ' seconds');
    text('validation-rule-schedule', scheduleLabel(cfg));
    text('validation-rule-geo', String(cfg.geo) === 'false' ? 'Disabled' : 'Enabled');
    var edit = byId('validation-edit-button'); if (edit) { edit.disabled = ['running', 'starting', 'paused'].includes(currentState); edit.onclick = function () { showMonitorSettings(id); }; }

    var badge = byId('validation-runtime-badge'); if (badge) { badge.dataset.state = currentState; badge.textContent = stateLabel(currentState); }
    text('validation-runtime-process', monitor.running ? 'PID ' + (monitor.pid || '—') : (monitor.starting ? 'Claim reserved' : 'No active process'));
    text('validation-runtime-service', monitor.service || 'Not installed');
    text('validation-runtime-started', time(monitor.start_time));
    text('validation-runtime-finished', time(monitor.end_time));
    text('validation-runtime-memory', monitor.running ? Number(monitor.memory_mb || 0).toFixed(1) + ' MB' : '—');
    text('validation-runtime-error', monitor.last_error || 'None');
    loadDetailData(id);
  }

  function renderResults(payload, id, sequence) {
    if (sequence !== state.detailSequence || id !== state.selectedId) return;
    var body = byId('validation-results-body'); if (!body) return;
    body.replaceChildren();
    var results = payload.results || [];
    text('validation-results-caption', results.length ? results.length + ' recent results' : 'No session results');
    if (!results.length) {
      var row = document.createElement('tr'); var cell = make('td', 'validation-table-empty', 'No results available.'); cell.colSpan = 6; row.append(cell); body.append(row); return;
    }
    results.forEach(function (result) {
      var row = document.createElement('tr');
      var endpoint = document.createElement('td'); endpoint.append(make('strong', '', (result.protocol || '').toUpperCase() + ' ' + result.endpoint));
      var statusCell = document.createElement('td'); var status = make('span', 'validation-result-status', title(result.status)); status.dataset.status = result.status || 'untested'; statusCell.append(status);
      var latency = make('td', '', result.speed_ms == null ? '—' : result.speed_ms + ' ms');
      var capsCell = document.createElement('td'); var caps = make('div', 'validation-result-caps');
      [['HTTPS', result.web_https_ok], ['DNS', result.remote_dns_ok], ['TG', result.telegram_ok]].forEach(function (item) { var cap = make('span', 'validation-result-cap' + (item[1] ? ' is-ready' : ''), item[0]); caps.append(cap); }); capsCell.append(caps);
      var location = make('td', '', result.country_code || '—');
      var tested = make('td', '', timeAgo(result.tested_at || result.last_checked));
      row.append(endpoint, statusCell, latency, capsCell, location, tested); body.append(row);
    });
  }

  function renderLog(payload, id, sequence) {
    if (sequence !== state.detailSequence || id !== state.selectedId) return;
    var output = byId('validation-log-output'); if (!output) return;
    var lines = payload.lines || [];
    output.textContent = lines.length ? lines.join('').trimEnd() : 'No log output yet.';
    output.scrollTop = output.scrollHeight;
  }

  async function loadDetailData(id) {
    var sequence = ++state.detailSequence;
    await Promise.allSettled([
      jsonRequest('/api/monitor/' + encodeURIComponent(id) + '/results?limit=25').then(function (payload) { renderResults(payload, id, sequence); }),
      jsonRequest('/api/monitor/log?monitor_id=' + encodeURIComponent(id)).then(function (payload) { renderLog(payload, id, sequence); })
    ]);
  }

  function selectProfile(id) {
    if (!state.monitors[id]) return;
    state.selectedId = id;
    renderProfiles();
    renderDetail();
  }

  async function refresh(showFeedback) {
    if (state.loading) return;
    state.loading = true;
    try {
      var payload = await jsonRequest('/api/monitor');
      state.monitors = payload.monitors || {};
      updateMetrics(); renderProfiles(); renderDetail();
      if (showFeedback && typeof showAlert === 'function') showAlert('Validation snapshot refreshed');
    } catch (error) {
      text('validation-profile-caption', 'Could not load validation profiles');
      if (showFeedback && typeof showAlert === 'function') showAlert('Error: ' + error.message);
    } finally { state.loading = false; }
  }

  function setStatusButtons() {
    STATES.forEach(function (status) {
      var button = byId('monitor-status-' + status);
      if (!button) return;
      var enabled = state.statusEnabled.has(status);
      button.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    });
  }

  function toggleMonitorStatus(status) {
    if (!STATES.includes(status)) return;
    if (state.statusEnabled.has(status)) state.statusEnabled.delete(status); else state.statusEnabled.add(status);
    if (!state.statusEnabled.size) state.statusEnabled.add(status);
    setStatusButtons(); schedulePreview();
  }

  function toggleRunModeOptions() {
    var mode = byId('monitor-run-mode') ? byId('monitor-run-mode').value : 'once';
    var interval = byId('interval-option'); var schedule = byId('schedule-option'); var custom = byId('custom-option');
    if (interval) interval.hidden = !['infinite', 'restart'].includes(mode);
    if (schedule) schedule.hidden = mode !== 'schedule';
    if (custom) custom.hidden = mode !== 'custom';
    schedulePreview();
  }

  function formPayload() {
    var selected = STATES.filter(function (status) { return state.statusEnabled.has(status); });
    return {
      monitor_id: state.editId,
      name: (byId('monitor-name').value || '').trim(),
      protocol: byId('monitor-protocol').value,
      status: selected.length === STATES.length ? '' : selected.join(','),
      check_urls: (byId('monitor-check-urls').value || '').trim(),
      threads: Number(byId('monitor-threads').value || 50),
      timeout: Number(byId('monitor-timeout').value || 5),
      probes: Number(byId('monitor-probes').value || 2),
      run_mode: byId('monitor-run-mode').value,
      interval: Number(byId('monitor-interval').value || 60),
      schedule_time: byId('monitor-schedule-time').value,
      schedule_days: byId('monitor-schedule-days').value,
      custom_every: Number(byId('monitor-custom-every').value || 24),
      geo: byId('monitor-geo').value,
      create_service: byId('monitor-create-service').value
    };
  }

  function previewPlaceholder(message) {
    text('validation-preview-total', '—'); text('validation-preview-https', '—'); text('validation-preview-dns', '—'); text('validation-preview-telegram', '—'); text('validation-preview-state', message);
    var protocols = byId('validation-preview-protocols'); var statuses = byId('validation-preview-statuses'); var samples = byId('validation-preview-samples');
    if (protocols) protocols.replaceChildren(make('span', '', '—')); if (statuses) statuses.replaceChildren(make('span', '', '—')); if (samples) samples.replaceChildren(make('span', '', 'No preview yet.'));
  }

  function renderPreview(preview) {
    preview = preview || {};
    text('validation-preview-total', number(preview.total || 0));
    text('validation-preview-state', preview.total ? 'Ready to validate this candidate set' : 'No proxies match these rules');
    text('validation-preview-https', number((preview.capabilities || {}).web_https || 0));
    text('validation-preview-dns', number((preview.capabilities || {}).remote_dns || 0));
    text('validation-preview-telegram', number((preview.capabilities || {}).telegram || 0));
    [['validation-preview-protocols', preview.protocols || {}], ['validation-preview-statuses', preview.statuses || {}]].forEach(function (item) {
      var holder = byId(item[0]); if (!holder) return; holder.replaceChildren();
      var keys = Object.keys(item[1]); if (!keys.length) holder.append(make('span', '', 'None'));
      keys.forEach(function (key) { holder.append(make('span', '', title(key) + ' · ' + number(item[1][key]))); });
    });
    var samples = byId('validation-preview-samples'); if (!samples) return; samples.replaceChildren();
    if (!(preview.samples || []).length) samples.append(make('span', '', 'No sample candidates.'));
    (preview.samples || []).forEach(function (sample) { var row = make('div', 'validation-preview-sample'); row.append(make('code', '', (sample.protocol || '').toUpperCase() + ' ' + sample.endpoint), make('span', '', sample.status || 'untested')); samples.append(row); });
  }

  async function previewProfile() {
    var payload = formPayload();
    if (!payload.name) { previewPlaceholder('Enter a profile name to preview'); return; }
    text('validation-preview-state', 'Calculating candidate pool…');
    try { var response = await jsonRequest('/api/monitor/preview', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}); renderPreview(response.preview); }
    catch (error) { previewPlaceholder(error.message); }
  }

  function schedulePreview() { clearTimeout(state.previewTimer); state.previewTimer = setTimeout(previewProfile, 260); }

  function resetForm() {
    state.editId = null; state.statusEnabled = new Set(STATES);
    byId('monitor-name').value = ''; byId('monitor-protocol').value = ''; byId('monitor-check-urls').value = '';
    byId('monitor-threads').value = 50; byId('monitor-timeout').value = 5; byId('monitor-probes').value = 2;
    byId('monitor-run-mode').value = 'once'; byId('monitor-interval').value = 60; byId('monitor-schedule-time').value = ''; byId('monitor-schedule-days').value = 'daily'; byId('monitor-custom-every').value = 24;
    byId('monitor-geo').value = 'true'; byId('monitor-create-service').value = 'no';
    text('validation-profile-modal-title', 'Create profile'); text('validation-profile-submit', 'Create profile'); text('validation-profile-form-status', ''); text('validation-preview-title', 'Configure the profile');
    setStatusButtons(); toggleRunModeOptions(); previewPlaceholder('Waiting for valid settings');
  }

  function showAddMonitorForm() { resetForm(); openModal('modal-add-monitor'); setTimeout(function () { byId('monitor-name').focus(); }, 30); }

  function showMonitorSettings(id) {
    var monitor = state.monitors[id]; if (!monitor) return;
    var cfg = monitor.config || {}; state.editId = id;
    byId('monitor-name').value = monitor.name || cfg.name || ''; byId('monitor-protocol').value = cfg.protocol || ''; byId('monitor-check-urls').value = cfg.check_urls || '';
    byId('monitor-threads').value = cfg.threads || 50; byId('monitor-timeout').value = cfg.timeout || 5; byId('monitor-probes').value = cfg.probes || 2;
    byId('monitor-run-mode').value = cfg.run_mode || 'once'; byId('monitor-interval').value = cfg.interval || 60; byId('monitor-schedule-time').value = cfg.schedule_time || ''; byId('monitor-schedule-days').value = cfg.schedule_days || 'daily'; byId('monitor-custom-every').value = cfg.custom_every || 24;
    byId('monitor-geo').value = String(cfg.geo == null ? 'true' : cfg.geo); byId('monitor-create-service').value = cfg.create_service || 'no';
    var saved = String(cfg.status || '').split(',').filter(Boolean); state.statusEnabled = new Set(saved.length ? saved : STATES);
    text('validation-profile-modal-title', 'Edit profile'); text('validation-profile-submit', 'Save changes'); text('validation-profile-form-status', 'Changes are blocked while a session is active or paused.'); text('validation-preview-title', monitor.name || 'Profile preview');
    setStatusButtons(); toggleRunModeOptions(); openModal('modal-add-monitor'); schedulePreview();
  }

  async function createMonitorProfile() {
    var payload = formPayload(); var submit = byId('validation-profile-submit');
    if (!payload.name) { text('validation-profile-form-status', 'Profile name is required.'); byId('monitor-name').focus(); return; }
    submit.disabled = true; text('validation-profile-form-status', state.editId ? 'Saving profile…' : 'Creating profile…');
    try {
      var endpoint = state.editId ? '/api/monitor/update' : '/api/monitor/create';
      var response = await jsonRequest(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
      closeModal('modal-add-monitor'); state.selectedId = response.monitor_id; await refresh(false);
      showAlert(state.editId ? 'Validation profile updated' : 'Validation profile created');
    } catch (error) { text('validation-profile-form-status', error.message); }
    finally { submit.disabled = false; }
  }

  async function mutate(endpoint, id, successMessage) {
    try { await jsonRequest(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({monitor_id: id})}); await refresh(false); if (successMessage) showAlert(successMessage); }
    catch (error) { showAlert('Error: ' + error.message); }
  }

  function startMonitor(id) { showConfirm('Start validation', 'Start this validation profile now?', function () { mutate('/api/monitor/start', id, 'Validation started'); }, {confirmText: 'Start', confirmClass: 'btn-primary'}); }
  function pauseMonitor(id) { mutate('/api/monitor/pause', id, 'Validation paused'); }
  function resumeMonitor(id) { mutate('/api/monitor/resume', id, 'Validation resumed'); }
  function stopMonitor(id) { showConfirm('Stop session', 'Stop this session gracefully? Starting again will create a fresh run.', function () { mutate('/api/monitor/stop', id, 'Validation stopped'); }, {confirmText: 'Stop', confirmClass: 'btn-danger'}); }
  function deleteMonitor(id, hasService) { showConfirm('Delete validation profile', (hasService ? 'The attached system service will also be removed. ' : '') + 'This removes the profile, its current progress, and its log.', async function () { await mutate('/api/monitor/delete', id, 'Validation profile deleted'); if (state.selectedId === id) state.selectedId = null; await refresh(false); }, {confirmText: 'Delete', confirmClass: 'btn-danger'}); }
  function removeMonitorService(id) { showConfirm('Remove system service', 'Remove the systemd service while keeping this validation profile?', function () { mutate('/api/monitor/remove-service', id, 'System service removed'); }, {confirmText: 'Remove', confirmClass: 'btn-danger'}); }

  function init() {
    if (!state.initialized) {
      state.initialized = true;
      var search = byId('validation-profile-search'); if (search) search.addEventListener('input', function () { state.search = search.value; renderProfiles(); renderDetail(); });
      var filter = byId('validation-state-filter'); if (filter) filter.addEventListener('change', function () { state.filter = filter.value; renderProfiles(); renderDetail(); });
      STATES.forEach(function (status) { var button = byId('monitor-status-' + status); if (button) button.addEventListener('click', function () { toggleMonitorStatus(status); }); });
      ['monitor-name', 'monitor-protocol', 'monitor-check-urls', 'monitor-threads', 'monitor-timeout', 'monitor-probes', 'monitor-interval', 'monitor-schedule-time', 'monitor-schedule-days', 'monitor-custom-every', 'monitor-geo'].forEach(function (id) { var input = byId(id); if (input) input.addEventListener('input', schedulePreview); });
      var logRefresh = byId('validation-log-refresh'); if (logRefresh) logRefresh.addEventListener('click', function () { if (state.selectedId) loadDetailData(state.selectedId); });
      state.timer = window.setInterval(function () { if (document.body.dataset.activeTab === 'monitor' && !document.hidden) refresh(false); }, 4000);
    }
    refresh(false);
  }

  window.ValidationWorkspace = {init: init, refresh: refresh, select: selectProfile};
  window.checkMonitorStatus = function () { return refresh(false); };
  window.showAddMonitorForm = showAddMonitorForm;
  window.showMonitorSettings = showMonitorSettings;
  window.toggleMonitorStatus = toggleMonitorStatus;
  window.toggleRunModeOptions = toggleRunModeOptions;
  window.createMonitorProfile = createMonitorProfile;
  window.startMonitor = startMonitor;
  window.pauseMonitor = pauseMonitor;
  window.resumeMonitor = resumeMonitor;
  window.stopMonitor = stopMonitor;
  window.deleteMonitor = deleteMonitor;
  window.removeMonitorService = removeMonitorService;
}());
