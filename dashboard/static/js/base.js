function getToken() {
  return localStorage.getItem('token') || '';
}

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
  const token = getToken();
  options.headers = options.headers || {};
  if (token) {
    options.headers['Authorization'] = 'Bearer ' + token;
  }
  return fetch(url, options);
}

function toggleRunModeOptions() {
  const mode = document.getElementById('monitor-run-mode').value;
  const optionsDiv = document.getElementById('run-mode-options');
  const intervalOption = document.getElementById('interval-option');
  const scheduleOption = document.getElementById('schedule-option');
  const customOption = document.getElementById('custom-option');
  
  if (mode === 'once') {
    optionsDiv.style.display = 'none';
  } else if (mode === 'infinite' || mode === 'restart') {
    optionsDiv.style.display = 'block';
    intervalOption.style.display = 'block';
    scheduleOption.style.display = 'none';
    customOption.style.display = 'none';
  } else if (mode === 'schedule') {
    optionsDiv.style.display = 'block';
    intervalOption.style.display = 'none';
    scheduleOption.style.display = 'block';
    customOption.style.display = 'none';
  } else if (mode === 'custom') {
    optionsDiv.style.display = 'block';
    intervalOption.style.display = 'none';
    scheduleOption.style.display = 'none';
    customOption.style.display = 'block';
  }
}

let monitorStatusEnabled = {alive: true, soft: true, flaky: true, cooling: true, dead: true, revived: true, 'semi-revived': true, untested: true};

