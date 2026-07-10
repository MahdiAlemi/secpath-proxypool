(function () {
  'use strict';

  var root = document.getElementById('tab-import');
  if (!root) return;

  var state = {
    mode: 'manual',
    preview: null,
    previewPayload: null,
    previewSourceId: null,
    editSourceId: null,
    dialogPayload: null,
    sources: [],
    runs: [],
    busy: false,
    initialized: false
  };

  function one(selector, scope) { return (scope || root).querySelector(selector); }
  function all(selector, scope) { return Array.prototype.slice.call((scope || root).querySelectorAll(selector)); }
  function text(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
  function number(value) { return Number(value || 0).toLocaleString(); }
  function setHidden(element, hidden) { if (element) element.classList.toggle('hidden', Boolean(hidden)); }
  function apiMessage(payload, fallback) { return (payload && (payload.error || payload.message)) || fallback; }

  async function request(url, options) {
    var response = await authFetch(url, options || {});
    var payload;
    try { payload = await response.json(); }
    catch (_error) { payload = {success: false, error: 'Unexpected server response'}; }
    if (!response.ok || payload.success === false) {
      var error = new Error(apiMessage(payload, 'Request failed'));
      error.payload = payload;
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function setBusy(busy) {
    state.busy = Boolean(busy);
    root.classList.toggle('source-loading', state.busy);
    all('button, input, select, textarea').forEach(function (element) {
      if (element.matches('[data-source-dialog-close]')) return;
      if (state.busy) {
        element.dataset.sourceWasDisabled = element.disabled ? '1' : '0';
        element.disabled = true;
      } else {
        element.disabled = element.dataset.sourceWasDisabled === '1';
        delete element.dataset.sourceWasDisabled;
      }
    });
    var importButton = one('[data-source-import-button]');
    if (!state.busy && importButton) {
      importButton.disabled = !state.preview || Number(state.preview.summary && state.preview.summary.new || 0) < 1;
    }
  }

  function invalidatePreview() {
    state.preview = null;
    state.previewPayload = null;
    state.previewSourceId = null;
    setHidden(one('[data-source-preview-empty]'), false);
    setHidden(one('[data-source-preview-result]'), true);
  }

  function setMode(mode) {
    if (!['manual', 'url', 'links'].includes(mode)) mode = 'manual';
    state.mode = mode;
    all('[data-source-mode]').forEach(function (button) {
      var active = button.dataset.sourceMode === mode;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    all('[data-source-panel]').forEach(function (panel) {
      panel.classList.toggle('hidden', panel.dataset.sourcePanel !== mode);
    });
    var saveButton = one('[data-source-save-button]');
    if (saveButton) saveButton.hidden = mode === 'manual';
    invalidatePreview();
  }

  function currentPayload() {
    if (state.mode === 'manual') {
      return {
        mode: 'manual',
        protocol: one('#source-manual-protocol').value,
        proxies: one('#source-manual-content').value
      };
    }
    if (state.mode === 'url') {
      return {
        mode: 'url',
        protocol: one('#source-url-protocol').value,
        url: one('#source-url-input').value.trim()
      };
    }
    return {mode: 'links', content: one('#source-links-content').value};
  }

  function validatePayload(payload) {
    if (payload.mode === 'manual' && !payload.proxies.trim()) return 'Paste or upload at least one proxy.';
    if (payload.mode === 'url' && !payload.url) return 'Enter a public source URL.';
    if (payload.mode === 'links' && !payload.content.trim()) return 'Paste or upload a grouped source configuration.';
    return '';
  }

  function protocolMarkup(protocols) {
    var keys = ['http', 'https', 'socks4', 'socks5'];
    var rows = keys.filter(function (key) { return Number(protocols[key] || 0) > 0; });
    if (!rows.length) return '<span class="field-help">No valid protocols detected.</span>';
    return rows.map(function (key) {
      return '<span class="protocol-chip">' + text(key.toUpperCase()) + '<strong>' + number(protocols[key]) + '</strong></span>';
    }).join('');
  }

  function sampleMarkup(samples) {
    if (!samples || !samples.length) return '<div class="source-list-placeholder">No normalized candidates to display.</div>';
    return samples.map(function (sample) {
      return '<div class="candidate-sample">' +
        '<code>' + text(sample.endpoint) + (sample.has_auth ? ' · auth' : '') + '</code>' +
        '<span class="candidate-state ' + (sample.state === 'new' ? 'is-new' : '') + '">' + text(sample.state) + '</span>' +
      '</div>';
    }).join('');
  }

  function sourceCheckMarkup(sources) {
    return (sources || []).map(function (source) {
      var failed = source.status === 'failed';
      var detail = failed ? source.error : number(source.new) + ' new · ' + number(source.existing) + ' stored · ' + number(source.invalid) + ' invalid';
      return '<div class="source-check-item">' +
        '<div class="source-check-copy"><strong>' + text(source.label) + '</strong><small>' + text(source.protocol.toUpperCase()) + ' · ' + text(detail) + '</small></div>' +
        '<span class="source-check-state ' + (failed ? 'is-failed' : 'is-ready') + '">' + (failed ? 'failed' : 'ready') + '</span>' +
      '</div>';
    }).join('');
  }

  function renderPreview(result, options) {
    options = options || {};
    state.preview = result;
    state.previewPayload = options.payload || null;
    state.previewSourceId = options.sourceId || null;
    var summary = result.summary || {};
    setHidden(one('[data-source-preview-empty]'), true);
    setHidden(one('[data-source-preview-result]'), false);

    one('[data-preview-new]').textContent = number(summary.new);
    one('[data-preview-existing]').textContent = number(summary.existing);
    one('[data-preview-invalid]').textContent = number(summary.invalid);
    one('[data-preview-duplicates]').textContent = number(summary.input_duplicates);
    one('[data-preview-total]').textContent = number(summary.valid) + ' unique candidates';
    one('[data-preview-protocols]').innerHTML = protocolMarkup(result.protocols || {});
    one('[data-preview-samples]').innerHTML = sampleMarkup(result.samples || []);

    var sourceWrap = one('[data-preview-sources-wrap]');
    var sourceRows = result.sources || [];
    setHidden(sourceWrap, sourceRows.length < 2 && !result.errors.length);
    one('[data-preview-source-count]').textContent = sourceRows.length + (sourceRows.length === 1 ? ' source' : ' sources');
    one('[data-preview-sources]').innerHTML = sourceCheckMarkup(sourceRows);

    var status = one('[data-source-preview-status]');
    var newCount = Number(summary.new || 0);
    var errors = result.errors || [];
    var tone = errors.length ? 'warning' : (newCount > 0 ? 'success' : 'warning');
    status.dataset.tone = tone;
    status.innerHTML = '<span>' + (errors.length ? text(errors.length + ' source issue' + (errors.length > 1 ? 's' : '') + ' detected') : text('Preview completed without writing to inventory')) + '</span>' +
      '<strong>' + number(summary.total_lines) + ' lines inspected</strong>';

    var importButton = one('[data-source-import-button]');
    importButton.disabled = newCount < 1;
    importButton.textContent = newCount > 0 ? 'Import ' + number(newCount) + ' new candidate' + (newCount === 1 ? '' : 's') : 'Nothing new to import';
    one('[data-preview-action-title]').textContent = newCount > 0 ? 'Ready to import' : 'Inventory is already current';
    one('[data-preview-action-copy]').textContent = errors.length ? 'Successful sources can still be imported; failed sources will be reported.' : (newCount > 0 ? 'Only new candidates will be written. Existing entries stay unchanged.' : 'Change the input or refresh the source to find new candidates.');
  }

  async function previewCurrent() {
    var payload = currentPayload();
    var validationError = validatePayload(payload);
    if (validationError) { showAlert(validationError, 'Preview required'); return; }
    setBusy(true);
    try {
      var result = await request('/api/import/preview', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      renderPreview(result, {payload: payload});
    } catch (error) {
      showAlert(error.message, 'Preview failed');
    } finally {
      setBusy(false);
    }
  }

  async function runCurrentImport() {
    if (!state.preview) return;
    setBusy(true);
    try {
      var url = state.previewSourceId ? '/api/import/sources/' + state.previewSourceId + '/run' : '/api/import';
      var options = state.previewSourceId ? {method: 'POST'} : {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(state.previewPayload)
      };
      var result = await request(url, options);
      var added = Number(result.added || 0);
      var skipped = Number(result.skipped || 0);
      var summary = result.summary || {};
      summary.existing = Number(summary.existing || 0) + added;
      summary.new = 0;
      result.summary = summary;
      result.samples = (result.samples || []).map(function (sample) {
        var updated = Object.assign({}, sample);
        if (updated.state === 'new') updated.state = 'existing';
        return updated;
      });
      renderPreview(result, {});
      var status = one('[data-source-preview-status]');
      status.dataset.tone = result.status === 'partial' ? 'warning' : 'success';
      status.innerHTML = '<span>Import ' + text(result.status || 'completed') + '</span><strong>' + number(added) + ' added · ' + number(skipped) + ' skipped</strong>';
      showAlert(number(added) + ' candidates added to inventory.', 'Import complete');
      if (typeof window.loadProxies === 'function') window.loadProxies();
      await refreshData();
    } catch (error) {
      showAlert(error.message, 'Import failed');
    } finally {
      setBusy(false);
    }
  }

  function resetComposer() {
    one('#source-manual-content').value = '';
    one('#source-url-input').value = '';
    one('#source-links-content').value = '';
    one('#source-manual-file').value = '';
    one('#source-links-file').value = '';
    invalidatePreview();
  }

  function loadFile(input, target) {
    var file = input.files && input.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { showAlert('The selected file is larger than 2 MB.', 'File too large'); input.value = ''; return; }
    var reader = new FileReader();
    reader.onload = function (event) { target.value = event.target.result || ''; invalidatePreview(); };
    reader.onerror = function () { showAlert('Could not read the selected file.', 'File error'); };
    reader.readAsText(file);
  }

  function sourceSummary(payload) {
    if (payload.mode === 'url') return text(payload.protocol.toUpperCase()) + ' · ' + text(payload.url);
    var count = (payload.content.match(/^\s*https?:\/\//gmi) || []).length;
    return 'Grouped source config · ' + count + ' URL' + (count === 1 ? '' : 's');
  }

  function openSourceDialog(source, payload) {
    state.editSourceId = source ? source.id : null;
    state.dialogPayload = payload;
    one('#source-dialog-id').value = source ? source.id : '';
    one('#source-dialog-name').value = source ? source.name : '';
    one('#source-dialog-active').checked = source ? source.is_active : true;
    one('#source-dialog-title').textContent = source ? 'Edit source' : 'Save source';
    one('[data-source-dialog-submit]').textContent = source ? 'Update source' : 'Save source';
    setHidden(one('[data-source-dialog-url-fields]'), payload.mode !== 'url');
    setHidden(one('[data-source-dialog-links-fields]'), payload.mode !== 'links');
    one('#source-dialog-protocol').value = payload.protocol || 'http';
    one('#source-dialog-url').value = payload.url || '';
    one('#source-dialog-content').value = payload.content || '';
    one('[data-source-dialog-summary]').innerHTML = '<strong>' + text(payload.mode === 'url' ? 'Single URL' : 'Source config') + '</strong><br>' + sourceSummary(payload);
    setHidden(one('[data-source-dialog-backdrop]'), false);
    setTimeout(function () { one('#source-dialog-name').focus(); }, 0);
  }

  function closeSourceDialog() {
    state.editSourceId = null;
    state.dialogPayload = null;
    setHidden(one('[data-source-dialog-backdrop]'), true);
  }

  function saveCurrentAsSource() {
    var payload = currentPayload();
    var validationError = validatePayload(payload);
    if (state.mode === 'manual') validationError = 'Manual batches cannot be saved as recurring sources.';
    if (validationError) { showAlert(validationError, 'Cannot save source'); return; }
    openSourceDialog(null, payload);
  }

  async function submitSourceDialog() {
    var name = one('#source-dialog-name').value.trim();
    if (name.length < 2) { showAlert('Enter a source name with at least 2 characters.', 'Source name required'); return; }
    var mode = state.dialogPayload && state.dialogPayload.mode || 'url';
    var payload = {
      name: name,
      mode: mode,
      is_active: one('#source-dialog-active').checked
    };
    if (mode === 'url') {
      payload.protocol = one('#source-dialog-protocol').value;
      payload.url = one('#source-dialog-url').value.trim();
      if (!payload.url) { showAlert('Enter a public source URL.', 'Source URL required'); return; }
    } else {
      payload.content = one('#source-dialog-content').value;
      if (!payload.content.trim()) { showAlert('Enter a grouped source configuration.', 'Source config required'); return; }
    }
    var sourceId = state.editSourceId;
    setBusy(true);
    try {
      await request(sourceId ? '/api/import/sources/' + sourceId : '/api/import/sources', {
        method: sourceId ? 'PUT' : 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      closeSourceDialog();
      await loadSources();
      showAlert(sourceId ? 'Saved source updated.' : 'Saved source created.', 'Source saved');
    } catch (error) {
      showAlert(error.message, 'Could not save source');
    } finally {
      setBusy(false);
    }
  }

  function sourceStatus(source) {
    if (!source.is_active) return {label: 'disabled', className: 'disabled'};
    if (source.last_status) return {label: source.last_status, className: source.last_status};
    return {label: 'ready', className: 'active'};
  }

  function formatDate(value) {
    if (!value) return 'Never';
    var date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Unknown';
    return date.toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'});
  }

  function renderSources() {
    var list = one('[data-source-library-list]');
    one('[data-source-library-count]').textContent = state.sources.length + ' source' + (state.sources.length === 1 ? '' : 's');
    if (!state.sources.length) {
      list.innerHTML = '<div class="source-library-empty"><strong>No saved sources yet</strong><span>Save a URL or grouped config to make recurring imports faster.</span></div>';
      return;
    }
    list.innerHTML = state.sources.map(function (source) {
      var status = sourceStatus(source);
      var type = source.mode === 'url' ? (source.protocol || 'http').toUpperCase() + ' URL' : 'Grouped config';
      var lastRun = source.last_run_at ? formatDate(source.last_run_at) : 'Not run yet';
      return '<article class="source-library-item" data-source-id="' + source.id + '">' +
        '<div class="source-library-primary"><strong>' + text(source.name) + '</strong><small>' + text(type) + '</small></div>' +
        '<div class="source-library-meta"><span>Status</span><strong class="source-status-pill ' + text(status.className) + '">' + text(status.label) + '</strong></div>' +
        '<div class="source-library-run"><span>Last run</span><strong>' + text(lastRun) + '</strong></div>' +
        '<div class="source-library-actions">' +
          '<button class="source-action-button" type="button" data-source-action="preview" title="Preview">Preview</button>' +
          '<button class="source-action-button" type="button" data-source-action="run" title="Run source"' + (source.is_active ? '' : ' disabled') + '>Run</button>' +
          '<button class="source-action-button" type="button" data-source-action="edit" title="Edit source">Edit</button>' +
          '<button class="source-action-button danger" type="button" data-source-action="delete" title="Delete source">×</button>' +
        '</div>' +
      '</article>';
    }).join('');
  }

  function runStatusMarkup(status) {
    var safe = ['completed', 'partial', 'failed'].includes(status) ? status : 'active';
    return '<span class="source-status-pill ' + safe + '">' + text(status || 'completed') + '</span>';
  }

  function renderRuns() {
    var body = one('[data-source-history-body]');
    if (!state.runs.length) {
      body.innerHTML = '<tr><td colspan="6" class="table-empty">No import runs have been recorded yet.</td></tr>';
      return;
    }
    body.innerHTML = state.runs.map(function (run) {
      var mix = Object.keys(run.protocol_counts || {}).filter(function (key) { return run.protocol_counts[key]; }).map(function (key) {
        return key.toUpperCase() + ' ' + run.protocol_counts[key];
      }).join(' · ') || '—';
      return '<tr>' +
        '<td>' + text(formatDate(run.started_at)) + '</td>' +
        '<td><strong>' + text(run.source_name || (run.mode === 'manual' ? 'Manual input' : 'Quick import')) + '</strong></td>' +
        '<td>' + runStatusMarkup(run.status) + '</td>' +
        '<td><strong>' + number(run.added) + '</strong></td>' +
        '<td>' + number(run.skipped) + '</td>' +
        '<td>' + text(mix) + '</td>' +
      '</tr>';
    }).join('');
  }

  async function loadSources() {
    var data = await request('/api/import/sources');
    state.sources = data.sources || [];
    renderSources();
  }

  async function loadRuns() {
    var data = await request('/api/import/runs?limit=20');
    state.runs = data.runs || [];
    renderRuns();
  }

  async function refreshData() {
    try { await Promise.all([loadSources(), loadRuns()]); }
    catch (error) { showAlert(error.message, 'Could not refresh Sources'); }
  }

  async function previewSavedSource(sourceId) {
    setBusy(true);
    try {
      var result = await request('/api/import/sources/' + sourceId + '/preview', {method: 'POST'});
      renderPreview(result, {sourceId: sourceId});
      window.scrollTo({top: root.offsetTop, behavior: 'smooth'});
    } catch (error) { showAlert(error.message, 'Source preview failed'); }
    finally { setBusy(false); }
  }

  async function runSavedSource(sourceId) {
    setBusy(true);
    try {
      var result = await request('/api/import/sources/' + sourceId + '/run', {method: 'POST'});
      showAlert(number(result.added) + ' candidates added to inventory.', 'Source run complete');
      await refreshData();
      if (typeof window.loadProxies === 'function') window.loadProxies();
    } catch (error) { showAlert(error.message, 'Source run failed'); }
    finally { setBusy(false); }
  }

  async function editSavedSource(sourceId) {
    setBusy(true);
    try {
      var data = await request('/api/import/sources/' + sourceId);
      var source = data.source;
      setMode(source.mode);
      var payload;
      if (source.mode === 'url') {
        one('#source-url-protocol').value = source.protocol || 'http';
        one('#source-url-input').value = source.url || '';
        payload = {mode: 'url', protocol: source.protocol || 'http', url: source.url || ''};
      } else {
        one('#source-links-content').value = source.content || '';
        payload = {mode: 'links', content: source.content || ''};
      }
      openSourceDialog(source, payload);
    } catch (error) { showAlert(error.message, 'Could not load source'); }
    finally { setBusy(false); }
  }

  function deleteSavedSource(sourceId) {
    var source = state.sources.find(function (row) { return row.id === sourceId; });
    showConfirm('Delete saved source', 'Delete “' + (source ? source.name : 'this source') + '”? Import history will remain.', async function () {
      setBusy(true);
      try {
        await request('/api/import/sources/' + sourceId, {method: 'DELETE'});
        await loadSources();
      } catch (error) { showAlert(error.message, 'Could not delete source'); }
      finally { setBusy(false); }
    }, {confirmText: 'Delete source', confirmClass: 'btn-danger'});
  }

  function bindEvents() {
    all('[data-source-mode]').forEach(function (button) {
      button.addEventListener('click', function () { setMode(button.dataset.sourceMode); });
    });
    all('textarea, input, select', root).forEach(function (input) {
      if (input.closest('.source-dialog')) return;
      input.addEventListener('input', invalidatePreview);
      input.addEventListener('change', invalidatePreview);
    });
    one('#source-manual-file').addEventListener('change', function () { loadFile(this, one('#source-manual-content')); });
    one('#source-links-file').addEventListener('change', function () { loadFile(this, one('#source-links-content')); });
    one('[data-source-preview-button]').addEventListener('click', previewCurrent);
    one('[data-source-import-button]').addEventListener('click', runCurrentImport);
    one('[data-source-reset]').addEventListener('click', resetComposer);
    one('[data-source-save-button]').addEventListener('click', saveCurrentAsSource);
    one('[data-source-refresh]').addEventListener('click', refreshData);
    all('[data-source-dialog-close]').forEach(function (button) { button.addEventListener('click', closeSourceDialog); });
    one('[data-source-dialog-submit]').addEventListener('click', submitSourceDialog);
    one('[data-source-dialog-backdrop]').addEventListener('click', function (event) {
      if (event.target === this) closeSourceDialog();
    });
    one('[data-source-library-list]').addEventListener('click', function (event) {
      var button = event.target.closest('[data-source-action]');
      var item = event.target.closest('[data-source-id]');
      if (!button || !item) return;
      var sourceId = Number(item.dataset.sourceId);
      var action = button.dataset.sourceAction;
      if (action === 'preview') previewSavedSource(sourceId);
      if (action === 'run') {
        showConfirm('Run saved source', 'Fetch this source and add only new candidates?', function () { runSavedSource(sourceId); }, {confirmText: 'Run source', confirmClass: 'btn-primary'});
      }
      if (action === 'edit') editSavedSource(sourceId);
      if (action === 'delete') deleteSavedSource(sourceId);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !one('[data-source-dialog-backdrop]').classList.contains('hidden')) closeSourceDialog();
    });
  }

  async function init() {
    if (!state.initialized) {
      bindEvents();
      setMode('manual');
      state.initialized = true;
    }
    await refreshData();
  }

  window.SourceWorkspace = {init: init, refresh: refreshData, setMode: setMode};
}());
