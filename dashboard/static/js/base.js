function togglePermCategory(catId) {
  const el = document.getElementById(catId);
  const icon = document.getElementById(catId + '-icon');
  if (el.style.display === 'none') {
    el.style.display = 'block';
    icon.textContent = '▼';
  } else {
    el.style.display = 'none';
    icon.textContent = '▶';
  }
}

function authFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const method = String(options.method || 'GET').toUpperCase();
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = document.querySelector('meta[name="csrf-token"]');
    if (csrf) headers.set('X-CSRF-Token', csrf.content);
  }
  return fetch(url, {...options, headers, credentials: 'same-origin'});
}

let currentPage = 1;
let sortCol = 'cost';
let sortOrder = 'asc';
let pageSize = parseInt(localStorage.getItem('pageSize')) || 50;
let searchRules = [];
let searchRuleId = 0;

const searchColumns = [
  {value: 'ip', label: 'IP'},
  {value: 'port', label: 'Port'},
  {value: 'protocol', label: 'Protocol'},
  {value: 'countryCode', label: 'Country'},
  {value: 'regionName', label: 'Region'},
  {value: 'city', label: 'City'},
  {value: 'isp', label: 'ISP'},
  {value: 'org', label: 'Organization'},
  {value: 'asn', label: 'ASN'},
  {value: 'alive_hits', label: 'Alive Hits'},
  {value: 'fail_hits', label: 'Fail Hits'},
  {value: 'speed_ms', label: 'Speed (ms)'}
];

const searchOperators = [
  {value: 'contains', label: 'contains'},
  {value: 'equals', label: 'equals'},
  {value: 'starts', label: 'starts with'},
  {value: 'gt', label: '>'},
  {value: 'lt', label: '<'},
  {value: 'gte', label: '>='},
  {value: 'lte', label: '<='}
];

function addSearchRule(rule = null) {
  const container = document.getElementById('adv-search-rules');
  const id = searchRuleId++;
  const div = document.createElement('div');
  div.style.cssText = 'display:flex;gap:8px;margin-bottom:8px;align-items:center;flex-wrap:wrap';
  div.dataset.id = id;

  if (searchRules.length > 0) {
    const logic = document.createElement('select');
    logic.style.cssText = 'padding:6px;border-radius:4px;border:1px solid var(--border)';
    logic.innerHTML = '<option value="AND">AND</option><option value="OR">OR</option>';
    if (rule) logic.value = rule.logic || 'AND';
    div.appendChild(logic);
  }

  const colSelect = document.createElement('select');
  colSelect.style.cssText = 'padding:6px;border-radius:4px;border:1px solid var(--border)';
  colSelect.innerHTML = searchColumns.map(c => '<option value="' + c.value + '">' + c.label + '</option>').join('');
  if (rule) colSelect.value = rule.column;
  div.appendChild(colSelect);

  const opSelect = document.createElement('select');
  opSelect.style.cssText = 'padding:6px;border-radius:4px;border:1px solid var(--border)';
  opSelect.innerHTML = searchOperators.map(o => '<option value="' + o.value + '">' + o.label + '</option>').join('');
  if (rule) opSelect.value = rule.operator;
  div.appendChild(opSelect);

  const valueInput = document.createElement('input');
  valueInput.type = 'text';
  valueInput.placeholder = 'Value';
  valueInput.style.cssText = 'padding:6px;border-radius:4px;border:1px solid var(--border)';
  if (rule) valueInput.value = rule.value;
  div.appendChild(valueInput);

  const removeBtn = document.createElement('button');
  removeBtn.innerHTML = '&times;';
  removeBtn.style.cssText = 'background:var(--danger);color:#fff;border:none;padding:4px 8px;border-radius:4px;cursor:pointer';
  removeBtn.onclick = function() { div.remove(); updateSearchRules(); };
  div.appendChild(removeBtn);

  container.appendChild(div);
}

function updateSearchRules() {
  searchRules = [];
  const container = document.getElementById('adv-search-rules');
  const ruleDivs = container.querySelectorAll('div[data-id]');
  ruleDivs.forEach(function(div) {
    const selects = div.querySelectorAll('select');
    const input = div.querySelector('input');
    if (input && input.value && selects.length >= 2) {
      searchRules.push({
        logic: selects[0] ? selects[0].value : 'AND',
        column: selects[selects.length - 2].value,
        operator: selects[selects.length - 1].value,
        value: input.value
      });
    }
  });
}

function openAdvSearch() {
  document.getElementById('modal-adv-search').classList.add('active');
}

function applyAdvancedSearch() {
  updateSearchRules();
  currentPage = 1;
  closeModal('modal-adv-search');
  var btn = document.getElementById('btn-adv-search');
  btn.style.background = searchRules.length > 0 ? 'var(--success)' : 'var(--accent)';
  loadProxies();
}

function clearAdvancedSearch() {
  searchRules = [];
  document.getElementById('adv-search-rules').innerHTML = '';
  var btn = document.getElementById('btn-adv-search');
  btn.style.background = 'var(--accent)';
  currentPage = 1;
  loadProxies();
}

function changePageSize(size) {
  localStorage.setItem('pageSize', size);
  currentPage = 1;
  loadProxies();
}

let autoRefreshInterval = 30;
let autoRefreshTimer = null;

function toggleTheme() {
  var html = document.documentElement;
  if (html.getAttribute('data-theme') === 'dark') {
    html.setAttribute('data-theme', 'light');
    localStorage.setItem('theme', 'light');
  } else {
    html.setAttribute('data-theme', 'dark');
    localStorage.setItem('theme', 'dark');
  }
}

function initTheme() {
  var saved = localStorage.getItem('theme');
  var preferred = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', saved || preferred);
}

function copyProxy(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(function() {
      showCopyToast(text);
    }).catch(function(err) {
      fallbackCopy(text);
    });
  } else {
    fallbackCopy(text);
  }
}

function fallbackCopy(text) {
  var textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  try {
    document.execCommand('copy');
    showCopyToast(text);
  } catch (err) {
    console.error('Failed to copy:', err);
  }
  document.body.removeChild(textarea);
}

function showCopyToast(text) {
  var toast = document.createElement('div');
  toast.style.cssText = 'position:fixed;bottom:20px;right:20px;background:var(--accent);color:#fff;padding:12px 20px;border-radius:8px;z-index:9999;animation:fadeIn 0.3s';
  toast.textContent = 'Copied: ' + text;
  document.body.appendChild(toast);
  setTimeout(function() { toast.remove(); }, 2000);
}

function toggleColumnsMenu() {
  var menu = document.getElementById('columns-menu');
  menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
  document.getElementById('filter-proto-menu').style.display = 'none';
  document.getElementById('filter-status-menu').style.display = 'none';
}

function toggleFilterMenu(type) {
  document.getElementById('columns-menu').style.display = 'none';
  if (type === 'proto') {
    var menu = document.getElementById('filter-proto-menu');
    menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
    document.getElementById('filter-status-menu').style.display = 'none';
  } else if (type === 'status') {
    var menu = document.getElementById('filter-status-menu');
    menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
    document.getElementById('filter-proto-menu').style.display = 'none';
  }
}

function formatTimeAgo(dateStr) {
  if (!dateStr) return 'Never';
  var diff = (Date.now() - new Date(dateStr)) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
  if (diff < 86400) return Math.floor(diff / 3600) + ' hours ago';
  return Math.floor(diff / 86400) + ' days ago';
}

function changeProtoFilter() {
  currentPage = 1;
  loadProxies();
  loadStats();
}

let cachedStats = null;
let currentUserPermissions = [];

async function loadCurrentUserPermissions() {
  var res = await authFetch('/api/users/me');
  if (res.ok) {
    var data = await res.json();
    currentUserPermissions = data.permissions || [];
  } else {
    // Built-in fallback admin should normally be handled by the backend. If an
    // older backend is running, default to full UI access instead of breaking.
    currentUserPermissions = ['*'];
  }
  applyTabPermissions();
}

let userProxyFilters = window.initialProxyFilters || { statuses: [], protocols: [] };

async function loadUserProxyFilters() {
  if (userProxyFilters.statuses.length > 0 || userProxyFilters.protocols.length > 0) {
    applyProxyFiltersToUI();
    return;
  }

  try {
    var res = await authFetch('/api/proxies/my-filters');
    if (res.ok) {
      userProxyFilters = await res.json();
      applyProxyFiltersToUI();
    }
  } catch (e) {
    console.error('Failed to load proxy filters:', e);
  }
}

function applyProxyFiltersToUI() {
  var statusFilters = ['alive', 'flaky', 'cooling', 'soft', 'revived', 'semi-revived', 'dead', 'untested'];

  statusFilters.forEach(function(status) {
    var btn = document.querySelector('.stat-card[data-status="' + status + '"]');
    if (btn) {
      var shouldShow = userProxyFilters.statuses.length === 0 || userProxyFilters.statuses.includes(status);
      if (shouldShow) {
        btn.classList.remove('hidden-by-filter');
      } else {
        btn.classList.add('hidden-by-filter');
      }
    }
  });

  var protoSelect = document.querySelector('select[onchange="changeProtoFilter()"]');
  if (protoSelect && userProxyFilters.protocols.length > 0) {
    protoSelect.value = userProxyFilters.protocols[0];
    changeProtoFilter();
  }
}

function hasPermission(perm) {
  return currentUserPermissions.includes(perm) || currentUserPermissions.includes('*');
}
window.hasPermission = hasPermission;

