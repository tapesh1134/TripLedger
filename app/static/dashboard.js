'use strict';
const $ = id => document.getElementById(id);
let token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('tripledger-token') || '';
if (token) sessionStorage.setItem('tripledger-token', token);
history.replaceState(null, '', location.pathname);
let selected = null;
let busy = false;
let refreshing = false;
function notice(text) { $('notice').textContent = text; }
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {'X-Session-Token':token, ...options.headers}});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error + (value.problems ? '\n' + value.problems.map(p=>p.field+': '+p.type).join('\n') : ''));
  return value;
}
function text(tag, value, className) {
  const node = document.createElement(tag); node.textContent = value;
  if (className) node.className = className;
  return node;
}
const money = value => value ? `${value.currency} ${value.amount}` : 'Unknown';
function show(job) {
  $('status').textContent = job.status;
  $('empty').hidden = true; $('outcome').hidden = false;
  const result = job.result || {}, d = result.decision || {};
  $('report-title').textContent = job.report_id;
  $('decision').textContent = job.status === 'complete' ? (d.decision || '').replaceAll('_',' ') : ({running:'Review in progress…',incomplete:'Review incomplete',failed:'Review failed',interrupted:'Review interrupted'}[job.status] || job.status);
  $('reason').textContent = job.status === 'running' ? 'The model is gathering evidence and validating its proposal. You can leave this tab open; the server must keep running.' : (d.reason || job.error || 'Validated proposal · not submitted to the queue');
  $('reimbursable').textContent = money(d.reimbursable_total); $('disallowed').textContent = money(d.disallowed_total);
  const meta = d.meta;
  $('performance').textContent = meta ? `${meta.steps} steps · ${(meta.latency_ms/1000).toFixed(1)} seconds · ${meta.tokens_in ?? 'unknown'} input / ${meta.tokens_out ?? 'unknown'} output tokens` : '';
  $('findings').replaceChildren();
  if (!d.findings?.length) $('findings').append(text('p', job.status === 'complete' ? 'No findings.' : 'No completed findings available.', 'muted'));
  for (const finding of d.findings || []) {
    const box = text('div', '', 'finding');
    box.append(text('strong', `${finding.rule_id} · ${finding.line_id || 'Report'} · ${finding.severity}`),text('p',finding.observed),text('p','Policy: '+finding.permitted));
    const details = document.createElement('details'); details.append(text('summary','Evidence references'));
    for (const ref of finding.evidence || []) details.append(text('p', `${ref.source}: ${ref.ref}`));
    box.append(details); $('findings').append(box);
  }
  $('reconciliation').replaceChildren();
  for (const line of d.reconciliation || []) {
    const row = document.createElement('tr');
    for (const value of [line.line_id,line.status,line.transaction_id ?? '—',line.delta ?? '—']) row.append(text('td',value));
    $('reconciliation').append(row);
  }
  $('draft').textContent = d.draft_query_to_submitter || 'No draft query available.';
  $('result-download').disabled = !job.result;
  $('trace-download').disabled = !job.result;
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const jobs = await api('/api/jobs');
    busy = jobs.some(j => j.status === 'running'); $('submit').disabled = busy;
    $('history').replaceChildren();
    if (!jobs.length) $('history').append(text('p','No reviews yet.', 'muted'));
    for (const job of jobs) {
      const button = text('button','','history-item'); const description = text('span',job.report_id);
      description.append(text('small',new Date(job.created_at).toLocaleString()));
      button.append(description,text('span',job.status,'pill'));
      button.onclick = () => { selected = job.id; show(job); }; $('history').append(button);
    }
    if (selected) { const job = jobs.find(j=>j.id===selected); if (job) show(job); }
  } catch (error) { notice(error.message); } finally { refreshing = false; }
}
$('load').onclick = async () => {
  try { $('report').value = JSON.stringify(await api('/api/examples/'+$('example').value),null,2); notice(''); } catch (error) { notice(error.message); }
};
$('file').onchange = async event => {
  const file = event.target.files[0]; if (!file) return;
  if (file.size > 1024*1024) { notice('Report must be no larger than 1 MiB.'); return; }
  $('report').value = await file.text(); notice('');
};
$('submit').onclick = async () => {
  if (busy) return;
  try {
    JSON.parse($('report').value); // Check syntax without rewriting exact decimal amounts.
    busy = true; $('submit').disabled = true; notice('');
    const job = await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:$('report').value});
    selected = job.id; show(job);
  } catch (error) { notice(error.message); } finally { await refresh(); }
};
async function download(name) {
  if (!selected) return;
  try {
    const value = await api(`/api/jobs/${selected}/${name}`);
    const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
    const a = document.createElement('a'); a.href = url; a.download = selected+'-'+name; a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  } catch (error) { notice(error.message); }
}
$('result-download').onclick = () => download('result.json');
$('trace-download').onclick = () => download('trace.json');
$('refresh').onclick = refresh;
refresh();
setInterval(refresh,2500);
