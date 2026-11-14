'use strict';
const $ = s => document.querySelector(s);
let csrf = '', cluster = null, busy = false, logsVisible = false, firstLoad = true;
const number = n => Number(n||0).toLocaleString('en-US');
const fmtBytes = v => v == null ? '—' : v >= 1024*1024 ? (v/(1024*1024)).toFixed(1)+' MiB' : v >= 1024 ? (v/1024).toFixed(v%1024===0?0:1)+' KiB' : number(v)+' B';
const safe = s => String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const range = (n,max) => Math.max(0, Math.min(100, max ? n / max * 100 : 0));
let lastManager = null;
const rates = [];
function renderTelemetry(data){
  const m = data.online ? data.metrics : null;
  if(!m){lastManager=null;rates.length=0;for(const id of ['metric-rps','metric-get','metric-set','metric-errors'])$('#'+id).textContent='—';
    $('#metric-requests').textContent='No metrics available';$('#metric-get-count').textContent='0 GET calls';$('#metric-set-count').textContent='0 SET calls';$('#metric-error-count').textContent='Last 10 seconds';$('#metric-p95').textContent='P95 bound: —';$('#metric-sparkline').replaceChildren();return;}
  const manager = data.manager_pid || ('attached:'+data.nodes.map(n=>n.port).join(','));
  if(lastManager!==manager || (rates.length && m.requests_total<rates[rates.length-1].total)){rates.length=0;lastManager=manager;}
  rates.push({rate:m.rps_10s,total:m.requests_total});if(rates.length>30)rates.shift();
  const fmtUs = (n) => n>=1000?(n/1000).toFixed(2)+' ms':n.toFixed(1)+' µs';
  $('#metric-rps').textContent=Number(m.rps_10s).toFixed(2);
  $('#metric-requests').textContent=number(m.requests_total)+' total requests';
  $('#metric-get').textContent=m.get_count?fmtUs(m.get_avg_us):'—';
  $('#metric-set').textContent=m.set_count?fmtUs(m.set_avg_us):'—';
  $('#metric-get-count').textContent=number(m.get_count)+' GET calls';
  $('#metric-set-count').textContent=number(m.set_count)+' SET calls';
  $('#metric-errors').textContent=Number(m.error_rate_10s_pct).toFixed(1)+'%';
  $('#metric-error-count').textContent=number(m.recent_errors)+' errors / '+number(m.recent_requests)+' requests';
  $('#metric-p95').textContent='Lifetime P95 bound: '+(!m.requests_total?'—':m.p95_us_le?'<='+fmtUs(m.p95_us_le):'>1 s');
  const max=Math.max(1,...rates.map(x=>x.rate));
  const graph=$('#metric-sparkline'); graph.replaceChildren();
  for(const item of rates){const bar=document.createElement('div');bar.className='sparkbar';bar.style.height=Math.max(2,100*item.rate/max)+'%';bar.title=item.rate.toFixed(2)+' req/s';graph.appendChild(bar);}
  graph.setAttribute('aria-label','Router throughput, most recent '+rates.length+' samples, current '+m.rps_10s.toFixed(2)+' requests per second');
}

