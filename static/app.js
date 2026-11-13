// ReBrand - plain-language interface. Round 3 adds: impact preview, Plan ahead tab (claim expiry, renewal, dispute learning).
let token = localStorage.getItem('rebrand_token') || '', me = null;
const $ = id => document.getElementById(id);
const safe = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path, method='GET', body=null) {
  const headers = token ? {Authorization:'Bearer '+token} : {};
  if (body && !(body instanceof FormData)) headers['Content-Type']='application/json';
  const r = await fetch('/api'+path,{method,headers,body:body ? body instanceof FormData ? body : JSON.stringify(body) : undefined});
  let value; try{ value = await r.json(); }catch(e){ throw Error('Server error ('+r.status+'). Try again.'); }
  if(!r.ok){
    if(r.status===401 && token){ localStorage.removeItem('rebrand_token'); location.reload(); }
    throw Error(typeof value.detail==='string' ? value.detail : JSON.stringify(value.detail || value));
  }
  return value;
}
async function logout(){ await act(async()=>{ try{ await api('/logout','POST'); }catch(e){} localStorage.removeItem('rebrand_token'); location.reload(); }) }
// Stay signed in across refresh: restore the session on page load.
(async()=>{ if(!token) return; try{ me = await api('/me'); $('login-view').classList.add('hidden'); $('app-view').classList.remove('hidden'); $('whoami').innerHTML=safe(me.name)+' ('+safe(me.role)+') <button onclick="logout()" class="underline">Sign out</button>'; showTab('whatsnew'); }catch(e){ /* api() already cleared a dead token */ } })()
let _busy=false;
async function act(f){if(_busy)return;_busy=true;try{await f()}catch(e){alert(e.message)}finally{_busy=false}}
// On-page question box. Replaces window.prompt(), which some browsers
// (including in-app browsers) block or hide, leaving buttons that do nothing.
function ask(title,help,def,options){return new Promise(res=>{
  $('ask-title').textContent=title;$('ask-help').textContent=help||'';
  const inp=$('ask-input'),sel=$('ask-select');
  if(options){sel.innerHTML=options.map(o=>'<option>'+safe(o)+'</option>').join('');sel.value=def||options[0];sel.classList.remove('hidden');inp.classList.add('hidden')}
  else{inp.value=def||'';inp.classList.remove('hidden');sel.classList.add('hidden')}
  $('ask-box').classList.remove('hidden');$('ask-box').scrollIntoView({block:'nearest'});
  $('ask-ok').onclick=()=>{$('ask-box').classList.add('hidden');res(options?sel.value:inp.value)};
  $('ask-cancel').onclick=()=>{$('ask-box').classList.add('hidden');res(null)};
})}
function quickLogin(role){$('email').value=role+'@demo.test';$('password').value=role+'123';login()}
async function login(){await act(async()=>{
  const v=await api('/login','POST',{email:$('email').value,password:$('password').value});
  token=v.token;me=v.user;localStorage.setItem('rebrand_token',token);
  $('login-view').classList.add('hidden');$('app-view').classList.remove('hidden');
  $('whoami').innerHTML=safe(me.name)+' ('+safe(me.role)+') <button onclick="logout()" class="underline">Sign out</button>';
  showTab('whatsnew');
})}
function showTab(name){
  $('ask-box').classList.add('hidden');
  document.querySelectorAll('.tab-panel').forEach(x=>x.classList.add('hidden'));
  $('tab-'+name).classList.remove('hidden');
  document.querySelectorAll('.tab-btn').forEach(x=>x.classList.toggle('active',x.dataset.tab===name));
  const loaders={blueprint:_loadBlueprint,plan:_loadPlan,review:_loadReview,published:_loadPublished,recovery:_loadRecovery,insights:_loadInsights,activity:_loadActivity};
  if(loaders[name]) loaders[name]().catch(e=>alert(e.message));
}
const sevWord = s => s==='high' ? 'Stop: fix this first' : s==='medium' ? 'Check this' : 'Small fix';
const sevStyle = s => s==='high' ? 'background:#fbe9e4;color:#a32b16' : s==='medium' ? 'background:#f5eeda;color:#7a5c17' : 'background:#eef0e6;color:#1f1c16';
async function _loadBlueprint(){
  const b=await api('/blueprint/current');
  $('bp-version').textContent=b.version ? '(version '+b.version+')' : '(no rules yet)';
  $('bp-current').innerHTML =
    '<h3 class="font-semibold mt-2">Rules</h3><ul class="list-disc ml-5 text-sm space-y-1">' +
    (b.guidelines||[]).map(x=>'<li><b>'+safe(x.title)+':</b> '+safe(x.body)+'</li>').join('') + '</ul>' +
    '<h3 class="font-semibold mt-3">Approved claims</h3><ul class="list-disc ml-5 text-sm space-y-1">' +
    (b.claims||[]).map(x=>'<li>'+safe(x.claim)+(x.expires_on?' <i>(ends '+safe(x.expires_on)+')</i>':'')+'</li>').join('') + '</ul>' +
    '<h3 class="font-semibold mt-3">Words to avoid</h3><p class="text-sm">' +
    (b.terms||[]).map(x=>safe(x.term)+' → '+safe(x.replacement||'remove')).join(' · ') + '</p>' +
    '<h3 class="font-semibold mt-3">Brand colours</h3><div class="flex gap-2 mt-1">' +
    (b.palette||[]).map(c=>'<span style="background:'+safe(c)+';width:36px;height:24px;border-radius:6px;border:1px solid #c9c2ae;display:inline-block" title="'+safe(c)+'"></span>').join('') + '</div>';
  $('bp-guidelines').value=(b.guidelines||[]).map(x=>x.title+': '+x.body).join('\n');
  $('bp-terms').value=(b.terms||[]).map(x=>[x.term,x.kind,x.replacement,x.note].join(' | ')).join('\n');
  $('bp-claims').value=(b.claims||[]).map(x=>[x.claim,x.risk,x.expires_on||''].join(' | ')).join('\n');
  $('bp-palette').value=(b.palette||[]).join(', ');
}
async function saveBlueprint(){await act(async()=>{
  const b=readBlueprintForm();
  // The server requires a matching preview before saving (blast radius first).
  await api('/blueprint/preview','POST',b);
  const v=await api('/blueprint','POST',b);
  $('bp-msg').textContent='Saved as version '+v.version+'. '+v.impacted_published.length+' live post(s) need another look.';
  await _loadBlueprint();
})}
async function uploadGuideline(){await act(async()=>{
  const f=$('bp-file').files[0]; if(!f) throw Error('Choose a file first');
  const form=new FormData(); form.append('file',f);
  const r=await api('/blueprint/upload-guideline','POST',form);
  $('bp-file-text').textContent=r.text;
})}
async function createSubmission(check=false){await act(async()=>{
  const r=await api('/submissions','POST',{title:$('sub-title').value||'Untitled',content_type:$('sub-type').value,channel:$('sub-channel').value,text:$('sub-text').value,alt_text:$('sub-alt').value});
  const f=$('sub-file').files[0];
  if(f){const fd=new FormData();fd.append('file',f);await api('/submissions/'+r.id+'/upload','POST',fd)}
  if(check){
    const res=await api('/submissions/'+r.id+'/check','POST');
    const bad=res.issues.filter(i=>i.severity==='high'&&i.status==='open').length;
    $('sub-result').innerHTML='<div class="rounded p-4 mt-3 text-sm" style="background:'+(bad?'#fbe9e4':'#eef0e6')+'">' +
      (bad ? '<b>'+bad+' thing(s) need fixing before this can be approved.</b>' : '<b>Looks good. Nothing blocking.</b>') +
      ' See the Review tab for the full list.</div>';
    showTab('review');
  } else {
    $('sub-result').innerHTML='<div class="rounded p-4 mt-3 text-sm" style="background:#eef0e6">Draft saved. You can check it later from the Review tab.</div>';
  }
})}
function issueHtml(x, id){
  return `<div class="rounded p-3 mb-2 text-sm sev-${x.severity}" style="background:#fbf9f3;border:1px solid #d6cfbb">
    <span class="badge" style="${sevStyle(x.severity)}">${safe(sevWord(x.severity))}</span>
    <span class="badge">${safe(x.rule_code)}</span>
    ${x.uncertain?'<span class="badge" style="background:#f5eeda">Not sure: a person should check</span>':''}
    <p class="mt-2"><b>What we found:</b> ${safe(x.evidence)}</p>
    <p><b>Why it matters:</b> <i>${safe(x.clause)}</i></p>
    ${x.suggestion?'<p><b>How to fix it:</b> '+safe(x.suggestion)+'</p>':''}
    <p class="mt-1">Status: <b>${safe(x.status)}</b>
    <button class="link ml-2" onclick="accept(${x.id},${id})">I fixed this</button>
    <button class="link ml-2" onclick="dispute(${x.id},${id})">This flag is wrong</button></p></div>`;
}
async function accept(i,id){await act(async()=>{await api('/issues/'+i+'/accept','POST');alert('Noted. Edit the post and run the check again before approval.');await _inspect(id)})}
async function dispute(i,id){await act(async()=>{
  const reason=await ask('Why is this flag wrong?','This goes to the reviewer.');
  if(!reason) return;
  await api('/issues/'+i+'/dispute','POST',{reason}); await _inspect(id);
})}
async function _loadReview(){
  const rows=await api('/submissions');
  $('review-list').innerHTML=rows.length ? '' : '<p class="text-sm" style="color:#6b6557">Nothing to review yet. Write your first post and it will show up here.</p>';
  for(const s of rows){
    const d=document.createElement('div');
    d.className='border rounded p-4'; d.style.borderColor='#d6cfbb'; d.style.background='#fbf9f3';
    const open=(await api('/submissions/'+s.id)).issues.filter(i=>i.status==='open').length;
    d.innerHTML=`<b class="text-lg" style="font-family:&quot;Space Grotesk&quot;,sans-serif">${safe(s.title)}</b>
      <span class="badge">${safe(s.state)}</span><span class="badge">${safe(s.content_type)}</span>
      <p class="text-xs mt-1" style="color:#6b6557">${open} thing(s) still to look at</p>
      <button class="link mr-3" onclick="inspect(${s.id})">Open this post</button>
      <button class="link" onclick="check(${s.id})">Run the check again</button>
      <div id="details-${s.id}"></div>`;
    $('review-list').appendChild(d);
  }
}
async function check(id){await act(async()=>{await api('/submissions/'+id+'/check','POST');await _inspect(id)})}
async function inspect(id){await act(()=>_inspect(id))}
async function _inspect(id){
  const s=await api('/submissions/'+id);
  $('details-'+id).innerHTML=`<p class="text-sm my-2 rounded p-3" style="background:#f2efe7">${safe(s.text)}</p>
    <label class="block text-sm font-medium">Edit the post here
    <textarea id="edit-${id}" class="field mt-1" rows="3">${safe(s.text)}</textarea></label>
    <button class="btn-dark mt-2" onclick="revise(${id})">Save my edit</button>
    <div class="mt-3">${s.issues.filter(x=>x.status!=='resolved').map(x=>issueHtml(x,id)).join('')||'<p class="text-sm" style="color:#1f1c16"><b style="color:#4f6b4a">Nothing wrong found.</b></p>'}</div>
    <div class="flex gap-2 flex-wrap mt-2">
      <button class="btn-primary" onclick="decision(${id},'approve')">Approve</button>
      <button class="btn-outline" onclick="decision(${id},'request_changes')">Ask for changes</button>
      <button class="btn-dark" onclick="publish(${id})">Mark as published</button>
      <button class="btn-outline" onclick="puterTone(${id})">Optional: AI tone review (Puter)</button>
    </div>
    <p id="puter-note-${id}" class="text-xs mt-1" style="color:#6b6557">The AI review is optional and runs in your browser on your own free Puter account. Without it, tone is left to the human reviewer.</p>`;
}
async function revise(id){await act(async()=>{await api('/submissions/'+id,'PATCH',{text:$('edit-'+id).value});await _inspect(id)})}
async function decision(id,action){await act(async()=>{
  let reason='';
  if(action!=='approve'){reason=await ask('What should change?','This is saved for the writer.')||''}
  try{await api('/submissions/'+id+'/decision','POST',{action,reason});}
  catch(e){alert(e.message);return}
  await _loadReview();
})}
async function publish(id){await act(async()=>{
  const url=await ask('Live link','Paste the live link, if you have one. You can leave it blank.','')||'';
  await api('/submissions/'+id+'/publish','POST',{url});
  await _loadReview(); showTab('published');
})}
async function _loadPublished(){
  const rows=await api('/published');
  $('published-list').innerHTML=rows.length ? '' : '<p class="text-sm" style="color:#6b6557">No live posts yet. Approved posts will show up here.</p>';
  for(const x of rows){
    const d=document.createElement('div');
    d.className='border rounded p-4'; d.style.borderColor='#d6cfbb'; d.style.background='#fbf9f3';
    d.innerHTML=`<b>${safe(x.title)}</b> <span class="badge">${safe(x.state)}</span><span class="badge">Rules v${x.blueprint_version}</span>
      <p class="text-sm mt-1">${x.url?'<a class="link" href="'+safe(x.url)+'" target="_blank" rel="noopener">'+safe(x.url)+'</a>':'No link saved'}</p>
      <p class="text-xs mt-1" style="color:#6b6557">Live since ${new Date(x.published_at*1000).toLocaleDateString()}</p>
      <button class="link mr-3" onclick="recheck(${x.id})">Check this post again</button>
      <button class="link" onclick="report(${x.id})">Something is wrong with it</button>
      <div id="pub-${x.id}" class="mt-1 text-sm"></div>`;
    $('published-list').appendChild(d);
  }
}
async function recheck(id){await act(async()=>{
  const r=await api('/published/'+id+'/recheck','POST');
  $('pub-'+id).innerHTML='<b>'+safe(r.verdict)+'</b>'+(r.issues.length?' ('+r.issues.length+' thing(s) found)':'');
  await _loadRecovery();
})}
async function report(id){await act(async()=>{
  const reason=await ask('What is wrong with this live post?','');
  if(!reason) return;
  await api('/published/'+id+'/report','POST',{reason});
  showTab('recovery');
})}
async function _loadRecovery(){
  const rows=await api('/recovery');
  $('recovery-list').innerHTML=rows.length ? '' : '<p class="text-sm" style="color:#6b6557">No posts to fix right now. That is good news.</p>';
  for(const x of rows){
    const d=document.createElement('div');
    d.className='border rounded p-4'; d.style.borderColor='#d6cfbb'; d.style.background='#fbf9f3';
    d.innerHTML=`<b>${safe(x.title)}</b> <span class="badge">${safe(x.state)}</span>
      <p class="text-sm mt-1">${safe(x.reason)}</p>
      <p class="text-xs mt-1" style="color:#6b6557">Found ${new Date(x.detected_at*1000).toLocaleDateString()}${x.owner_name?' · Owner: '+safe(x.owner_name):''}${x.deadline?' · Due: '+safe(x.deadline):''}${x.action?' · Planned fix: '+safe(x.action):''}${x.correction_note?' · Fix: '+safe(x.correction_note):''}</p>
      <div class="flex gap-2 flex-wrap mt-2">
        <button class="link" onclick="propose(${x.id})">Suggest a fix</button>
        <button class="link" onclick="recoveryAction(${x.id},'approve-action')">Approve the fix</button>
        <button class="link" onclick="markCorrected(${x.id})">I fixed the live post</button>
        <button class="link" onclick="recoveryAction(${x.id},'close')">Check again and close</button>
      </div>`;
    $('recovery-list').appendChild(d);
  }
}
async function propose(id){await act(async()=>{
  const action=await ask('What should we do?','Pick the fix for this post.','edit',['edit','replace','correction_note','unpublish']);
  if(!action) return;
  await api('/recovery/'+id+'/propose','POST',{action});
  await _loadRecovery();
})}
async function markCorrected(id){await act(async()=>{
  const correction_note=await ask('What did you actually change on the live post?','Write it in your own words. This is a human confirmation, not an automatic check.');
  if(!correction_note) return;
  await api('/recovery/'+id+'/mark-corrected','POST',{correction_note});
  await _loadRecovery();
})}
async function recoveryAction(id,action){await act(async()=>{await api('/recovery/'+id+'/'+action,'POST');await _loadRecovery()})}
async function _loadInsights(){
  const d=await api('/insights');
  const list=(arr,fn)=>arr.length?'<ul class="list-disc ml-5 text-sm space-y-1">'+arr.map(fn).join('')+'</ul>':'<p class="text-sm" style="color:#6b6557">Nothing yet.</p>';
  $('insights-body').innerHTML=`
    <div class="grid sm:grid-cols-2 gap-4">
      <div class="rounded p-4" style="background:#fbf9f3;border:1px solid #d6cfbb"><h3 class="font-semibold mb-2">What keeps going wrong</h3>${list(d.repeat_issues,x=>'<li>'+safe(x.rule_code)+': '+x.n+' time(s)</li>')}</div>
      <div class="rounded p-4" style="background:#fbf9f3;border:1px solid #d6cfbb"><h3 class="font-semibold mb-2">Rules people keep questioning</h3>${list(d.disputed_rules,x=>'<li>'+safe(x.rule_code)+': disputed '+x.n+' time(s)</li>')}${d.unclear_guideline_signals.length?'<p class="text-sm mt-2" style="color:#7a5c17">These rules may need clearer wording.</p>':''}</div>
      <div class="rounded p-4" style="background:#fbf9f3;border:1px solid #d6cfbb"><h3 class="font-semibold mb-2">How fast things get approved</h3><p class="text-sm">Average: ${d.avg_time_to_approve_hours} hour(s).</p>${list(d.approval_actions,x=>'<li>'+safe(x.action)+': '+x.n+'</li>')}</div>
      <div class="rounded p-4" style="background:#fbf9f3;border:1px solid #d6cfbb"><h3 class="font-semibold mb-2">Fixing live posts</h3>${list(d.recovery_by_state,x=>'<li>'+safe(x.state)+': '+x.n+'</li>')}<p class="text-sm mt-1">Average days to fix: ${d.avg_days_to_close} (${d.closed_recoveries} fixed).</p><p class="text-sm">Still unsure, waiting for a person: ${d.open_evidence_debt}</p></div>
    </div>`;
}
async function memoryCheck(){await act(async()=>{
  if(!$('sub-title').value.trim()&&!$('sub-text').value.trim()){$('memory-result').innerHTML='<p class="text-sm mt-2">Enter a title or draft text to compare.</p>';return}
  const result=await api('/memory/check','POST',{title:$('sub-title').value,text:$('sub-text').value});
  const items=result.matches.map(x=>`<article class="rounded p-4 my-2" style="background:#fbf9f3;border:1px solid #d6cfbb">
    <b style="font-family:&quot;Space Grotesk&quot;,sans-serif">${safe(x.title)}</b> · last posted ${new Date(x.published_at*1000).toLocaleDateString()}
    <p class="text-sm mt-1">It said: “${safe(x.previous_text)}”</p>
    <p class="text-xs mt-1" style="color:#6b6557">Same topic words: ${safe(x.shared_terms.join(', '))}</p>
    ${x.possible_numeric_change?`<p class="text-sm font-semibold" style="color:#7a5c17">The numbers may have changed: before ${safe(x.previous_numbers.join(', '))}; in your draft ${safe(x.draft_numbers.join(', '))}. Please check the real numbers before publishing.</p>`:''}
    <p class="text-sm">${safe(x.verification_note)}</p></article>`).join('');
  $('memory-result').innerHTML='<h3 class="font-semibold mt-4" style="font-family:&quot;Space Grotesk&quot;,sans-serif">Older posts on this topic</h3><p class="text-xs" style="color:#6b6557">'+safe(result.note)+'</p>'+(items||'<p class="text-sm mt-2">No older posts on this topic. You are starting fresh.</p>');
})}

