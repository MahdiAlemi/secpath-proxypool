(function () {
  'use strict';

  var users = [];
  var permissions = null;
  var selectedId = null;
  var initialized = false;

  var permissionGroups = {
    Inventory: ['proxies.view', 'proxies.add', 'proxies.edit', 'proxies.delete', 'proxies.test', 'proxies.export', 'proxies.credentials'],
    Sources: ['proxies.import'],
    Validation: ['monitor.view', 'monitor.control'],
    Serving: ['server.view', 'server.control'],
    Intelligence: ['stats.view'],
    Operations: ['settings.view', 'settings.edit'],
    Access: ['users.manage']
  };

  function text(id, value) {
    var node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function formatDate(value) {
    if (!value) return 'Never';
    var date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Unknown' : date.toLocaleString();
  }

  function selectedUser() {
    return users.find(function (user) { return user.id === selectedId; }) || null;
  }

  function roleLabel(role) {
    if (role === 'admin') return 'Admin';
    if (role === 'superadmin') return 'Superadmin';
    return 'User';
  }

  function renderSummary() {
    text('access-total', users.length);
    text('access-active', users.filter(function (user) { return user.is_active; }).length);
    text('access-admins', users.filter(function (user) { return user.is_active && (user.role === 'admin' || user.role === 'superadmin'); }).length);
    text('access-tokens', users.reduce(function (sum, user) { return sum + Number(user.token_count || 0); }, 0));
    text('access-updated', 'Updated ' + new Date().toLocaleTimeString());
  }

  function renderList() {
    var target = document.getElementById('access-user-list');
    var search = String(document.getElementById('access-search').value || '').trim().toLowerCase();
    var role = document.getElementById('access-role-filter').value;
    target.innerHTML = '';
    var filtered = users.filter(function (user) {
      return (!search || user.username.toLowerCase().includes(search)) && (role === 'all' || user.role === role);
    });
    document.getElementById('access-empty').hidden = filtered.length > 0;
    filtered.forEach(function (user) {
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'access-user-row' + (user.id === selectedId ? ' active' : '');
      row.dataset.userId = user.id;
      var avatar = document.createElement('span'); avatar.className = 'access-user-row-avatar'; avatar.textContent = user.username.charAt(0).toUpperCase();
      var identity = document.createElement('span'); var name = document.createElement('strong'); name.textContent = user.username; var sub = document.createElement('small'); sub.textContent = user.is_current ? 'Current account' : 'Created ' + formatDate(user.created_at); identity.append(name, sub);
      var roleNode = document.createElement('span'); roleNode.className = 'access-user-role'; roleNode.textContent = roleLabel(user.role);
      var status = document.createElement('span'); status.textContent = user.is_active ? 'Active' : 'Inactive'; status.style.color = user.is_active ? 'var(--success)' : 'var(--danger)';
      var login = document.createElement('span'); login.className = 'access-user-login'; login.textContent = user.last_login ? formatDate(user.last_login).split(',')[0] : 'Never';
      row.append(avatar, identity, roleNode, status, login);
      row.addEventListener('click', function () { selectedId = user.id; renderList(); renderDetail(); });
      target.appendChild(row);
    });
  }

  function renderDetail() {
    var user = selectedUser();
    document.getElementById('access-detail-empty').hidden = Boolean(user);
    document.getElementById('access-detail').hidden = !user;
    if (!user) return;
    text('access-detail-avatar', user.username.charAt(0).toUpperCase());
    text('access-detail-name', user.username);
    text('access-detail-role', roleLabel(user.role));
    document.getElementById('access-detail-role').dataset.tone = user.role === 'admin' ? 'good' : '';
    text('access-detail-meta', user.is_current ? 'This is your current account' : 'User #' + user.id);
    text('access-detail-status', user.is_active ? 'Active' : 'Inactive');
    text('access-detail-created', formatDate(user.created_at));
    text('access-detail-login', formatDate(user.last_login));
    text('access-detail-tokens', user.token_count || 0);
    var deleteButton = document.getElementById('access-delete-button');
    deleteButton.hidden = Boolean(user.is_current);

    var effective = (user.effective_permissions || []).filter(function (permission) { return permission !== '*'; });
    text('access-permission-count', user.effective_permissions && user.effective_permissions.includes('*') ? 'All' : effective.length);
    var perms = document.getElementById('access-permissions'); perms.innerHTML = '';
    if (user.effective_permissions && user.effective_permissions.includes('*')) {
      var all = document.createElement('span'); all.textContent = 'All permissions'; perms.appendChild(all);
    } else {
      effective.forEach(function (permission) { var chip = document.createElement('span'); chip.textContent = permission; perms.appendChild(chip); });
      if (!effective.length) { var none = document.createElement('span'); none.textContent = 'No effective permissions'; perms.appendChild(none); }
    }

    var scope = user.proxy_scope || {};
    var scopeNode = document.getElementById('access-scope'); scopeNode.innerHTML = '';
    [['Statuses', scope.statuses || []], ['Protocols', scope.protocols || []]].forEach(function (entry) {
      var card = document.createElement('div'); var label = document.createElement('strong'); label.textContent = entry[0]; var value = document.createElement('span'); value.textContent = entry[1].length ? entry[1].join(', ') : 'Unrestricted'; card.append(label, value); scopeNode.appendChild(card);
    });
  }

  async function ensurePermissions() {
    if (permissions) return permissions;
    var response = await authFetch('/api/users/permissions');
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load permissions');
    permissions = data;
    return data;
  }

  function buildPermissionEditor(role, user) {
    var target = document.getElementById('custom-perms-list'); target.innerHTML = '';
    var defaults = (permissions.role_permissions[role] || []);
    var wildcard = defaults.includes('*');
    var added = user && user.custom_permissions ? (user.custom_permissions.add || []) : [];
    var removed = user && user.custom_permissions ? (user.custom_permissions.remove || []) : [];

    Object.keys(permissionGroups).forEach(function (groupName) {
      var group = document.createElement('section'); group.className = 'access-permission-group';
      var title = document.createElement('strong'); title.textContent = groupName;
      var options = document.createElement('div'); options.className = 'access-permission-options';
      permissionGroups[groupName].forEach(function (permission) {
        if (!permissions.all_permissions.includes(permission)) return;
        var isDefault = wildcard || defaults.includes(permission);
        var checked = (isDefault && !removed.includes(permission)) || added.includes(permission);
        var label = document.createElement('label');
        var input = document.createElement('input'); input.type = 'checkbox'; input.value = permission; input.checked = checked; input.dataset.default = isDefault ? '1' : '0'; input.className = 'access-permission-input';
        var copy = document.createElement('span'); copy.textContent = permission.replace(/^[^.]+\./, '') + (isDefault ? ' · role default' : '');
        label.append(input, copy); options.appendChild(label);
      });
      group.append(title, options); target.appendChild(group);
    });
  }

  function updateRoleDescription() {
    var role = document.getElementById('user-role').value;
    var descriptions = {
      user: 'Limited role. Proxy and server visibility are the defaults; add only the capabilities this operator needs.',
      superadmin: 'Operational role with inventory, validation, serving, settings, and access control capabilities.',
      admin: 'Full wildcard access. Use this role only for trusted administrators.'
    };
    text('role-description', descriptions[role]);
    document.getElementById('proxy-filters-group').hidden = role !== 'user';
    var user = selectedUser();
    buildPermissionEditor(role, document.getElementById('edit-user-id').value ? user : null);
  }

  function setScope(user) {
    var scope = user ? (user.proxy_scope || {}) : {};
    document.querySelectorAll('.proxy-filter-status').forEach(function (input) { input.checked = !(scope.statuses || []).length || scope.statuses.includes(input.value); });
    document.querySelectorAll('.proxy-filter-proto').forEach(function (input) { input.checked = !(scope.protocols || []).length || scope.protocols.includes(input.value); });
  }

  async function openEditor(user) {
    await ensurePermissions();
    document.getElementById('edit-user-id').value = user ? user.id : '';
    text('user-form-title', user ? 'Edit user' : 'Create user');
    text('user-form-subtitle', user ? 'Update role, permissions, scope, or credentials.' : 'Define identity, role defaults, permission overrides, and proxy scope.');
    document.getElementById('user-username').value = user ? user.username : '';
    document.getElementById('user-password').value = '';
    text('user-password-hint', user ? 'Leave empty to keep the current password.' : 'At least 12 characters.');
    document.getElementById('user-role').value = user ? user.role : 'user';
    document.getElementById('user-active').checked = user ? Boolean(user.is_active) : true;
    setScope(user);
    buildPermissionEditor(document.getElementById('user-role').value, user);
    updateRoleDescription();
    text('access-user-form-status', '');
    openModal('modal-user-form');
  }

  async function saveUser() {
    var id = document.getElementById('edit-user-id').value;
    var role = document.getElementById('user-role').value;
    var defaults = permissions.role_permissions[role] || [];
    var wildcard = defaults.includes('*');
    var add = [], remove = [];
    document.querySelectorAll('.access-permission-input').forEach(function (input) {
      var isDefault = wildcard || defaults.includes(input.value);
      if (input.checked && !isDefault) add.push(input.value);
      if (!input.checked && isDefault) remove.push(input.value);
    });
    var payload = {
      username: document.getElementById('user-username').value.trim(),
      role: role,
      is_active: document.getElementById('user-active').checked,
      custom_permissions: {add: add, remove: remove}
    };
    var password = document.getElementById('user-password').value;
    if (password) payload.password = password;
    if (role === 'user') {
      var statuses = Array.from(document.querySelectorAll('.proxy-filter-status:checked')).map(function (node) { return node.value; });
      var protocols = Array.from(document.querySelectorAll('.proxy-filter-proto:checked')).map(function (node) { return node.value; });
      var allStatuses = document.querySelectorAll('.proxy-filter-status').length;
      var allProtocols = document.querySelectorAll('.proxy-filter-proto').length;
      payload.custom_permissions.proxy_filters = {
        statuses: statuses.length === allStatuses ? [] : statuses,
        protocols: protocols.length === allProtocols ? [] : protocols
      };
    } else payload.custom_permissions.proxy_filters = {statuses: [], protocols: []};

    text('access-user-form-status', 'Saving…');
    var response = await authFetch(id ? '/api/users/' + id : '/api/users', {method: id ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    var data = await response.json();
    if (!response.ok || !data.success) { text('access-user-form-status', data.error || 'Save failed'); return; }
    closeModal('modal-user-form');
    await refresh();
    selectedId = id ? Number(id) : Number(data.id);
    renderList(); renderDetail();
  }

  async function refresh() {
    text('access-updated', 'Loading…');
    try {
      await ensurePermissions();
      var response = await authFetch('/api/users');
      var data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not load users');
      users = data;
      if (selectedId && !users.some(function (user) { return user.id === selectedId; })) selectedId = null;
      if (!selectedId && users.length) selectedId = users[0].id;
      renderSummary(); renderList(); renderDetail();
    } catch (error) {
      text('access-updated', 'Failed to load');
      if (typeof showAlert === 'function') showAlert(error.message || String(error), 'Access control unavailable');
    }
  }

  function deleteSelected() {
    var user = selectedUser();
    if (!user || user.is_current) return;
    showConfirm('Delete user', 'Delete “' + user.username + '” and revoke all API sessions?', function () {
      authFetch('/api/users/' + user.id, {method: 'DELETE'}).then(async function (response) {
        var data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || 'Delete failed');
        selectedId = null; await refresh();
      }).catch(function (error) { showAlert(error.message, 'Delete user failed'); });
    }, {confirmText: 'Delete user', confirmClass: 'btn-danger'});
  }

  function bind() {
    document.getElementById('access-search').addEventListener('input', renderList);
    document.getElementById('access-role-filter').addEventListener('change', renderList);
    document.getElementById('user-role').addEventListener('change', updateRoleDescription);
    document.getElementById('access-user-save').addEventListener('click', function () { saveUser().catch(function (error) { text('access-user-form-status', error.message || String(error)); }); });
  }

  window.AccessWorkspace = {
    init: function () { if (!initialized) { bind(); initialized = true; } refresh(); },
    refresh: refresh,
    create: function () { openEditor(null).catch(function (error) { showAlert(error.message); }); },
    editSelected: function () { var user = selectedUser(); if (user) openEditor(user).catch(function (error) { showAlert(error.message); }); },
    deleteSelected: deleteSelected
  };
  window.showAddUserModal = function () { window.AccessWorkspace.create(); };
  window.editUser = function (id) { selectedId = Number(id); window.AccessWorkspace.editSelected(); };
  window.saveUser = saveUser;
  window.deleteUser = function (id) { selectedId = Number(id); deleteSelected(); };
}());