function toggleMonitorStatus(status) {
  monitorStatusEnabled[status] = !monitorStatusEnabled[status];
  const el = document.getElementById('monitor-status-' + status);
  if (monitorStatusEnabled[status]) {
    el.style.opacity = '1';
    el.style.filter = 'none';
  } else {
    el.style.opacity = '0.3';
    el.style.filter = 'grayscale(100%)';
  }
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
  var saved = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', saved);
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

let userProxyFilters = { statuses: [], protocols: [] };

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

function applyTabPermissions() {
  if (!hasPermission('proxies.view')) {
    document.querySelectorAll('.nav-btn').forEach(function(btn) {
      if (btn.textContent.includes('Proxies')) btn.style.display = 'none';
    });
    document.getElementById('tab-proxies')?.classList.add('hidden');
  }
  if (!hasPermission('proxies.import')) {
    document.querySelectorAll('.nav-btn').forEach(function(btn) {
      if (btn.textContent.includes('Import')) btn.style.display = 'none';
    });
  }
  if (!hasPermission('monitor.view')) {
    document.querySelectorAll('.nav-btn').forEach(function(btn) {
      if (btn.textContent.includes('Monitor')) btn.style.display = 'none';
    });
  }
  if (!hasPermission('server.view')) {
    document.querySelectorAll('.nav-btn').forEach(function(btn) {
      if (btn.textContent.includes('Server')) btn.style.display = 'none';
    });
  }
  if (!hasPermission('stats.view')) {
    document.querySelectorAll('.nav-btn').forEach(function(btn) {
      if (btn.textContent.includes('Stats')) btn.style.display = 'none';
    });
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
  if (!hasPermission('users.manage')) {
    document.querySelector('.theme-toggle[onclick*="modal-users"]')?.style.setProperty('display', 'none');
  }
}

let selectedStatuses = ['alive', 'flaky', 'cooling', 'soft', 'revived', 'semi-revived', 'dead', 'untested'];

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

async function fetchStats() {
  var res = await authFetch('/api/stats');
  cachedStats = await res.json();
}

function toggleColumn(col, show) {
  if (!hasPermission('proxies.columns')) return;
  
  var display = show ? '' : 'none';
  var colMap = {protocol: 2, port: 3, status: 4, cost: 5, speed: 6, alive: 7, fails: 8, country: 9, region: 10, city: 11, isp: 12, asn: 13, org: 14, mobile: 15, hosting: 16, lastalive: 17, lastcheck: 18};
  var colIdx = colMap[col];
  
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

var currentTab = 'proxies';

function showTab(tab) {
  currentTab = tab;
  var guide = document.querySelector('.product-guide');
  if (guide) guide.style.display = ['proxies','import','monitor','server'].includes(tab) ? 'grid' : 'none';
  document.querySelectorAll('.tab-content').forEach(function(el) { el.classList.add('hidden'); });
  document.getElementById('tab-' + tab).classList.remove('hidden');
  document.querySelectorAll('.nav-btn').forEach(function(el) { el.classList.remove('active'); });
  event.target.classList.add('active');

  if (tab === 'proxies') {
    loadProxies();
    fetchStats();
    applyProxyFiltersToUI();
  }
  if (tab === 'stats') loadStats();
  if (tab === 'monitor') checkMonitorStatus();
  if (tab === 'server') checkServerStatus();
}

function showImportTab(tab) {
  document.querySelectorAll('.import-panel').forEach(function(el) { el.classList.add('hidden'); });
  document.getElementById('import-' + tab).classList.remove('hidden');
  document.querySelectorAll('.tab-btn').forEach(function(el) { el.classList.remove('active'); });
  event.target.classList.add('active');
}

function openModal(id) {
  document.getElementById(id).classList.add('active');
  if (id === 'modal-settings') loadSettings();
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
      '<td style="padding:8px">' + u.username + '</td>' +
      '<td style="padding:8px">' + u.role + '</td>' +
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

  if (searchRules.length > 0) {
    params.append('adv_search', JSON.stringify(searchRules));
  }

  var res = await authFetch('/api/proxies?' + params);
  var data = await res.json();

  var tbody = document.getElementById('proxies-tbody');
  tbody.innerHTML = '';

  data.proxies.forEach(function(p) {
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
    var proxyUrl = p.username && p.password 
      ? p.protocol + '://' + p.username + ':' + p.password + '@' + p.ip + ':' + p.port
      : p.protocol + '://' + p.ip + ':' + p.port;
    var actionsHtml = '';
    if (hasPermission('proxies.test')) {
      actionsHtml += '<button class="btn btn-sm" onclick="testProxy(' + p.id + ')">Test</button> ';
    }
    if (hasPermission('proxies.edit')) {
      actionsHtml += '<button class="btn btn-sm" onclick="editProxy(' + p.id + ',\'' + p.protocol + '\',\'' + p.ip + '\',' + p.port + ',\'' + (p.username||'') + '\',\'' + (p.password||'') + '\')">Edit</button> ';
    }
    if (hasPermission('proxies.delete')) {
      actionsHtml += '<button class="btn btn-sm btn-danger" onclick="deleteProxy(' + p.id + ')">Del</button>';
    }
    tr.innerHTML = 
      '<td style="cursor:pointer;color:var(--accent);font-weight:500" onclick="copyProxy(\'' + proxyUrl + '\')" title="Click to copy">' + p.ip + ':' + p.port + '</td>' +
      '<td class="col-toggle" data-col="protocol">' + p.protocol + '</td>' +
      '<td class="col-toggle" data-col="port">' + p.port + '</td>' +
      '<td class="col-toggle" data-col="status"><span class="status-dot ' + statusClass + '"></span> ' + statusLabel + '</td>' +
      '<td class="col-toggle" data-col="prev_state">' + (p.previous_state || '-') + '</td>' +
      '<td class="col-toggle" data-col="delta">' + (p.last_transition || '-') + '</td>' +
      '<td class="col-toggle" data-col="cost">' + (p.cost || 0).toFixed(3) + '</td>' +
      '<td class="col-toggle" data-col="latency">' + (p.latency_score != null ? (p.latency_score).toFixed(3) : '-') + '</td>' +
      '<td class="col-toggle" data-col="reliability">' + (p.reliability != null ? (p.reliability).toFixed(3) : '-') + '</td>' +
      '<td class="col-toggle" data-col="jitter">' + (p.jitter_score != null ? (p.jitter_score).toFixed(3) : '-') + '</td>' +
      '<td class="col-toggle" data-col="recency">' + (p.recency_score != null ? (p.recency_score).toFixed(3) : '-') + '</td>' +
      '<td class="col-toggle" data-col="prev_cost">' + (p.previous_cost != null ? (p.previous_cost).toFixed(3) : '-') + '</td>' +
      '<td class="col-toggle" data-col="speed">' + (p.speed_ms || '-') + 'ms</td>' +
      '<td class="col-toggle" data-col="alive">' + (p.alive_hits || 0) + '</td>' +
      '<td class="col-toggle" data-col="fails">' + (p.fail_hits || 0) + '</td>' +
      '<td class="col-toggle" data-col="total_checks">' + (p.total_checks || 0) + '</td>' +
      '<td class="col-toggle" data-col="consecutive_fails">' + (p.consecutive_fails || 0) + '</td>' +
      '<td class="col-toggle" data-col="country">' + (p.countryCode || '-') + '</td>' +
      '<td class="col-toggle" data-col="region">' + (p.regionName || '-') + '</td>' +
      '<td class="col-toggle" data-col="city">' + (p.city || '-') + '</td>' +
      '<td class="col-toggle" data-col="district">' + (p.district || '-') + '</td>' +
      '<td class="col-toggle" data-col="zip">' + (p.zip || '-') + '</td>' +
      '<td class="col-toggle" data-col="isp">' + (p.isp || '-') + '</td>' +
      '<td class="col-toggle" data-col="asn">' + (p.asn || '-') + '</td>' +
      '<td class="col-toggle" data-col="org">' + (p.org || '-') + '</td>' +
      '<td class="col-toggle" data-col="location">' + (p.lat && p.lon ? p.lat.toFixed(4) + ',' + p.lon.toFixed(4) : '-') + '</td>' +
      '<td class="col-toggle" data-col="timezone">' + (p.timezone || '-') + '</td>' +
      '<td class="col-toggle" data-col="mobile">' + (p.mobile ? '✓' : '-') + '</td>' +
      '<td class="col-toggle" data-col="hosting">' + (p.hosting ? '✓' : '-') + '</td>' +
      '<td class="col-toggle" data-col="lastalive">' + (p.last_alive ? new Date(p.last_alive).toLocaleDateString() : '-') + '</td>' +
      '<td class="col-toggle" data-col="lastcheck">' + (p.last_checked ? new Date(p.last_checked).toLocaleDateString() : '-') + '</td>' +
      '<td class="row-actions">' + actionsHtml + '</td>';
    tbody.appendChild(tr);
  });

  document.getElementById('pager-info').textContent = 'Page ' + data.page + ' of ' + data.pages + ' (' + data.total + ' total)';

  var hasAnyActionPerm = hasPermission('proxies.test') || hasPermission('proxies.edit') || hasPermission('proxies.delete');
  var actionsHeader = document.getElementById('actions-header');
  if (actionsHeader) {
    actionsHeader.style.display = hasAnyActionPerm ? '' : 'none';
  }
  document.querySelectorAll('#proxies-table td:last-child, #proxies-table th:last-child').forEach(function(el) {
    el.style.display = hasAnyActionPerm ? '' : 'none';
  });

  var pagerBtns = '<button class="btn btn-sm" onclick="goPage(1)">&laquo;</button>';
  for (var i = Math.max(1, data.page - 2); i <= Math.min(data.pages, data.page + 2); i++) {
    pagerBtns += '<button class="btn btn-sm ' + (i === data.page ? 'btn-primary' : '') + '" onclick="goPage(' + i + ')">' + i + '</button>';
  }
  pagerBtns += '<button class="btn btn-sm" onclick="goPage(' + data.pages + ')">&raquo;</button>';
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

function editProxy(id, proto, ip, port, user, pass) {
  document.getElementById('edit-id').value = id;
  document.getElementById('edit-proto').value = proto;
  document.getElementById('edit-ip').value = ip;
  document.getElementById('edit-port').value = port;
  document.getElementById('edit-user').value = user;
  document.getElementById('edit-pass').value = pass;
  document.getElementById('modal-edit').classList.add('active');
}

async function doEditProxy() {
  var id = document.getElementById('edit-id').value;
  var data = {
    protocol: document.getElementById('edit-proto').value,
    ip: document.getElementById('edit-ip').value,
    port: parseInt(document.getElementById('edit-port').value),
    username: document.getElementById('edit-user').value,
    password: document.getElementById('edit-pass').value
  };

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

async function testProxy(id) {
  var btn = event.target;
  btn.textContent = 'Testing...';
  btn.disabled = true;

  var res = await authFetch('/api/proxies/test/' + id, {method: 'POST'});
  var data = await res.json();

  btn.textContent = data.result === 'alive' ? 'Alive' : 'Dead';
  setTimeout(function() { btn.textContent = 'Test'; btn.disabled = false; }, 2000);
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

async function doImportUrl() {
  var proto = document.getElementById('import-url-proto').value;
  var url = document.getElementById('import-url-input').value;
  if (!url) { showAlert('URL required'); return; }

  var countText = document.getElementById('import-url-count').textContent;
  var match = countText.match(/Found (\d+)/);
  var count = match ? parseInt(match[1]) : 0;
  
  if (count > 0) {
    showConfirm('Import Proxies', 'Import ' + count + ' proxies from URL?', async function() {
      document.getElementById('import-result').innerHTML = 'Importing...';
      var res = await authFetch('/api/import', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: 'url', protocol: proto, url: url})
      });
      var data = await res.json();
      document.getElementById('import-result').innerHTML = data.success 
        ? 'Imported: ' + (data.added || 0) + ', Skipped (duplicates): ' + (data.skipped || 0) + '<br><pre style="font-size:10px;max-height:100px;overflow:auto">' + (data.message || '') + '</pre>' 
        : 'Error: ' + data.error;
    }, {confirmText: 'Import', confirmClass: 'btn-primary'});
    return;
  }

  document.getElementById('import-result').innerHTML = 'Importing...';
  var res = await authFetch('/api/import', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mode: 'url', protocol: proto, url: url})
  });
  var data = await res.json();
  document.getElementById('import-result').innerHTML = data.success 
    ? 'Imported: ' + (data.added || 0) + ', Skipped (duplicates): ' + (data.skipped || 0) + '<br><pre style="font-size:10px;max-height:100px;overflow:auto">' + (data.message || '') + '</pre>' 
    : 'Error: ' + data.error;
}

async function doImportLinks() {
  var content = document.getElementById('import-links-content').value;
  if (!content) { showAlert('Content required'); return; }

  var countText = document.getElementById('import-links-count').textContent;
  var match = countText.match(/Total: (\d+)/);
  var count = match ? parseInt(match[1]) : 0;
  
  if (count > 0) {
    showConfirm('Import Proxies', 'Import ' + count + ' proxies?', async function() {
      document.getElementById('import-result').innerHTML = 'Importing...';
      var res = await authFetch('/api/import', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: 'links', content: content})
      });
      var data = await res.json();
      var resultText = data.success 
        ? 'Imported: ' + (data.added || 0) + ', Skipped (duplicates): ' + (data.skipped || 0)
        : 'Error: ' + data.error;
      document.getElementById('import-result').innerHTML = resultText;
      loadProxies();
    }, {confirmText: 'Import', confirmClass: 'btn-primary'});
    return;
  }

  document.getElementById('import-result').innerHTML = 'Importing...';
  var res = await authFetch('/api/import', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mode: 'links', content: content})
  });
  var data = await res.json();
  var resultText = data.success 
    ? 'Imported: ' + (data.added || 0) + ', Skipped (duplicates): ' + (data.skipped || 0)
    : 'Error: ' + data.error;
  document.getElementById('import-result').innerHTML = resultText;
  loadProxies();
}

