'use strict';
const $ = s => document.querySelector(s);
let csrf = '', cluster = null, busy = false, logsVisible = false, firstLoad = true;
let lastLifetimePolicy = undefined;
const number = n => Number(n || 0).toLocaleString('en-US');
const fmtBytes = v => v == null ? '—' : v >= 1024 * 1024 ? (v / (1024 * 1024)).toFixed(1) + ' MiB' : v >= 1024 ? (v / 1024).toFixed(v % 1024 === 0 ? 0 : 1) + ' KiB' : number(v) + ' B';
const safe = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const range = (n, max) => Math.max(0, Math.min(100, max ? n / max * 100 : 0));
let lastManager = null;
const rates = [];
function renderTelemetry(data) {
  const m = data.online ? data.metrics : null;
  if (!m) {
    lastManager = null;
    rates.length = 0;
    for (const id of ['metric-rps', 'metric-get', 'metric-set', 'metric-errors']) {
      $('#' + id).textContent = '—';
    }
    $('#metric-requests').textContent = 'No metrics available';
    $('#metric-get-count').textContent = '0 GET calls';
    $('#metric-set-count').textContent = '0 SET calls';
    $('#metric-error-count').textContent = 'Last 10 seconds';
    $('#metric-p95').textContent = 'P95 bound: —';
    $('#metric-sparkline').replaceChildren();
    return;
  }
  const manager = data.manager_pid || ('attached:' + data.nodes.map(n => n.port).join(','));
  if (lastManager !== manager || (rates.length && m.requests_total < rates[rates.length - 1].total)) { rates.length = 0; lastManager = manager; }
  rates.push({ rate: m.rps_10s, total: m.requests_total }); if (rates.length > 30) rates.shift();
  const fmtUs = (n) => n >= 1000 ? (n / 1000).toFixed(2) + ' ms' : n.toFixed(1) + ' µs';
  $('#metric-rps').textContent = Number(m.rps_10s).toFixed(2);
  $('#metric-requests').textContent = number(m.requests_total) + ' total requests';
  $('#metric-get').textContent = m.get_count ? fmtUs(m.get_avg_us) : '—';
  $('#metric-set').textContent = m.set_count ? fmtUs(m.set_avg_us) : '—';
  $('#metric-get-count').textContent = number(m.get_count) + ' GET calls';
  $('#metric-set-count').textContent = number(m.set_count) + ' SET calls';
  $('#metric-errors').textContent = Number(m.error_rate_10s_pct).toFixed(1) + '%';
  $('#metric-error-count').textContent = number(m.recent_errors) + ' errors / ' + number(m.recent_requests) + ' requests';
  $('#metric-p95').textContent = 'Lifetime P95 bound: ' + (!m.requests_total ? '—' : m.p95_us_le ? '<=' + fmtUs(m.p95_us_le) : '>1 s');
  const max = Math.max(1, ...rates.map(x => x.rate));
  const graph = $('#metric-sparkline'); graph.replaceChildren();
  for (const item of rates) { const bar = document.createElement('div'); bar.className = 'sparkbar'; bar.style.height = Math.max(2, 100 * item.rate / max) + '%'; bar.title = item.rate.toFixed(2) + ' req/s'; graph.appendChild(bar); }
  graph.setAttribute('aria-label', 'Router throughput, most recent ' + rates.length + ' samples, current ' + m.rps_10s.toFixed(2) + ' requests per second');
}

function toast(message, error = false) {
  const element = document.createElement('div');
  element.className = 'toast' + (error ? ' error' : '');
  element.textContent = message;
  $('#toast-region').appendChild(element);
  setTimeout(() => element.remove(), 4300);
}