function readBlueprintForm(){
  const lines=id=>$(id).value.split('\n').map(x=>x.trim()).filter(Boolean);
  return {note:$('bp-note').value,
    guidelines:lines('bp-guidelines').map(x=>{const n=x.indexOf(':');return {title:n>=0?x.slice(0,n):'Rule',body:n>=0?x.slice(n+1).trim():x}}),
    terms:lines('bp-terms').map(x=>{const a=x.split('|').map(s=>s.trim());return {term:a[0],kind:a[1],replacement:a[2]||'',note:a[3]||''}}),
    claims:lines('bp-claims').map(x=>{const a=x.split('|').map(s=>s.trim());return {claim:a[0],risk:a[1]||'medium',expires_on:a[2]||null}}),
    palette:$('bp-palette').value.split(',').map(x=>x.trim()).filter(Boolean)};
}
async function previewBlueprint(){await act(async()=>{
  const p=await api('/blueprint/preview','POST',readBlueprintForm());
  let h='<b>Preview only, nothing saved.</b> '+p.newly_failing_posts+' of '+p.checked_live_posts+' live post(s) would newly fail ('+p.estimated_recovery_tasks+' fix task(s)).';
  h+=p.affected.map(a=>'<div class="mt-1"><b>'+safe(a.title)+'</b> <span class="badge">'+safe(a.triage)+'</span><br>'+a.new_issues.map(i=>safe(i.evidence)+' <i>'+safe(i.suggestion)+'</i>').join('<br>')+'</div>').join('');
  if(p.would_clear.length)h+='<div class="mt-1">Would clear problems on '+p.would_clear.length+' post(s).</div>';
  $('bp-preview').innerHTML=h;
})}
async function _loadPlan(){
  const ds=await fetch('/api/demo/status').then(r=>r.json());
  $('plan-demo').innerHTML=(ds.story_loaded||!['manager','reviewer'].includes(me.role))?'':'<button class="btn-primary" onclick="loadDemoStory()">Load the demo story (fictional data)</button>';
  const c=await api('/claims/expiry?days=30');
  $('plan-claims').innerHTML=c.claims.length?c.claims.map((x,i)=>'<div class="mb-2"><b>'+safe(x.claim)+'</b> <span class="badge">'+safe(x.status.replace('_',' '))+'</span> '+safe(x.expires_on)+' ('+x.days_left+' days)<br><span class="text-sm">Used by '+(x.live_posts_using_it.map(p=>safe(p.title)).join(', ')||'no live post')+'</span> <button class="btn-dark" onclick="renewClaim('+i+')">Renew</button></div>').join(''):'<p class="help">No claims have an expiry date.</p>';
  window._claims=c.claims;
  const n=await api('/notifications');
  $('plan-notes').innerHTML=n.length?n.map(x=>'<div>'+safe(x.message)+'</div>').join(''):'<p class="help">No notices yet.</p>';
  const s=await api('/guideline-suggestions');
  $('plan-suggest').innerHTML=s.suggestions.length?s.suggestions.map((x,i)=>'<div class="mb-3"><b>'+safe(x.rule_code)+'</b> <span class="badge">'+safe(x.confidence)+'</span> disputed '+x.times_disputed+' of '+x.times_flagged+'<br><span class="text-sm">Reasons: '+x.dispute_reasons.map(safe).join('; ')+'</span><textarea id="sg-'+i+'" rows="3" class="field mt-1">'+safe(x.proposed_wording)+'</textarea><button class="btn-primary" onclick="approveClarify('+i+')">Approve this wording</button></div>').join(''):'<p class="help">No disputed rules yet.</p>';
  window._sg=s.suggestions;
}
async function runExpiryScan(){await act(async()=>{
  const r=await api('/claims/expiry/scan','POST');
  $('plan-scan').textContent=r.notices.length+' notice(s) sent, '+r.recovery_opened.length+' fix task(s) opened.';
  await _loadPlan();
})}
async function renewClaim(i){await act(async()=>{
  const c=window._claims[i];
  const d=await ask('New expiry date','YYYY-MM-DD',c.expires_on);if(!d)return;
  const e=await ask('What supports renewing this claim?','A short note for the record','');if(!e)return;
  const r=await api('/claims/renew','POST',{claim:c.claim,new_expires_on:d,evidence_note:e});
  $('plan-scan').textContent='Renewed. Saved as version '+r.version+'.';
  await _loadPlan();
})}
async function approveClarify(i){await act(async()=>{
  const x=window._sg[i];
  const r=await api('/guideline-suggestions/approve','POST',{rule_code:x.rule_code,wording:$('sg-'+i).value});
  $('plan-scan').textContent='Clarification saved as rules version '+r.version+'.';
  await _loadPlan();
})}