async function doImportManual() {
  var proxies = document.getElementById('import-manual-content').value;
  if (!proxies) { showAlert('Proxies required'); return; }

  var countText = document.getElementById('import-manual-count').textContent;
  var match = countText.match(/Total: (\d+)/);
  var count = match ? parseInt(match[1]) : 0;
  
  if (count > 0) {
    showConfirm('Import Proxies', 'Import ' + count + ' proxies?', async function() {
      var res = await authFetch('/api/import', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: 'manual', proxies: proxies})
      });
      var data = await res.json();
      document.getElementById('import-result').innerHTML = 'Added: ' + data.added + ', Skipped: ' + data.skipped;
      loadProxies();
    }, {confirmText: 'Import', confirmClass: 'btn-primary'});
    return;
  }

  var res = await authFetch('/api/import', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({mode: 'manual', proxies: proxies})
  });
  var data = await res.json();
  document.getElementById('import-result').innerHTML = 'Added: ' + data.added + ', Skipped: ' + data.skipped;
  loadProxies();
}

function clearImportCount(type) {
  document.getElementById('import-' + type + '-count').textContent = '';
}

function handleLinksFileUpload() {
  var file = document.getElementById('import-links-file').files[0];
  if (!file) return;
  
  var reader = new FileReader();
  reader.onload = function(e) {
    document.getElementById('import-links-content').value = e.target.result;
    countImportLinks();
  };
  reader.readAsText(file);
}

function handleManualFileUpload() {
  var file = document.getElementById('import-manual-file').files[0];
  if (!file) return;
  
  var reader = new FileReader();
  reader.onload = function(e) {
    document.getElementById('import-manual-content').value = e.target.result;
    countImportManual();
  };
  reader.readAsText(file);
}

async function countImportUrl() {
  var proto = document.getElementById('import-url-proto').value;
  var url = document.getElementById('import-url-input').value;
  if (!url) { showAlert('URL required'); return; }

  document.getElementById('import-url-count').textContent = 'Counting...';

  try {
    var res = await authFetch('/api/import/count-url', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: url, protocol: proto})
    });
    var data = await res.json();
    
    if (data.success) {
      document.getElementById('import-url-count').textContent = 'Found ' + data.count + ' proxies';
    } else {
      document.getElementById('import-url-count').textContent = 'Error: ' + data.error;
    }
  } catch (e) {
    document.getElementById('import-url-count').textContent = 'Error: ' + e.message;
  }
}

function countImportLinks() {
  var content = document.getElementById('import-links-content').value;
  if (!content) {
    document.getElementById('import-links-count').textContent = '';
    return;
  }

  var counts = {http: 0, https: 0, socks4: 0, socks5: 0};
  var lines = content.split('\n');
  var currentSection = 'http';
  
  for (var i = 0; i < lines.length; i++) {
    var trimmed = lines[i].trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    
    if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
      currentSection = trimmed.slice(1, -1).toLowerCase();
      if (!counts[currentSection]) currentSection = 'http';
    } else if (trimmed.includes('://') || trimmed.includes('.')) {
      if (counts[currentSection] !== undefined) {
        counts[currentSection]++;
      }
    }
  }

  var total = 0;
  var breakdown = [];
  for (var k in counts) {
    total += counts[k];
    if (counts[k] > 0) breakdown.push(k + ': ' + counts[k]);
  }
  document.getElementById('import-links-count').textContent = 'Total: ' + total + ' (' + breakdown.join(', ') + ')';
}

