(function () {
  'use strict';

  var root = document.getElementById('tab-proxies');
  if (!root) return;

  var STATUS_GROUPS = {
    all: '',
    alive: 'alive',
    attention: 'flaky,soft,cooling,revived,semi-revived',
    dead: 'dead',
    untested: 'untested'
  };

  var STATUS_LABELS = {
    alive: 'Alive',
    flaky: 'Flaky',
    soft: 'Soft',
    cooling: 'Cooling',
    dead: 'Dead',
    revived: 'Revived',
    'semi-revived': 'Semi-revived',
    untested: 'Untested'
  };

  var state = {
    page: 1,
    pages: 1,
    pageSize: parseInt(localStorage.getItem('inventory.pageSize') || localStorage.getItem('pageSize') || '50', 10) || 50,
    protocol: localStorage.getItem('inventory.protocol') || 'all',
    statusGroup: localStorage.getItem('inventory.status') || 'all',
    capabilities: new Set(JSON.parse(localStorage.getItem('inventory.capabilities') || '[]')),
    sort: localStorage.getItem('inventory.sort') || 'cost:asc',
    search: '',
    rows: [],
    rowCache: new Map(),
    selected: new Map(),
    requestNumber: 0,
    loading: false,
    lastStats: null,
    searchTimer: null,
    initialized: false,
    permissionsPromise: null
  };

  var icons = {
    inspect: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5c-5.5 0-9.5 5.5-9.5 7s4 7 9.5 7 9.5-5.5 9.5-7S17.5 5 12 5Zm0 12c-3.55 0-6.6-3.4-7.35-5 .75-1.6 3.8-5 7.35-5s6.6 3.4 7.35 5c-.75 1.6-3.8 5-7.35 5Zm0-8a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z"/></svg>',
    test: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 2h6v2h-1v5.59l4.7 7.82A3 3 0 0 1 16.13 22H7.87a3 3 0 0 1-2.57-4.59L10 9.59V4H9V2Zm3 8.14-5 8.33A1 1 0 0 0 7.87 20h8.26a1 1 0 0 0 .86-1.53L12 10.14Z"/></svg>',
    edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 15.5-.5 5 5-.5L19 9.5 14.5 5 4 15.5ZM16 3l5 5-1.5 1.5-5-5L16 3Z"/></svg>',
    delete: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-2 6h10l-1 12H8L7 9Zm3 2v8h2v-8h-2Zm4 0v8h2v-8h-2Z"/></svg>'
  };

  function byId(id) { return document.getElementById(id); }
  function permission(name) { return typeof window.hasPermission !== 'function' || window.hasPermission(name); }
  function safe(value) { return typeof window.escapeHtml === 'function' ? window.escapeHtml(value == null ? '' : String(value)) : String(value == null ? '' : value); }
  function endpoint(row) { return String(row.protocol || '') + '://' + String(row.ip || '') + ':' + String(row.port || ''); }
  function normalizedStatus(row) { return row.status || 'untested'; }
  function number(value, fallback) { var parsed = Number(value); return Number.isFinite(parsed) ? parsed : (fallback || 0); }
  function percent(value) { return value == null ? '—' : Math.round(number(value) * 100) + '%'; }
  function decimal(value, digits) { return value == null ? '—' : number(value).toFixed(digits == null ? 3 : digits); }

  function relativeTime(value) {
    if (!value) return 'Never';
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Unknown';
    var seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (seconds < 45) return 'Just now';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
    if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
    if (seconds < 604800) return Math.floor(seconds / 86400) + 'd ago';
    return date.toLocaleDateString();
  }

  function formatDate(value) {
    if (!value) return 'Never';
    var date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Unknown' : date.toLocaleString();
  }

  function statusLabel(value) { return STATUS_LABELS[value || 'untested'] || String(value || 'Untested'); }

  function statusHint(row) {
    var checks = number(row.total_checks);
    var alive = number(row.alive_hits);
    var failures = number(row.fail_hits);
    if (!checks) return 'No validation history';
    return alive + ' passed · ' + failures + ' failed';
  }

  function locationLabel(row) {
    var parts = [row.city, row.regionName, row.countryCode].filter(Boolean);
    return parts.length ? parts.join(', ') : 'Location unknown';
  }

  function readinessMarkup(row) {
    return [
      ['H', 'HTTPS', row.web_https_ok],
      ['D', 'Remote DNS', row.remote_dns_ok],
      ['T', 'Telegram', row.telegram_ok]
    ].map(function (item) {
      return '<span class="inventory-capability' + (item[2] ? ' is-ready' : '') + '" title="' + item[1] + ': ' + (item[2] ? 'ready' : 'not verified') + '">' + item[0] + '</span>';
    }).join('');
  }

  function rowActionsMarkup(row) {
    var buttons = '<button class="inventory-row-action" type="button" data-action="inspect" data-id="' + Number(row.id) + '" title="Inspect proxy" aria-label="Inspect proxy">' + icons.inspect + '</button>';
    if (permission('proxies.test')) buttons += '<button class="inventory-row-action" type="button" data-action="test" data-id="' + Number(row.id) + '" title="Test proxy" aria-label="Test proxy">' + icons.test + '</button>';
    if (permission('proxies.edit')) buttons += '<button class="inventory-row-action" type="button" data-action="edit" data-id="' + Number(row.id) + '" title="Edit proxy" aria-label="Edit proxy">' + icons.edit + '</button>';
    if (permission('proxies.delete')) buttons += '<button class="inventory-row-action" type="button" data-action="delete" data-id="' + Number(row.id) + '" title="Delete proxy" aria-label="Delete proxy">' + icons.delete + '</button>';
    return buttons;
  }

  function rowMarkup(row) {
    var id = Number(row.id);
    var selected = state.selected.has(id);
    var status = normalizedStatus(row);
    var speed = row.speed_ms == null ? 'Not measured' : number(row.speed_ms) + ' ms';
    var quality = row.reliability == null ? 'Reliability unavailable' : percent(row.reliability) + ' reliable';
    var network = row.isp || row.org || 'Network unknown';
    var checked = relativeTime(row.last_checked);
    return '<tr data-proxy-id="' + id + '" aria-selected="' + (selected ? 'true' : 'false') + '">' +
      '<td class="inventory-check-column"><input type="checkbox" data-selection-id="' + id + '" aria-label="Select ' + safe(endpoint(row)) + '" ' + (selected ? 'checked' : '') + '></td>' +
      '<td><div class="inventory-endpoint"><div class="inventory-endpoint-main"><span class="inventory-protocol-badge">' + safe(row.protocol) + '</span><strong>' + safe(row.ip) + ':' + safe(row.port) + '</strong>' + (row.has_auth ? '<span class="inventory-auth-mark" title="Stored upstream credentials">●</span>' : '') + '</div><small>#' + id + (row.exit_ip ? ' · exit ' + safe(row.exit_ip) : '') + '</small></div></td>' +
      '<td><div class="inventory-health"><div class="inventory-status-line"><span class="inventory-status-dot" data-status="' + safe(status) + '"></span><strong>' + safe(statusLabel(status)) + '</strong></div><small class="inventory-health-score">' + safe(statusHint(row)) + '</small></div></td>' +
      '<td><div class="inventory-response"><strong>' + safe(speed) + '</strong><small>' + safe(quality) + ' · cost ' + safe(decimal(row.cost)) + '</small></div></td>' +
      '<td><div class="inventory-network"><strong title="' + safe(network) + '">' + safe(network) + '</strong><small title="' + safe(locationLabel(row)) + '">' + safe(locationLabel(row)) + '</small></div></td>' +
      '<td><div class="inventory-readiness">' + readinessMarkup(row) + '</div></td>' +
      '<td><div class="inventory-checked"><strong>' + safe(checked) + '</strong><small>' + safe(row.validation_profile || 'No profile') + '</small></div></td>' +
      '<td class="inventory-actions-column"><div class="inventory-row-actions">' + rowActionsMarkup(row) + '</div></td>' +
    '</tr>';
  }

  function buildParams() {
    var splitSort = state.sort.split(':');
    var params = new URLSearchParams({
      page: String(state.page),
      page_size: String(state.pageSize),
      proto: state.protocol,
      sort_col: splitSort[0] || 'cost',
      sort_order: splitSort[1] || 'asc'
    });
    var status = STATUS_GROUPS[state.statusGroup] || '';
    if (status) params.set('status', status);
    if (state.search) params.set('search', state.search);
    if (state.capabilities.size) params.set('capability', Array.from(state.capabilities).join(','));
    return params;
  }

  function savePreferences() {
    localStorage.setItem('inventory.pageSize', String(state.pageSize));
    localStorage.setItem('pageSize', String(state.pageSize));
    localStorage.setItem('inventory.protocol', state.protocol);
    localStorage.setItem('inventory.status', state.statusGroup);
    localStorage.setItem('inventory.capabilities', JSON.stringify(Array.from(state.capabilities)));
    localStorage.setItem('inventory.sort', state.sort);
  }

  function filterDescription() {
    var parts = [];
    if (state.protocol !== 'all') parts.push(state.protocol.toUpperCase());
    if (state.statusGroup !== 'all') parts.push(byId('inventory-status-filter').selectedOptions[0].textContent);
    if (state.capabilities.size) parts.push(Array.from(state.capabilities).map(function (item) { return item === 'web_https' ? 'HTTPS' : item === 'remote_dns' ? 'Remote DNS' : 'Telegram'; }).join(' + '));
    if (state.search) parts.push('Search “' + state.search + '”');
    return parts.length ? parts.join(' · ') : 'No filters applied';
  }

  function updateMetrics(data, stats) {
    var total = number(data.total);
    var globalTotal = number(stats && stats.total);
    var alive = number(stats && stats.alive);
    var web = number(stats && stats.web_ready);
    var untested = number(stats && stats.untested);
    byId('inventory-metric-total').textContent = total.toLocaleString();
    byId('inventory-metric-total-hint').textContent = total === globalTotal ? 'Entire scoped inventory' : 'Filtered from ' + globalTotal.toLocaleString();
    byId('inventory-metric-alive').textContent = alive.toLocaleString();
    byId('inventory-metric-alive-hint').textContent = globalTotal ? Math.round((alive / globalTotal) * 100) + '% of scoped inventory' : 'Current scoped pool';
    byId('inventory-metric-web').textContent = web.toLocaleString();
    byId('inventory-metric-web-hint').textContent = alive ? Math.round((web / alive) * 100) + '% of alive pool' : 'Run validation first';
    byId('inventory-metric-untested').textContent = untested.toLocaleString();
    byId('inventory-metric-untested-hint').textContent = globalTotal ? Math.round((untested / globalTotal) * 100) + '% await a check' : 'Untested endpoints';
  }

  function updateSelectionUI() {
    var count = state.selected.size;
    var bar = byId('inventory-selection-bar');
    bar.hidden = count === 0;
    byId('inventory-selection-count').textContent = count + ' selected';
    var pageIds = state.rows.map(function (row) { return Number(row.id); });
    var selectedOnPage = pageIds.filter(function (id) { return state.selected.has(id); }).length;
    var all = byId('inventory-select-page');
    all.checked = pageIds.length > 0 && selectedOnPage === pageIds.length;
    all.indeterminate = selectedOnPage > 0 && selectedOnPage < pageIds.length;
    byId('inventory-test-selected').hidden = !permission('proxies.test');
    byId('inventory-delete-selected').hidden = !permission('proxies.delete');
  }

  function updatePager(data) {
    state.pages = Math.max(1, number(data.pages, 1));
    state.page = Math.max(1, number(data.page, 1));
    var total = number(data.total);
    var first = total ? ((state.page - 1) * state.pageSize) + 1 : 0;
    var last = Math.min(total, state.page * state.pageSize);
    byId('pager-info').textContent = total ? first.toLocaleString() + '–' + last.toLocaleString() + ' of ' + total.toLocaleString() : 'No matching proxies';

    var pages = [];
    if (state.pages <= 7) {
      for (var i = 1; i <= state.pages; i += 1) pages.push(i);
    } else {
      pages.push(1);
      var start = Math.max(2, state.page - 1);
      var end = Math.min(state.pages - 1, state.page + 1);
      if (start > 2) pages.push('…');
      for (var j = start; j <= end; j += 1) pages.push(j);
      if (end < state.pages - 1) pages.push('…');
      pages.push(state.pages);
    }

    var html = '<button class="inventory-page-button" type="button" data-page="' + Math.max(1, state.page - 1) + '" aria-label="Previous page" ' + (state.page <= 1 ? 'disabled' : '') + '>‹</button>';
    pages.forEach(function (page) {
      if (page === '…') html += '<span class="inventory-page-button" aria-hidden="true">…</span>';
      else html += '<button class="inventory-page-button' + (page === state.page ? ' is-active' : '') + '" type="button" data-page="' + page + '">' + page + '</button>';
    });
    html += '<button class="inventory-page-button" type="button" data-page="' + Math.min(state.pages, state.page + 1) + '" aria-label="Next page" ' + (state.page >= state.pages ? 'disabled' : '') + '>›</button>';
    byId('pager-btns').innerHTML = html;
  }

  function renderRows(data) {
    var body = byId('proxies-tbody');
    state.rows = Array.isArray(data.proxies) ? data.proxies : [];
    state.rows.forEach(function (row) { state.rowCache.set(Number(row.id), row); });
    var empty = byId('inventory-empty-state');
    empty.hidden = state.rows.length !== 0;
    if (!state.rows.length) {
      body.innerHTML = '';
      return;
    }
    body.innerHTML = state.rows.map(rowMarkup).join('');
    updateSelectionUI();
  }

  async function fetchJson(url, options) {
    var response = await window.authFetch(url, options || {});
    var payload = await response.json().catch(function () { return {}; });
    if (!response.ok || payload.success === false) throw new Error(payload.error || 'Request failed');
    return payload;
  }

  async function loadInventory(options) {
    options = options || {};
    if (state.permissionsPromise) {
      try { await state.permissionsPromise; } catch (_error) {}
      applyPermissionUI();
    }
    var requestNumber = ++state.requestNumber;
    state.loading = true;
    var body = byId('proxies-tbody');
    body.innerHTML = '<tr><td colspan="8"><div class="inventory-loading-state"><span></span>Loading proxy inventory…</div></td></tr>';
    byId('inventory-empty-state').hidden = true;
    byId('inventory-refresh-button').disabled = true;
    try {
      var results = await Promise.all([
        fetchJson('/api/proxies?' + buildParams().toString()),
        fetchJson('/api/stats').catch(function () { return state.lastStats || {}; })
      ]);
      if (requestNumber !== state.requestNumber) return;
      var data = results[0];
      var stats = results[1];
      state.lastStats = stats;
      state.page = number(data.page, 1);
      renderRows(data);
      updatePager(data);
      updateMetrics(data, stats);
      byId('inventory-result-summary').textContent = number(data.total).toLocaleString() + ' matching proxies';
      byId('inventory-filter-summary').textContent = filterDescription();
      byId('inventory-last-updated').textContent = 'Updated ' + new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
      if (options.focusTable) byId('inventory-table-shell').scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (error) {
      if (requestNumber !== state.requestNumber) return;
      body.innerHTML = '<tr><td colspan="8"><div class="inventory-error-state"><strong>Inventory could not be loaded</strong><span>' + safe(error.message || error) + '</span><button class="btn btn-sm" type="button" id="inventory-inline-retry">Try again</button></div></td></tr>';
      var retry = byId('inventory-inline-retry');
      if (retry) retry.addEventListener('click', function () { loadInventory(); });
      byId('inventory-result-summary').textContent = 'Inventory unavailable';
    } finally {
      if (requestNumber === state.requestNumber) {
        state.loading = false;
        byId('inventory-refresh-button').disabled = false;
      }
    }
  }

  function setPage(page) {
    var next = Math.max(1, Math.min(state.pages, Number(page) || 1));
    if (next === state.page && !state.loading) return;
    state.page = next;
    loadInventory({focusTable: true});
  }

  function resetFilters() {
    state.page = 1;
    state.protocol = 'all';
    state.statusGroup = 'all';
    state.capabilities.clear();
    state.sort = 'cost:asc';
    state.search = '';
    byId('inventory-search-input').value = '';
    byId('inventory-protocol-filter').value = state.protocol;
    byId('inventory-status-filter').value = state.statusGroup;
    byId('inventory-sort-select').value = state.sort;
    root.querySelectorAll('[data-capability]').forEach(function (button) { button.setAttribute('aria-pressed', 'false'); });
    savePreferences();
    loadInventory();
  }

  function toggleCapability(button) {
    var capability = button.dataset.capability;
    if (state.capabilities.has(capability)) state.capabilities.delete(capability);
    else state.capabilities.add(capability);
    button.setAttribute('aria-pressed', state.capabilities.has(capability) ? 'true' : 'false');
    state.page = 1;
    savePreferences();
    loadInventory();
  }

  function toggleSelection(id, checked) {
    var row = state.rowCache.get(id);
    if (checked && row) state.selected.set(id, row);
    else state.selected.delete(id);
    var tr = root.querySelector('tr[data-proxy-id="' + id + '"]');
    if (tr) tr.setAttribute('aria-selected', state.selected.has(id) ? 'true' : 'false');
    updateSelectionUI();
  }

  function togglePageSelection(checked) {
    state.rows.forEach(function (row) {
      var id = Number(row.id);
      if (checked) state.selected.set(id, row);
      else state.selected.delete(id);
    });
    root.querySelectorAll('[data-selection-id]').forEach(function (input) { input.checked = checked; });
    root.querySelectorAll('tr[data-proxy-id]').forEach(function (tr) { tr.setAttribute('aria-selected', checked ? 'true' : 'false'); });
    updateSelectionUI();
  }

  function clearSelection() {
    state.selected.clear();
    root.querySelectorAll('[data-selection-id]').forEach(function (input) { input.checked = false; });
    root.querySelectorAll('tr[data-proxy-id]').forEach(function (tr) { tr.setAttribute('aria-selected', 'false'); });
    updateSelectionUI();
  }

  async function copySelected() {
    var text = Array.from(state.selected.values()).map(endpoint).join('\n');
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(text);
    else if (typeof window.copyProxy === 'function') window.copyProxy(text);
    if (typeof window.showAlert === 'function') window.showAlert('Copied ' + state.selected.size + ' endpoints');
  }

  async function testOne(id, trigger) {
    var rowElement = root.querySelector('tr[data-proxy-id="' + id + '"]');
    if (rowElement) rowElement.classList.add('is-testing');
    if (trigger) trigger.disabled = true;
    try {
      var data = await fetchJson('/api/proxies/test/' + id, {method: 'POST'});
      if (typeof window.showAlert === 'function') {
        var validation = data.validation || {};
        window.showAlert('HTTPS ' + (validation.web_https_ok ? 'ready' : 'not ready') + ' · DNS ' + (validation.remote_dns_ok ? 'ready' : 'not ready') + ' · Telegram ' + (validation.telegram_ok ? 'ready' : 'not ready'));
      }
    } catch (error) {
      if (typeof window.showAlert === 'function') window.showAlert('Test failed: ' + (error.message || error));
    } finally {
      if (rowElement) rowElement.classList.remove('is-testing');
      if (trigger) trigger.disabled = false;
      await loadInventory();
    }
  }

  async function testSelected() {
    var ids = Array.from(state.selected.keys());
    if (!ids.length) return;
    var limit = Math.min(ids.length, 10);
    var button = byId('inventory-test-selected');
    button.disabled = true;
    try {
      for (var i = 0; i < limit; i += 1) {
        button.textContent = 'Testing ' + (i + 1) + '/' + limit;
        try { await fetchJson('/api/proxies/test/' + ids[i], {method: 'POST'}); } catch (_error) {}
      }
      if (ids.length > limit && typeof window.showAlert === 'function') window.showAlert('Tested the first 10 selected proxies to keep the request bounded.');
      await loadInventory();
    } finally {
      button.disabled = false;
      button.textContent = 'Test selected';
    }
  }

  function deleteSelected() {
    var ids = Array.from(state.selected.keys());
    if (!ids.length || typeof window.showConfirm !== 'function') return;
    window.showConfirm('Delete selected proxies', 'Delete ' + ids.length + ' selected proxies? This cannot be undone.', async function () {
      try {
        var data = await fetchJson('/api/proxies/selection/delete', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ids: ids})
        });
        clearSelection();
        closeDrawer();
        await loadInventory();
        if (typeof window.showAlert === 'function') window.showAlert('Deleted ' + data.deleted + ' proxies');
      } catch (error) {
        if (typeof window.showAlert === 'function') window.showAlert('Delete failed: ' + (error.message || error));
      }
    });
  }

  function deleteSingle(id) {
    if (typeof window.showConfirm !== 'function') return;
    window.showConfirm('Delete proxy', 'Delete this proxy from the inventory? This cannot be undone.', async function () {
      try {
        await fetchJson('/api/proxies/' + id, {method: 'DELETE'});
        state.selected.delete(id);
        closeDrawer();
        await loadInventory();
      } catch (error) {
        if (typeof window.showAlert === 'function') window.showAlert('Delete failed: ' + (error.message || error));
      }
    });
  }

  function editSingle(row) {
    if (!row || typeof window.editProxy !== 'function') return;
    window.editProxy(row.id, row.protocol, row.ip, row.port);
  }

  function detailItem(label, value) {
    return '<div class="inventory-detail-item"><span>' + safe(label) + '</span><strong title="' + safe(value == null ? '—' : value) + '">' + safe(value == null || value === '' ? '—' : value) + '</strong></div>';
  }

  function detailCapability(label, ready) {
    return '<div class="inventory-detail-capability' + (ready ? ' is-ready' : '') + '"><strong>' + (ready ? '✓' : '—') + '</strong><span>' + safe(label) + '</span></div>';
  }

  function renderDrawer(row) {
    var status = normalizedStatus(row);
    byId('inventory-drawer-title').textContent = row.ip + ':' + row.port;
    byId('inventory-drawer-subtitle').textContent = row.protocol.toUpperCase() + ' proxy · record #' + row.id;
    byId('inventory-drawer-body').innerHTML =
      '<div class="inventory-detail-hero"><div class="inventory-detail-endpoint"><code>' + safe(endpoint(row)) + '</code><button class="icon-button small" type="button" data-drawer-action="copy" title="Copy endpoint">⧉</button></div><div class="inventory-detail-state"><div><span class="inventory-status-dot" data-status="' + safe(status) + '"></span><strong>' + safe(statusLabel(status)) + '</strong></div><span>' + safe(statusHint(row)) + '</span></div></div>' +
      '<section class="inventory-detail-section"><h4>Capabilities</h4><div class="inventory-detail-capabilities">' + detailCapability('HTTPS', row.web_https_ok) + detailCapability('Remote DNS', row.remote_dns_ok) + detailCapability('Telegram', row.telegram_ok) + '</div></section>' +
      '<section class="inventory-detail-section"><h4>Quality</h4><div class="inventory-detail-grid">' + detailItem('Response', row.speed_ms == null ? 'Not measured' : row.speed_ms + ' ms') + detailItem('Reliability', percent(row.reliability)) + detailItem('Cost', decimal(row.cost)) + detailItem('Jitter score', decimal(row.jitter_score)) + detailItem('Latency score', decimal(row.latency_score)) + detailItem('Recency score', decimal(row.recency_score)) + detailItem('Total checks', number(row.total_checks)) + detailItem('Consecutive fails', number(row.consecutive_fails)) + '</div></section>' +
      '<section class="inventory-detail-section"><h4>Network</h4><div class="inventory-detail-grid">' + detailItem('Country', row.country || row.countryCode) + detailItem('Region', row.regionName) + detailItem('City', row.city) + detailItem('ISP', row.isp) + detailItem('Organization', row.org) + detailItem('ASN', row.asn) + detailItem('Resolved IP', row.resolved_ip) + detailItem('Exit IP', row.exit_ip) + '</div></section>' +
      '<section class="inventory-detail-section"><h4>Timeline</h4><div class="inventory-detail-grid">' + detailItem('Last checked', formatDate(row.last_checked)) + detailItem('Last alive', formatDate(row.last_alive)) + detailItem('Last failure', formatDate(row.last_fail)) + detailItem('Last transition', row.last_transition) + detailItem('Previous state', row.previous_state) + detailItem('Validation profile', row.validation_profile) + '</div></section>' +
      (row.validation_summary ? '<section class="inventory-detail-section"><h4>Validation summary</h4><pre class="inventory-detail-json">' + safe(JSON.stringify(row.validation_summary, null, 2)) + '</pre></section>' : '');

    var footer = '<button class="btn" type="button" data-drawer-action="copy">Copy endpoint</button>';
    if (permission('proxies.test')) footer += '<button class="btn" type="button" data-drawer-action="test">Test now</button>';
    if (permission('proxies.edit')) footer += '<button class="btn btn-primary" type="button" data-drawer-action="edit">Edit</button>';
    if (permission('proxies.delete')) footer += '<button class="btn btn-danger" type="button" data-drawer-action="delete">Delete</button>';
    byId('inventory-drawer-footer').innerHTML = footer;
    byId('inventory-drawer').dataset.proxyId = String(row.id);
  }

  async function openDrawer(id) {
    var drawer = byId('inventory-drawer');
    var scrim = byId('inventory-drawer-scrim');
    drawer.classList.add('is-open');
    drawer.setAttribute('aria-hidden', 'false');
    scrim.hidden = false;
    document.body.classList.add('inventory-drawer-open');
    var row = state.rowCache.get(Number(id));
    if (row) renderDrawer(row);
    else {
      byId('inventory-drawer-body').innerHTML = '<div class="inventory-loading-state"><span></span>Loading record…</div>';
      try {
        var data = await fetchJson('/api/proxies/' + id);
        state.rowCache.set(Number(id), data.proxy);
        renderDrawer(data.proxy);
      } catch (error) {
        byId('inventory-drawer-body').innerHTML = '<div class="inventory-error-state"><strong>Record unavailable</strong><span>' + safe(error.message || error) + '</span></div>';
      }
    }
  }

  function closeDrawer() {
    var drawer = byId('inventory-drawer');
    drawer.classList.remove('is-open');
    drawer.setAttribute('aria-hidden', 'true');
    byId('inventory-drawer-scrim').hidden = true;
    document.body.classList.remove('inventory-drawer-open');
  }

  function exportView() {
    var format = byId('inventory-export-format').value;
    var params = buildParams();
    params.delete('page');
    params.delete('page_size');
    params.delete('sort_col');
    params.delete('sort_order');
    params.set('format', format);
    params.set('columns', 'protocol,port,status,cost,speed,country,region,city,isp,asn,lastcheck');
    window.location.href = '/api/export?' + params.toString();
  }

  function handleRowAction(action, id, button) {
    var row = state.rowCache.get(Number(id));
    if (action === 'inspect') openDrawer(id);
    if (action === 'test') testOne(Number(id), button);
    if (action === 'edit') editSingle(row);
    if (action === 'delete') deleteSingle(Number(id));
  }

  function applyPermissionUI() {
    byId('inventory-add-button').hidden = !permission('proxies.add');
    byId('inventory-bulk-add-button').hidden = !permission('proxies.add');
    byId('inventory-empty-add').hidden = !permission('proxies.add');
    byId('inventory-export-button').hidden = !permission('proxies.export');
    byId('inventory-export-format').closest('label').hidden = !permission('proxies.export');
    byId('inventory-refresh-button').hidden = !permission('proxies.refresh');
    byId('inventory-search-input').disabled = !permission('proxies.search');
    byId('inventory-test-selected').hidden = !permission('proxies.test');
    byId('inventory-delete-selected').hidden = !permission('proxies.delete');
  }

  function applyUserScopeDefaults() {
    var filters = window.initialProxyFilters || {statuses: [], protocols: []};
    if (Array.isArray(filters.protocols) && filters.protocols.length === 1 && state.protocol === 'all') state.protocol = filters.protocols[0];
    var protocolSelect = byId('inventory-protocol-filter');
    Array.from(protocolSelect.options).forEach(function (option) {
      if (option.value === 'all') return;
      if (filters.protocols && filters.protocols.length && !filters.protocols.includes(option.value)) option.disabled = true;
    });
  }

  function bindEvents() {
    byId('inventory-refresh-button').addEventListener('click', function () { loadInventory(); });
    byId('inventory-add-button').addEventListener('click', function () { window.openModal('modal-add'); });
    byId('inventory-bulk-add-button').addEventListener('click', function () { window.openModal('modal-bulk'); });
    byId('inventory-empty-add').addEventListener('click', function () { window.openModal('modal-add'); });
    byId('inventory-empty-reset').addEventListener('click', resetFilters);
    byId('inventory-reset-filters').addEventListener('click', resetFilters);
    byId('inventory-export-button').addEventListener('click', exportView);
    byId('inventory-clear-selection').addEventListener('click', clearSelection);
    byId('inventory-copy-selected').addEventListener('click', copySelected);
    byId('inventory-test-selected').addEventListener('click', testSelected);
    byId('inventory-delete-selected').addEventListener('click', deleteSelected);
    byId('inventory-drawer-close').addEventListener('click', closeDrawer);
    byId('inventory-drawer-scrim').addEventListener('click', closeDrawer);

    byId('inventory-protocol-filter').addEventListener('change', function (event) { state.protocol = event.target.value; state.page = 1; savePreferences(); loadInventory(); });
    byId('inventory-status-filter').addEventListener('change', function (event) { state.statusGroup = event.target.value; state.page = 1; savePreferences(); loadInventory(); });
    byId('inventory-sort-select').addEventListener('change', function (event) { state.sort = event.target.value; state.page = 1; savePreferences(); loadInventory(); });
    byId('page-size').addEventListener('change', function (event) { state.pageSize = Number(event.target.value) || 50; state.page = 1; savePreferences(); loadInventory(); });
    byId('inventory-search-input').addEventListener('input', function (event) {
      clearTimeout(state.searchTimer);
      state.searchTimer = setTimeout(function () { state.search = event.target.value.trim().slice(0, 255); state.page = 1; loadInventory(); }, 260);
    });
    root.querySelectorAll('[data-capability]').forEach(function (button) { button.addEventListener('click', function () { toggleCapability(button); }); });

    byId('inventory-select-page').addEventListener('change', function (event) { togglePageSelection(event.target.checked); });
    byId('pager-btns').addEventListener('click', function (event) { var button = event.target.closest('[data-page]'); if (button && !button.disabled) setPage(button.dataset.page); });
    byId('proxies-tbody').addEventListener('change', function (event) { var input = event.target.closest('[data-selection-id]'); if (input) toggleSelection(Number(input.dataset.selectionId), input.checked); });
    byId('proxies-tbody').addEventListener('click', function (event) {
      var action = event.target.closest('[data-action]');
      if (action) { event.stopPropagation(); handleRowAction(action.dataset.action, action.dataset.id, action); return; }
      if (event.target.closest('[data-selection-id]')) return;
      var row = event.target.closest('tr[data-proxy-id]');
      if (row) openDrawer(Number(row.dataset.proxyId));
    });

    function drawerAction(event) {
      var button = event.target.closest('[data-drawer-action]');
      if (!button) return;
      var id = Number(byId('inventory-drawer').dataset.proxyId);
      var row = state.rowCache.get(id);
      if (button.dataset.drawerAction === 'copy' && row) window.copyProxy(endpoint(row));
      if (button.dataset.drawerAction === 'test') testOne(id, button);
      if (button.dataset.drawerAction === 'edit') editSingle(row);
      if (button.dataset.drawerAction === 'delete') deleteSingle(id);
    }
    byId('inventory-drawer-body').addEventListener('click', drawerAction);
    byId('inventory-drawer-footer').addEventListener('click', drawerAction);

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && byId('inventory-drawer').classList.contains('is-open')) closeDrawer();
      if (event.key === '/' && !/input|textarea|select/i.test(document.activeElement.tagName)) {
        event.preventDefault();
        byId('inventory-search-input').focus();
      }
    });
  }

  function initialize() {
    if (state.initialized) return;
    state.initialized = true;
    applyUserScopeDefaults();
    byId('inventory-protocol-filter').value = state.protocol;
    byId('inventory-status-filter').value = state.statusGroup;
    byId('inventory-sort-select').value = state.sort;
    byId('page-size').value = String(state.pageSize);
    root.querySelectorAll('[data-capability]').forEach(function (button) { button.setAttribute('aria-pressed', state.capabilities.has(button.dataset.capability) ? 'true' : 'false'); });
    bindEvents();
    updateSelectionUI();
    state.permissionsPromise = typeof window.loadCurrentUserPermissions === 'function' ? window.loadCurrentUserPermissions() : Promise.resolve();
    state.permissionsPromise.then(applyPermissionUI).catch(function () { applyPermissionUI(); });
  }

  window.loadProxies = loadInventory;
  window.goPage = setPage;
  window.changePageSize = function (size) { state.pageSize = Number(size) || 50; state.page = 1; byId('page-size').value = String(state.pageSize); savePreferences(); loadInventory(); };
  window.ProxyPoolInventory = {reload: loadInventory, reset: resetFilters, closeDrawer: closeDrawer};

  initialize();
}());
