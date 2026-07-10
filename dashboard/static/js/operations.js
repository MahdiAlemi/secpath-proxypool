(function () {
  'use strict';

  var initialized = false;

  function setText(id, value) {
    var node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function hasAllPermissions(value) {
    var required = String(value || '').split(',').map(function (item) { return item.trim(); }).filter(Boolean);
    return required.every(function (permission) {
      return typeof window.hasPermission !== 'function' || window.hasPermission(permission);
    });
  }

  function requirePermissions(value, action) {
    if (hasAllPermissions(value)) return true;
    if (typeof showAlert === 'function') showAlert('Your account does not have permission to ' + action + '.', 'Permission required');
    return false;
  }

  function applyPermissions() {
    document.querySelectorAll('#tab-operations [data-permissions]').forEach(function (node) {
      var allowed = hasAllPermissions(node.dataset.permissions);
      if ('disabled' in node) node.disabled = !allowed;
      node.setAttribute('aria-disabled', allowed ? 'false' : 'true');
      if (node.tagName === 'FORM') {
        node.querySelectorAll('input, select, button').forEach(function (control) { control.disabled = !allowed; });
      }
    });
  }

  function formatSize(value) {
    return Number(value || 0).toFixed(Number(value || 0) >= 10 ? 1 : 2) + ' MB';
  }

  function securityCheck(label, detail, ok) {
    var row = document.createElement('div');
    row.className = 'operations-check';
    row.dataset.ok = ok ? 'true' : 'false';
    var dot = document.createElement('i');
    var copy = document.createElement('div');
    var strong = document.createElement('strong'); strong.textContent = label;
    var span = document.createElement('span'); span.textContent = detail;
    copy.append(strong, span); row.append(dot, copy);
    return row;
  }

  function renderDiagnostics(data) {
    var db = data.db || {};
    var runtime = data.runtime || {};
    var backups = data.backups || {};
    var security = data.security || {};
    var access = data.access || {};

    var dbOk = db.type !== 'sqlite' || db.sqlite_exists;
    setText('operations-db-state', dbOk ? String(db.type || 'DB').toUpperCase() + ' ready' : 'Missing');
    setText('operations-db-detail', db.type === 'sqlite' ? formatSize(db.sqlite_size_mb) : 'External database');

    var securityOk = security.flask_secret_configured && security.jwt_secret_configured && !security.legacy_admin_configured;
    setText('operations-security-state', securityOk ? 'Configured' : 'Action needed');
    setText('operations-security-detail', securityOk ? 'Secrets and database access are ready' : 'Review secret and legacy admin settings');

    var running = Number(runtime.running_monitors || 0) + Number(runtime.running_servers || 0);
    setText('operations-runtime-state', running ? running + ' active' : 'Idle');
    setText('operations-runtime-detail', (runtime.monitor_profiles || 0) + ' monitor · ' + (runtime.server_profiles || 0) + ' server profiles');
    setText('operations-backup-state', backups.count || 0);
    setText('operations-backup-detail', backups.latest ? 'Latest: ' + backups.latest : 'No backup created');

    var status = document.getElementById('operations-preflight-status');
    status.textContent = securityOk && dbOk ? 'Ready' : 'Review';
    status.dataset.tone = securityOk && dbOk ? 'good' : 'warn';

    var recs = document.getElementById('operations-recommendations');
    recs.innerHTML = '';
    (data.recommendations || []).forEach(function (message) {
      var row = document.createElement('div'); row.className = 'operations-recommendation';
      var dot = document.createElement('i'); var text = document.createElement('span'); text.textContent = message;
      row.append(dot, text); recs.appendChild(row);
    });

    var metrics = [
      ['Active monitors', runtime.running_monitors || 0],
      ['Active servers', runtime.running_servers || 0],
      ['Progress files', runtime.progress_files || 0],
      ['Runtime files', runtime.runtime_files || 0],
      ['Log files', runtime.log_files || 0],
      ['Log size', formatSize(runtime.log_size_mb)],
      ['Active users', access.active_users || 0],
      ['API sessions', access.active_tokens || 0]
    ];
    var grid = document.getElementById('operations-runtime-metrics'); grid.innerHTML = '';
    metrics.forEach(function (item) {
      var card = document.createElement('div'); var label = document.createElement('span'); var value = document.createElement('strong');
      label.textContent = item[0]; value.textContent = item[1]; card.append(label, value); grid.appendChild(card);
    });

    var checks = document.getElementById('operations-security-checks'); checks.innerHTML = '';
    checks.append(
      securityCheck('Flask session secret', security.flask_secret_configured ? 'Configured in the environment' : 'Missing; sessions reset on restart', security.flask_secret_configured),
      securityCheck('JWT signing secret', security.jwt_secret_configured ? 'Configured independently' : 'Missing; API tokens reset on restart', security.jwt_secret_configured),
      securityCheck('Secure session cookie', security.session_cookie_secure ? 'Enabled for HTTPS deployment' : 'Disabled for local HTTP use', security.session_cookie_secure || location.protocol !== 'https:'),
      securityCheck('Legacy administrator', security.legacy_admin_configured ? 'Environment-backed login is still enabled' : 'Database users only', !security.legacy_admin_configured)
    );
    setText('operations-updated', 'Updated ' + new Date().toLocaleTimeString());
  }

  function renderBackups(data) {
    var target = document.getElementById('operations-backup-list');
    target.innerHTML = '';
    var rows = data.backups || [];
    if (!rows.length) {
      var empty = document.createElement('div'); empty.className = 'workspace-empty'; empty.textContent = 'No database backups are stored in the project root.'; target.appendChild(empty); return;
    }
    rows.forEach(function (backup, index) {
      var row = document.createElement('div'); row.className = 'operations-backup-row';
      var copy = document.createElement('div'); var name = document.createElement('strong'); name.textContent = backup.name;
      var meta = document.createElement('span'); meta.textContent = backup.created + ' · ' + formatSize(backup.size_mb) + (index === 0 ? ' · latest' : '');
      copy.append(name, meta);
      var button = document.createElement('button'); button.className = 'btn btn-sm'; button.type = 'button'; button.textContent = 'Download';
      button.disabled = !hasAllPermissions('settings.edit,proxies.credentials');
      button.setAttribute('aria-disabled', button.disabled ? 'true' : 'false');
      button.addEventListener('click', function () {
        if (!requirePermissions('settings.edit,proxies.credentials', 'download credential-bearing backups')) return;
        window.location.href = '/api/settings/backups/' + encodeURIComponent(backup.name);
      });
      row.append(copy, button); target.appendChild(row);
    });
  }

  async function refresh() {
    setText('operations-updated', 'Loading…');
    try {
      var responses = await Promise.all([authFetch('/api/settings/diagnostics'), authFetch('/api/settings/backups')]);
      var diagnostics = await responses[0].json();
      var backups = await responses[1].json();
      if (!responses[0].ok) throw new Error(diagnostics.error || 'Could not load diagnostics');
      if (!responses[1].ok) throw new Error(backups.error || 'Could not load backups');
      renderDiagnostics(diagnostics);
      renderBackups(backups);
    } catch (error) {
      setText('operations-updated', 'Failed to load');
      if (typeof showAlert === 'function') showAlert(error.message || String(error), 'Operations unavailable');
    }
  }

  async function jsonAction(url, options) {
    var response = await authFetch(url, options || {method: 'POST'});
    var data = await response.json();
    if (!response.ok || data.success === false) throw new Error(data.error || 'Operation failed');
    return data;
  }

  function confirmAction(title, message, label, callback) {
    showConfirm(title, message, function () {
      Promise.resolve(callback()).catch(function (error) { showAlert(error.message || String(error), title + ' failed'); });
    }, {confirmText: label, confirmClass: label.toLowerCase().includes('delete') ? 'btn-danger' : 'btn-primary'});
  }

  async function createBackup() {
    if (!requirePermissions('settings.edit', 'create backups')) return;
    try {
      var data = await jsonAction('/api/settings/backup', {method: 'POST'});
      showAlert('Backup created: ' + data.file + ' (' + formatSize(data.size_mb) + ')', 'Backup complete');
      await refresh();
    } catch (error) { showAlert(error.message, 'Backup failed'); }
  }

  function restoreDatabase() {
    if (!requirePermissions('settings.edit,proxies.credentials', 'restore the database')) return;
    var input = document.getElementById('operations-restore-file');
    if (!input.files || !input.files[0]) { showAlert('Choose a backup file first.', 'Restore database'); return; }
    var file = input.files[0];
    var mode = document.getElementById('operations-restore-mode').value;
    confirmAction('Restore database', 'This replaces or imports database state. A pre-restore backup will be created automatically. Continue with ' + file.name + '?', 'Restore', async function () {
      var body = new FormData(); body.append('file', file); body.append('mode', mode);
      var response = await authFetch('/api/settings/import', {method: 'POST', body: body});
      var data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Restore failed');
      input.value = '';
      showAlert('Database restored successfully. Pre-restore backup: ' + (data.backup || 'created'), 'Restore complete');
      await refresh();
      if (window.InventoryWorkspace && window.InventoryWorkspace.refresh) window.InventoryWorkspace.refresh();
    });
  }

  function cleanupLogs() {
    if (!requirePermissions('settings.edit', 'clear logs')) return;
    confirmAction('Clear log files', 'Delete root dashboard, monitor, and server log files? The database is not affected.', 'Clear logs', async function () {
      var data = await jsonAction('/api/settings/cleanup/logs', {method: 'POST'});
      showAlert('Deleted ' + data.deleted + ' log files.', 'Cleanup complete'); await refresh();
    });
  }

  function cleanupRuntime() {
    if (!requirePermissions('settings.edit', 'clear runtime state')) return;
    confirmAction('Clear stale runtime state', 'This is blocked while a managed monitor or server is active. Continue?', 'Clear runtime', async function () {
      var data = await jsonAction('/api/settings/cleanup/runtime', {method: 'POST'});
      showAlert('Deleted ' + data.deleted + ' runtime items.', 'Cleanup complete'); await refresh();
    });
  }

  function normalizeStatuses() {
    if (!requirePermissions('settings.edit', 'normalize statuses')) return;
    confirmAction('Normalize legacy statuses', 'Convert legacy revived records to dead or soft so normal validation can classify them again?', 'Normalize', async function () {
      var data = await jsonAction('/api/settings/cleanup/legacy-statuses', {method: 'POST'});
      showAlert('Updated ' + data.updated + ' proxies.', 'Normalization complete'); await refresh();
    });
  }

  function deleteGroup() {
    if (!requirePermissions('proxies.delete', 'delete proxy groups')) return;
    var protocol = document.getElementById('operations-delete-protocol').value;
    var status = document.getElementById('operations-delete-status').value;
    confirmAction('Delete matching proxies', 'Permanently delete all proxies matching protocol “' + protocol + '” and status “' + status + '”?', 'Delete proxies', async function () {
      var data = await jsonAction('/api/proxies/delete', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({filter: 'custom', protocol: protocol, status: status})});
      showAlert('Deleted ' + data.deleted + ' proxies.', 'Deletion complete'); await refresh();
    });
  }

  async function changePassword(event) {
    event.preventDefault();
    if (!requirePermissions('settings.edit', 'change this password')) return;
    var input = document.getElementById('operations-new-password');
    if (input.value.length < 12) { showAlert('Password must be at least 12 characters.', 'Weak password'); return; }
    try {
      await jsonAction('/api/settings/password', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password: input.value})});
      input.value = '';
      showAlert('Your password was updated and API sessions were revoked.', 'Password updated');
    } catch (error) { showAlert(error.message, 'Password update failed'); }
  }

  window.OperationsWorkspace = {
    init: function () { if (!initialized) initialized = true; applyPermissions(); refresh(); },
    refresh: refresh,
    createBackup: createBackup,
    restoreDatabase: restoreDatabase,
    cleanupLogs: cleanupLogs,
    cleanupRuntime: cleanupRuntime,
    normalizeStatuses: normalizeStatuses,
    deleteGroup: deleteGroup,
    changePassword: changePassword
  };
}());