function countImportManual() {
  var content = document.getElementById('import-manual-content').value;
  if (!content) {
    document.getElementById('import-manual-count').textContent = '';
    return;
  }

  var counts = {http: 0, https: 0, socks4: 0, socks5: 0};
  var lines = content.split('\n');
  
  for (var i = 0; i < lines.length; i++) {
    var trimmed = lines[i].trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    
    var parts = trimmed.split(/\s+/);
    if (parts.length >= 2) {
      var proto = parts[0].toLowerCase();
      if (counts[proto] !== undefined) {
        counts[proto]++;
      }
    }
  }

  var total = 0;
  var breakdown = [];
  for (var k in counts) {
    total += counts[k];
    if (counts[k] > 0) breakdown.push(k + ': ' + counts[k]);
  }
  document.getElementById('import-manual-count').textContent = 'Total: ' + total + ' (' + breakdown.join(', ') + ')';
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

async function checkMonitorStatus() {
  var res = await authFetch('/api/monitor');
  var data = await res.json();
  
  var grid = document.getElementById('monitors-grid');
  var monitors = data.monitors || {};
  var monitorIds = Object.keys(monitors);
  
  if (monitorIds.length === 0) {
    grid.innerHTML = '<div class="monitors-empty">No monitor profiles. Click "+ Add New Monitor Profile" to create one.</div>';
    return;
  }
  
  grid.innerHTML = '';
  monitorIds.forEach(function(mid) {
    var m = monitors[mid];
    var wasRunning = previousMonitorState[mid] && previousMonitorState[mid].running;
    var isRunning = m.running;
    
    if (wasRunning && !isRunning) {
      loadProxies();
      loadStats();
    }
    
    previousMonitorState[mid] = { running: isRunning };
    
    var config = m.config || {};
    var profileName = m.name || config.name || mid.replace('monitor_', '');
    var protocol = (config.protocol || 'all').toUpperCase();
    var status = config.status || 'all';
    var threads = config.threads || 50;
    var timeout = config.timeout || 5;
    var probes = config.probes || 2;
    var runMode = config.run_mode || 'once';
    var interval = config.interval || 60;
    var geo = config.geo === 'true' ? 'Yes' : 'No';
    var checkUrls = config.check_urls || '-';
    var serviceName = m.service || '';
    var scheduleTime = config.schedule_time || '';
    var scheduleDays = config.schedule_days || '';
    var customEvery = config.custom_every || 24;
    var proxyCount = m.proxy_count || 0;
    var startTime = m.start_time;
    var endTime = m.end_time;
    
    var runModeDisplay = runMode;
    if (runMode === 'schedule' && scheduleTime) {
      runModeDisplay = 'schedule @ ' + scheduleTime;
    } else if (runMode === 'custom') {
      runModeDisplay = 'every ' + customEvery + 'h';
    } else if (runMode === 'infinite' || runMode === 'restart') {
      runModeDisplay = runMode + ' (' + interval + 's)';
    }
    
    var card = document.createElement('div');
    card.className = 'monitor-card';
    
    var progress = m.progress || {};
    var isPaused = !isRunning && progress && progress.paused === true;
    
    var statusClass, statusText, statusDotClass;
    if (isPaused) {
      statusClass = 'paused';
      statusText = 'Paused';
      statusDotClass = 'status-flaky';
      if (m.pid) statusText += ' (PID: ' + m.pid + ')';
    } else if (isRunning) {
      statusClass = 'running';
      statusText = 'Running';
      statusDotClass = 'status-alive';
      if (m.pid) statusText += ' (PID: ' + m.pid + ')';
    } else {
      statusClass = 'stopped';
      statusText = 'Stopped';
      statusDotClass = 'status-dead';
    }
    
    var serviceBadge = serviceName ? ' <span style="background:var(--accent);color:white;padding:2px 6px;border-radius:4px;font-size:10px">SERVICE</span>' : '';
    
    var progressHtml = '';
    var progress = m.progress || {};
    
    if ((isRunning || isPaused) && progress && !progress.completed) {
      var p = progress;
      var tested = p.tested || 0;
      var total = p.total || 1;
      var percent = p.percent || 0;
      var aliveC = p.alive || 0;
      var deadC = p.dead || 0;
      var otherC = p.other || 0;
      
      var aliveWidth = total > 0 ? (aliveC / total * 100) : 0;
      var deadWidth = total > 0 ? (deadC / total * 100) : 0;
      var otherWidth = total > 0 ? (otherC / total * 100) : 0;
      
      var pausedLabel = isPaused ? ' <span style="background:#f59e0b;color:white;padding:2px 6px;border-radius:4px;font-size:10px;margin-left:4px">PAUSED</span>' : '';
      
      progressHtml = 
        '<div class="monitor-progress">' +
          '<div class="monitor-progress-bar-wrap">' +
            '<div class="monitor-progress-bar" style="width:' + aliveWidth + '%;background:var(--success)"></div>' +
            '<div class="monitor-progress-bar" style="width:' + deadWidth + '%;background:var(--danger)"></div>' +
            '<div class="monitor-progress-bar" style="width:' + otherWidth + '%;background:#818cf8"></div>' +
          '</div>' +
          '<div class="monitor-progress-text">' +
            '<div class="monitor-progress-count">' +
              '<span class="alive-count">✓ ' + aliveC + '</span>' +
              '<span class="dead-count">✗ ' + deadC + '</span>' +
              '<span class="other-count">~ ' + otherC + '</span>' +
              pausedLabel +
            '</div>' +
            '<div class="monitor-progress-percent">' + tested + ' / ' + total + ' (' + percent + '%)</div>' +
          '</div>' +
        '</div>';
    } else if (!isRunning && progress && progress.completed) {
      var p = progress;
      progressHtml = 
        '<div class="monitor-final-stats">' +
          '<div class="monitor-final-stats-row">' +
            '<span class="stat-alive">✓ ' + (p.alive || 0) + ' alive</span>' +
            '<span class="stat-soft">◐ ' + (p.soft || 0) + ' soft</span>' +
            '<span class="stat-flaky">⚡ ' + (p.flaky || 0) + ' flaky</span>' +
            '<span class="stat-cooling">⏸ ' + (p.cooling || 0) + ' cooling</span>' +
            '<span class="stat-dead">✗ ' + (p.dead || 0) + ' dead</span>' +
            '<span class="stat-revived">↻ ' + (p.revived || 0) + ' revived</span>' +
            '<span class="stat-semi">⇄ ' + (p.semi_revived || 0) + ' semi</span>' +
            '<span class="stat-untested">? ' + (p.untested || 0) + ' untested</span>' +
          '</div>' +
        '</div>';
    }
    
    card.innerHTML = 
      '<div class="monitor-card-header">' +
        '<div class="monitor-card-title">' +
          '<span class="status-dot ' + statusDotClass + '"></span>' +
          profileName + serviceBadge +
        '</div>' +
        '<span class="monitor-card-status ' + statusClass + '">' + statusText + '</span>' +
      '</div>' +
      '<div class="monitor-card-body">' +
        '<div class="monitor-card-row"><span class="monitor-card-label">Protocol</span><span class="monitor-card-value">' + protocol + '</span></div>' +
        '<div class="monitor-card-row"><span class="monitor-card-label">Proxies to Test</span><span class="monitor-card-value" style="color:var(--accent);font-weight:700">' + proxyCount + '</span></div>' +
        '<div class="monitor-card-row"><span class="monitor-card-label">Status Filter</span><span class="monitor-card-value">' + status + '</span></div>' +
        '<div class="monitor-card-row"><span class="monitor-card-label">Threads / Timeout</span><span class="monitor-card-value">' + threads + ' / ' + timeout + 's</span></div>' +
        '<div class="monitor-card-row"><span class="monitor-card-label">Run Mode</span><span class="monitor-card-value">' + runModeDisplay + '</span></div>' +
        '<div class="monitor-card-row"><span class="monitor-card-label">Started</span><span class="monitor-card-value">' + formatMonitorTime(startTime) + '</span></div>' +
        '<div class="monitor-card-row"><span class="monitor-card-label">Finished</span><span class="monitor-card-value">' + (endTime ? formatMonitorTime(endTime) : (isPaused ? '<span style="color:#f59e0b">paused...</span>' : (isRunning ? '<span style="color:var(--success)">running...</span>' : '-'))) + '</span></div>' +
      '</div>' +
      progressHtml +
      '<div class="monitor-card-footer">' +
        (isPaused ? '<button class="btn btn-sm btn-primary" onclick="resumeMonitor(\'' + mid + '\')">Resume</button>' : '') +
        (isRunning && !isPaused && !serviceName ? '<button class="btn btn-sm" onclick="pauseMonitor(\'' + mid + '\')">Pause</button>' : '') +
        (!isRunning && !isPaused ? '<button class="btn btn-sm btn-primary" onclick="startMonitor(\'' + mid + '\')">Start</button>' : '') +
        '<button class="btn btn-sm" onclick="showMonitorSettings(\'' + mid + '\')">Settings</button>' +
        (serviceName && !isRunning ? '<button class="btn btn-sm" onclick="removeMonitorService(\'' + mid + '\')">Remove Service</button>' : '') +
        (isRunning || isPaused ? '<button class="btn btn-sm btn-danger" onclick="stopMonitor(\'' + mid + '\')">Stop</button>' : '<button class="btn btn-sm btn-danger" onclick="deleteMonitor(\'' + mid + '\', ' + (serviceName ? 'true' : 'false') + ')">Delete</button>') +
      '</div>';
    
    grid.appendChild(card);
  });
}

async function deleteMonitor(monitorId, hasService) {
  if (hasService) {
    showConfirm('Delete Monitor', 'This monitor has a systemd service. The service will be removed along with the monitor. Continue?', async function() {
      await doDeleteMonitor(monitorId);
    }, {confirmText: 'Delete', confirmClass: 'btn-danger'});
  } else {
    showConfirm('Delete Monitor', 'Delete this monitor?', async function() {
      await doDeleteMonitor(monitorId);
    }, {confirmText: 'Delete', confirmClass: 'btn-danger'});
  }
}

async function doDeleteMonitor(monitorId) {
  var res = await authFetch('/api/monitor/delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({monitor_id: monitorId})
  });
  var data = await res.json();
  if (data.success) {
    checkMonitorStatus();
  } else {
    showAlert('Error: ' + (data.error || 'Failed to delete monitor'));
  }
}

async function removeMonitorService(monitorId) {
  showConfirm('Remove Service', 'Remove systemd service? The monitor config will be kept.', async function() {
    var res = await authFetch('/api/monitor/remove-service', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({monitor_id: monitorId})
    });
    var data = await res.json();
    if (data.success) {
      showAlert('Service removed');
      checkMonitorStatus();
    } else {
      showAlert('Error: ' + (data.error || 'Failed to remove service'));
    }
  }, {confirmText: 'Remove', confirmClass: 'btn-danger'});
}

setInterval(function() {
  if (currentTab === 'monitor') {
    checkMonitorStatus();
  }
}, 5000);

var currentEditMonitorId = null;