function fillSample(){
  $('sub-title').value='Winter launch post';
  const t=document.getElementById('sub-text')||document.querySelector('#tab-submit textarea');
  t.value="Hey guys! We are the best in the world. Rated 4.8/5 by 2,000+ customers. We utilise synergy to win.";
}
async function loadDemoStory(){await act(async()=>{
  await api('/demo/load','POST');
  $('plan-scan').textContent='Demo story loaded: 3 live posts, 1 fix task, a claim running out, disputes to learn from.';
  await _loadPlan();
})}

// Optional AI tone review through Puter.js (user-pays: the signed-in person's own Puter account
// is used, the app owner pays nothing and holds no key). Loaded only on click; the app works without it.
function loadPuter(){return new Promise((res,rej)=>{
  if(window.puter)return res();
  const s=document.createElement('script');s.src='https://js.puter.com/v2/';
  s.onload=()=>res();s.onerror=()=>rej(Error('Could not load Puter. The human review still works.'));
  document.head.appendChild(s);
})}
function puterText(r){
  if(typeof r==='string')return r;
  const c=r&&r.message&&r.message.content;
  if(typeof c==='string')return c;
  if(Array.isArray(c))return c.map(x=>x.text||'').join('');
  return JSON.stringify(r||'');
}
async function puterTone(id){await act(async()=>{
  const note=$('puter-note-'+id);note.textContent='Opening Puter. You may be asked to sign in or create a free account.';
  await loadPuter();
  const s=await api('/submissions/'+id);
  const bp=await api('/blueprint/current');
  const guidelines=bp.guidelines.map(g=>g.body).join('\n');
  const prompt='You check a draft against brand guidelines. Flag a problem only if you can quote the exact guideline sentence it breaks AND quote the exact words from the draft. '+
    'Reply with JSON only: [{"clause":"exact guideline text","evidence":"exact words from the draft","suggestion":"short fix"}]. Reply [] if nothing is wrong.\n\nGUIDELINES:\n'+guidelines.slice(0,4000)+'\n\nDRAFT:\n'+(s.text||'').slice(0,4000);
  const out=puterText(await puter.ai.chat(prompt));
  const a=out.indexOf('['),b=out.lastIndexOf(']');
  let items=[];
  try{items=a>=0?JSON.parse(out.slice(a,b+1)):[]}catch(e){throw Error('The AI reply was not valid JSON, so nothing was added.')}
  const r=await api('/submissions/'+id+'/ai-tone','POST',{items,provider:'puter'});
  note.textContent='AI review added '+r.kept+' finding(s); '+r.dropped_not_quoted_from_draft+' dropped because they did not quote the draft. AI findings are labelled and a human decides.';
  await _inspect(id);
  $('puter-note-'+id).textContent='AI review added '+r.kept+' finding(s); '+r.dropped_not_quoted_from_draft+' dropped (not quoted from the draft). AI findings are labelled; a human decides.';
})}

async function _loadActivity(){
  const rows = await api('/audit');
  const el = $('activity-body');
  if(!rows.length){ el.innerHTML = '<p class="help">Nothing recorded yet.</p>'; return; }
  const verb = k => k.replace(/[._]/g,' ');
  el.innerHTML = rows.map(e=>{
    const when = e.created_at ? new Date(e.created_at*1000).toLocaleString() : '';
    const who = e.actor || 'System';
    const detail = e.detail ? ' · '+safe(e.detail) : '';
    return '<div style="padding:.45rem 0;border-bottom:1px solid #eee5d0">'
      + '<span style="color:#6b6557">'+safe(when)+'</span> · <b>'+safe(who)+'</b> '
      + safe(verb(e.action||'')) + ' ' + safe(e.entity||'') + detail + '</div>';
  }).join('');
}
