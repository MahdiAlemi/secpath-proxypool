(function () {
  'use strict';

  var currentPermissions = [];
  var confirmCallback = null;
  var currentTab = 'cockpit';

  function byId(id) { return document.getElementById(id); }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function authFetch(url, options) {
    options = options || {};
    var headers = new Headers(options.headers || {});
    var method = String(options.method || 'GET').toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      var csrf = document.querySelector('meta[name="csrf-token"]');
      if (csrf) headers.set('X-CSRF-Token', csrf.content);
    }
    return fetch(url, Object.assign({}, options, {headers: headers, credentials: 'same-origin'}));
  }

  async function readJson(response) {
    var payload = {};
    try { payload = await response.json(); } catch (_error) {}
    if (!response.ok) throw new Error(payload.error || payload.message || ('Request failed (' + response.status + ')'));
    return payload;
  }

  function toggleTheme() {
    var html = document.documentElement;
    var next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (_error) {}
  }

  function openModal(id) {
    var modal = byId(id);
    if (!modal) return;
    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
    var focusable = modal.querySelector('input:not([type="hidden"]), select, textarea, button');
    if (focusable) window.setTimeout(function () { focusable.focus(); }, 20);
  }

  function closeModal(id) {
    var modal = byId(id);
    if (!modal) return;
    modal.classList.remove('active');
    modal.setAttribute('aria-hidden', 'true');
  }

  function showConfirm(title, message, callback, options) {
    options = options || {};
    confirmCallback = callback;
    var titleNode = byId('confirm-title');
    var messageNode = byId('confirm-message');
    var button = byId('confirm-btn');
    if (titleNode) titleNode.textContent = title || 'Confirm';
    if (messageNode) messageNode.textContent = message || '';
    if (button) {
      button.textContent = options.confirmText || 'Confirm';
      button.className = 'btn ' + (options.confirmClass || 'btn-danger');
    }
    openModal('modal-confirm');
  }

  async function confirmAction() {
    var callback = confirmCallback;
    confirmCallback = null;
    closeModal('modal-confirm');
    if (typeof callback === 'function') await callback();
  }

  function closeConfirmModal() {
    confirmCallback = null;
    closeModal('modal-confirm');
  }

  function showAlert(message, title) {
    var titleNode = byId('alert-title');
    var messageNode = byId('alert-message');
    if (titleNode) titleNode.textContent = title || 'Notice';
    if (messageNode) messageNode.textContent = String(message == null ? '' : message);
    openModal('modal-alert');
  }

  function closeAlertModal() { closeModal('modal-alert'); }

  function showToast(message) {
    var toast = document.createElement('div');
    toast.className = 'app-toast';
    toast.setAttribute('role', 'status');
    toast.textContent = message;
    document.body.appendChild(toast);
    window.setTimeout(function () { toast.classList.add('visible'); }, 10);
    window.setTimeout(function () {
      toast.classList.remove('visible');
      window.setTimeout(function () { toast.remove(); }, 180);
    }, 1800);
  }

  function copyProxy(text) {
    var value = String(text || '');
    if (!value) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(function () { showToast('Copied to clipboard'); }).catch(function () { fallbackCopy(value); });
      return;
    }
    fallbackCopy(value);
  }

  function fallbackCopy(text) {
    var textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.className = 'clipboard-helper';
    document.body.appendChild(textarea);
    textarea.select();
    try { document.execCommand('copy'); showToast('Copied to clipboard'); }
    catch (_error) { showAlert('Could not copy the value.', 'Clipboard unavailable'); }
    textarea.remove();
  }

  function hasPermission(permission) {
    return currentPermissions.includes('*') || currentPermissions.includes(permission);
  }

  function applyTabPermissions() {
    var rules = {
      proxies: 'proxies.view', import: 'proxies.import', monitor: 'monitor.view', server: 'server.view',
      stats: 'stats.view', operations: 'settings.view', users: 'users.manage'
    };
    Object.keys(rules).forEach(function (tab) {
      var allowed = hasPermission(rules[tab]);
      var button = document.querySelector('.nav-btn[data-tab="' + tab + '"]');
      var panel = byId('tab-' + tab);
      if (button) button.hidden = !allowed;
      if (panel && !allowed) panel.classList.add('hidden-by-perm');
    });
    if (typeof window.updateShellForTab === 'function') window.updateShellForTab(currentTab, {updateHistory: false});
  }

  async function loadCurrentUserPermissions() {
    try {
      var response = await authFetch('/api/users/me');
      var data = await readJson(response);
      currentPermissions = data.permissions || [];
    } catch (_error) {
      currentPermissions = ['*'];
    }
    applyTabPermissions();
    return currentPermissions;
  }

  function metricCard(label, value, hint, tone) {
    return '<article class="overview-metric" data-tone="' + escapeHtml(tone || 'neutral') + '">' +
      '<div class="overview-metric-head"><span class="overview-metric-label">' + escapeHtml(label) + '</span><span class="overview-metric-dot"></span></div>' +
      '<strong class="overview-metric-value">' + escapeHtml(value) + '</strong>' +
      '<span class="overview-metric-hint">' + escapeHtml(hint || '') + '</span></article>';
  }

  function readinessRow(label, value, total, hint, tone) {
    var percent = total > 0 ? Math.max(0, Math.min(100, Math.round((value / total) * 100))) : 0;
    return '<div class="readiness-row" data-tone="' + escapeHtml(tone || 'neutral') + '">' +
      '<div class="readiness-copy"><strong>' + escapeHtml(label) + '</strong><small>' + escapeHtml(hint || '') + '</small></div>' +
      '<div class="readiness-track"><span data-readiness-width="' + percent + '"></span></div>' +
      '<div class="readiness-value">' + escapeHtml(value) + ' <small>/ ' + escapeHtml(total) + '</small></div></div>';
  }

  function actionItem(text, tone) {
    return '<div class="cockpit-action' + (tone ? ' ' + escapeHtml(tone) : '') + '">' + escapeHtml(text) + '</div>';
  }

  async function optionalJson(url) {
    try {
      var response = await authFetch(url);
      return response.ok ? await response.json() : null;
    } catch (_error) { return null; }
  }

  async function loadCockpit() {
    var health = byId('cockpit-health');
    var readiness = byId('cockpit-readiness');
    var runtime = byId('cockpit-runtime');
    var actions = byId('cockpit-next-actions');
    if (!health || !readiness || !runtime || !actions) return;

    health.innerHTML = '<div class="metric-skeleton"></div>'.repeat(4);
    readiness.innerHTML = '<div class="section-hint">Calculating capability coverage…</div>';
    runtime.innerHTML = '<div class="section-hint">Reading runtime state…</div>';
    actions.innerHTML = '<div class="section-hint">Preparing the priority queue…</div>';

    var results = await Promise.all([optionalJson('/api/stats'), optionalJson('/api/settings/diagnostics'), optionalJson('/api/server'), optionalJson('/api/monitor')]);
    var stats = results[0] || {};
    var diag = results[1] || {};
    if (!results[0] && !results[1]) {
      health.innerHTML = readiness.innerHTML = runtime.innerHTML = '';
      actions.innerHTML = actionItem('The overview is unavailable for this account or the API could not be reached.', 'danger');
      return;
    }

    var counts = diag.counts || {};
    var total = Number(stats.total != null ? stats.total : counts.total || 0);
    var alive = Number(stats.alive != null ? stats.alive : counts.alive || 0);
    var webReady = Number(stats.web_ready != null ? stats.web_ready : counts.web_ready || 0);
    var dnsReady = Number(stats.dns_ready != null ? stats.dns_ready : counts.dns_ready || 0);
    var telegramReady = Number(stats.telegram_ready != null ? stats.telegram_ready : counts.telegram_ready || 0);
    var fullCap = Number(stats.full_capability != null ? stats.full_capability : counts.full_capability || 0);
    var legacy = Number(counts.legacy_revived || 0);
    var servers = Object.values((results[2] || {}).servers || {});
    var monitors = Object.values((results[3] || {}).monitors || {});
    var runningServers = servers.filter(function (item) { return Boolean(item.running || item.starting); }).length;
    var runningMonitors = monitors.filter(function (item) { return Boolean(item.running || item.starting); }).length;
    var score = total ? Math.min(100, 25 + Math.round((alive / total) * 25) + (alive ? Math.round((webReady / alive) * 30) + Math.round((fullCap / alive) * 20) : 0)) : 0;

    health.innerHTML = metricCard('Inventory', total.toLocaleString(), 'all imported candidates') +
      metricCard('Alive pool', alive.toLocaleString(), total ? Math.round((alive / total) * 100) + '% of inventory' : 'no candidates yet', alive ? 'success' : 'warning') +
      metricCard('Web-ready', webReady.toLocaleString(), alive ? Math.round((webReady / alive) * 100) + '% of alive pool' : 'run validation first', webReady ? 'success' : 'warning') +
      metricCard('Active runtimes', String(runningServers + runningMonitors), runningMonitors + ' monitors · ' + runningServers + ' servers', runningServers + runningMonitors ? 'success' : 'neutral');

    readiness.innerHTML = readinessRow('HTTPS browsing', webReady, alive, 'Verified HTTPS capability', webReady === alive && alive ? 'success' : 'neutral') +
      readinessRow('Remote DNS', dnsReady, alive, 'DNS resolved through the proxy', dnsReady === alive && alive ? 'success' : 'neutral') +
      readinessRow('Telegram', telegramReady, alive, 'Telegram endpoint reachable', telegramReady === alive && alive ? 'success' : 'neutral') +
      readinessRow('Full capability', fullCap, alive, 'HTTPS, DNS, and Telegram together', fullCap === alive && alive ? 'success' : 'warning');
    readiness.querySelectorAll('[data-readiness-width]').forEach(function (node) { node.style.width = node.dataset.readinessWidth + '%'; });

    var database = diag.db || {};
    runtime.innerHTML = '<div class="cockpit-runtime-row"><span>Database</span><strong>' + escapeHtml(String(database.type || 'unknown').toUpperCase()) + '</strong></div>' +
      '<div class="cockpit-runtime-row"><span>Validation jobs</span><strong class="runtime-status">' + runningMonitors + ' active / ' + monitors.length + ' profiles</strong></div>' +
      '<div class="cockpit-runtime-row"><span>Serving routes</span><strong class="runtime-status">' + runningServers + ' active / ' + servers.length + ' profiles</strong></div>' +
      '<div class="cockpit-runtime-row"><span>Last validation</span><strong>' + escapeHtml(stats.last_scan ? new Date(stats.last_scan).toLocaleString() : 'Not yet') + '</strong></div>';

    var recommendations = (diag.recommendations || []).slice();
    if (!total) recommendations.unshift('Import a fresh source to create the first inventory candidates.');
    else if (!alive) recommendations.unshift('Run validation to identify working proxies in the current inventory.');
    else if (!webReady) recommendations.unshift('Validate HTTPS capability before routing browser traffic.');
    else if (!runningServers) recommendations.unshift('Create a serving profile when you are ready to expose a local route.');
    if (legacy) recommendations.unshift('Normalize ' + legacy + ' legacy status records, then validate them again.');
    if (!recommendations.length) recommendations.push('The pool is healthy. Keep validation fresh and review failed routes periodically.');
    actions.innerHTML = recommendations.slice(0, 5).map(function (item, index) { return actionItem(item, index === 0 ? (score >= 75 ? 'ok' : 'danger') : ''); }).join('');

    var scoreNode = byId('cockpit-readiness-score');
    var captionNode = byId('cockpit-readiness-caption');
    if (scoreNode) scoreNode.textContent = score + '%';
    if (captionNode) captionNode.textContent = score >= 75 ? 'Pool coverage is ready for controlled traffic.' : score >= 40 ? 'Usable coverage exists, but validation gaps remain.' : 'Import and validate proxies to build readiness.';
  }

  function showTab(tab, event, options) {
    options = options || {};
    var allowed = ['cockpit', 'proxies', 'import', 'monitor', 'server', 'stats', 'operations', 'users'];
    if (!allowed.includes(tab)) tab = 'cockpit';
    currentTab = tab;
    window.currentTab = tab;
    document.querySelectorAll('.tab-content').forEach(function (node) { node.classList.add('hidden'); });
    var target = byId('tab-' + tab);
    if (target) target.classList.remove('hidden');
    document.querySelectorAll('.nav-btn').forEach(function (node) { node.classList.remove('active'); });
    var button = document.querySelector('.nav-btn[data-tab="' + tab + '"]');
    if (!button && event && event.currentTarget) button = event.currentTarget.closest('.nav-btn');
    if (button) button.classList.add('active');
    if (typeof window.updateShellForTab === 'function') window.updateShellForTab(tab, options);

    if (tab === 'cockpit') loadCockpit();
    if (tab === 'proxies' && window.ProxyPoolInventory) window.ProxyPoolInventory.reload();
    if (tab === 'import' && window.SourceWorkspace) window.SourceWorkspace.init();
    if (tab === 'monitor' && window.ValidationWorkspace) window.ValidationWorkspace.init();
    if (tab === 'server' && window.ServingWorkspace) window.ServingWorkspace.init();
    if (tab === 'stats' && window.InsightsWorkspace) window.InsightsWorkspace.init();
    if (tab === 'operations' && window.OperationsWorkspace) window.OperationsWorkspace.init();
    if (tab === 'users' && window.AccessWorkspace) window.AccessWorkspace.init();
    if (options.scroll !== false) window.scrollTo({top: 0, behavior: 'smooth'});
  }

  async function doAddProxy() {
    var data = {
      protocol: byId('add-proto').value,
      ip: byId('add-ip').value.trim(),
      port: Number(byId('add-port').value),
      username: byId('add-user').value,
      password: byId('add-pass').value
    };
    if (!data.ip || !Number.isInteger(data.port) || data.port < 1 || data.port > 65535) {
      showAlert('Enter a valid host and port.', 'Invalid proxy');
      return;
    }
    try {
      await readJson(await authFetch('/api/proxies', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)}));
      closeModal('modal-add');
      ['add-ip', 'add-port', 'add-user', 'add-pass'].forEach(function (id) { byId(id).value = ''; });
      if (window.ProxyPoolInventory) window.ProxyPoolInventory.reload();
      showToast('Proxy added');
    } catch (error) { showAlert(error.message, 'Add proxy failed'); }
  }

  async function doBulkAdd() {
    var value = byId('bulk-proxies').value.trim();
    if (!value) { showAlert('Paste at least one proxy.', 'Nothing to import'); return; }
    try {
      var result = await readJson(await authFetch('/api/proxies/bulk', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({proxies: value})}));
      closeModal('modal-bulk');
      byId('bulk-proxies').value = '';
      if (window.ProxyPoolInventory) window.ProxyPoolInventory.reload();
      showAlert('Added ' + Number(result.added || 0) + ' proxies.', 'Bulk import complete');
    } catch (error) { showAlert(error.message, 'Bulk import failed'); }
  }

  function editProxy(id, protocol, ip, port) {
    byId('edit-id').value = id;
    byId('edit-proto').value = protocol;
    byId('edit-ip').value = ip;
    byId('edit-port').value = port;
    byId('edit-user').value = '';
    byId('edit-pass').value = '';
    openModal('modal-edit');
  }

  async function doEditProxy() {
    var id = byId('edit-id').value;
    var data = {protocol: byId('edit-proto').value, ip: byId('edit-ip').value.trim(), port: Number(byId('edit-port').value)};
    var username = byId('edit-user').value;
    var password = byId('edit-pass').value;
    if (username || password) { data.username = username; data.password = password; }
    try {
      await readJson(await authFetch('/api/proxies/' + encodeURIComponent(id), {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)}));
      closeModal('modal-edit');
      if (window.ProxyPoolInventory) window.ProxyPoolInventory.reload();
      showToast('Proxy updated');
    } catch (error) { showAlert(error.message, 'Update failed'); }
  }

  document.addEventListener('click', function (event) {
    if (event.target.classList.contains('modal')) closeModal(event.target.id);
  });

  Object.assign(window, {
    authFetch: authFetch,
    escapeHtml: escapeHtml,
    toggleTheme: toggleTheme,
    openModal: openModal,
    closeModal: closeModal,
    showConfirm: showConfirm,
    confirmAction: confirmAction,
    closeConfirmModal: closeConfirmModal,
    showAlert: showAlert,
    closeAlertModal: closeAlertModal,
    copyProxy: copyProxy,
    hasPermission: hasPermission,
    loadCurrentUserPermissions: loadCurrentUserPermissions,
    loadCockpit: loadCockpit,
    showTab: showTab,
    doAddProxy: doAddProxy,
    doBulkAdd: doBulkAdd,
    editProxy: editProxy,
    doEditProxy: doEditProxy
  });

  loadCurrentUserPermissions();
  loadCockpit();
}());