async function showMonitorSettings(monitorId) {
  var res = await authFetch('/api/monitor');
  var data = await res.json();
  var monitors = data.monitors || {};
  var monitor = monitors[monitorId];
  
  if (!monitor || !monitor.config) {
    showAlert('No configuration found for this monitor');
    return;
  }
  
  var cfg = monitor.config;
  currentEditMonitorId = monitorId;
  
  document.getElementById('monitor-name').value = monitor.name || cfg.name || '';
  document.getElementById('monitor-protocol').value = cfg.protocol || '';
  document.getElementById('monitor-check-urls').value = cfg.check_urls || '';
  document.getElementById('monitor-threads').value = cfg.threads || 50;
  document.getElementById('monitor-timeout').value = cfg.timeout || 5;
  document.getElementById('monitor-probes').value = cfg.probes || 2;
  document.getElementById('monitor-run-mode').value = cfg.run_mode || 'once';
  document.getElementById('monitor-interval').value = cfg.interval || 60;
  document.getElementById('monitor-schedule-time').value = cfg.schedule_time || '';
  document.getElementById('monitor-schedule-days').value = cfg.schedule_days || 'daily';
  document.getElementById('monitor-custom-every').value = cfg.custom_every || 24;
  document.getElementById('monitor-geo').value = cfg.geo || 'true';
  document.getElementById('monitor-create-service').value = cfg.create_service || 'no';
  
  var savedStatuses = (cfg.status || '').split(',').filter(function(s) { return s; });
  if (savedStatuses.length > 0) {
    monitorStatusEnabled = {alive: false, soft: false, flaky: false, cooling: false, dead: false, revived: false, 'semi-revived': false, untested: false};
    savedStatuses.forEach(function(s) {
      if (monitorStatusEnabled.hasOwnProperty(s)) {
        monitorStatusEnabled[s] = true;
      }
    });
  } else {
    monitorStatusEnabled = {alive: true, soft: true, flaky: true, cooling: true, dead: true, revived: true, 'semi-revived': true, untested: true};
  }
  
  ['alive', 'soft', 'flaky', 'cooling', 'dead', 'revived', 'semi-revived', 'untested'].forEach(function(s) {
    var el = document.getElementById('monitor-status-' + s);
    if (el) {
      if (monitorStatusEnabled[s]) {
        el.style.opacity = '1';
        el.style.filter = 'none';
      } else {
        el.style.opacity = '0.3';
        el.style.filter = 'grayscale(100%)';
      }
    }
  });
  
  toggleRunModeOptions();
  document.getElementById('modal-add-monitor').classList.add('active');
  document.querySelector('#modal-add-monitor .modal-title').textContent = 'Edit Monitor';
}

function showAddMonitorForm() {
  document.getElementById('monitor-name').value = '';
  document.getElementById('monitor-protocol').value = '';
  document.getElementById('monitor-check-urls').value = '';
  document.getElementById('monitor-threads').value = 50;
  document.getElementById('monitor-timeout').value = 5;
  document.getElementById('monitor-probes').value = 2;
  document.getElementById('monitor-run-mode').value = 'once';
  document.getElementById('monitor-interval').value = 60;
  document.getElementById('monitor-schedule-time').value = '';
  document.getElementById('monitor-schedule-days').value = 'daily';
  document.getElementById('monitor-custom-every').value = 24;
  document.getElementById('monitor-geo').value = 'true';
  document.getElementById('monitor-create-service').value = 'no';
  
  monitorStatusEnabled = {alive: true, soft: true, flaky: true, cooling: true, dead: true, revived: true, 'semi-revived': true, untested: true};
  ['alive', 'soft', 'flaky', 'cooling', 'dead', 'revived', 'semi-revived', 'untested'].forEach(function(s) {
    var el = document.getElementById('monitor-status-' + s);
    if (el) {
      el.style.opacity = '1';
      el.style.filter = 'none';
    }
  });
  
  toggleRunModeOptions();
  currentEditMonitorId = null;
  document.querySelector('#modal-add-monitor .modal-title').textContent = 'Add New Monitor Profile';
  var createBtn = document.querySelector('#modal-add-monitor .btn-primary');
  if (createBtn) {
    createBtn.textContent = 'Create';
    createBtn.setAttribute('onclick', 'createMonitorProfile()');
  }
  document.getElementById('modal-add-monitor').classList.add('active');
}

async function updateMonitorProfile() {
  if (!currentEditMonitorId) {
    showAlert('No monitor selected for editing');
    return;
  }
  
  var btn = event.target;
  if (btn.disabled) return;
  btn.disabled = true;
  btn.textContent = 'Updating...';
  
  var name = (document.getElementById('monitor-name').value || '').trim();
  if (!name) {
    showAlert('Profile name is required');
    btn.disabled = false;
    btn.textContent = 'Update';
    return;
  }
  
  var statusValues = [];
  ['alive', 'soft', 'flaky', 'cooling', 'dead', 'revived', 'semi-revived', 'untested'].forEach(function(s) {
    if (monitorStatusEnabled[s]) {
      statusValues.push(s);
    }
  });
  
  if (statusValues.length === 0) {
    showAlert('Please select at least one status');
    btn.disabled = false;
    btn.textContent = 'Update';
    return;
  }
  
  var data = {
    monitor_id: currentEditMonitorId,
    name: name,
    protocol: document.getElementById('monitor-protocol').value,
    status: statusValues.join(','),
    check_urls: document.getElementById('monitor-check-urls').value,
    threads: parseInt(document.getElementById('monitor-threads').value) || 50,
    timeout: parseInt(document.getElementById('monitor-timeout').value) || 5,
    probes: parseInt(document.getElementById('monitor-probes').value) || 2,
    run_mode: document.getElementById('monitor-run-mode').value,
    interval: parseInt(document.getElementById('monitor-interval').value) || 60,
    schedule_time: document.getElementById('monitor-schedule-time').value,
    schedule_days: document.getElementById('monitor-schedule-days').value,
    custom_every: parseInt(document.getElementById('monitor-custom-every').value) || 24,
    geo: document.getElementById('monitor-geo').value,
    create_service: document.getElementById('monitor-create-service').value
  };
  
  try {
    var res = await authFetch('/api/monitor/update', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    var result = await res.json();
    
    if (result.success) {
      closeModal('modal-add-monitor');
      checkMonitorStatus();
      showAlert('Monitor profile updated');
    } else {
      showAlert('Error: ' + (result.error || 'Failed to update monitor profile'));
    }
  } catch(e) {
    showAlert('Error: ' + e);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Update';
  }
}

async function createMonitorProfile() {
  var btn = event.target;
  if (btn.disabled) return;
  btn.disabled = true;
  btn.textContent = 'Creating...';
  
  var name = (document.getElementById('monitor-name').value || '').trim();
  if (!name) {
    showAlert('Profile name is required');
    btn.disabled = false;
    btn.textContent = 'Create';
    return;
  }
  
  var statusValues = [];
  ['alive', 'soft', 'flaky', 'cooling', 'dead', 'revived', 'semi-revived', 'untested'].forEach(function(s) {
    if (monitorStatusEnabled[s]) {
      statusValues.push(s);
    }
  });
  
  if (statusValues.length === 0) {
    showAlert('Please select at least one status');
    btn.disabled = false;
    btn.textContent = 'Create';
    return;
  }
  
  var data = {
    name: name,
    protocol: document.getElementById('monitor-protocol').value,
    status: statusValues.join(','),
    check_urls: document.getElementById('monitor-check-urls').value,
    threads: parseInt(document.getElementById('monitor-threads').value) || 50,
    timeout: parseInt(document.getElementById('monitor-timeout').value) || 5,
    probes: parseInt(document.getElementById('monitor-probes').value) || 2,
    run_mode: document.getElementById('monitor-run-mode').value,
    interval: parseInt(document.getElementById('monitor-interval').value) || 60,
    schedule_time: document.getElementById('monitor-schedule-time').value,
    schedule_days: document.getElementById('monitor-schedule-days').value,
    custom_every: parseInt(document.getElementById('monitor-custom-every').value) || 24,
    geo: document.getElementById('monitor-geo').value,
    create_service: document.getElementById('monitor-create-service').value
  };
  
  try {
    var res = await authFetch('/api/monitor/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    var result = await res.json();
    
    if (result.success) {
      closeModal('modal-add-monitor');
      checkMonitorStatus();
      showAlert('Monitor profile created with ' + result.proxy_count + ' proxies');
    } else {
      showAlert('Error: ' + (result.error || 'Failed to create monitor profile'));
    }
  } catch(e) {
    showAlert('Error: ' + e);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create';
  }
}

async function startMonitor(monitorId) {
  if (!monitorId) return;
  showConfirm('Start Monitor', 'Start this monitor?', async function() {
    var res = await authFetch('/api/monitor/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({monitor_id: monitorId})
    });
    var result = await res.json();
    if (result.success) {
      checkMonitorStatus();
    } else {
      showAlert('Error: ' + (result.error || 'Failed to start monitor'));
    }
  }, {confirmText: 'Start', confirmClass: 'btn-primary'});
}

async function pauseMonitor(monitorId) {
  if (!monitorId) return;
  var res = await authFetch('/api/monitor/pause', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({monitor_id: monitorId})
  });
  var result = await res.json();
  if (result.success) {
    checkMonitorStatus();
  } else {
    showAlert('Error: ' + (result.error || 'Failed to pause monitor'));
  }
}