function toast(message, error=false){const el=document.createElement('div');el.className='toast'+(error?' error':'');el.textContent=message;$('#toast-region').appendChild(el);setTimeout(()=>el.remove(),4300)}
async function api(path, data){const result=await fetch(path,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:data===undefined?undefined:JSON.stringify(data),cache:'no-store'});const body=await result.json();if(!result.ok)throw new Error(body.error||'Request failed');return body.data??body;}
function renderNode(n,i){const usage=range(n.used,n.capacity),healthy=n.online&&(!cluster.replication||n.replica_state==='ready');const replica=n.replica==null?'':`<div class="replica-stripe"><span class="replica-label">◈ &nbsp; Replica <strong>:${safe(n.replica)}</strong> · PID ${safe(n.replica_pid)} · ${fmtBytes(n.replica_used)}</span><span class="replica-state ${n.replica_state==='ready'?'':'degraded'}">${safe(n.replica_state||'unknown').toUpperCase()}</span></div>`;return `<article class="node-card"><div class="node-header"><div class="node-name"><div class="server-icon">▤</div><div><strong>Shard ${String(i+1).padStart(2,'0')}</strong><div class="node-meta">Port ${n.port} · PID ${n.pid??'—'}</div></div></div><span class="health-label ${healthy?'':'degraded'}">● &nbsp; ${healthy?'HEALTHY':'DEGRADED'}</span></div><div class="progress-top"><span>Memory utilized</span><strong>${fmtBytes(n.used)} / ${fmtBytes(n.capacity)}</strong></div><div class="track"><div class="fill ${usage>85?'high':''}" style="width:${usage.toFixed(2)}%"></div></div><div class="node-details"><div><div class="detail-k">UTILIZATION</div><div class="detail-v">${usage.toFixed(1)}%</div></div><div><div class="detail-k">RESTARTS</div><div class="detail-v">${n.restarts??0}</div></div><div><div class="detail-k">PROMOTIONS</div><div class="detail-v">${n.promotions??0}</div></div><div><div class="detail-k">OS RSS</div><div class="detail-v">${fmtBytes(n.rss_bytes)}</div></div></div>${replica}</article>`}
function render(data){cluster=data;renderTelemetry(data);const online=data.online;$('#connection').classList.toggle('online',online);$('#connection-label').textContent=online?'Connected':'Offline';$('#last-updated').textContent='Updated '+new Date().toLocaleTimeString();$('#metric-nodes').textContent=online?number(data.node_count):'0';$('#metric-node-sub').textContent=online?`${data.max_nodes} max nodes · ${data.replication?'Replicated':'No replica'}`:'Waiting for cluster';$('#metric-usage').textContent=online?(range(data.total_used,data.total_capacity)).toFixed(1)+'%':'—';$('#metric-usage-sub').textContent=online?`${fmtBytes(data.total_used)} / ${fmtBytes(data.total_capacity)} stored`:'Allocated node capacity';$('#metric-failover').textContent=online?number(data.total_promotions):'—';$('#metric-restarts').textContent=online?number(data.total_restarts):'—';$('#node-count-pill').textContent=online?`${data.node_count} ACTIVE`:'0 NODES';$('#node-cards').innerHTML=online&&data.nodes.length?data.nodes.map(renderNode).join(''):'<div class="empty-state"><div class="empty-symbol">◇</div><strong>No active cluster</strong><p>Start a cluster below or connect to an existing manager on port 7001.</p></div>';
$('#start-btn').disabled=online||busy;$('#stop-btn').disabled=!data.owned||busy;$('#resize-btn').disabled=!online||busy;$('#run-command').disabled=!online||busy;$('#control-note').textContent=online?(data.owned?'Cluster started by this dashboard. Stop to change startup limits.':'Attached to an external manager. Stop it from its original terminal to change startup limits.'):'Startup settings can be adjusted below.';
const select=$('#resize-node'),prior=select.value;select.innerHTML='<option value="">Select a node</option>'+data.nodes.map((n,i)=>`<option value="${n.port}">Shard ${i+1} · :${n.port} · ${fmtBytes(n.capacity)}</option>`).join('');if(data.nodes.some(n=>String(n.port)===prior))select.value=prior;
$('#event-feed').innerHTML=data.events?.length?data.events.map(e=>`<div class="event-row"><span class="event-time">${safe(e.time)}</span><span class="event-desc">${safe(e.message)}</span></div>`).join(''):'<p class="muted">No events yet.</p>';
if(firstLoad){firstLoad=false;const cfg=data.config;for(const k of ['capacity','max_nodes','threshold','replicas']){const input=$(`[name="${k}"]`);if(input&&cfg[k]!==undefined)input.value=cfg[k]}}
}
async function refresh(){if(busy)return;try{render(await api('/api/status'))}catch(err){console.error(err);$('#last-updated').textContent='Connection error'}}
function withAction(task){return async event=>{event?.preventDefault();if(busy)return;busy=true;try{await task()}catch(err){toast(err.message,true)}finally{busy=false;await refresh()}}}
$('#start-form').addEventListener('submit',withAction(async()=>{const f=new FormData($('#start-form'));const cfg={capacity:Number(f.get('capacity')),max_nodes:Number(f.get('max_nodes')),threshold:Number(f.get('threshold')),replicas:Number(f.get('replicas'))};await api('/api/start',cfg);toast('Cluster started successfully')}));
$('#stop-btn').addEventListener('click',withAction(async()=>{if(!confirm('Stop the cluster managed by this dashboard? Existing data stays on disk.'))return;await api('/api/stop',{});toast('Cluster stopped')}));
$('#resize-form').addEventListener('submit',withAction(async()=>{const f=new FormData($('#resize-form'));await api('/api/resize',{port:Number(f.get('port')),capacity:Number(f.get('capacity'))});toast('Node capacity increased')}));
$('#key-action').addEventListener('change',()=>{$('#value-field').classList.toggle('hidden',$('#key-action').value!=='SET')});
$('#key-form').addEventListener('submit',withAction(async()=>{const f=new FormData($('#key-form'));const action=f.get('action'),key=f.get('key');const payload={action,key};if(action==='SET')payload.value=f.get('value');const result=await api('/api/key',payload);$('#command-output').textContent=`> ${action} ${key}${action==='SET'?' [value]':''}\n${result.reply}`;toast('Command completed')}));
$('#refresh-btn').addEventListener('click',()=>refresh());$('#scroll-config').addEventListener('click',()=>$('#configure').scrollIntoView({behavior:'smooth'}));
$('#logs-btn').addEventListener('click',async()=>{logsVisible=!logsVisible;$('#log-output').classList.toggle('hidden',!logsVisible);$('#logs-btn').textContent=logsVisible?'Hide logs ↑':'Manager logs ↗';if(logsVisible){try{const result=await api('/api/logs');$('#log-output').textContent=result.lines?.join('\n')||'No manager logs recorded yet.'}catch(err){toast(err.message,true)}}});
for(const link of document.querySelectorAll('.nav-item'))link.addEventListener('click',()=>{document.querySelectorAll('.nav-item').forEach(e=>e.classList.remove('selected'));link.classList.add('selected')});
(async()=>{try{csrf=(await api('/api/session')).csrf;await refresh()}catch(err){toast('Dashboard backend unavailable',true)}setInterval(refresh,2500)})();