async function api(path, data) {
  const hasBody = data !== undefined;
  const response = await fetch(path, {
    method: hasBody ? 'POST' : 'GET',
    headers: hasBody ? { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf } : {},
    body: hasBody ? JSON.stringify(data) : undefined,
    cache: 'no-store',
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Request failed');
  return body.data ?? body;
}

function renderNode(node, index) {
  const utilization = range(node.used, node.capacity);
  const healthy = node.online && (!cluster.replication || node.replica_state === 'ready');
  const replica = node.replica == null ? '' : `
    <div class="replica-stripe">
      <span class="replica-label">◈ &nbsp; Replica <strong>:${safe(node.replica)}</strong> · PID ${safe(node.replica_pid)} · ${fmtBytes(node.replica_used)}</span>
      <span class="replica-state ${node.replica_state === 'ready' ? '' : 'degraded'}">${safe(node.replica_state || 'unknown').toUpperCase()}</span>
    </div>`;

  return `
    <article class="node-card">
      <div class="node-header">
        <div class="node-name">
          <div class="server-icon">▤</div>
          <div><strong>Shard ${String(index + 1).padStart(2, '0')}</strong><div class="node-meta">Port ${node.port} · PID ${node.pid ?? '—'}</div></div>
        </div>
        <span class="health-label ${healthy ? '' : 'degraded'}">● &nbsp; ${healthy ? 'HEALTHY' : 'DEGRADED'}</span>
      </div>
      <div class="progress-top"><span>Memory utilized</span><strong>${fmtBytes(node.used)} / ${fmtBytes(node.capacity)}</strong></div>
      <div class="track"><div class="fill ${utilization > 85 ? 'high' : ''}" style="width:${utilization.toFixed(2)}%"></div></div>
      <div class="node-details">
        <div><div class="detail-k">UTILIZATION</div><div class="detail-v">${utilization.toFixed(1)}%</div></div>
        <div><div class="detail-k">RESTARTS</div><div class="detail-v">${node.restarts ?? 0}</div></div>
        <div><div class="detail-k">PROMOTIONS</div><div class="detail-v">${node.promotions ?? 0}</div></div>
        <div><div class="detail-k">OS RSS</div><div class="detail-v">${fmtBytes(node.rss_bytes)}</div></div>
      </div>
      ${replica}
    </article>`;
}

function render(data) {
cluster = data; renderTelemetry(data); const online = data.online; $('#connection').classList.toggle('online', online); $('#connection-label').textContent = online ? 'Connected' : 'Offline'; $('#last-updated').textContent = 'Updated ' + new Date().toLocaleTimeString(); $('#metric-nodes').textContent = online ? number(data.node_count) : '0'; $('#metric-node-sub').textContent = online ? `${data.max_nodes} max nodes · ${data.replication ? 'Replicated' : 'No replica'}` : 'Waiting for cluster'; $('#metric-usage').textContent = online ? (range(data.total_used, data.total_capacity)).toFixed(1) + '%' : '—'; $('#metric-usage-sub').textContent = online ? `${fmtBytes(data.total_used)} / ${fmtBytes(data.total_capacity)} stored` : 'Allocated node capacity'; $('#metric-failover').textContent = online ? number(data.total_promotions) : '—'; $('#metric-restarts').textContent = online ? number(data.total_restarts) : '—'; $('#node-count-pill').textContent = online ? `${data.node_count} ACTIVE` : '0 NODES'; $('#node-cards').innerHTML = online && data.nodes.length ? data.nodes.map(renderNode).join('') : '<div class="empty-state"><div class="empty-symbol">◇</div><strong>No active cluster</strong><p>Start a cluster below or connect to an existing manager on port 7001.</p></div>';
  $('#default-ttl-save').disabled = !online || busy; $('#backup-create').disabled = online || busy; $('#backup-restore').disabled = online || busy; $('#start-btn').disabled = online || busy; $('#stop-btn').disabled = !data.owned || busy; $('#resize-btn').disabled = !online || busy; $('#run-command').disabled = !online || busy; $('#browser-save').disabled = !online || busy; $('#browser-apply-ttl').disabled = !online || !browserSelection || busy; $('#browser-delete').disabled = !online || !browserSelection || busy; $('#browser-prev').disabled = !online || browserHistory.length === 0; $('#browser-next').disabled = !online || browserNext === '-'; $('#browser-refresh').disabled = !online || busy; $('#browser-search-form').querySelector('button').disabled = !online || busy; $('#control-note').textContent = online ? (data.owned ? 'Cluster started by this dashboard. Stop to change startup limits.' : 'Attached to an external manager. Stop it from its original terminal to change startup limits.') : 'Startup settings can be adjusted below.';
  if (online && data.default_ttl !== lastLifetimePolicy) {
    lastLifetimePolicy = data.default_ttl;
    const s = $('#default-ttl-mode');
    if (data.default_ttl === null) s.value = 'never';
    else if ([300, 3600, 86400].includes(data.default_ttl)) s.value = String(data.default_ttl);
    else { s.value = 'custom'; $('#default-ttl-custom').value = String(data.default_ttl); }
    updateLifetimeFields();
  }
  const select = $('#resize-node'), prior = select.value; select.innerHTML = '<option value="">Select a node</option>' + data.nodes.map((n, i) => `<option value="${n.port}">Shard ${i + 1} · :${n.port} · ${fmtBytes(n.capacity)}</option>`).join(''); if (data.nodes.some(n => String(n.port) === prior)) select.value = prior;
  $('#event-feed').innerHTML = data.events?.length ? data.events.map(e => `<div class="event-row"><span class="event-time">${safe(e.time)}</span><span class="event-desc">${safe(e.message)}</span></div>`).join('') : '<p class="muted">No events yet.</p>';
  if (firstLoad) { firstLoad = false; const cfg = data.config; for (const k of ['capacity', 'max_nodes', 'threshold', 'replicas']) { const input = $(`[name="${k}"]`); if (input && cfg[k] !== undefined) input.value = cfg[k] } }
}
async function refreshBackups() {
  try {
    const data = await api('/api/backups'); const selected = $('#backup-select').value;
    const options = data.items || [];
    $('#backup-select').innerHTML = '<option value="">Choose a saved backup</option>' + options.map(b => `<option value="${safe(b.name)}">${safe(b.name)} · ${fmtBytes(b.archive_bytes)}</option>`).join('');
    if (options.some(b => b.name === selected)) $('#backup-select').value = selected;
    $('#backup-feedback').textContent = options.length ? `${options.length} backup(s) available. Cluster must be stopped for create/restore.` : 'No backups yet. Stop cluster to create one.';
  } catch (err) { $('#backup-feedback').textContent = 'Could not list backups: ' + err.message; }
}
async function refresh() {
  if (busy) return;
  try {
    render(await api('/api/status'));
  } catch (error) {
    console.error(error);
    $('#last-updated').textContent = 'Connection error';
  }
}

function withAction(task) {
  return async event => {
    event?.preventDefault();
    if (busy) return;

    const wasOnline = !!cluster?.online;
    busy = true;
    try {
      await task();
    } catch (error) {
      toast(error.message, true);
    } finally {
      busy = false;
      await refresh();
      if (cluster?.online && !wasOnline) {
        browserScan('-', []).catch(error => toast(error.message, true));
      }
      if (!cluster?.online) {
        $('#browser-list').innerHTML = '<div class="browser-placeholder">Start the cluster to browse keys.</div>';
      }
    }
  };
}

$('#start-form').addEventListener('submit', withAction(async () => { const f = new FormData($('#start-form')); const cfg = { capacity: Number(f.get('capacity')), max_nodes: Number(f.get('max_nodes')), threshold: Number(f.get('threshold')), replicas: Number(f.get('replicas')) }; await api('/api/start', cfg); toast('Cluster started successfully') }));
$('#stop-btn').addEventListener('click', withAction(async () => { if (!confirm('Stop the cluster managed by this dashboard? Existing data stays on disk.')) return; await api('/api/stop', {}); toast('Cluster stopped') }));
$('#resize-form').addEventListener('submit', withAction(async () => { const f = new FormData($('#resize-form')); await api('/api/resize', { port: Number(f.get('port')), capacity: Number(f.get('capacity')) }); toast('Node capacity increased') }));
function updateLifetimeFields() {
  $('#default-ttl-custom-field').classList.toggle('hidden', $('#default-ttl-mode').value !== 'custom');
  $('#console-ttl-custom-field').classList.toggle('hidden', $('#console-ttl-mode').value !== 'custom' || $('#key-action').value !== 'SET');
}
function selectedTTL(mode, custom) {
  const value = mode.value;
  if (value === 'default' || value === 'keep' || value === 'never') return { ttl_mode: value };
  const seconds = value === 'custom' ? Number(custom.value) : Number(value);
  if (!Number.isSafeInteger(seconds) || seconds < 1 || seconds > 3153600000) throw Error('TTL must be 1..3153600000 seconds');
  return { ttl_mode: 'seconds', ttl_seconds: seconds };
}
$('#default-ttl-mode').addEventListener('change', updateLifetimeFields);
$('#console-ttl-mode').addEventListener('change', updateLifetimeFields);
$('#ttl-policy-form').addEventListener('submit', withAction(async () => {
  const mode = $('#default-ttl-mode').value;
  const seconds = mode === 'custom' ? Number($('#default-ttl-custom').value) : Number(mode);
  const result = await api('/api/ttl-policy', mode === 'never' ? { mode: 'never' } : { mode: 'seconds', seconds });
  toast('Cache default TTL updated');
  lastLifetimePolicy = undefined;
}));
$('#key-action').addEventListener('change', () => {
  const isSet = $('#key-action').value === 'SET';
  $('#value-field').classList.toggle('hidden', !isSet);
  $('#console-ttl-field').classList.toggle('hidden', !isSet);
  updateLifetimeFields();
});
$('#key-form').addEventListener('submit', withAction(async () => { const f = new FormData($('#key-form')); const action = f.get('action'), key = f.get('key'); const payload = { action, key }; if (action === 'SET') { payload.value = f.get('value'); Object.assign(payload, selectedTTL($('#console-ttl-mode'), $('#console-ttl-custom'))); } const result = await api('/api/key', payload); $('#command-output').textContent = `> ${action} ${key}${action === 'SET' ? ' [value]' : ''}\n${result.reply}`; toast('Command completed') }));
let browserCursor = '-', browserHistory = [], browserNext = '-', browserSelection = null;
function browserMode() {
  const value = $('#browser-ttl-mode').value;
  if (['default', 'keep', 'never'].includes(value)) return { ttl_mode: value };
  const seconds = value === 'custom' ? Number($('#browser-ttl-custom').value) : Number(value);
  if (!Number.isSafeInteger(seconds) || seconds < 1 || seconds > 3153600000) throw Error('TTL must be a positive whole number of seconds');
  return { ttl_mode: 'seconds', ttl_seconds: seconds };
}
function browserUpdateTTL() {
  const custom = $('#browser-ttl-mode').value === 'custom';
  $('#browser-ttl-custom-field').classList.toggle('hidden', !custom);
  $('#browser-ttl-custom').required = custom;
}
function browserReset() {
  browserSelection = null;
  $('#browser-editor-title').textContent = 'Create a key';
  $('#browser-key').readOnly = false; $('#browser-key').value = ''; $('#browser-value').value = '';
  $('#browser-ttl-mode').value = 'default'; browserUpdateTTL();
  $('#browser-apply-ttl').disabled = true; $('#browser-delete').disabled = true;
  $('#browser-key-info').textContent = 'New keys inherit the cache default unless overridden.';
}
async function browserScan(cursor = '-', history = null) {
  if (!cluster?.online) { $('#browser-list').innerHTML = '<div class="browser-placeholder">Start the cluster to browse keys.</div>'; return; }
  const prefix = $('#browser-prefix').value.trim();
  const result = await api('/api/keys/scan', { cursor, limit: 15, prefix });
  browserCursor = cursor; if (history !== null) browserHistory = history;
  browserNext = result.next_cursor;
  const list = $('#browser-list'); list.replaceChildren();
  if (!result.items.length) { list.innerHTML = '<div class="browser-placeholder">No keys on this page.</div>'; }
  for (const item of result.items) {
    const b = document.createElement('button'); b.type = 'button'; b.className = 'browser-key-row';
    if (browserSelection === item.key) b.classList.add('selected');
    const name = document.createElement('span'); name.className = 'browser-key-name'; name.textContent = item.key;
    const meta = document.createElement('span'); meta.className = 'browser-key-meta';
    meta.textContent = item.ttl === -1 ? 'No expiry' : item.ttl >= 0 ? item.ttl + 's TTL' : 'Expired';
    b.append(name, meta);
    b.addEventListener('click', () => browserOpen(item.key)); list.appendChild(b);
  }
  $('#browser-prev').disabled = browserHistory.length === 0;
  $('#browser-next').disabled = browserNext === '-';
  $('#browser-page-label').textContent = 'Page ' + (browserHistory.length + 1);
}
async function browserOpen(key) {
  try {
    const result = await api('/api/keys/detail', { key });
    if (!result.found) { toast('Key no longer exists', true); await browserScan(browserCursor); return; }
    browserSelection = key;
    $('#browser-key').value = key; $('#browser-key').readOnly = true;
    $('#browser-value').value = result.value; $('#browser-editor-title').textContent = 'Edit key';
    $('#browser-apply-ttl').disabled = false; $('#browser-delete').disabled = false;
    $('#browser-ttl-mode').value = 'keep'; // Do not renew a deadline merely by editing the value.
    browserUpdateTTL();
    $('#browser-key-info').textContent = `Stored on :${result.owner} · ${result.ttl < 0 ? 'No expiration' : result.ttl + ' seconds remaining'}. Saving with Keep preserves the current deadline. Select a different lifetime to override it.`;
    document.querySelectorAll('.browser-key-row').forEach(el => el.classList.toggle('selected', el.querySelector('.browser-key-name').textContent === key));
  } catch (err) { toast(err.message, true) }
}
$('#browser-ttl-mode').addEventListener('change', browserUpdateTTL);
$('#browser-new').addEventListener('click', browserReset);
$('#browser-refresh').addEventListener('click', () => browserScan('-', []).catch(err => toast(err.message, true)));
$('#browser-search-form').addEventListener('submit', e => { e.preventDefault(); browserScan('-', []).catch(err => toast(err.message, true)) });
$('#browser-prev').addEventListener('click', () => { if (!browserHistory.length) return; const h = browserHistory.slice(0, -1); browserScan(browserHistory[browserHistory.length - 1], h).catch(err => toast(err.message, true)) });
$('#browser-next').addEventListener('click', () => { if (browserNext === '-') return; browserScan(browserNext, [...browserHistory, browserCursor]).catch(err => toast(err.message, true)) });
$('#browser-save-form').addEventListener('submit', withAction(async () => {
  const key = $('#browser-key').value, value = $('#browser-value').value;
  await api('/api/keys/save', { key, value, overwrite: browserSelection === key, ...browserMode() });
  toast('Key saved with ' + $('#browser-ttl-mode').selectedOptions[0].textContent.toLowerCase());
  await browserOpen(key); await browserScan('-', []);
}));
$('#browser-apply-ttl').addEventListener('click', withAction(async () => {
  if (!browserSelection) throw Error('Select an existing key first');
  await api('/api/keys/expire', { key: browserSelection, ...browserMode() });
  toast('Expiration updated'); await browserOpen(browserSelection); await browserScan(browserCursor);
}));
$('#browser-delete').addEventListener('click', withAction(async () => {
  if (!browserSelection) throw Error('Select a key first');
  const key = browserSelection;
  if (!confirm('Permanently delete key ' + key + '?')) return;
  await api('/api/keys/delete', { key, confirmation: key });
  browserReset(); toast('Key deleted'); await browserScan('-', []);
}));
$('#backup-refresh').addEventListener('click', () => refreshBackups());
$('#backup-create').addEventListener('click', withAction(async () => {
  const result = await api('/api/backup/create', {});
  await refreshBackups(); $('#backup-select').value = result.name;
  toast('Backup created and verified'); $('#backup-feedback').textContent = 'Saved ' + result.name + ' · ' + result.files + ' files';
}));
$('#backup-verify').addEventListener('click', withAction(async () => {
  const name = $('#backup-select').value; if (!name) throw Error('Choose a backup first');
  const result = await api('/api/backup/verify', { name });
  toast('Backup checksum verification passed'); $('#backup-feedback').textContent = 'Verified ' + name + ' · ' + result.files + ' files';
}));
$('#backup-restore').addEventListener('click', withAction(async () => {
  const name = $('#backup-select').value; if (!name) throw Error('Choose a backup first');
  if ($('#backup-confirm').value.trim() !== 'RESTORE') throw Error('Type RESTORE to confirm');
  if (!confirm('Restore ' + name + '? The cluster must be stopped. Your current cluster-data is moved into backups/ for rollback.')) return;
  const result = await api('/api/backup/restore', { name, confirmation: 'RESTORE' });
  $('#backup-confirm').value = ''; firstLoad = true;
  toast('Backup restored; restart cluster to load restored data');
  $('#backup-feedback').textContent = 'Restored ' + name + '. Previous data preserved at backups/' + result.previous_data;
}));
$('#refresh-btn').addEventListener('click', () => refresh()); $('#scroll-config').addEventListener('click', () => $('#configure').scrollIntoView({ behavior: 'smooth' }));
$('#logs-btn').addEventListener('click', async () => { logsVisible = !logsVisible; $('#log-output').classList.toggle('hidden', !logsVisible); $('#logs-btn').textContent = logsVisible ? 'Hide logs ↑' : 'Manager logs ↗'; if (logsVisible) { try { const result = await api('/api/logs'); $('#log-output').textContent = result.lines?.join('\n') || 'No manager logs recorded yet.' } catch (err) { toast(err.message, true) } } });
for (const link of document.querySelectorAll('.nav-item')) link.addEventListener('click', () => { document.querySelectorAll('.nav-item').forEach(e => e.classList.remove('selected')); link.classList.add('selected') });
(async () => { try { csrf = (await api('/api/session')).csrf; await refresh(); await refreshBackups(); if (cluster?.online) await browserScan('-', []) } catch (err) { toast('Dashboard backend unavailable', true) } setInterval(refresh, 2500) })();