async function resumeMonitor(monitorId) {
  if (!monitorId) return;
  var res = await authFetch('/api/monitor/resume', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({monitor_id: monitorId})
  });
  var result = await res.json();
  if (result.success) {
    checkMonitorStatus();
  } else {
    showAlert('Error: ' + (result.error || 'Failed to resume monitor'));
  }
}

async function stopMonitor(monitorId) {
  if (!monitorId) return;
  showConfirm('Stop Monitor', 'Kill this monitor immediately? Unfinished tests will be lost.', async function() {
    var res = await authFetch('/api/monitor/stop', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({monitor_id: monitorId})
    });
    var result = await res.json();
    if (result.success) {
      checkMonitorStatus();
    } else {
      showAlert('Error: ' + (result.error || 'Failed to stop monitor'));
    }
  }, {confirmText: 'Kill', confirmClass: 'btn-danger'});
}

async function checkServerStatus() {
  try {
    var res = await authFetch('/api/server');
    var data = await res.json();
    console.log('Server status:', data);
    
    var grid = document.getElementById('servers-list');
    var servers = data.servers || {};
    var ports = Object.keys(servers);
    
    if (ports.length === 0) {
      grid.innerHTML = '<div class="servers-empty">No server profiles. Click "+ Add New Server Profile" to create one.</div>';
      return;
    }
    
    grid.innerHTML = '';
    ports.forEach(function(port) {
      var s = servers[port];
      var cfg = s.config || {};
      
      var card = document.createElement('div');
      card.className = 'server-card';
      
      var statusClass = s.running ? 'running' : 'stopped';
      var statusText = s.running ? 'Running' : 'Stopped';
      var statusDotClass = s.running ? 'status-alive' : 'status-dead';
      
      card.innerHTML = 
        '<div class="server-card-header">' +
          '<div class="server-card-title">' +
            '<span class="status-dot ' + statusDotClass + '"></span>' +
            (cfg.protocol || 'http').toUpperCase() + ' on port ' + port +
          '</div>' +
          '<span class="server-card-status ' + statusClass + '">' + statusText + (s.running && s.pid ? ' (PID: ' + s.pid + ')' : '') + '</span>' +
        '</div>' +
        '<div class="server-card-body">' +
          '<div class="server-card-row"><span class="server-card-label">Protocol</span><span class="server-card-value">' + (cfg.protocol || '-').toUpperCase() + '</span></div>' +
          '<div class="server-card-row"><span class="server-card-label">Bind Address</span><span class="server-card-value">' + (cfg.bind || '0.0.0.0') + '</span></div>' +
          '<div class="server-card-row"><span class="server-card-label">Port</span><span class="server-card-value">' + port + '</span></div>' +
          '<div class="server-card-row"><span class="server-card-label">Rotate Mode</span><span class="server-card-value">' + (cfg.rotate || 'fixed') + '</span></div>' +
          '<div class="server-card-row"><span class="server-card-label">Rotate Interval</span><span class="server-card-value">' + (cfg.rotate_interval || 60) + 's</span></div>' +
          '<div class="server-card-row"><span class="server-card-label">Min Cost</span><span class="server-card-value">$' + (cfg.min_cost || 0) + '</span></div>' +
          '<div class="server-card-row"><span class="server-card-label">Cost Threshold</span><span class="server-card-value">$' + (cfg.cost_threshold || 0.3) + '</span></div>' +
          '<div class="server-card-row"><span class="server-card-label">Candidates</span><span class="server-card-value">' + (cfg.candidate_statuses || 'alive') + '</span></div>' +
        '</div>' +
        '<div class="server-card-footer">' +
          (s.running ? '<button class="btn btn-sm btn-danger" onclick="stopServer(\'' + port + '\')">Stop</button>' : '<button class="btn btn-sm btn-primary" onclick="startServer(\'' + port + '\')">Start</button>') +
          '<button class="btn btn-sm" onclick="showServerSettings(\'' + port + '\')">Settings</button>' +
          (s.running ? '' : '<button class="btn btn-sm btn-danger" onclick="deleteServer(\'' + port + '\')">Delete</button>') +
        '</div>';
      
      grid.appendChild(card);
    });
  } catch(e) {
    console.error('Error loading server status:', e);
  }
}

function hideAddServerForm() {
  closeModal('modal-add-server');
}

async function startServerFromModal() {
  function getVal(id, def) {
    var el = document.getElementById(id);
    return el && el.value ? el.value : (def || '');
  }
  
  var port = parseInt(getVal('server-port', '8080'));
  
  var data = {
    protocol: getVal('server-proto'),
    bind: getVal('server-bind', '0.0.0.0'),
    port: port,
    rotate: getVal('server-rotate'),
    rotate_interval: parseInt(getVal('server-rotate-interval', '60')),
    min_cost: parseFloat(getVal('server-min-cost', '0.0')),
    cost_threshold: getVal('server-cost') ? parseFloat(getVal('server-cost')) : null,
    username: getVal('server-user'),
    password: getVal('server-pass'),
    auth_required: getVal('server-auth-required') || null,
    certfile: getVal('server-certfile') || null,
    keyfile: getVal('server-keyfile') || null,
    sticky_upstream: getVal('server-sticky-upstream') || null,
    insecure_upstream: getVal('server-insecure-upstream') === 'true',
    upstream_protocol: getVal('server-upstream-proto') || null,
    candidate_statuses: getVal('server-candidate-statuses', 'alive') || 'alive',
    countryCodes: getVal('server-country') || null,
    regions: getVal('server-regions') || null,
    cities: getVal('server-cities') || null,
    orgs: getVal('server-orgs') || null,
    isp: getVal('server-isp') || null,
    asn: getVal('server-asn') || null,
    continentCode: getVal('server-continent') || null,
    zip_codes: getVal('server-zip') || null,
    timezones: getVal('server-timezones') || null,
    mobile: getVal('server-mobile') || null,
    proxy: getVal('server-proxy') || null,
    hosting: getVal('server-hosting') || null
  };

  try {
    var res = await authFetch('/api/server/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
      credentials: 'same-origin'
    });
    var result = await res.json();

    if (!result.success) {
      showAlert('Error: ' + result.error);
      return;
    }
    
    res = await authFetch('/api/server/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({port: port}),
      credentials: 'same-origin'
    });
    result = await res.json();

    if (!result.success) {
      showAlert('Error: ' + result.error);
    } else {
      hideAddServerForm();
      showAlert('Server on port ' + port + ' started successfully!');
    }
    setTimeout(checkServerStatus, 1000);
  } catch(e) {
    showAlert('Error: ' + e);
  }
}

var currentEditPort = null;
var isEditingServer = false;