function applyTabPermissions() {
  var toggleTab = function(tab, visible) {
    var button = document.querySelector('.nav-btn[data-tab="' + tab + '"]');
    if (button) button.style.display = visible ? '' : 'none';
    if (!visible) document.getElementById('tab-' + tab)?.classList.add('hidden');
  };

  toggleTab('proxies', hasPermission('proxies.view'));
  toggleTab('import', hasPermission('proxies.import'));
  toggleTab('monitor', hasPermission('monitor.view'));
  toggleTab('server', hasPermission('server.view'));
  toggleTab('stats', hasPermission('stats.view'));
  toggleTab('operations', hasPermission('settings.view'));
  toggleTab('users', hasPermission('users.manage'));

  if (!hasPermission('proxies.add')) {
    document.getElementById('topbar-add-proxy')?.style.setProperty('display', 'none');
  }
  if (!hasPermission('proxies.export')) {
    document.getElementById('btn-export-csv')?.style.setProperty('display', 'none');
    document.getElementById('btn-export-json')?.style.setProperty('display', 'none');
  }
  if (!hasPermission('proxies.columns')) {
    document.querySelector('button[onclick="toggleColumnsMenu()"]')?.style.setProperty('display', 'none');
    localStorage.removeItem('hiddenColumns');
  }
  if (!hasPermission('proxies.search')) {
    document.getElementById('btn-adv-search')?.style.setProperty('display', 'none');
  }
  if (!hasPermission('proxies.refresh')) {
    document.getElementById('auto-refresh-sec')?.style.setProperty('display', 'none');
    document.getElementById('auto-refresh-btn')?.style.setProperty('display', 'none');
  }
  if (typeof window.updateShellForTab === 'function') {
    window.updateShellForTab(currentTab || 'cockpit', {updateHistory: false});
  }
}


let selectedStatuses = ['alive', 'flaky', 'cooling', 'soft', 'revived', 'semi-revived', 'dead', 'untested'];
let selectedCapabilities = [];

function toggleStatusFilter(status) {
  var idx = selectedStatuses.indexOf(status);
  if (idx > -1) {
    if (selectedStatuses.length > 1) {
      selectedStatuses.splice(idx, 1);
    }
  } else {
    selectedStatuses.push(status);
  }
  updateStatusFilterUI();
  loadProxies();
}

function updateStatusFilterUI() {
  var statuses = ['alive', 'flaky', 'cooling', 'soft', 'revived', 'semi-revived', 'dead', 'untested'];
  var statusColors = {
    alive: 'var(--success)',
    soft: '#FF9800',
    flaky: '#f59e0b',
    cooling: '#8b5cf6',
    dead: 'var(--danger)',
    revived: '#757575',
    'semi-revived': '#424242',
    untested: 'var(--muted)'
  };
  statuses.forEach(function(s) {
    var el = document.querySelector('#status-filters .stat-card:nth-child(' + (statuses.indexOf(s) + 2) + ')');
    if (el) {
      var isSelected = selectedStatuses.includes(s);
      el.style.opacity = isSelected ? '1' : '0.3';
      var countEl = el.querySelector('div:first-child');
      if (countEl) {
        countEl.style.color = isSelected ? statusColors[s] : 'var(--muted)';
      }
    }
  });
}

function getStatusFilterParam() {
  if (selectedStatuses.length === 5) return '';
  return selectedStatuses.join(',');
}

function toggleCapabilityFilter(cap) {
  var idx = selectedCapabilities.indexOf(cap);
  if (idx > -1) { selectedCapabilities.splice(idx, 1); }
  else { selectedCapabilities.push(cap); }
  updateCapabilityFilterUI();
  currentPage = 1;
  loadProxies();
}

function updateCapabilityFilterUI() {
  document.querySelectorAll('#capability-filters .stat-card').forEach(function(el) {
    var cap = el.getAttribute('data-cap');
    el.style.opacity = selectedCapabilities.includes(cap) ? '1' : '0.5';
  });
}

function getCapabilityFilterParam() {
  return selectedCapabilities.join(',');
}


async function fetchStats() {
  var res = await authFetch('/api/stats');
  cachedStats = await res.json();
}

function toggleColumn(col, show) {
  if (!hasPermission('proxies.columns')) return;

  var display = show ? '' : 'none';
  var header = document.querySelector('#proxies-table th[data-col="' + col + '"]');
  var colIdx = header ? (Array.prototype.indexOf.call(header.parentNode.children, header) + 1) : null;

  if (colIdx) {
    document.querySelectorAll('#proxies-table th:nth-child(' + colIdx + ')').forEach(function(el) { el.style.display = display; });
    document.querySelectorAll('#proxies-table td:nth-child(' + colIdx + ')').forEach(function(el) { el.style.display = display; });
  }

  var hidden = JSON.parse(localStorage.getItem('hiddenColumns') || '{}');
  hidden[col] = !show;
  localStorage.setItem('hiddenColumns', JSON.stringify(hidden));
}

function initColumns() {
  if (currentUserPermissions.length === 0) {
    setTimeout(initColumns, 100);
    return;
  }
  if (!hasPermission('proxies.columns')) return;
  var hidden = JSON.parse(localStorage.getItem('hiddenColumns') || '{}');
  for (var col in hidden) {
    if (hidden[col]) {
      toggleColumn(col, false);
      var checkbox = document.querySelector('#columns-menu input[onchange*="' + col + '"]');
      if (checkbox) checkbox.checked = false;
    }
  }
}

function toggleAutoRefresh() {
  var btn = document.getElementById('auto-refresh-btn');
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
    btn.style.background = 'transparent';
    btn.style.color = 'var(--text)';
  } else {
    btn.style.background = 'var(--success)';
    btn.style.color = '#fff';
    autoRefreshTimer = setInterval(function() {
      loadProxies();
    }, autoRefreshInterval * 1000);
  }
}

function setAutoRefreshInterval(sec) {
  autoRefreshInterval = sec;
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = setInterval(function() {
      loadProxies();
    }, autoRefreshInterval * 1000);
  }
}

var currentTab = 'cockpit';


function cockpitMetricCard(label, value, hint, tone) {
  return '<article class="overview-metric" data-tone="' + escapeHtml(tone || 'neutral') + '">' +
    '<div class="overview-metric-head"><span class="overview-metric-label">' + escapeHtml(label) + '</span><span class="overview-metric-dot"></span></div>' +
    '<strong class="overview-metric-value">' + escapeHtml(value) + '</strong>' +
    '<span class="overview-metric-hint">' + escapeHtml(hint || '') + '</span>' +
  '</article>';
}

function cockpitReadinessRow(label, value, total, hint, tone) {
  var percent = total > 0 ? Math.max(0, Math.min(100, Math.round((value / total) * 100))) : 0;
  return '<div class="readiness-row" data-tone="' + escapeHtml(tone || 'neutral') + '">' +
    '<div class="readiness-copy"><strong>' + escapeHtml(label) + '</strong><small>' + escapeHtml(hint || '') + '</small></div>' +
    '<div class="readiness-track"><span style="width:' + percent + '%"></span></div>' +
    '<div class="readiness-value">' + escapeHtml(value) + ' <small>/ ' + escapeHtml(total) + '</small></div>' +
  '</div>';
}

function cockpitAction(text, tone) {
  var cls = tone === 'danger' ? ' danger' : (tone === 'ok' ? ' ok' : '');
  return '<div class="cockpit-action' + cls + '">' + escapeHtml(text) + '</div>';
}

async function cockpitFetch(url) {
  try {
    var response = await authFetch(url);
    if (!response.ok) return null;
    return await response.json();
  } catch (_error) {
    return null;
  }
}

