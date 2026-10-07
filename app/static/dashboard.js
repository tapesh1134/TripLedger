'use strict';
const $ = id => document.getElementById(id);
let token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('tripledger-token') || '';
if (token) sessionStorage.setItem('tripledger-token', token);
history.replaceState(null, '', location.pathname);
let selected = null;
let busy = false;
let refreshing = false;
let submitting = false;
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
    busy = jobs.some(j => j.status === 'running'); $('submit').disabled = busy || submitting;
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
let rowSequence = 0;
let submittedAt = new Date().toISOString();
const reportFields = {'report-id':'report_id','employee-id':'employee_id','trip-id':'trip_id','base-currency':'base_currency'};
function field(card, name, label, value, options = {}) {
  const box = document.createElement('div');
  const input = document.createElement(options.choices ? 'select' : 'input');
  input.id = `expense-${rowSequence}-${name}`; input.dataset.field = name;
  if (options.choices) for (const [v, caption] of options.choices) {
    const option = text('option', caption); option.value = v; input.append(option);
  }
  else { input.type = options.type || 'text'; input.required = !!options.required;
    for (const key of ['pattern','maxLength','min','max','step','placeholder']) if (options[key] !== undefined) input[key] = options[key];
    if (options.list) input.setAttribute('list', options.list);
    if (options.decimal) input.inputMode = 'decimal';
  }
  input.value = value ?? '';
  const caption = text('label', label + (options.required ? ' *' : '')); caption.htmlFor = input.id;
  box.append(caption,input); card.append(box); return input;
}
const decimalOptions = {pattern:'[0-9]{1,18}(\\.[0-9]{1,6})?', decimal:true, placeholder:'0.00'};
function localDate() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
}
function addLine(value = {}) {
  rowSequence++;
  const card = text('fieldset','','expense-card');
  card.append(text('legend','Expense'));
  const grid = text('div','','field-grid'); card.append(grid);
  const used = new Set([...document.querySelectorAll('[data-field="line_id"]')].map(n=>n.value));
  let n = 1; while (used.has(`L${n}`)) n++;
  field(grid,'line_id','Line ID',value.line_id ?? `L${n}`,{required:true,maxLength:100});
  field(grid,'date','Expense date',value.date ?? localDate(),{type:'date',required:true});
  field(grid,'merchant','Merchant',value.merchant,{required:true,placeholder:'Who did you pay?'});
  field(grid,'category','Category',value.category,{required:true,list:'categories',placeholder:'Choose or type a category'});
  field(grid,'amount','Amount',value.amount,{...decimalOptions,required:true});
  field(grid,'currency','Currency',value.currency ?? $('base-currency').value,{required:true,pattern:'[A-Za-z]{3}',maxLength:3,list:'currencies'});
  field(card,'description','Business purpose',value.description,{placeholder:'What was this expense for?'});
  field(card,'receipt_file','Receipt path (optional)',value.receipt_file,{placeholder:'samples/sample-taxi.png'});
  card.append(text('p','Use an existing file under the project receipts folder. This field does not upload files.','fine'));
  const details = document.createElement('details'); details.append(text('summary','Hotel and meal details (optional)'));
  const extra = text('div','','field-grid'); details.append(extra);card.append(details);
  field(extra,'hotel_nights','Hotel nights',value.hotel_nights,{type:'number',min:1,max:365,step:1});
  field(extra,'attendee_count','Meal attendees',value.attendee_count,{type:'number',min:1,max:1000,step:1});
  field(extra,'is_client_dinner','Client dinner',value.is_client_dinner == null ? '' : String(value.is_client_dinner),{choices:[['','Not specified'],['true','Yes'],['false','No']]});
  field(extra,'alcohol_amount','Alcohol amount',value.alcohol_amount,decimalOptions);
  details.open = ['hotel_nights','attendee_count','is_client_dinner','alcohol_amount'].some(k=>value[k]!=null);
  const remove = text('button','Remove expense','remove-line'); remove.type = 'button';
  remove.onclick = () => { card.remove(); updateRows(); preview(); $('add-line').focus(); }; card.append(remove);
  $('expense-lines').append(card); updateRows();preview(); return card;
}
function updateRows() {
  const cards = [...$('expense-lines').children];
  cards.forEach((card,i)=>{card.querySelector('legend').textContent=`Expense ${i+1}`;card.querySelector('.remove-line').disabled=cards.length===1;});
  $('line-count').textContent = `${cards.length} expense${cards.length===1?'':'s'}`;
}
function reportValue() {
  const report = {submitted_at:submittedAt};
  for (const [id,key] of Object.entries(reportFields)) report[key] = $(id).value.trim();
  report.base_currency = report.base_currency.toUpperCase();
  report.line_items = [...$('expense-lines').children].map(card=>{
    const line = {};
    for (const input of card.querySelectorAll('[data-field]')) {
      const key = input.dataset.field, value = input.value.trim();
      if (['hotel_nights','attendee_count'].includes(key)) {if(value) line[key]=Number(value);}
      else if (key==='is_client_dinner') {if(value) line[key]=value==='true';}
      else if (key==='alcohol_amount') {if(value) line[key]=value;}
      else line[key] = key==='receipt_file' ? value || null : key==='currency' ? value.toUpperCase() : value;
    }
    return line;
  }); return report;
}
function preview() { $('report').value = JSON.stringify(reportValue(),null,2); }
function validateForm() {
  const ids = [...document.querySelectorAll('[data-field="line_id"]')];
  ids.forEach(input=>input.setCustomValidity(ids.filter(other=>other.value.trim()===input.value.trim()).length>1 ? 'Each expense needs a different line ID.' : ''));
  for (const input of $('expense-form').querySelectorAll('input[required]:not([data-field="line_id"])')) input.setCustomValidity(input.value.trim() ? '' : 'Please fill in this field.');
  for (const input of $('expense-form').querySelectorAll('[data-field="amount"], [data-field="alcohol_amount"]')) {
    const parts = input.value.split('.');
    const digits = (parts[0].replace(/^0+/, '') + (parts[1] || '').replace(/0+$/, '')).length;
    input.setCustomValidity(digits > 18 ? 'Use no more than 18 significant decimal digits.' : '');
  }
  for (const input of $('expense-form').querySelectorAll('input:invalid')) {
    let parent=input.parentElement;while(parent){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}
  }
  return $('expense-form').reportValidity();
}
function populate(report) {
  if (!report || !Array.isArray(report.line_items) || !report.line_items.length || report.line_items.some(line=>!line || typeof line!=='object')) throw new Error('Choose a report JSON with at least one expense in line_items.');
  for (const [id,key] of Object.entries(reportFields)) $(id).value = report[key] ?? '';
  submittedAt = report.submitted_at || new Date().toISOString();
  $('expense-lines').replaceChildren(); report.line_items.forEach(addLine); preview();
  notice('Report loaded. Check the fields, then start your review.');
}
$('load').onclick = async () => { try {populate(await api('/api/examples/'+$('example').value));} catch(error){notice(error.message);} };
$('file').onchange = async event => {
  const file = event.target.files[0]; if(!file) return;
  try { if(file.size>1024*1024) throw new Error('Report must be no larger than 1 MiB.'); populate(JSON.parse(await file.text())); }
  catch(error){notice(error.message);} finally{event.target.value='';}
};
$('add-line').onclick = () => {const card=addLine();card.querySelector('[data-field="merchant"]').focus();};
$('expense-form').noValidate = true;
$('expense-form').oninput = event => {if(event.target.setCustomValidity)event.target.setCustomValidity('');preview();};
$('expense-form').onchange = preview;
$('expense-form').onsubmit = async event => {
  event.preventDefault(); if(busy || submitting || !validateForm()) return;
  try {
    submitting = true; $('submit').disabled = true; notice('');
    submittedAt = new Date().toISOString(); preview();
    const job = await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:$('report').value});
    selected = job.id; show(job);
  } catch(error){notice(error.message);} finally{submitting=false;$('submit').disabled=busy;await refresh();}
};
function saveJSON(value, filename) {
  const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('request-download').onclick = () => {if(validateForm())saveJSON(reportValue(),'expense-report.json');};
addLine();
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