async function showServerSettings(port) {
  var res = await authFetch('/api/server');
  var data = await res.json();
  var servers = data.servers || {};
  var server = servers[port];
  
  if (!server || !server.config) {
    showAlert('No configuration found for this server');
    return;
  }
  
  var cfg = server.config;
  currentEditPort = port;
  isEditingServer = true;
  
  document.getElementById('server-proto').value = cfg.protocol || 'http';
  document.getElementById('server-bind').value = cfg.bind || '0.0.0.0';
  document.getElementById('server-port').value = cfg.port || port;
  document.getElementById('server-rotate').value = cfg.rotate || 'better_cost';
  document.getElementById('server-rotate-interval').value = cfg.rotate_interval || 60;
  document.getElementById('server-min-cost').value = cfg.min_cost || 0;
  document.getElementById('server-cost').value = cfg.cost_threshold || '';
  document.getElementById('server-user').value = cfg.username || '';
  document.getElementById('server-pass').value = cfg.password || '';
  document.getElementById('server-auth-required').value = cfg.auth_required || '';
  document.getElementById('server-certfile').value = cfg.certfile || '';
  document.getElementById('server-keyfile').value = cfg.keyfile || '';
  document.getElementById('server-sticky-upstream').value = cfg.sticky_upstream || '';
  document.getElementById('server-upstream-proto').value = cfg.upstream_protocol || '';
  document.getElementById('server-candidate-statuses').value = cfg.candidate_statuses || 'alive';
  document.getElementById('server-insecure-upstream').value = cfg.insecure_upstream ? 'true' : 'false';
  document.getElementById('server-country').value = cfg.countryCodes || '';
  document.getElementById('server-regions').value = cfg.regions || '';
  document.getElementById('server-cities').value = cfg.cities || '';
  document.getElementById('server-orgs').value = cfg.orgs || '';
  document.getElementById('server-isp').value = cfg.isp || '';
  document.getElementById('server-asn').value = cfg.asn || '';
  document.getElementById('server-continent').value = cfg.continentCode || '';
  document.getElementById('server-zip').value = cfg.zip_codes || '';
  document.getElementById('server-timezones').value = cfg.timezones || '';
  document.getElementById('server-mobile').value = cfg.mobile || '';
  document.getElementById('server-proxy').value = cfg.proxy || '';
  document.getElementById('server-hosting').value = cfg.hosting || '';
  
  document.querySelector('#modal-add-server .modal-title').textContent = 'Edit Server Profile';
  var createBtn = document.querySelector('#modal-add-server .btn-primary');
  if (createBtn) {
    createBtn.textContent = 'Update Profile';
    createBtn.setAttribute('onclick', 'updateServerProfile()');
  }
  document.getElementById('modal-add-server').classList.add('active');
}

function showAddServerForm() {
  isEditingServer = false;
  currentEditPort = null;
  
  document.getElementById('server-proto').value = 'http';
  document.getElementById('server-bind').value = '0.0.0.0';
  document.getElementById('server-port').value = '8080';
  document.getElementById('server-rotate').value = 'better_cost';
  document.getElementById('server-rotate-interval').value = '60';
  document.getElementById('server-min-cost').value = '0.0';
  document.getElementById('server-cost').value = '';
  document.getElementById('server-user').value = '';
  document.getElementById('server-pass').value = '';
  document.getElementById('server-auth-required').value = '';
  document.getElementById('server-certfile').value = '';
  document.getElementById('server-keyfile').value = '';
  document.getElementById('server-sticky-upstream').value = '';
  document.getElementById('server-upstream-proto').value = '';
  document.getElementById('server-candidate-statuses').value = 'alive';
  document.getElementById('server-insecure-upstream').value = 'false';
  document.getElementById('server-country').value = '';
  document.getElementById('server-regions').value = '';
  document.getElementById('server-cities').value = '';
  document.getElementById('server-orgs').value = '';
  document.getElementById('server-isp').value = '';
  document.getElementById('server-asn').value = '';
  document.getElementById('server-continent').value = '';
  document.getElementById('server-zip').value = '';
  document.getElementById('server-timezones').value = '';
  document.getElementById('server-mobile').value = '';
  document.getElementById('server-proxy').value = '';
  document.getElementById('server-hosting').value = '';
  
  document.querySelector('#modal-add-server .modal-title').textContent = 'Add New Server Profile';
  var createBtn = document.querySelector('#modal-add-server .btn-primary');
  if (createBtn) {
    createBtn.textContent = 'Create Profile';
    createBtn.setAttribute('onclick', 'createServerProfile()');
  }
  document.getElementById('modal-add-server').classList.add('active');
}

function hideAddServerForm() {
  closeModal('modal-add-server');
}

async function updateServerProfile() {
  if (!currentEditPort) {
    showAlert('No server selected for editing');
    return;
  }
  
  function getVal(id, def) {
    var el = document.getElementById(id);
    return el && el.value ? el.value : (def || '');
  }
  
  var port = currentEditPort;
  var data = {
    protocol: getVal('server-proto'),
    bind: getVal('server-bind', '0.0.0.0'),
    port: parseInt(getVal('server-port', '8080')),
    rotate: getVal('server-rotate'),
    rotate_interval: parseInt(getVal('server-rotate-interval', '60')),
    min_cost: parseFloat(getVal('server-min-cost', '0.0')),
    cost_threshold: getVal('server-cost') ? parseFloat(getVal('server-cost')) : null,
    username: getVal('server-user'),
    password: getVal('server-pass'),
    auth_required: getVal('server-auth-required') || null,
    certfile: getVal('server-certfile') || null,
    keyfile: getVal('server-keyfile') || null,
    sticky_upstream: getVal('server-sticky-upstream') || null,
    insecure_upstream: getVal('server-insecure-upstream') === 'true',
    upstream_protocol: getVal('server-upstream-proto') || null,
    candidate_statuses: getVal('server-candidate-statuses', 'alive') || 'alive',
    countryCodes: getVal('server-country') || null,
    regions: getVal('server-regions') || null,
    cities: getVal('server-cities') || null,
    orgs: getVal('server-orgs') || null,
    isp: getVal('server-isp') || null,
    asn: getVal('server-asn') || null,
    continentCode: getVal('server-continent') || null,
    zip_codes: getVal('server-zip') || null,
    timezones: getVal('server-timezones') || null,
    mobile: getVal('server-mobile') || null,
    proxy: getVal('server-proxy') || null,
    hosting: getVal('server-hosting') || null
  };

  try {
    var res = await authFetch('/api/server/update', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
      credentials: 'same-origin'
    });
    var result = await res.json();

    if (!result.success) {
      showAlert('Error: ' + (result.error || 'Unknown error'));
    } else {
      hideAddServerForm();
      if (result.was_running) {
        showAlert('Server profile updated! Restarting server...');
        setTimeout(function() {
          startServer(port);
        }, 500);
      } else {
        showAlert('Server profile updated!');
      }
    }
    setTimeout(checkServerStatus, 1000);
  } catch(e) {
    showAlert('Error: ' + e);
  }
}

function editServerSettings() {
  // This function is no longer needed as we now directly edit in the modal
  // Keeping it for compatibility
  closeModal('modal-server-settings');
}

