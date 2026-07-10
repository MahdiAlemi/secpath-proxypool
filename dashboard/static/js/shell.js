(function () {
  'use strict';

  var tabMeta = {
    cockpit: {section: 'Overview', title: 'Cockpit'},
    proxies: {section: 'Workflow', title: 'Inventory'},
    import: {section: 'Workflow', title: 'Sources'},
    monitor: {section: 'Workflow', title: 'Validation'},
    server: {section: 'Workflow', title: 'Serving'},
    stats: {section: 'Intelligence', title: 'Insights'},
    operations: {section: 'Administration', title: 'Operations'},
    users: {section: 'Administration', title: 'Access'}
  };

  function setSidebar(open) {
    document.body.classList.toggle('sidebar-open', Boolean(open));
  }

  window.updateShellForTab = function updateShellForTab(tab, options) {
    var meta = tabMeta[tab] || tabMeta.cockpit;
    var title = document.getElementById('topbar-title');
    var section = document.getElementById('topbar-section');
    if (title) title.textContent = meta.title;
    if (section) section.textContent = meta.section;
    document.body.dataset.activeTab = tab;
    document.title = meta.title + ' · ProxyPool';

    var primary = document.getElementById('topbar-add-proxy');
    if (primary) {
      var can = function (permission) {
        return typeof window.hasPermission !== 'function' || window.hasPermission(permission);
      };
      primary.hidden = false;
      if (tab === 'monitor' && can('monitor.control')) {
        primary.textContent = '＋ New profile';
        primary.onclick = function () { if (typeof window.showAddMonitorForm === 'function') window.showAddMonitorForm(); };
      } else if (tab === 'server' && can('server.control')) {
        primary.textContent = '＋ New server';
        primary.onclick = function () { if (typeof window.showAddServerForm === 'function') window.showAddServerForm(); };
      } else if (tab === 'users' && can('users.manage')) {
        primary.textContent = '＋ New user';
        primary.onclick = function () { if (window.AccessWorkspace) window.AccessWorkspace.create(); };
      } else if ((tab === 'cockpit' || tab === 'proxies') && can('proxies.add')) {
        primary.textContent = '＋ Add proxy';
        primary.onclick = function () { if (typeof window.openModal === 'function') window.openModal('modal-add'); };
      } else {
        primary.hidden = true;
      }
    }

    if (!options || options.updateHistory !== false) {
      var url = new URL(window.location.href);
      if (tab === 'cockpit') url.searchParams.delete('tab');
      else url.searchParams.set('tab', tab);
      window.history.replaceState({tab: tab}, '', url.pathname + url.search + url.hash);
    }
    if (window.innerWidth <= 820) setSidebar(false);
  };

  document.querySelectorAll('[data-sidebar-open]').forEach(function (button) {
    button.addEventListener('click', function () { setSidebar(true); });
  });
  document.querySelectorAll('[data-sidebar-close]').forEach(function (button) {
    button.addEventListener('click', function () { setSidebar(false); });
  });

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') return;
    if (document.body.classList.contains('sidebar-open')) setSidebar(false);
    var activeModal = document.querySelector('.modal.active');
    if (activeModal && typeof window.closeModal === 'function') window.closeModal(activeModal.id);
  });

  window.addEventListener('popstate', function () {
    var tab = new URL(window.location.href).searchParams.get('tab') || 'cockpit';
    if (tabMeta[tab] && typeof window.showTab === 'function') {
      window.showTab(tab, null, {updateHistory: false});
    }
  });

  var initial = window.initialDashboardTab || document.querySelector('.app-shell')?.dataset.initialTab || 'cockpit';
  if (!tabMeta[initial]) initial = 'cockpit';
  if (typeof window.showTab === 'function') window.showTab(initial, null, {updateHistory: false, scroll: false});
  else window.updateShellForTab(initial, {updateHistory: false});
}());
