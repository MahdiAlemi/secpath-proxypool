(function () {
  'use strict';

  var initialized = false;

  function setText(id, value) {
    var node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function pct(value, total) {
    return total ? Math.round((Number(value || 0) / Number(total)) * 100) : 0;
  }

  function toneForRate(rate) {
    if (rate >= 70) return 'good';
    if (rate >= 35) return 'warn';
    return 'danger';
  }

  function barRows(targetId, rows, total) {
    var target = document.getElementById(targetId);
    if (!target) return;
    target.innerHTML = '';
    rows.forEach(function (row) {
      var wrapper = document.createElement('div');
      wrapper.className = 'insights-band-row';
      var label = document.createElement('span');
      label.textContent = row.label;
      var track = document.createElement('div');
      track.className = 'insights-band-track';
      var fill = document.createElement('i');
      fill.style.width = pct(row.value, total) + '%';
      if (row.color) fill.style.background = row.color;
      track.appendChild(fill);
      var value = document.createElement('strong');
      value.textContent = row.value + ' · ' + pct(row.value, total) + '%';
      wrapper.append(label, track, value);
      target.appendChild(wrapper);
    });
  }

  function renderHealth(data) {
    var quality = data.quality || {};
    var segments = [
      {label: 'Stable', value: quality.stable || 0, color: 'var(--success)'},
      {label: 'Unstable', value: quality.unstable || 0, color: '#f59e0b'},
      {label: 'Unavailable', value: quality.unavailable || 0, color: 'var(--danger)'},
      {label: 'Pending', value: quality.pending || 0, color: 'var(--muted)'}
    ];
    var total = Math.max(1, data.total || 0);
    var bars = document.getElementById('insights-health-bars');
    var legend = document.getElementById('insights-health-legend');
    bars.innerHTML = '';
    legend.innerHTML = '';
    segments.forEach(function (segment) {
      var part = document.createElement('span');
      part.style.width = pct(segment.value, total) + '%';
      part.style.background = segment.color;
      part.title = segment.label + ': ' + segment.value;
      bars.appendChild(part);

      var item = document.createElement('div');
      item.className = 'insights-legend-item';
      var dot = document.createElement('i');
      dot.style.background = segment.color;
      var label = document.createElement('span');
      label.textContent = segment.label;
      var value = document.createElement('strong');
      value.textContent = segment.value;
      item.append(dot, label, value);
      legend.appendChild(item);
    });

    var rate = Number(quality.success_rate || 0);
    var note = document.getElementById('insights-quality-note');
    note.textContent = rate >= 70 ? 'Healthy' : (rate >= 35 ? 'Mixed' : 'Needs attention');
    note.dataset.tone = toneForRate(rate);
    var recommendation = document.getElementById('insights-recommendation');
    if (!data.total) recommendation.textContent = 'Import candidates first, then validate them before creating a route.';
    else if (!quality.tested) recommendation.textContent = 'The inventory has not been validated yet. Run a focused validation profile.';
    else if (rate < 35) recommendation.textContent = 'Stable coverage is low. Refresh sources and revalidate before routing client traffic.';
    else if ((quality.full_rate || 0) < 40) recommendation.textContent = 'Basic stability exists, but capability coverage is limited. Use strict server filters.';
    else recommendation.textContent = 'The pool has useful stable coverage. Keep validation fresh and watch provider concentration.';
  }

  function renderProtocols(data) {
    var target = document.getElementById('insights-protocols');
    target.innerHTML = '';
    var stats = data.protocol_stats || {};
    Object.keys(stats).forEach(function (protocol) {
      var item = stats[protocol] || {};
      if (!item.total) return;
      var row = document.createElement('div');
      row.className = 'insights-protocol-row';
      var name = document.createElement('span');
      name.textContent = protocol.toUpperCase();
      var track = document.createElement('div');
      track.className = 'insights-row-bar';
      var fill = document.createElement('i');
      fill.style.width = Number(item.alive_rate || 0) + '%';
      track.appendChild(fill);
      var value = document.createElement('strong');
      value.textContent = item.alive + '/' + item.total;
      row.append(name, track, value);
      target.appendChild(row);
    });
    if (!target.children.length) target.textContent = 'No protocol data yet.';
  }

  function renderCapabilities(data) {
    var alive = Number(data.alive || 0);
    var rows = [
      ['HTTPS ready', data.web_ready || 0],
      ['Remote DNS', data.dns_ready || 0],
      ['Telegram ready', data.telegram_ready || 0],
      ['Full capability', data.full_capability || 0]
    ];
    var target = document.getElementById('insights-capabilities');
    target.innerHTML = '';
    rows.forEach(function (entry) {
      var row = document.createElement('div');
      row.className = 'insights-capability-row';
      var label = document.createElement('span');
      label.textContent = entry[0];
      var track = document.createElement('div');
      track.className = 'insights-row-bar';
      var fill = document.createElement('i');
      fill.style.width = pct(entry[1], alive) + '%';
      track.appendChild(fill);
      var value = document.createElement('strong');
      value.textContent = pct(entry[1], alive) + '%';
      row.append(label, track, value);
      target.appendChild(row);
    });
  }

  function renderRanking(targetId, rows, total, riskId) {
    var target = document.getElementById(targetId);
    target.innerHTML = '';
    var max = rows.length ? rows[0].count : 1;
    rows.forEach(function (entry, index) {
      var row = document.createElement('div');
      row.className = 'insights-ranking-row';
      var rank = document.createElement('span'); rank.textContent = index + 1;
      var name = document.createElement('span'); name.textContent = entry.country || entry.isp || 'Unknown'; name.title = name.textContent;
      var track = document.createElement('div'); track.className = 'insights-row-bar';
      var fill = document.createElement('i'); fill.style.width = pct(entry.count, max) + '%'; track.appendChild(fill);
      var value = document.createElement('strong'); value.textContent = entry.count;
      row.append(rank, name, track, value); target.appendChild(row);
    });
    if (!rows.length) target.textContent = 'No enriched location data yet.';
    var share = rows.length ? pct(rows[0].count, total) : 0;
    var risk = document.getElementById(riskId);
    risk.textContent = share ? share + '% top share' : 'No data';
    risk.dataset.tone = share > 50 ? 'danger' : (share > 30 ? 'warn' : 'good');
  }

  function render(data) {
    var quality = data.quality || {};
    var freshness = data.freshness || {};
    setText('insights-stable', quality.stable || 0);
    setText('insights-success-rate', (quality.success_rate || 0) + '% of tested inventory');
    setText('insights-web-rate', (quality.web_rate || 0) + '%');
    setText('insights-web-count', (data.web_ready || 0) + ' proxies');
    setText('insights-full-rate', (quality.full_rate || 0) + '%');
    setText('insights-full-count', (data.full_capability || 0) + ' proxies');
    setText('insights-latency', data.avg_speed ? Math.round(data.avg_speed) + ' ms' : 'No data');
    setText('insights-fresh-rate', pct(freshness.under_1h || 0, data.total || 0) + '%');
    setText('insights-fresh-count', (freshness.under_1h || 0) + ' checked within one hour');
    setText('insights-updated', 'Updated ' + new Date().toLocaleTimeString());

    renderHealth(data);
    barRows('insights-freshness', [
      {label: 'Under 1 hour', value: freshness.under_1h || 0, color: 'var(--success)'},
      {label: '1–24 hours', value: freshness.one_to_24h || 0},
      {label: '1–7 days', value: freshness.one_to_7d || 0, color: '#f59e0b'},
      {label: 'Older than 7d', value: freshness.older_7d || 0, color: 'var(--danger)'},
      {label: 'Never checked', value: freshness.never || 0, color: 'var(--muted)'}
    ], data.total || 0);
    var latency = data.latency_bands || {};
    barRows('insights-latency-bands', [
      {label: 'Fast ≤300ms', value: latency.fast || 0, color: 'var(--success)'},
      {label: 'Balanced', value: latency.balanced || 0},
      {label: 'Slow >800ms', value: latency.slow || 0, color: '#f59e0b'},
      {label: 'Unknown', value: latency.unknown || 0, color: 'var(--muted)'}
    ], data.alive || 0);
    var reliability = data.reliability_bands || {};
    barRows('insights-reliability-bands', [
      {label: 'High ≥90%', value: reliability.high || 0, color: 'var(--success)'},
      {label: 'Medium', value: reliability.medium || 0},
      {label: 'Low <60%', value: reliability.low || 0, color: 'var(--danger)'},
      {label: 'Unknown', value: reliability.unknown || 0, color: 'var(--muted)'}
    ], data.alive || 0);
    renderProtocols(data);
    renderCapabilities(data);
    renderRanking('insights-countries', data.by_country || [], data.total || 0, 'insights-country-risk');
    renderRanking('insights-isps', data.by_isp || [], data.total || 0, 'insights-isp-risk');
  }

  async function refresh() {
    setText('insights-updated', 'Loading…');
    try {
      var response = await authFetch('/api/stats');
      var data = await response.json();
      if (!response.ok || data.success === false) throw new Error(data.error || 'Could not load insights');
      render(data);
    } catch (error) {
      setText('insights-updated', 'Failed to load');
      if (typeof showAlert === 'function') showAlert(error.message || String(error), 'Insights unavailable');
    }
  }

  window.InsightsWorkspace = {
    init: function () {
      if (!initialized) initialized = true;
      refresh();
    },
    refresh: refresh
  };
  window.loadStats = refresh;
}());