async function startServer(port) {
  var portNum;
  if (port) {
    portNum = parseInt(port);
  } else {
    function getVal(id, def) {
      var el = document.getElementById(id);
      return el && el.value ? el.value : (def || '');
    }
    
    var data = {
    protocol: getVal('server-proto'),
    bind: getVal('server-bind', '0.0.0.0'),
    port: parseInt(getVal('server-port', '8080')),
    rotate: getVal('server-rotate'),
    rotate_interval: parseInt(getVal('server-rotate-interval', '60')),
    min_cost: parseFloat(getVal('server-min-cost', '0.0')),
    cost_threshold: getVal('server-cost') ? parseFloat(getVal('server-cost')) : null,
    username: getVal('server-user'),
      password: getVal('server-pass'),
      auth_required: getVal('server-auth-required') || null,
      certfile: getVal('server-certfile') || null,
      keyfile: getVal('server-keyfile') || null,
      sticky_upstream: getVal('server-sticky-upstream') || null,
      insecure_upstream: getVal('server-insecure-upstream') === 'true',
      upstream_protocol: getVal('server-upstream-proto') || null,
    candidate_statuses: getVal('server-candidate-statuses', 'alive') || 'alive',
      countryCodes: getVal('server-country') || null,
      regions: getVal('server-regions') || null,
      cities: getVal('server-cities') || null,
      orgs: getVal('server-orgs') || null,
      isp: getVal('server-isp') || null,
      asn: getVal('server-asn') || null,
      continentCode: getVal('server-continent') || null,
      zip_codes: getVal('server-zip') || null,
      timezones: getVal('server-timezones') || null,
      mobile: getVal('server-mobile') || null,
      proxy: getVal('server-proxy') || null,
      hosting: getVal('server-hosting') || null
    };

    try {
      var res = await authFetch('/api/server/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
        credentials: 'same-origin'
      });
      var result = await res.json();

      if (!result.success) {
        showAlert('Error: ' + result.error);
      } else {
        hideAddServerForm();
        showAlert(result.port + ' started successfully!');
      }
      setTimeout(checkServerStatus, 1000);
    } catch(e) {
      showAlert('Error: ' + e);
    }
    return;
  }
  
  var res = await authFetch('/api/server/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({port: portNum}),
    credentials: 'same-origin'
  });
  var result = await res.json();
  console.log('Start server result:', result);
  if (!result.success) {
    showAlert('Error: ' + (result.error || 'Failed to start server'));
  } else {
    showAlert('Server on port ' + port + ' started successfully!');
  }
  setTimeout(checkServerStatus, 1000);
}

async function stopServer(port) {
  if (!port) return;
  showConfirm('Stop Server', 'Stop server on port ' + port + '?', async function() {
    var res = await authFetch('/api/server/stop', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({port: String(port)})
    });
    var data = await res.json();
    if (data.success) {
      showAlert('Server on port ' + port + ' stopped.');
      setTimeout(checkServerStatus, 1000);
    } else {
      showAlert('Error: ' + (data.error || 'Failed to stop server'));
    }
  });
}

async function createServerProfile() {
  function getVal(id, def) {
    var el = document.getElementById(id);
    return el && el.value ? el.value : (def || '');
  }
  
  var data = {
    protocol: getVal('server-proto'),
    bind: getVal('server-bind', '0.0.0.0'),
    port: parseInt(getVal('server-port', '8080')),
    rotate: getVal('server-rotate'),
    rotate_interval: parseInt(getVal('server-rotate-interval', '60')),
    min_cost: parseFloat(getVal('server-min-cost', '0.0')),
    cost_threshold: getVal('server-cost') ? parseFloat(getVal('server-cost')) : null,
    username: getVal('server-user'),
    password: getVal('server-pass'),
    auth_required: getVal('server-auth-required') || null,
    certfile: getVal('server-certfile') || null,
    keyfile: getVal('server-keyfile') || null,
    sticky_upstream: getVal('server-sticky-upstream') || null,
    insecure_upstream: getVal('server-insecure-upstream') === 'true',
    upstream_protocol: getVal('server-upstream-proto') || null,
    candidate_statuses: getVal('server-candidate-statuses', 'alive') || 'alive',
    countryCodes: getVal('server-country') || null,
    regions: getVal('server-regions') || null,
    cities: getVal('server-cities') || null,
    orgs: getVal('server-orgs') || null,
    isp: getVal('server-isp') || null,
    asn: getVal('server-asn') || null,
    continentCode: getVal('server-continent') || null,
    zip_codes: getVal('server-zip') || null,
    timezones: getVal('server-timezones') || null,
    mobile: getVal('server-mobile') || null,
    proxy: getVal('server-proxy') || null,
    hosting: getVal('server-hosting') || null
  };

  try {
    var res = await authFetch('/api/server/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
      credentials: 'same-origin'
    });
    var result = await res.json();
    console.log('Create server result:', result);

    if (!result.success) {
      showAlert('Error: ' + (result.error || 'Unknown error'));
    } else {
      hideAddServerForm();
      showAlert('Server profile on port ' + result.port + ' created!');
    }
    setTimeout(checkServerStatus, 1000);
  } catch(e) {
    showAlert('Error: ' + e);
  }
}

async function deleteServer(port) {
  if (!port) return;
  showConfirm('Delete Server', 'Delete server profile on port ' + port + '?', async function() {
    var res = await authFetch('/api/server/delete', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({port: String(port)})
    });
    var data = await res.json();
    if (data.success) {
      showAlert('Server profile on port ' + port + ' deleted.');
      setTimeout(checkServerStatus, 1000);
    } else {
      showAlert('Error: ' + (data.error || 'Failed to delete server'));
    }
  });
}

var serverEventSource = null;

function startServerLogStream() {
  if (serverEventSource) serverEventSource.close();
  serverEventSource = new EventSource('/api/server/log/stream');
  var logEl = document.getElementById('server-log');
  serverEventSource.onmessage = function(e) {
    if (e.data) {
      logEl.innerHTML += e.data;
      logEl.scrollTop = logEl.scrollHeight;
    }
  };
}

function stopServerLogStream() {
  if (serverEventSource) {
    serverEventSource.close();
    serverEventSource = null;
  }
}

async function loadServerLog() {
  var res = await authFetch('/api/server/log');
  var data = await res.json();
  document.getElementById('server-log').innerHTML = data.lines.join('');
  document.getElementById('server-log').scrollTop = document.getElementById('server-log').scrollHeight;
}

function clearServerLog() {
  document.getElementById('server-log').innerHTML = '';
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
        countryList.innerHTML += '<div style="display:flex;align-items:center;gap:12px"><span style="width:20px;font-weight:bold;color:var(--muted)">' + (i+1) + '</span><span style="width:60px">' + c.country + '</span><div style="flex:1;height:16px;background:var(--panel-light);border-radius:4px"><div style="height:100%;width:' + (c.count/maxCountry)*100 + '%;background:var(--accent);border-radius:4px"></div></div><span style="width:50px;text-align:right">' + c.count + '</span></div>';
      });
    }

    var ispList = document.getElementById('stats-isp-list');
    ispList.innerHTML = '';
    if (data.by_isp && data.by_isp.length > 0) {
      var maxIsp = data.by_isp[0] ? data.by_isp[0].count : 1;
      data.by_isp.forEach(function(isp, i) {
        ispList.innerHTML += '<div style="display:flex;align-items:center;gap:12px"><span style="width:20px;font-weight:bold;color:var(--muted)">' + (i+1) + '</span><span style="width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + isp.isp + '</span><div style="flex:1;height:16px;background:var(--panel-light);border-radius:4px"><div style="height:100%;width:' + (isp.count/maxIsp)*100 + '%;background:var(--accent);border-radius:4px"></div></div><span style="width:50px;text-align:right">' + isp.count + '</span></div>';
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
  } else {
    document.getElementById('db-info').textContent = (data.db_path || data.sqlite_db_path || 'SQLite') + ' - ' + Number(data.db_size || 0).toFixed(2) + ' MB';
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
loadUserProxyFilters();

if (typeof userProxyFilters !== 'undefined' && (userProxyFilters.statuses.length > 0 || userProxyFilters.protocols.length > 0)) {
  applyProxyFiltersToUI();
}

document.addEventListener('click', function(e) {
  var colsBtn = e.target.closest('button') && e.target.closest('button').getAttribute('onclick');
  if (!e.target.closest('#columns-menu') && colsBtn !== 'toggleColumnsMenu()') {
    var colsMenu = document.getElementById('columns-menu');
    if (colsMenu) colsMenu.style.display = 'none';
  }
});

var savedPageSize = localStorage.getItem('pageSize');
if (savedPageSize) {
  document.getElementById('page-size').value = savedPageSize;
}
loadProxies().then(function() {
  setTimeout(function() {
    initColumns();
  }, 100);
});
