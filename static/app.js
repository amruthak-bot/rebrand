// ReBrand — plain-language checks, human approval, then publication registration.
let token = '', me = null;
const $ = id => document.getElementById(id);
const safe = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path, method='GET', body=null) {
  const headers = token ? {Authorization:'Bearer '+token} : {};
  if (body && !(body instanceof FormData)) headers['Content-Type']='application/json';
  const r = await fetch('/api'+path,{method,headers,body:body ? body instanceof FormData ? body : JSON.stringify(body) : undefined});
  const value = await r.json();
  if(!r.ok) throw Error(typeof value.detail==='string' ? value.detail : JSON.stringify(value.detail || value));
  return value;
}
async function act(f){try{await f()}catch(e){alert(e.message)}}
async function login(){await act(async()=>{
  const v=await api('/login','POST',{email:$('email').value,password:$('password').value});
  token=v.token;me=v.user;
  $('login-view').classList.add('hidden');$('app-view').classList.remove('hidden');
  $('whoami').innerHTML=safe(me.name)+' ('+safe(me.role)+') <button onclick="location.reload()" class="underline">Sign out</button>';
  showTab('submit');
})}
function showTab(name, postId=null){
  document.querySelectorAll('.tab-panel').forEach(x=>x.classList.add('hidden'));
  $('tab-'+name).classList.remove('hidden');
  document.querySelectorAll('.tab-btn').forEach(x=>x.classList.toggle('active',x.dataset.tab===name));
  return act(async()=>{
    if(name==='blueprint')await loadBlueprint();
    if(name==='review')await loadReview(postId);
    if(name==='published')await loadPublished();
    if(name==='recovery')await loadRecovery();
    if(name==='insights')await loadInsights();
  });
}
const sevWord = s => s==='high' ? 'Stop — fix this first' : s==='medium' ? 'Check this' : 'Small fix';
const sevStyle = s => s==='high' ? 'background:#fdeceb;color:#8c2b1d' : s==='medium' ? 'background:#fdf3d7;color:#7a5410' : 'background:#e7efe8;color:#17573f';
async function loadBlueprint(){
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
    (b.palette||[]).map(c=>'<span style="background:'+safe(c)+';width:36px;height:24px;border-radius:6px;border:1px solid #cbbf9f;display:inline-block" title="'+safe(c)+'"></span>').join('') + '</div>';
  $('bp-guidelines').value=(b.guidelines||[]).map(x=>x.title+': '+x.body).join('\n');
  $('bp-terms').value=(b.terms||[]).map(x=>[x.term,x.kind,x.replacement,x.note].join(' | ')).join('\n');
  $('bp-claims').value=(b.claims||[]).map(x=>[x.claim,x.risk,x.expires_on||''].join(' | ')).join('\n');
  $('bp-palette').value=(b.palette||[]).join(', ');
}
async function saveBlueprint(){await act(async()=>{
  const lines=id=>$(id).value.split('\n').map(x=>x.trim()).filter(Boolean);
  const b={note:$('bp-note').value,
    guidelines:lines('bp-guidelines').map(x=>{const n=x.indexOf(':');return {title:n>=0?x.slice(0,n):'Rule',body:n>=0?x.slice(n+1).trim():x}}),
    terms:lines('bp-terms').map(x=>{const a=x.split('|').map(s=>s.trim());return {term:a[0],kind:a[1],replacement:a[2]||'',note:a[3]||''}}),
    claims:lines('bp-claims').map(x=>{const a=x.split('|').map(s=>s.trim());return {claim:a[0],risk:a[1]||'medium',expires_on:a[2]||null}}),
    palette:$('bp-palette').value.split(',').map(x=>x.trim()).filter(Boolean)};
  const v=await api('/blueprint','POST',b);
  $('bp-msg').textContent='Saved as version '+v.version+'. '+v.impacted_published.length+' live post(s) need another look.';
  await loadBlueprint();
})}
async function uploadGuideline(){await act(async()=>{
  const f=$('bp-file').files[0]; if(!f) throw Error('Choose a file first');
  const form=new FormData(); form.append('file',f);
  const r=await api('/blueprint/upload-guideline','POST',form);
  $('bp-file-text').textContent=r.text;
})}
async function createSubmission(check=false){await act(async()=>{
  const f=$('sub-file').files[0];
  if(check && ($('sub-type').value==='image' ? !f : !$('sub-text').value.trim()&&!f)){
    $('sub-result').textContent=$('sub-type').value==='image'?'Choose an image first.':'Write a post or choose a document first.';
    return;
  }
  const r=await api('/submissions','POST',{title:$('sub-title').value||'Untitled',content_type:$('sub-type').value,channel:$('sub-channel').value,text:$('sub-text').value,alt_text:$('sub-alt').value});
  if(f){const fd=new FormData();fd.append('file',f);await api('/submissions/'+r.id+'/upload','POST',fd)}
  if(check){
    await api('/submissions/'+r.id+'/check','POST');
    $('sub-result').textContent='';
    await showTab('review',r.id);
  } else {
    $('sub-result').innerHTML='<div class="rounded-2xl p-4 mt-3 text-sm" style="background:#e7efe8">Draft saved. You can check it later from the Review tab.</div>';
  }
})}
function issueHtml(x, id){
  return `<div class="rounded-xl p-3 mb-2 text-sm sev-${x.severity}" style="background:#fffdf8;border:1px solid #e5dcc6">
    <span class="badge" style="${sevStyle(x.severity)}">${safe(sevWord(x.severity))}</span>
    <span class="badge">${safe(x.rule_code)}</span>
    ${x.uncertain?'<span class="badge" style="background:#fdf3d7">Not sure — a person should check</span>':''}
    <p class="mt-2"><b>What we found:</b> ${safe(x.evidence)}</p>
    <p><b>Why it matters:</b> <i>${safe(x.clause)}</i></p>
    ${x.suggestion?'<p><b>How to fix it:</b> '+safe(x.suggestion)+'</p>':''}
    <p class="mt-1">Status: <b>${safe(x.status)}</b>
    <button class="link ml-2" onclick="accept(${x.id},${id})">I fixed this</button>
    <button class="link ml-2" onclick="dispute(${x.id},${id})">This flag is wrong</button></p></div>`;
}
async function accept(i,id){await act(async()=>{await api('/issues/'+i+'/accept','POST');alert('Noted. Edit the post and run the check again before approval.');await inspect(id)})}
async function dispute(i,id){await act(async()=>{
  const reason=prompt('Why is this flag wrong? This goes to the reviewer.');
  if(!reason) return;
  await api('/issues/'+i+'/dispute','POST',{reason}); await inspect(id);
})}
async function loadReview(postId=null){
  const rows=await api('/submissions');
  $('review-list').innerHTML=rows.length ? '' : '<p class="text-sm" style="color:#5c6b58">Nothing to review yet. Write your first post and it will show up here.</p>';
  for(const s of rows){
    const d=document.createElement('div');
    d.className='border rounded-2xl p-4'; d.style.borderColor='#e5dcc6'; d.style.background='#fff';
    const open=s.open_issues;
    d.innerHTML=`<b class="text-lg" style="font-family:Fraunces,Georgia,serif">${safe(s.title)}</b>
      <span class="badge">${safe(s.state)}</span><span class="badge">${safe(s.content_type)}</span>
      <p class="text-xs mt-1" style="color:#5c6b58">${!s.checked_fingerprint&&['Draft','In Review'].includes(s.state)?'Check required before approval':open+' thing(s) still to look at'}</p>
      <button class="link mr-3" onclick="inspect(${s.id})">Open this post</button>
      <div id="details-${s.id}"></div>`;
    $('review-list').appendChild(d);
  }
  if(postId!==null)await inspect(postId);
}
async function check(id){await act(async()=>{await api('/submissions/'+id+'/check','POST');await loadReview(id)})}
async function inspect(id){await act(async()=>{
  const s=await api('/submissions/'+id);
  const editable=['Draft','In Review','In Recovery'].includes(s.state);
  const reviewer=['manager','reviewer'].includes(me.role);
  const issues=s.issues.filter(x=>x.status!=='resolved');
  const ready=s.state==='In Review'&&s.checked_fingerprint&&!issues.some(x=>x.severity==='high');
  $('details-'+id).innerHTML=`<p class="text-sm my-2 rounded-xl p-3" style="background:#f6f1e7">${safe(s.text)}</p>
    ${editable?`<label class="block text-sm font-medium">Edit the post here
    <textarea id="edit-${id}" class="field mt-1" rows="3" oninput="markEdit(${id})">${safe(s.text)}</textarea></label>
    <button class="btn-dark mt-2" onclick="revise(${id},${s.state!=='In Recovery'})">${s.state==='In Recovery'?'Save correction':'Save and recheck'}</button>`:''}
    <p id="review-status-${id}" class="text-sm mt-3" role="status">${!s.checked_fingerprint&&['Draft','In Review'].includes(s.state)?'Check required before approval.':ready?(reviewer?'Ready for your review and approval.':'Checked. Waiting for a manager or reviewer to approve.'):'Status: '+safe(s.state)}</p>
    <div class="mt-3">${issues.map(x=>issueHtml(x,id)).join('')|| (s.checked_fingerprint?'<p class="text-sm" style="color:#17573f">No rule findings in the last check. A person still reviews the content.</p>':'')}</div>
    <div class="flex gap-2 flex-wrap mt-2">
      ${reviewer&&ready?`<button id="approve-${id}" class="btn-primary" onclick="decision(${id},'approve')">Approve</button>`:''}
      ${reviewer&&s.state==='In Review'?`<button class="btn-outline" onclick="decision(${id},'request_changes')">Ask for changes</button>`:''}
      ${s.state==='Approved'?`<label class="text-sm">Live link (optional)<input id="publish-url-${id}" type="url" class="field mt-1" placeholder="https://..."></label><button class="btn-primary" onclick="publish(${id})">Mark as published</button><p class="help">After posting on your channel, record it here. ReBrand does not post externally.</p>`:''}
    </div>
    <div id="memory-${id}" aria-live="polite"></div>`;
  if(s.checked_fingerprint&&['Draft','In Review','Approved'].includes(s.state))await memoryCheck('memory-'+id,s.title,s.text);
})}
function markEdit(id){
  $('review-status-'+id).textContent='Changes not checked. Save and recheck before approval.';
  if($('approve-'+id))$('approve-'+id).disabled=true;
  $('memory-'+id).innerHTML='';
}
async function revise(id,recheck=true){await act(async()=>{
  await api('/submissions/'+id,'PATCH',{text:$('edit-'+id).value});
  if(recheck)await api('/submissions/'+id+'/check','POST');
  await loadReview(id);
})}
async function decision(id,action){await act(async()=>{
  let reason='';
  if(action!=='approve'){reason=prompt('What should change? (This is saved for the writer)')||''}
  try{await api('/submissions/'+id+'/decision','POST',{action,reason});}
  catch(e){alert(e.message);return}
  await loadReview(id);
})}
async function publish(id){await act(async()=>{
  const url=$('publish-url-'+id).value.trim();
  if(url&&!$('publish-url-'+id).reportValidity())return;
  await api('/submissions/'+id+'/publish','POST',{url});
  await showTab('published');
})}
async function loadPublished(){
  const rows=await api('/published');
  $('published-list').innerHTML=rows.length ? '' : '<p class="text-sm" style="color:#5c6b58">No live posts yet. Approved posts will show up here.</p>';
  for(const x of rows){
    const d=document.createElement('div');
    d.className='border rounded-2xl p-4'; d.style.borderColor='#e5dcc6'; d.style.background='#fff';
    d.innerHTML=`<b>${safe(x.title)}</b> <span class="badge">${safe(x.state)}</span><span class="badge">Rules v${x.blueprint_version}</span>
      <p class="text-sm mt-1">${x.url?'<a class="link" href="'+safe(x.url)+'" target="_blank" rel="noopener">'+safe(x.url)+'</a>':'No link saved'}</p>
      <p class="text-xs mt-1" style="color:#5c6b58">Live since ${new Date(x.published_at*1000).toLocaleDateString()}</p>
      <button class="link mr-3" onclick="recheck(${x.id})">Check this post again</button>
      <button class="link" onclick="report(${x.id})">Something is wrong with it</button>
      <div id="pub-${x.id}" class="mt-1 text-sm"></div>`;
    $('published-list').appendChild(d);
  }
}
async function recheck(id){await act(async()=>{
  const r=await api('/published/'+id+'/recheck','POST');
  $('pub-'+id).innerHTML='<b>'+safe(r.verdict)+'</b>'+(r.issues.length?' ('+r.issues.length+' thing(s) found)':'');
  await loadRecovery();
})}
async function report(id){await act(async()=>{
  const reason=prompt('What is wrong with this live post?');
  if(!reason) return;
  await api('/published/'+id+'/report','POST',{reason});
  showTab('recovery');
})}
async function loadRecovery(){
  const rows=await api('/recovery');
  $('recovery-list').innerHTML=rows.length ? '' : '<p class="text-sm" style="color:#5c6b58">No posts to fix right now. That is good news.</p>';
  for(const x of rows){
    const d=document.createElement('div');
    d.className='border rounded-2xl p-4'; d.style.borderColor='#e5dcc6'; d.style.background='#fff';
    d.innerHTML=`<b>${safe(x.title)}</b> <span class="badge">${safe(x.state)}</span>
      <p class="text-sm mt-1">${safe(x.reason)}</p>
      <p class="text-xs mt-1" style="color:#5c6b58">Found ${new Date(x.detected_at*1000).toLocaleDateString()}${x.owner_name?' · Owner: '+safe(x.owner_name):''}${x.deadline?' · Due: '+safe(x.deadline):''}${x.action?' · Planned fix: '+safe(x.action):''}${x.correction_note?' · Fix: '+safe(x.correction_note):''}</p>
      <div class="flex gap-2 flex-wrap mt-2">
        ${x.state==='open'?`<button class="link" onclick="propose(${x.id})">Suggest a fix</button>`:''}
        ${x.state==='action_proposed'&&['manager','reviewer'].includes(me.role)?`<button class="link" onclick="recoveryAction(${x.id},'approve-action')">Approve the fix</button>`:''}
        ${x.state==='in_progress'?`<button class="link" onclick="markCorrected(${x.id})">I fixed the live post</button>`:''}
        ${x.state==='recheck'&&['manager','reviewer'].includes(me.role)?`<button class="link" onclick="recoveryAction(${x.id},'close')">Check again and close</button>`:''}
      </div>`;
    $('recovery-list').appendChild(d);
  }
}
async function propose(id){await act(async()=>{
  const action=prompt('What should we do? Type: edit, replace, correction_note, or unpublish','edit');
  if(!action) return;
  await api('/recovery/'+id+'/propose','POST',{action});
  await loadRecovery();
})}
async function markCorrected(id){await act(async()=>{
  const correction_note=prompt('What did you actually change on the live post? (Write it in your own words — this is a human confirmation, not an automatic check.)');
  if(!correction_note) return;
  await api('/recovery/'+id+'/mark-corrected','POST',{correction_note});
  await loadRecovery();
})}
async function recoveryAction(id,action){await act(async()=>{await api('/recovery/'+id+'/'+action,'POST');await loadRecovery()})}
async function loadInsights(){
  const d=await api('/insights');
  const list=(arr,fn)=>arr.length?'<ul class="list-disc ml-5 text-sm space-y-1">'+arr.map(fn).join('')+'</ul>':'<p class="text-sm" style="color:#5c6b58">Nothing yet.</p>';
  $('insights-body').innerHTML=`
    <div class="grid sm:grid-cols-2 gap-4">
      <div class="rounded-2xl p-4" style="background:#fff;border:1px solid #e5dcc6"><h3 class="font-semibold mb-2">What keeps going wrong</h3>${list(d.repeat_issues,x=>'<li>'+safe(x.rule_code)+' — '+x.n+' time(s)</li>')}</div>
      <div class="rounded-2xl p-4" style="background:#fff;border:1px solid #e5dcc6"><h3 class="font-semibold mb-2">Rules people keep questioning</h3>${list(d.disputed_rules,x=>'<li>'+safe(x.rule_code)+' — disputed '+x.n+' time(s)</li>')}${d.unclear_guideline_signals.length?'<p class="text-sm mt-2" style="color:#7a5410">These rules may need clearer wording.</p>':''}</div>
      <div class="rounded-2xl p-4" style="background:#fff;border:1px solid #e5dcc6"><h3 class="font-semibold mb-2">How fast things get approved</h3><p class="text-sm">Average: ${d.avg_time_to_approve_hours} hour(s).</p>${list(d.approval_actions,x=>'<li>'+safe(x.action)+': '+x.n+'</li>')}</div>
      <div class="rounded-2xl p-4" style="background:#fff;border:1px solid #e5dcc6"><h3 class="font-semibold mb-2">Fixing live posts</h3>${list(d.recovery_by_state,x=>'<li>'+safe(x.state)+': '+x.n+'</li>')}<p class="text-sm mt-1">Average days to fix: ${d.avg_days_to_close} (${d.closed_recoveries} fixed).</p><p class="text-sm">Still unsure, waiting for a person: ${d.open_evidence_debt}</p></div>
    </div>`;
}
async function memoryCheck(target='memory-result',title=$('sub-title').value,text=$('sub-text').value){await act(async()=>{
  const result=await api('/memory/check','POST',{title,text});
  const items=result.matches.map(x=>`<article class="rounded-2xl p-4 my-2" style="background:#fff;border:1px solid #e5dcc6">
    <b style="font-family:Fraunces,Georgia,serif">${safe(x.title)}</b> · last posted ${new Date(x.published_at*1000).toLocaleDateString()}
    <p class="text-sm mt-1">It said: “${safe(x.previous_text)}”</p>
    <p class="text-xs mt-1" style="color:#5c6b58">Same topic words: ${safe(x.shared_terms.join(', '))}</p>
    ${x.possible_numeric_change?`<p class="text-sm font-semibold" style="color:#7a5410">The numbers may have changed: before ${safe(x.previous_numbers.join(', '))}; in your draft ${safe(x.draft_numbers.join(', '))}. Please check the real numbers before publishing.</p>`:''}
    <p class="text-sm">${safe(x.verification_note)}</p></article>`).join('');
  if(!$(target))return;
  if(target==='memory-result'&&(title!==$('sub-title').value||text!==$('sub-text').value))return;
  if(target.startsWith('memory-')&&target!=='memory-result'){
    const editor=$('edit-'+target.slice(7));
    if(editor&&editor.value!==text)return;
  }
  $(target).innerHTML='<h3 class="font-semibold mt-4" style="font-family:Fraunces,Georgia,serif">Older posts on this topic</h3><p class="text-xs" style="color:#5c6b58">'+safe(result.note)+'</p>'+(items||'<p class="text-sm mt-2">No older posts on this topic. You are starting fresh.</p>');
})}
$('tab-submit').addEventListener('input',()=>{
  $('sub-result').textContent='';
  $('memory-result').textContent='';
});
$('sub-type').addEventListener('change',()=>{
  $('image-fields').classList.toggle('hidden',$('sub-type').value!=='image');
});