async function loadCockpit() {
  var health = document.getElementById('cockpit-health');
  var readiness = document.getElementById('cockpit-readiness');
  var runtime = document.getElementById('cockpit-runtime');
  var actions = document.getElementById('cockpit-next-actions');
  var scoreElement = document.getElementById('cockpit-readiness-score');
  var captionElement = document.getElementById('cockpit-readiness-caption');
  if (!health || !readiness || !runtime || !actions) return;

  health.innerHTML = '<div class="metric-skeleton"></div><div class="metric-skeleton"></div><div class="metric-skeleton"></div><div class="metric-skeleton"></div>';
  readiness.innerHTML = '<div class="section-hint">Calculating capability coverage…</div>';
  runtime.innerHTML = '<div class="section-hint">Reading runtime state…</div>';
  actions.innerHTML = '<div class="section-hint">Preparing the priority queue…</div>';

  var results = await Promise.all([
    cockpitFetch('/api/stats'),
    cockpitFetch('/api/settings/diagnostics'),
    cockpitFetch('/api/server'),
    cockpitFetch('/api/monitor')
  ]);
  var stats = results[0] || {};
  var diag = results[1] || {};
  var serverData = results[2] || {};
  var monitorData = results[3] || {};

  if (!results[0] && !results[1]) {
    health.innerHTML = '';
    readiness.innerHTML = '';
    runtime.innerHTML = '';
    actions.innerHTML = cockpitAction('The overview is unavailable for this account or the API could not be reached.', 'danger');
    if (scoreElement) scoreElement.textContent = '—';
    if (captionElement) captionElement.textContent = 'Overview unavailable';
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

  var servers = serverData.servers || {};
  var monitors = monitorData.monitors || {};
  var serverList = Object.keys(servers).map(function (key) { return servers[key] || {}; });
  var monitorList = Object.keys(monitors).map(function (key) { return monitors[key] || {}; });
  var runningServers = serverList.filter(function (item) { return Boolean(item.running || item.starting); }).length;
  var runningMonitors = monitorList.filter(function (item) { return Boolean(item.running || item.starting); }).length;
  var activeRuntimes = runningServers + runningMonitors;

  var inventoryScore = total > 0 ? Math.min(100, 25 + Math.round((alive / total) * 25)) : 0;
  var webScore = alive > 0 ? Math.round((webReady / alive) * 30) : 0;
  var fullScore = alive > 0 ? Math.round((fullCap / alive) * 20) : 0;
  var score = Math.max(0, Math.min(100, inventoryScore + webScore + fullScore));
  var scoreTone = score >= 75 ? 'success' : (score >= 40 ? 'warning' : 'neutral');

  health.innerHTML =
    cockpitMetricCard('Inventory', total.toLocaleString(), 'all imported candidates') +
    cockpitMetricCard('Alive pool', alive.toLocaleString(), total ? Math.round((alive / total) * 100) + '% of inventory' : 'no candidates yet', alive > 0 ? 'success' : 'warning') +
    cockpitMetricCard('Web-ready', webReady.toLocaleString(), alive ? Math.round((webReady / alive) * 100) + '% of alive pool' : 'run validation first', webReady > 0 ? 'success' : 'warning') +
    cockpitMetricCard('Active runtimes', activeRuntimes.toLocaleString(), runningMonitors + ' ' + (runningMonitors === 1 ? 'monitor' : 'monitors') + ' · ' + runningServers + ' ' + (runningServers === 1 ? 'server' : 'servers'), activeRuntimes > 0 ? 'success' : 'neutral');

  readiness.innerHTML =
    cockpitReadinessRow('HTTPS browsing', webReady, alive, 'Verified HTTPS capability', webReady && webReady === alive ? 'success' : 'neutral') +
    cockpitReadinessRow('Remote DNS', dnsReady, alive, 'DNS resolved through the proxy', dnsReady && dnsReady === alive ? 'success' : 'neutral') +
    cockpitReadinessRow('Telegram', telegramReady, alive, 'Telegram endpoint reachable', telegramReady && telegramReady === alive ? 'success' : 'neutral') +
    cockpitReadinessRow('Full capability', fullCap, alive, 'HTTPS, DNS, and Telegram together', fullCap && fullCap === alive ? 'success' : 'warning');

  var db = diag.db || {};
  runtime.innerHTML =
    '<div class="cockpit-runtime-row"><span>Database</span><strong>' + escapeHtml(String(db.type || 'unknown').toUpperCase()) + (db.sqlite_size_mb != null ? ' · ' + Number(db.sqlite_size_mb).toFixed(2) + ' MB' : '') + '</strong></div>' +
    '<div class="cockpit-runtime-row"><span>Validation jobs</span><strong class="runtime-status">' + runningMonitors + ' active / ' + monitorList.length + ' profiles</strong></div>' +
    '<div class="cockpit-runtime-row"><span>Serving routes</span><strong class="runtime-status">' + runningServers + ' active / ' + serverList.length + ' profiles</strong></div>' +
    '<div class="cockpit-runtime-row"><span>Last validation</span><strong>' + escapeHtml(stats.last_scan ? new Date(stats.last_scan).toLocaleString() : 'Not yet') + '</strong></div>';

  var recommendations = (diag.recommendations || []).slice();
  if (total === 0) recommendations.unshift('Import a fresh source to create the first inventory candidates.');
  else if (alive === 0) recommendations.unshift('Run validation to identify working proxies in the current inventory.');
  else if (webReady === 0) recommendations.unshift('Validate HTTPS capability before routing browser traffic.');
  else if (runningServers === 0) recommendations.unshift('Create a serving profile when you are ready to expose a local route.');
  if (legacy > 0) recommendations.unshift('Normalize ' + legacy + ' legacy status records, then validate them again.');
  if (!recommendations.length) recommendations.push('The pool is healthy. Keep validation fresh and review failed routes periodically.');
  actions.innerHTML = recommendations.slice(0, 5).map(function (item, index) {
    var tone = index === 0 && (total === 0 || alive === 0 || legacy > 0) ? 'danger' : (index === 0 ? 'ok' : '');
    return cockpitAction(item, tone);
  }).join('');

  if (scoreElement) scoreElement.textContent = score + '%';
  if (captionElement) {
    captionElement.textContent = score >= 75 ? 'Pool coverage is ready for controlled traffic.' : (score >= 40 ? 'Usable coverage exists, but validation gaps remain.' : 'Import and validate proxies to build readiness.');
  }
  var orb = document.getElementById('cockpit-readiness-orb');
  if (orb) orb.dataset.tone = scoreTone;
}

function showTab(tab, evt, options) {
  var allowedTabs = ['cockpit', 'proxies', 'import', 'monitor', 'server', 'stats', 'operations', 'users'];
  if (!allowedTabs.includes(tab)) tab = 'cockpit';
  currentTab = tab;

  document.querySelectorAll('.tab-content').forEach(function (element) { element.classList.add('hidden'); });
  var targetTab = document.getElementById('tab-' + tab);
  if (targetTab) targetTab.classList.remove('hidden');

  document.querySelectorAll('.nav-btn').forEach(function (element) { element.classList.remove('active'); });
  var button = document.querySelector('.nav-btn[data-tab="' + tab + '"]');
  if (!button) {
    var source = evt && (evt.currentTarget || evt.target);
    button = source && source.closest ? source.closest('.nav-btn') : null;
  }
  if (button) button.classList.add('active');

  if (typeof window.updateShellForTab === 'function') window.updateShellForTab(tab, options || {});

  if (tab === 'cockpit') loadCockpit();
  if (tab === 'proxies') {
    loadProxies();
    fetchStats();
    applyProxyFiltersToUI();
  }
  if (tab === 'import' && window.SourceWorkspace) window.SourceWorkspace.init();
  if (tab === 'stats' && window.InsightsWorkspace) window.InsightsWorkspace.init();
  if (tab === 'operations' && window.OperationsWorkspace) window.OperationsWorkspace.init();
  if (tab === 'users' && window.AccessWorkspace) window.AccessWorkspace.init();
  if (tab === 'monitor' && window.ValidationWorkspace) window.ValidationWorkspace.init();
  if (tab === 'server' && window.ServingWorkspace) window.ServingWorkspace.init();

  if (!options || options.scroll !== false) window.scrollTo({top: 0, behavior: 'smooth'});
}




function openModal(id) {
  document.getElementById(id).classList.add('active');
  if (id === 'modal-settings') { loadSettings(); loadDiagnostics(); }
  if (id === 'modal-users') loadUsers();
}

function closeModal(id) {
  document.getElementById(id).classList.remove('active');
}

var confirmCallback = null;

function showConfirm(title, message, onConfirm, options) {
  options = options || {};
  var confirmText = options.confirmText || 'Confirm';
  var confirmClass = options.confirmClass || 'btn-danger';

  document.getElementById('confirm-title').textContent = title;
  document.getElementById('confirm-message').textContent = message;

  var btn = document.getElementById('confirm-btn');
  btn.textContent = confirmText;
  btn.className = 'btn ' + confirmClass;

  confirmCallback = onConfirm;
  document.getElementById('modal-confirm').classList.add('active');
}

function confirmAction() {
  var callback = confirmCallback;
  closeConfirmModal();
  if (callback) {
    callback();
  }
}

function closeConfirmModal() {
  document.getElementById('modal-confirm').classList.remove('active');
  confirmCallback = null;
}

function showAlert(message, title) {
  title = title || 'Alert';
  document.getElementById('alert-title').textContent = title;
  document.getElementById('alert-message').textContent = message;
  document.getElementById('modal-alert').classList.add('active');
}

function closeAlertModal() {
  document.getElementById('modal-alert').classList.remove('active');
}

async function loadUsers() {
  var res = await authFetch('/api/users');
  if (!res.ok) {
    if (res.status === 403 || res.status === 401) {
      document.getElementById('users-list').innerHTML = '<div style="color:var(--danger)">Permission denied</div>';
    } else {
      document.getElementById('users-list').innerHTML = '<div style="color:var(--danger)">Error loading users</div>';
    }
    return;
  }
  var users = await res.json();
  var html = '<table style="width:100%;border-collapse:collapse"><tr style="text-align:left;background:var(--panel-light)"><th style="padding:8px">User</th><th style="padding:8px">Role</th><th style="padding:8px">Status</th><th style="padding:8px">Actions</th></tr>';
  users.forEach(function(u) {
    html += '<tr style="border-bottom:1px solid var(--border)">' +
      '<td style="padding:8px">' + escapeHtml(u.username) + '</td>' +
      '<td style="padding:8px">' + escapeHtml(u.role) + '</td>' +
      '<td style="padding:8px">' + (u.is_active ? '<span style="color:var(--success)">Active</span>' : '<span style="color:var(--danger)">Inactive</span>') + '</td>' +
      '<td style="padding:8px">' +
        '<button class="btn btn-sm" onclick="editUser(' + u.id + ')">Edit</button> ' +
        '<button class="btn btn-sm" style="color:var(--danger)" onclick="deleteUser(' + u.id + ')">Delete</button>' +
      '</td>' +
    '</tr>';
  });
  html += '</table>';
  document.getElementById('users-list').innerHTML = html;
}

function showAddUserModal() {
  document.getElementById('edit-user-id').value = '';
  document.getElementById('user-form-title').innerText = 'Add User';
  document.getElementById('user-username').value = '';
  document.getElementById('user-password').value = '';
  document.getElementById('user-role').value = 'user';
  document.getElementById('user-active').checked = true;

  document.querySelectorAll('.proxy-filter-status').forEach(function(cb) { cb.checked = true; });
  document.querySelectorAll('.proxy-filter-proto').forEach(function(cb) { cb.checked = true; });

  loadPermissions().then(function(data) {
    if (!data) return;
    var rolePerms = data.role_permissions['user'] || [];
    var isRoleWildcard = rolePerms.includes('*');
    data.all_permissions.forEach(function(p) {
      var cb = document.getElementById('perm-' + p);
      if (!cb) return;
      var isDefault = isRoleWildcard || rolePerms.includes(p);
      cb.checked = isDefault;
      cb.dataset.isRoleDefault = isDefault ? '1' : '0';
    });
    updateRolePermissions();
  });

  document.getElementById('modal-user-form').classList.add('active');
}

async function editUser(id) {
  var res = await authFetch('/api/users');
  if (!res.ok) { showAlert('Session expired. Please login again.'); window.location.href = '/login'; return; }
  var users = await res.json();
  var user = users.find(function(u) { return u.id === id; });
  if (!user) return;

  document.getElementById('edit-user-id').value = id;
  document.getElementById('user-form-title').innerText = 'Edit User';
  document.getElementById('user-username').value = user.username;
  document.getElementById('user-password').value = '';
  document.getElementById('user-role').value = user.role;
  document.getElementById('user-active').checked = user.is_active;

  var permData = await loadPermissions();
  if (!permData) return;
  var rolePerms = permData.role_permissions[user.role] || [];
  var userAddPerms = user.custom_permissions && user.custom_permissions.add ? user.custom_permissions.add : [];
  var userRemovePerms = user.custom_permissions && user.custom_permissions.remove ? user.custom_permissions.remove : [];

  permData.all_permissions.forEach(function(p) {
    var cb = document.getElementById('perm-' + p);
    if (!cb) return;
    var isRoleDefault = rolePerms.includes(p) || rolePerms.includes('*');
    var isCustomAdded = userAddPerms.includes(p);
    var isCustomRemoved = userRemovePerms.includes(p);
    cb.checked = (isRoleDefault && !isCustomRemoved) || isCustomAdded;
    cb.dataset.isRoleDefault = isRoleDefault ? '1' : '0';
  });

  var proxyFiltersGroup = document.getElementById('proxy-filters-group');
  proxyFiltersGroup.style.display = user.role === 'user' ? 'block' : 'none';

  var userFilters = user.custom_permissions && user.custom_permissions.proxy_filters ? user.custom_permissions.proxy_filters : {};
  var allowedStatuses = userFilters.statuses || [];
  var allowedProtocols = userFilters.protocols || [];

  document.querySelectorAll('.proxy-filter-status').forEach(function(cb) {
    cb.checked = allowedStatuses.length === 0 || allowedStatuses.includes(cb.value);
  });

  document.querySelectorAll('.proxy-filter-proto').forEach(function(cb) {
    cb.checked = allowedProtocols.length === 0 || allowedProtocols.includes(cb.value);
  });

  updateRolePermissions();
  document.getElementById('modal-user-form').classList.add('active');
}

async function loadPermissions() {
  var res = await authFetch('/api/users/permissions');
  if (!res.ok) { showAlert('Session expired. Please login again.'); window.location.href = '/login'; return null; }
  var data = await res.json();

  var permCategories = {
    'Proxies': ['proxies.view', 'proxies.add', 'proxies.edit', 'proxies.delete', 'proxies.test', 'proxies.export', 'proxies.columns', 'proxies.search', 'proxies.refresh'],
    'Import': ['proxies.import'],
    'Monitor': ['monitor.view', 'monitor.control'],
    'Server': ['server.view', 'server.control'],
    'Stats': ['stats.view'],
    'Settings': ['settings.view', 'settings.edit'],
    'Users': ['users.manage']
  };

  var html = '';
  for (var category in permCategories) {
    var perms = permCategories[category];
    var catId = 'perm-cat-' + category.toLowerCase();
    html += '<div style="margin-bottom:8px">' +
      '<div onclick="togglePermCategory(\'' + catId + '\')" style="font-weight:600;font-size:12px;color:var(--accent);margin-bottom:4px;padding:6px 8px;background:var(--panel-light);border-radius:6px;cursor:pointer;display:flex;justify-content:space-between;align-items:center">' +
        '<span>' + category + '</span>' +
        '<span id="' + catId + '-icon">▶</span>' +
      '</div>' +
      '<div id="' + catId + '" style="display:none;padding:4px 0">';
    perms.forEach(function(p) {
      if (!data.all_permissions.includes(p)) return;
      var role = document.getElementById('user-role') ? document.getElementById('user-role').value : 'user';
      var roleDefaults = data.role_permissions[role] || [];
      var isRoleDefault = roleDefaults.includes(p) || roleDefaults.includes('*');
      var labelStyle = isRoleDefault ? 'display:flex;align-items:center;gap:4px;padding:4px;background:#e8f5e9;border-radius:4px;margin:2px 0' : 'display:flex;align-items:center;gap:4px;padding:4px';
      var defaultBadge = isRoleDefault ? '<span style="font-size:10px;background:#4caf50;color:white;padding:1px 4px;border-radius:3px;margin-right:4px">default</span>' : '';
      var permLabel = p.replace('proxies.', '').replace('monitor.', '').replace('server.', '').replace('settings.', '').replace('users.', '');
      html += '<label style="' + labelStyle + '">' +
        '<input type="checkbox" id="perm-' + p + '" value="' + p + '" data-is-role-default="' + (isRoleDefault ? '1' : '0') + '"> ' + defaultBadge + permLabel +
      '</label>';
    });
    html += '</div></div>';
  }
  document.getElementById('custom-perms-list').innerHTML = html;
  return data;
}

function updateRolePermissions() {
  var role = document.getElementById('user-role').value;
  var customGroup = document.getElementById('custom-perms-group');
  var proxyFiltersGroup = document.getElementById('proxy-filters-group');
  customGroup.style.display = role === 'user' ? 'block' : 'none';

  proxyFiltersGroup.style.display = role === 'user' ? 'block' : 'none';

  document.getElementById('role-desc-user').style.display = role === 'user' ? 'block' : 'none';
  document.getElementById('role-desc-superadmin').style.display = role === 'superadmin' ? 'block' : 'none';
  document.getElementById('role-desc-admin').style.display = role === 'admin' ? 'block' : 'none';

  document.querySelectorAll('#custom-perms-list label').forEach(function(label) {
    var cb = label.querySelector('input');
    if (!cb) return;
    var perm = cb.value;
    var isChecked = cb.checked;
    var span = label.querySelector('span');
    if (role === 'user' && (perm === 'proxies.view' || perm === 'server.view')) {
      if (!span) label.innerHTML = cb.outerHTML + '<span style="font-size:11px;background:#4caf50;color:white;padding:1px 4px;border-radius:3px;margin-right:4px">default</span> ' + perm;
      if (!cb.checked) cb.checked = true;
    }
  });
}

async function saveUser() {
  var id = document.getElementById('edit-user-id').value;
  var username = document.getElementById('user-username').value;
  var password = document.getElementById('user-password').value;
  var role = document.getElementById('user-role').value;
  var is_active = document.getElementById('user-active').checked;

  var permRes = await authFetch('/api/users/permissions');
  if (!permRes.ok) { showAlert('Session expired. Please login again.'); window.location.href = '/login'; return; }
  var permData = await permRes.json();
  var rolePerms = permData.role_permissions[role] || [];
  var isRoleWildcard = rolePerms.includes('*');

  var addPerms = [];
  var removePerms = [];
  document.querySelectorAll('#custom-perms-list input').forEach(function(cb) {
    var isDefault = isRoleWildcard || rolePerms.includes(cb.value);
    if (cb.checked && !isDefault) {
      addPerms.push(cb.value);
    } else if (!cb.checked && isDefault) {
      removePerms.push(cb.value);
    }
  });

  var data = {
    username: username,
    role: role,
    is_active: is_active,
    custom_permissions: { add: addPerms, remove: removePerms }
  };

  if (role === 'user') {
    var selectedStatuses = [];
    document.querySelectorAll('.proxy-filter-status:checked').forEach(function(cb) {
      selectedStatuses.push(cb.value);
    });

    var selectedProtocols = [];
    document.querySelectorAll('.proxy-filter-proto:checked').forEach(function(cb) {
      selectedProtocols.push(cb.value);
    });

    if (selectedStatuses.length > 0 || selectedProtocols.length > 0) {
      data.custom_permissions.proxy_filters = {
        statuses: selectedStatuses,
        protocols: selectedProtocols
      };
    }
  }

  if (password) data.password = password;

  var method = id ? 'PUT' : 'POST';
  var url = id ? '/api/users/' + id : '/api/users';

  var res = await authFetch(url, {
    method: method,
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });

  var result = await res.json();
  if (result.success) {
    closeModal('modal-user-form');
    loadUsers();
  } else {
    showAlert(result.error || 'Error saving user');
  }
}

async function deleteUser(id) {
  showConfirm('Delete User', 'Are you sure you want to delete this user?', async function() {
    var res = await authFetch('/api/users/' + id, {method: 'DELETE'});
    var result = await res.json();
    if (result.success) {
      loadUsers();
    } else {
      showAlert(result.error || 'Error deleting user');
    }
  });
}

function showAddProxy() {
  document.getElementById('modal-add').classList.add('active');
}

function showBulkAdd() {
  document.getElementById('modal-bulk').classList.add('active');
}


function setTextSafe(id, value) {
  var el = document.getElementById(id);
  if (el) el.textContent = value == null ? '' : value;
}

function updateInventoryOverview(data, statsData) {
  data = data || {};
  statsData = statsData || data;
  setTextSafe('inventory-total', data.total || 0);
  setTextSafe('inventory-alive', statsData.alive || 0);
  setTextSafe('inventory-web-ready', data.web_ready || 0);
  setTextSafe('inventory-telegram-ready', data.telegram_ready || 0);
  setTextSafe('inventory-full-capability', data.full_capability || 0);

  var protoEl = document.querySelector('#tab-proxies select');
  var proto = protoEl ? protoEl.value : 'all';
  var statuses = getStatusFilterParam() || 'all statuses';
  var caps = getCapabilityFilterParam() || 'all capabilities';
  var search = searchRules.length ? (searchRules.length + ' advanced rule' + (searchRules.length > 1 ? 's' : '')) : 'no advanced search';
  setTextSafe('inventory-filter-summary', 'Protocol: ' + proto + ' · Status: ' + statuses + ' · Capability: ' + caps + ' · Search: ' + search);
}

function updateInventoryResultState(data) {
  data = data || {};
  var visible = (data.proxies || []).length;
  var total = data.total || 0;
  setTextSafe('inventory-result-summary', visible + ' shown on this page · ' + total + ' matching total');
  var empty = document.getElementById('inventory-empty-state');
  if (empty) empty.style.display = visible === 0 ? 'block' : 'none';
}

function capabilityMark(v) {
  return v ? '<span style="color:var(--success);font-weight:700">✓</span>' : '<span style="color:var(--muted)">-</span>';
}

async function loadProxies() {
  await loadStats();

  var protoEl = document.querySelector('#tab-proxies select');
  var proto = protoEl ? protoEl.value : 'all';
  var statusFilter = getStatusFilterParam();

  var ps = parseInt(document.getElementById('page-size').value) || 50;
  var params = new URLSearchParams({
    page: currentPage,
    page_size: ps,
    proto: proto,
    sort_col: sortCol,
    sort_order: sortOrder
  });

  if (statusFilter) {
    params.append('status', statusFilter);
  }

  var capFilter = getCapabilityFilterParam();
  if (capFilter) {
    params.append('capability', capFilter);
  }

  if (searchRules.length > 0) {
    params.append('adv_search', JSON.stringify(searchRules));
  }

  var res = await authFetch('/api/proxies?' + params);
  var data = await res.json();

  var tbody = document.getElementById('proxies-tbody');
  tbody.innerHTML = '';
  updateInventoryResultState(data);

  if (!data.proxies || data.proxies.length === 0) {
    tbody.innerHTML = '<tr class="inventory-empty-row"><td colspan="40">No rows in this view. Adjust filters or run validation.</td></tr>';
  }

  (data.proxies || []).forEach(function(p) {
    var statusClass = 'status-untested';
    var statusLabel = 'Untested';

    var status = p.status || 'untested';
    if (status === 'alive') {
      statusClass = 'status-alive';
      statusLabel = 'Alive';
    } else if (status === 'flaky') {
      statusClass = 'status-flaky';
      statusLabel = 'Flaky';
    } else if (status === 'soft') {
      statusClass = 'status-soft';
      statusLabel = 'Soft';
    } else if (status === 'cooling') {
      statusClass = 'status-cooling';
      statusLabel = 'Cooling';
    } else if (status === 'dead') {
      statusClass = 'status-dead';
      statusLabel = 'Dead';
    } else if (status === 'revived') {
      statusClass = 'status-revived';
      statusLabel = 'Revived';
    } else if (status === 'semi-revived') {
      statusClass = 'status-semi-revived';
      statusLabel = 'Semi-Revived';
    } else {
      statusClass = 'status-untested';
      statusLabel = 'Untested';
    }

    var tr = document.createElement('tr');
    var proxyUrl = String(p.protocol || '') + '://' + String(p.ip || '') + ':' + String(p.port || '');
    var actionsHtml = '';
    var safeId = Number(p.id) || 0;
    if (hasPermission('proxies.test')) {
      actionsHtml += '<button class="btn btn-sm" data-proxy-id="' + safeId + '" onclick="testProxyFromButton(this)">Test</button> ';
    }
    if (hasPermission('proxies.edit')) {
      actionsHtml += '<button class="btn btn-sm" data-proxy-id="' + safeId + '" data-protocol="' + escapeHtml(p.protocol || '') + '" data-ip="' + escapeHtml(p.ip || '') + '" data-port="' + escapeHtml(p.port || '') + '" onclick="editProxyFromButton(this)">Edit</button> ';
    }
    if (hasPermission('proxies.delete')) {
      actionsHtml += '<button class="btn btn-sm btn-danger" data-proxy-id="' + safeId + '" onclick="deleteProxyFromButton(this)">Del</button>';
    }
    var authBadge = p.has_auth ? ' <span title="Upstream credentials are stored but hidden">&#128274;</span>' : '';
    var locationText = (p.lat != null && p.lon != null) ? Number(p.lat).toFixed(4) + ',' + Number(p.lon).toFixed(4) : '-';
    tr.innerHTML =
      '<td class="proxy-copy-cell" title="Click to copy address">' + escapeHtml(p.ip) + ':' + escapeHtml(p.port) + authBadge + '</td>' +
      '<td class="col-toggle" data-col="protocol">' + escapeHtml(p.protocol) + '</td>' +
      '<td class="col-toggle" data-col="port">' + escapeHtml(p.port) + '</td>' +
      '<td class="col-toggle" data-col="status"><span class="status-dot ' + statusClass + '"></span> ' + escapeHtml(statusLabel) + '</td>' +
      '<td class="col-toggle" data-col="prev_state">' + escapeHtml(p.previous_state || '-') + '</td>' +
      '<td class="col-toggle" data-col="delta">' + escapeHtml(p.last_transition || '-') + '</td>' +
      '<td class="col-toggle" data-col="cost">' + Number(p.cost || 0).toFixed(3) + '</td>' +
      '<td class="col-toggle" data-col="latency">' + (p.latency_score != null ? Number(p.latency_score).toFixed(3) : '-') + '</td>' +
      '<td class="col-toggle" data-col="reliability">' + (p.reliability != null ? Number(p.reliability).toFixed(3) : '-') + '</td>' +
      '<td class="col-toggle" data-col="jitter">' + (p.jitter_score != null ? Number(p.jitter_score).toFixed(3) : '-') + '</td>' +
      '<td class="col-toggle" data-col="recency">' + (p.recency_score != null ? Number(p.recency_score).toFixed(3) : '-') + '</td>' +
      '<td class="col-toggle" data-col="prev_cost">' + (p.previous_cost != null ? Number(p.previous_cost).toFixed(3) : '-') + '</td>' +
      '<td class="col-toggle" data-col="speed">' + escapeHtml(p.speed_ms == null ? '-' : p.speed_ms) + 'ms</td>' +
      '<td class="col-toggle" data-col="web_https">' + capabilityMark(p.web_https_ok) + '</td>' +
      '<td class="col-toggle" data-col="remote_dns">' + capabilityMark(p.remote_dns_ok) + '</td>' +
      '<td class="col-toggle" data-col="telegram">' + capabilityMark(p.telegram_ok) + '</td>' +
      '<td class="col-toggle" data-col="exit_ip">' + escapeHtml(p.exit_ip || '-') + '</td>' +
      '<td class="col-toggle" data-col="alive">' + escapeHtml(p.alive_hits || 0) + '</td>' +
      '<td class="col-toggle" data-col="fails">' + escapeHtml(p.fail_hits || 0) + '</td>' +
      '<td class="col-toggle" data-col="total_checks">' + escapeHtml(p.total_checks || 0) + '</td>' +
      '<td class="col-toggle" data-col="consecutive_fails">' + escapeHtml(p.consecutive_fails || 0) + '</td>' +
      '<td class="col-toggle" data-col="country">' + escapeHtml(p.countryCode || '-') + '</td>' +
      '<td class="col-toggle" data-col="region">' + escapeHtml(p.regionName || '-') + '</td>' +
      '<td class="col-toggle" data-col="city">' + escapeHtml(p.city || '-') + '</td>' +
      '<td class="col-toggle" data-col="district">' + escapeHtml(p.district || '-') + '</td>' +
      '<td class="col-toggle" data-col="zip">' + escapeHtml(p.zip || '-') + '</td>' +
      '<td class="col-toggle" data-col="isp">' + escapeHtml(p.isp || '-') + '</td>' +
      '<td class="col-toggle" data-col="asn">' + escapeHtml(p.asn || '-') + '</td>' +
      '<td class="col-toggle" data-col="org">' + escapeHtml(p.org || '-') + '</td>' +
      '<td class="col-toggle" data-col="location">' + escapeHtml(locationText) + '</td>' +
      '<td class="col-toggle" data-col="timezone">' + escapeHtml(p.timezone || '-') + '</td>' +
      '<td class="col-toggle" data-col="mobile">' + (p.mobile ? '✓' : '-') + '</td>' +
      '<td class="col-toggle" data-col="hosting">' + (p.hosting ? '✓' : '-') + '</td>' +
      '<td class="col-toggle" data-col="lastalive">' + (p.last_alive ? escapeHtml(new Date(p.last_alive).toLocaleDateString()) : '-') + '</td>' +
      '<td class="col-toggle" data-col="lastcheck">' + (p.last_checked ? escapeHtml(new Date(p.last_checked).toLocaleDateString()) : '-') + '</td>' +
      '<td class="row-actions">' + actionsHtml + '</td>';
    var copyCell = tr.querySelector('.proxy-copy-cell');
    if (copyCell) copyCell.addEventListener('click', function() { copyProxy(proxyUrl); });
    tbody.appendChild(tr);
  });

  document.getElementById('pager-info').textContent = 'Page ' + (data.page || 1) + ' of ' + Math.max(data.pages || 1, 1) + ' (' + (data.total || 0) + ' total)';

  var hasAnyActionPerm = hasPermission('proxies.test') || hasPermission('proxies.edit') || hasPermission('proxies.delete');
  var actionsHeader = document.getElementById('actions-header');
  if (actionsHeader) {
    actionsHeader.style.display = hasAnyActionPerm ? '' : 'none';
  }
  document.querySelectorAll('#proxies-table td:last-child, #proxies-table th:last-child').forEach(function(el) {
    el.style.display = hasAnyActionPerm ? '' : 'none';
  });

  var pagerBtns = '<button class="btn btn-sm" onclick="goPage(1)">&laquo;</button>';
  var pageCount = Math.max(data.pages || 1, 1);
  for (var i = Math.max(1, (data.page || 1) - 2); i <= Math.min(pageCount, (data.page || 1) + 2); i++) {
    pagerBtns += '<button class="btn btn-sm ' + (i === data.page ? 'btn-primary' : '') + '" onclick="goPage(' + i + ')">' + i + '</button>';
  }
  pagerBtns += '<button class="btn btn-sm" onclick="goPage(' + pageCount + ')">&raquo;</button>';
  document.getElementById('pager-btns').innerHTML = pagerBtns;
  initColumns();
}

function goPage(p) {
  currentPage = p;
  loadProxies();
}

function sortTable(col) {
  var colMap = {
    'total_checks': 'total_checks',
    'consecutive_fails': 'consecutive_fails',
    'latency': 'latency_score',
    'reliability': 'reliability',
    'jitter': 'jitter_score',
    'recency': 'recency_score',
    'prev_cost': 'previous_cost'
  };
  var dbCol = colMap[col] || col;
  if (sortCol === dbCol) {
    sortOrder = sortOrder === 'asc' ? 'desc' : 'asc';
  } else {
    sortCol = dbCol;
    sortOrder = 'asc';
  }
  loadProxies();
}

async function doAddProxy() {
  var data = {
    protocol: document.getElementById('add-proto').value,
    ip: document.getElementById('add-ip').value,
    port: parseInt(document.getElementById('add-port').value),
    username: document.getElementById('add-user').value,
    password: document.getElementById('add-pass').value
  };

  if (!data.ip || !data.port) {
    showAlert('IP and port are required');
    return;
  }

  var res = await authFetch('/api/proxies', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
  var result = await res.json();

  if (result.success) {
    closeModal('modal-add');
    loadProxies();
  } else {
    showAlert('Error: ' + result.error);
  }
}

async function doBulkAdd() {
  var data = {
    proxies: document.getElementById('bulk-proxies').value
  };

  var res = await authFetch('/api/proxies/bulk', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
  var result = await res.json();

  if (result.success) {
    closeModal('modal-bulk');
    loadProxies();
    showAlert('Added ' + result.added + ' proxies');
  }
}

function editProxy(id, proto, ip, port) {
  document.getElementById('edit-id').value = id;
  document.getElementById('edit-proto').value = proto;
  document.getElementById('edit-ip').value = ip;
  document.getElementById('edit-port').value = port;
  document.getElementById('edit-user').value = '';
  document.getElementById('edit-pass').value = '';
  document.getElementById('modal-edit').classList.add('active');
}

function editProxyFromButton(button) {
  editProxy(button.dataset.proxyId, button.dataset.protocol, button.dataset.ip, button.dataset.port);
}

function deleteProxyFromButton(button) {
  deleteProxy(Number(button.dataset.proxyId));
}

function testProxyFromButton(button) {
  testProxy(Number(button.dataset.proxyId), button);
}

async function doEditProxy() {
  var id = document.getElementById('edit-id').value;
  var data = {
    protocol: document.getElementById('edit-proto').value,
    ip: document.getElementById('edit-ip').value,
    port: parseInt(document.getElementById('edit-port').value)
  };
  var newUsername = document.getElementById('edit-user').value;
  var newPassword = document.getElementById('edit-pass').value;
  if (newUsername || newPassword) {
    data.username = newUsername;
    data.password = newPassword;
  }

  var res = await authFetch('/api/proxies/' + id, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });

  if (res.ok) {
    closeModal('modal-edit');
    loadProxies();
  }
}

async function deleteProxy(id) {
  showConfirm('Delete Proxy', 'Are you sure you want to delete this proxy?', async function() {
    await authFetch('/api/proxies/' + id, {method: 'DELETE'});
    loadProxies();
  });
}

async function testProxy(id, button) {
  var btn = button || event.target;
  btn.textContent = 'Testing...';
  btn.disabled = true;

  var res = await authFetch('/api/proxies/test/' + id, {method: 'POST'});
  var data = await res.json();

  btn.textContent = data.result === 'alive' ? 'Alive' : 'Dead';
  if (data.validation) {
    showAlert('HTTPS: ' + (data.validation.web_https_ok ? 'OK' : 'NO') + ' | DNS: ' + (data.validation.remote_dns_ok ? 'OK' : 'NO') + ' | Telegram: ' + (data.validation.telegram_ok ? 'OK' : 'NO') + ' | Exit: ' + (data.validation.exit_ip || '-'));
  }
  setTimeout(function() { btn.textContent = 'Test'; btn.disabled = false; loadProxies(); }, 2000);
}

async function exportProxies(fmt) {
  var visibleCols = [];
  document.querySelectorAll('#proxies-table th.col-toggle').forEach(function(th) {
    if (th.style.display !== 'none') {
      visibleCols.push(th.dataset.col);
    }
  });

  var protoEl = document.querySelector('input[name="filter-proto"]:checked');
  var proto = protoEl ? protoEl.value : 'all';
  var statusEl = document.querySelector('input[name="filter-status"]:checked');
  var status = statusEl ? statusEl.value : 'all';

  var params = new URLSearchParams({
    format: fmt,
    columns: visibleCols.join(','),
    proto: proto,
    status: status
  });

  if (searchRules.length > 0) {
    params.append('adv_search', JSON.stringify(searchRules));
  }

  window.location.href = '/api/export?' + params.toString();
}



var previousMonitorState = {};

function formatMonitorTime(isoString) {
  if (!isoString) return '-';
  var d = new Date(isoString);
  var now = new Date();
  var diffMs = now - d;
  var diffMins = Math.floor(diffMs / 60000);
  var diffHours = Math.floor(diffMs / 3600000);
  var diffDays = Math.floor(diffMs / 86400000);

  var timeStr = d.toLocaleTimeString('en-US', {hour: '2-digit', minute: '2-digit'});
  var dateStr = d.toLocaleDateString('en-US', {month: 'short', day: 'numeric'});

  var relativeStr;
  if (diffMins < 1) relativeStr = 'just now';
  else if (diffMins < 60) relativeStr = diffMins + 'm ago';
  else if (diffHours < 24) relativeStr = diffHours + 'h ago';
  else relativeStr = diffDays + 'd ago';

  return timeStr + ' (' + relativeStr + ')';
}


function pct(part, whole) {
  part = Number(part || 0);
  whole = Number(whole || 0);
  return whole > 0 ? Math.round((part / whole) * 100) : 0;
}

function updateStatsInsights(data, statsData) {
  data = data || {};
  statsData = statsData || data;
  var alive = Number(statsData.alive || data.alive || 0);
  var web = Number(data.web_ready || 0);
  var telegram = Number(data.telegram_ready || 0);
  var full = Number(data.full_capability || 0);
  var total = Number(data.total || 0);
  var dead = Number(statsData.dead || data.dead || 0);
  var untested = Number(statsData.untested || data.untested || 0);
  var webPct = pct(web, alive);
  var telegramPct = pct(telegram, alive);
  var fullPct = pct(full, alive);
  setTextSafe('stats-insight-web', webPct + '%');
  setTextSafe('stats-insight-telegram', telegramPct + '%');
  setTextSafe('stats-insight-full', fullPct + '%');

  var note = 'Needs data';
  var detail = 'Import and validate proxies to build quality signals.';
  if (total > 0 && alive === 0) {
    note = 'Validate now';
    detail = 'Inventory exists, but no alive proxies are ready for serving.';
  } else if (alive > 0 && webPct >= 80 && fullPct >= 50) {
    note = 'Strong pool';
    detail = 'The pool is ready for web browsing and advanced use cases.';
  } else if (alive > 0 && webPct >= 40) {
    note = 'Usable pool';
    detail = 'Web-ready capacity exists; keep monitoring for stronger quality.';
  } else if (alive > 0) {
    note = 'Partial pool';
    detail = 'Alive proxies exist, but capability validation is still thin.';
  }
  setTextSafe('stats-insight-note', note);
  setTextSafe('stats-insight-note-detail', detail);

  var summary = document.getElementById('stats-insight-summary');
  if (summary) {
    summary.textContent = 'Total ' + total + ' · Alive ' + alive + ' · Dead ' + dead + ' · Untested ' + untested + ' · Web-ready ' + web + ' · Telegram-ready ' + telegram + ' · Full-capability ' + full;
  }
}

async function loadStats() {
  try {
    var res = await authFetch('/api/stats');
    var data = await res.json();

    var protoEl = document.querySelector('#tab-proxies select');
    var currentProto = protoEl ? protoEl.value : 'all';

    var statsData = data;
    if (currentProto !== 'all' && data.protocol_stats && data.protocol_stats[currentProto]) {
      statsData = data.protocol_stats[currentProto];
    }

    document.getElementById('stat-total').textContent = data.total;
    document.getElementById('stat-alive').textContent = statsData.alive || 0;
    document.getElementById('stat-soft').textContent = statsData.soft || 0;
    document.getElementById('stat-dead').textContent = statsData.dead || 0;
    document.getElementById('stat-flaky').textContent = statsData.flaky || 0;
    document.getElementById('stat-cooling').textContent = statsData.cooling || 0;
    document.getElementById('stat-revived').textContent = statsData.revived || 0;
    document.getElementById('stat-semi-revived').textContent = statsData['semi-revived'] || 0;
    document.getElementById('stat-untested').textContent = statsData.untested || 0;
    document.getElementById('stat-speed').textContent = data.avg_speed + 'ms';

    document.getElementById('filter-count-alive').textContent = statsData.alive || 0;
    document.getElementById('filter-count-soft').textContent = statsData.soft || 0;
    document.getElementById('filter-count-flaky').textContent = statsData.flaky || 0;
    document.getElementById('filter-count-cooling').textContent = statsData.cooling || 0;
    document.getElementById('filter-count-dead').textContent = statsData.dead || 0;
    document.getElementById('filter-count-revived').textContent = statsData.revived || 0;
    document.getElementById('filter-count-semi-revived').textContent = statsData['semi-revived'] || 0;
    document.getElementById('filter-count-untested').textContent = statsData.untested || 0;

    var setTxt = function(id, v) { var el = document.getElementById(id); if (el) el.textContent = v || 0; };
    setTxt('cap-count-web', data.web_ready);
    setTxt('cap-count-telegram', data.telegram_ready);
    setTxt('cap-count-dns', data.dns_ready);
    setTxt('stat-web-ready', data.web_ready);
    setTxt('stat-telegram-ready', data.telegram_ready);
    setTxt('stat-full-capability', data.full_capability);
    updateInventoryOverview(data, statsData);
    updateStatsInsights(data, statsData);

    var lastScanInfo = document.getElementById('last-scan-info');
    var lastScanTime = null;

    if (currentProto !== 'all' && data.protocol_stats && data.protocol_stats[currentProto] && data.protocol_stats[currentProto].last_check) {
      lastScanTime = data.protocol_stats[currentProto].last_check;
    } else if (currentProto === 'all') {
      var protocols = ['http', 'https', 'socks4', 'socks5'];
      var newestTime = data.last_scan;
      protocols.forEach(function(p) {
        if (data.protocol_stats && data.protocol_stats[p] && data.protocol_stats[p].last_check) {
          if (!newestTime || new Date(data.protocol_stats[p].last_check) > new Date(newestTime)) {
            newestTime = data.protocol_stats[p].last_check;
          }
        }
      });
      lastScanTime = newestTime;
    }

    if (lastScanTime) {
      var lastCheck = new Date(lastScanTime);
      var now = new Date();
      var diffMs = now - lastCheck;
      var diffMins = Math.floor(diffMs / 60000);

      var dotColor = '#ef4444';
      var timeDisplay = '';

      if (diffMins < 5) {
        dotColor = '#22c55e';
        timeDisplay = 'now';
      } else if (diffMins < 60) {
        timeDisplay = diffMins + ' min ago';
      } else if (diffMins < 1440) {
        timeDisplay = Math.floor(diffMins / 60) + ' hours ago';
      } else {
        timeDisplay = Math.floor(diffMins / 1440) + ' days ago';
      }

      var fullTime = lastCheck.toLocaleString();
      lastScanInfo.innerHTML = '<span style="display:inline-flex;align-items:center;gap:4px;font-size:12px"><span style="width:6px;height:6px;border-radius:50%;background:' + dotColor + ';display:inline-block"></span><span>' + timeDisplay + '</span><span style="color:var(--muted)">(' + fullTime + ')</span></span>';
    } else {
      lastScanInfo.innerHTML = '';
    }
    updateStatusFilterUI();

    var maxVal = Math.max(data.alive, data.flaky, data.cooling, data.soft, data.revived, data['semi-revived'], data.dead, data.untested) || 1;
    document.getElementById('chart-bar-alive').style.height = (data.alive / maxVal) * 150 + 'px';
    document.getElementById('chart-bar-flaky').style.height = (data.flaky / maxVal) * 150 + 'px';
    document.getElementById('chart-bar-cooling').style.height = (data.cooling / maxVal) * 150 + 'px';
    document.getElementById('chart-bar-soft').style.height = (data.soft / maxVal) * 150 + 'px';
    document.getElementById('chart-bar-revived').style.height = (data.revived / maxVal) * 150 + 'px';
    document.getElementById('chart-bar-semi-revived').style.height = (data['semi-revived'] / maxVal) * 150 + 'px';
    document.getElementById('chart-bar-dead').style.height = (data.dead / maxVal) * 150 + 'px';
    document.getElementById('chart-bar-untested').style.height = (data.untested / maxVal) * 150 + 'px';
    document.getElementById('chart-label-alive').textContent = data.alive;
    document.getElementById('chart-label-flaky').textContent = data.flaky;
    document.getElementById('chart-label-cooling').textContent = data.cooling;
    document.getElementById('chart-label-soft').textContent = data.soft;
    document.getElementById('chart-label-revived').textContent = data.revived;
    document.getElementById('chart-label-semi-revived').textContent = data['semi-revived'];
    document.getElementById('chart-label-dead').textContent = data.dead;
    document.getElementById('chart-label-untested').textContent = data.untested;

    var protoList = document.getElementById('stats-protocol-list');
    protoList.innerHTML = '';
    if (data.by_protocol) {
      for (var proto in data.by_protocol) {
        var cnt = data.by_protocol[proto];
        if (cnt > 0) {
          protoList.innerHTML += '<div style="display:flex;justify-content:space-between;padding:8px;background:var(--panel-light);border-radius:6px"><span style="font-weight:bold">' + proto.toUpperCase() + '</span><span>' + cnt + ' (' + ((cnt/data.total)*100).toFixed(1) + '%)</span></div>';
        }
      }
    }

    var protoBreakdown = document.getElementById('stats-protocol-breakdown');
    protoBreakdown.innerHTML = '';
    if (data.protocol_stats) {
      for (var proto in data.protocol_stats) {
        var stats = data.protocol_stats[proto];
        var total = (stats.alive || 0) + (stats.soft || 0) + (stats.dead || 0) + (stats.flaky || 0) + (stats.cooling || 0) + (stats.revived || 0) + (stats['semi-revived'] || 0) + (stats.untested || 0);
        if (total > 0) {
          protoBreakdown.innerHTML += '<div style="background:var(--panel-light);padding:12px;border-radius:8px"><div style="font-weight:bold;margin-bottom:8px">' + proto.toUpperCase() + '</div><div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;font-size:12px"><div style="color:var(--success)">Alive: ' + (stats.alive||0) + '</div><div style="color:#FF9800">Soft: ' + (stats.soft||0) + '</div><div style="color:#f59e0b">Flaky: ' + (stats.flaky||0) + '</div><div style="color:#8b5cf6">Cooling: ' + (stats.cooling||0) + '</div><div style="color:var(--danger)">Dead: ' + (stats.dead||0) + '</div><div style="color:#757575">Revived: ' + (stats.revived||0) + '</div><div style="color:#424242">Semi: ' + (stats['semi-revived']||0) + '</div><div style="color:var(--muted)">Untested: ' + (stats.untested||0) + '</div></div></div>';
        }
      }
    }

    var countryList = document.getElementById('stats-country-list');
    countryList.innerHTML = '';
    if (data.by_country && data.by_country.length > 0) {
      var maxCountry = data.by_country[0] ? data.by_country[0].count : 1;
      data.by_country.forEach(function(c, i) {
        countryList.innerHTML += '<div style="display:flex;align-items:center;gap:12px"><span style="width:20px;font-weight:bold;color:var(--muted)">' + (i+1) + '</span><span style="width:60px">' + escapeHtml(c.country) + '</span><div style="flex:1;height:16px;background:var(--panel-light);border-radius:4px"><div style="height:100%;width:' + (c.count/maxCountry)*100 + '%;background:var(--accent);border-radius:4px"></div></div><span style="width:50px;text-align:right">' + c.count + '</span></div>';
      });
    }

    var ispList = document.getElementById('stats-isp-list');
    ispList.innerHTML = '';
    if (data.by_isp && data.by_isp.length > 0) {
      var maxIsp = data.by_isp[0] ? data.by_isp[0].count : 1;
      data.by_isp.forEach(function(isp, i) {
        ispList.innerHTML += '<div style="display:flex;align-items:center;gap:12px"><span style="width:20px;font-weight:bold;color:var(--muted)">' + (i+1) + '</span><span style="width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + escapeHtml(isp.isp) + '</span><div style="flex:1;height:16px;background:var(--panel-light);border-radius:4px"><div style="height:100%;width:' + (isp.count/maxIsp)*100 + '%;background:var(--accent);border-radius:4px"></div></div><span style="width:50px;text-align:right">' + isp.count + '</span></div>';
      });
    }
  } catch (e) {
    console.error('loadStats error:', e);
  }
}

async function loadSettings() {
  var res = await authFetch('/api/settings');
  var data = await res.json();
  if (data.db_type === 'mysql') {
    document.getElementById('db-info').textContent = 'MySQL: ' + data.db_name;
    setTextSafe('settings-db-summary', 'Production-style external database');
  } else {
    var sqliteLabel = (data.db_path || data.sqlite_db_path || 'SQLite') + ' - ' + Number(data.db_size || 0).toFixed(2) + ' MB';
    document.getElementById('db-info').textContent = sqliteLabel;
    setTextSafe('settings-db-summary', 'Local SQLite default');
  }
}

function escapeHtml(text) {
  return String(text == null ? '' : text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function diagnosticCard(label, value, color) {
  return '<div class="settings-diagnostic-card">' +
    '<div class="settings-diagnostic-label">' + escapeHtml(label) + '</div>' +
    '<div class="settings-diagnostic-value" style="color:' + (color || 'var(--text)') + '">' + escapeHtml(value) + '</div>' +
    '</div>';
}

async function loadDiagnostics() {
  var statusEl = document.getElementById('diagnostics-status');
  var panel = document.getElementById('diagnostics-panel');
  var recs = document.getElementById('diagnostics-recommendations');
  if (!panel || !recs) return;
  if (statusEl) statusEl.textContent = 'Loading...';
  try {
    var res = await authFetch('/api/settings/diagnostics');
    var data = await res.json();
    if (!data.success) throw new Error(data.error || 'diagnostics failed');
    var c = data.counts || {};
    var db = data.db || {};
    panel.innerHTML = '' +
      diagnosticCard('DB', (db.type || '-').toUpperCase(), db.type === 'sqlite' ? 'var(--success)' : 'var(--accent)') +
      diagnosticCard('SQLite size', Number(db.sqlite_size_mb || 0).toFixed(2) + ' MB') +
      diagnosticCard('Total proxies', c.total || 0) +
      diagnosticCard('Alive', c.alive || 0, 'var(--success)') +
      diagnosticCard('Web-ready', c.web_ready || 0, 'var(--success)') +
      diagnosticCard('Telegram-ready', c.telegram_ready || 0, '#0088cc') +
      diagnosticCard('Full-capability', c.full_capability || 0, 'var(--accent)') +
      diagnosticCard('Legacy revived', c.legacy_revived || 0, (c.legacy_revived || 0) > 0 ? 'var(--danger)' : 'var(--success)') +
      diagnosticCard('Progress files', (data.runtime && data.runtime.progress_files) || 0);
    recs.innerHTML = (data.recommendations || []).map(function(r) {
      return '<div style="background:var(--panel-light);border-left:3px solid var(--accent);padding:8px;border-radius:6px">' + escapeHtml(r) + '</div>';
    }).join('');
    if (statusEl) statusEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (e) {
    panel.innerHTML = '';
    recs.innerHTML = '<div style="color:var(--danger)">Diagnostics failed: ' + escapeHtml(e.message || e) + '</div>';
    if (statusEl) statusEl.textContent = 'Failed';
  }
}

async function changePassword() {
  var pass = document.getElementById('new-password').value;
  if (!pass) { showAlert('Password required'); return; }

  var res = await authFetch('/api/settings/password', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({password: pass})
  });

  if (res.ok) {
    showAlert('Password updated');
    document.getElementById('new-password').value = '';
  }
}

async function backupDB() {
  var res = await authFetch('/api/settings/backup', {method: 'POST'});
  var data = await res.json();
  if (data.success) {
    showAlert('Backup created: ' + data.file + ' (' + data.size_mb.toFixed(2) + ' MB)');
    window.location.href = '/api/settings/backup/download';
  } else {
    showAlert('Backup failed: ' + data.error);
  }
}

function openImportModal() {
  document.getElementById('import-modal').style.display = 'block';
}

async function importDB() {
  var fileInput = document.getElementById('import-file');
  var mode = document.getElementById('import-mode').value;
  var btn = document.getElementById('import-btn');

  if (!fileInput.files[0]) {
    showAlert('Please select a file');
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Importing...';

  var formData = new FormData();
  formData.append('file', fileInput.files[0]);
  formData.append('mode', mode);

  try {
    var res = await authFetch('/api/settings/import', {
      method: 'POST',
      body: formData
    });
    var data = await res.json();

    if (data.success) {
      showAlert('Import successful!');
      document.getElementById('import-modal').style.display = 'none';
      fileInput.value = '';
      loadProxies();
      loadStats();
    } else {
      showAlert('Import failed: ' + (data.error || 'Unknown error'));
    }
  } catch(e) {
    showAlert('Error: ' + e);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Import';
  }
}

async function clearDeadProxies() {
  showConfirm('Delete Dead Proxies', 'Delete all dead proxies (fail_hits >= 5)? This cannot be undone.', async function() {
    var res = await authFetch('/api/proxies/delete', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({filter: 'all', protocol: 'all', status: 'dead'})
    });
    var data = await res.json();
    if (data.success) {
      showAlert('Deleted ' + data.deleted + ' dead proxies');
      loadProxies();
      loadStats();
    } else {
      showAlert('Error: ' + (data.error || 'Unknown error'));
    }
  });
}

async function clearByProtocol(protocol) {
  showConfirm('Delete Proxies', 'Delete all ' + protocol.toUpperCase() + ' proxies? This cannot be undone.', async function() {
    var res = await authFetch('/api/proxies/delete', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({filter: 'all', protocol: protocol, status: 'all'})
    });
    var data = await res.json();
    if (data.success) {
      showAlert('Deleted ' + data.deleted + ' ' + protocol.toUpperCase() + ' proxies');
      loadProxies();
      loadStats();
    } else {
      showAlert('Error: ' + (data.error || 'Unknown error'));
    }
  });
}

async function clearAllProxies() {
  showConfirm('Delete ALL Proxies', 'WARNING: Delete ALL proxies? This cannot be undone!', function() {
    showConfirm('Confirm Delete', 'Are you absolutely sure? This will delete all data.', async function() {
      var res = await authFetch('/api/proxies/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({filter: 'all', protocol: 'all', status: 'all'})
      });
      var data = await res.json();
      if (data.success) {
        showAlert('Deleted ' + data.deleted + ' proxies');
        loadProxies();
        loadStats();
      } else {
        showAlert('Error: ' + (data.error || 'Unknown error'));
      }
    }, {confirmText: 'Yes, Delete All', confirmClass: 'btn-danger'});
  }, {confirmText: 'Continue', confirmClass: 'btn-primary'});
}

async function bulkDeleteProxies() {
  var protocol = document.getElementById('delete-protocol').value;
  var status = document.getElementById('delete-status').value;

  var confirmMsg = 'Delete all ' + (protocol === 'all' ? '' : protocol.toUpperCase()) + ' proxies';
  if (status !== 'all') confirmMsg += ' with status "' + status + '"';
  confirmMsg += '? This cannot be undone.';

  showConfirm('Delete Proxies', confirmMsg, async function() {
    var res = await authFetch('/api/proxies/delete', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({filter: 'custom', protocol: protocol, status: status})
    });
    var data = await res.json();
    if (data.success) {
      showAlert('Deleted ' + data.deleted + ' proxies');
      loadProxies();
      loadStats();
    } else {
      showAlert('Error: ' + (data.error || 'Unknown error'));
    }
  });
}

async function cleanupLogs() {
  showConfirm('Clear Logs', 'Delete dashboard/server/monitor log files? This does not delete the database.', async function() {
    var res = await authFetch('/api/settings/cleanup/logs', {method: 'POST'});
    var data = await res.json();
    if (data.success) showAlert('Deleted ' + data.deleted + ' log files');
    else showAlert('Cleanup failed: ' + (data.error || 'Unknown error'));
  }, {confirmText: 'Clear Logs', confirmClass: 'btn-danger'});
}

async function cleanupRuntimeFiles() {
  showConfirm('Clear Runtime Files', 'Delete stale monitor/server config and progress files? Running processes should be stopped first.', async function() {
    var res = await authFetch('/api/settings/cleanup/runtime', {method: 'POST'});
    var data = await res.json();
    if (data.success) {
      showAlert('Deleted ' + data.deleted + ' runtime items');
      checkMonitorStatus();
      checkServerStatus();
    } else showAlert('Cleanup failed: ' + (data.error || 'Unknown error'));
  }, {confirmText: 'Clear Runtime', confirmClass: 'btn-danger'});
}

async function cleanupLegacyStatuses() {
  showConfirm('Normalize Legacy Statuses', 'Convert old pre-Phase-5 revived records into dead/soft. This keeps proxies but changes statuses.', async function() {
    var res = await authFetch('/api/settings/cleanup/legacy-statuses', {method: 'POST'});
    var data = await res.json();
    if (data.success) {
      showAlert('Updated ' + data.updated + ' proxies (revived→dead: ' + data.revived_to_dead + ', revived→soft: ' + data.revived_to_soft + ')');
      loadProxies();
      loadStats();
    } else showAlert('Cleanup failed: ' + (data.error || 'Unknown error'));
  }, {confirmText: 'Normalize', confirmClass: 'btn-primary'});
}

async function updateProxyFilterInfo() {
  var proto = document.querySelector('input[name="filter-proto"]:checked') ? document.querySelector('input[name="filter-proto"]:checked').value : 'all';
  var info = document.getElementById('proxy-filter-info');

  if (!cachedStats || proto === 'all') {
    info.innerHTML = '';
    return;
  }

  var stats = cachedStats.protocol_stats && cachedStats.protocol_stats[proto];
  if (!stats) {
    info.innerHTML = '';
    return;
  }

  var lastCheck = formatTimeAgo(stats.last_check);
  var total = (stats.alive || 0) + (stats.dead || 0) + (stats.flaky || 0) + (stats.cooling || 0) + (stats.untested || 0);

  info.innerHTML =
    '<span style="background:var(--panel-light);padding:3px 10px;border-radius:12px;font-size:11px;margin-left:8px">' +
      '<span style="color:var(--muted)">Last:</span> <span style="color:var(--text)">' + lastCheck + '</span>' +
    '</span>' +
    '<span style="background:rgba(34,197,94,0.15);color:var(--success);padding:3px 8px;border-radius:12px;font-size:11px;margin-left:4px;border:1px solid rgba(34,197,94,0.3)">' +
      (stats.alive || 0) + ' alive' +
    '</span>' +
    '<span style="background:rgba(245,158,11,0.15);color:#f59e0b;padding:3px 8px;border-radius:12px;font-size:11px;margin-left:4px;border:1px solid rgba(245,158,11,0.3)">' +
      (stats.flaky || 0) + ' flaky' +
    '</span>' +
    '<span style="background:rgba(139,92,246,0.15);color:#8b5cf6;padding:3px 8px;border-radius:12px;font-size:11px;margin-left:4px;border:1px solid rgba(139,92,246,0.3)">' +
      (stats.cooling || 0) + ' cooling' +
    '</span>' +
    '<span style="background:rgba(239,68,68,0.15);color:var(--danger);padding:3px 8px;border-radius:12px;font-size:11px;margin-left:4px;border:1px solid rgba(239,68,68,0.3)">' +
      (stats.dead || 0) + ' dead' +
    '</span>' +
    '<span style="background:rgba(107,114,128,0.15);color:var(--muted);padding:3px 8px;border-radius:12px;font-size:11px;margin-left:4px;border:1px solid rgba(107,114,128,0.3)">' +
      (stats.untested || 0) + ' untested' +
    '</span>';
}

initTheme();
loadCurrentUserPermissions();
updateImportModeSummary('url');

document.addEventListener('click', function(e) {
  var colsBtn = e.target.closest('button') && e.target.closest('button').getAttribute('onclick');
  if (!e.target.closest('#columns-menu') && colsBtn !== 'toggleColumnsMenu()') {
    var colsMenu = document.getElementById('columns-menu');
    if (colsMenu) colsMenu.style.display = 'none';
  }
});

loadCockpit();
