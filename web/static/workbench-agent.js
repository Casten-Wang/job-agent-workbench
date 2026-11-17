'use strict';

(() => {
  const $ = name => document.getElementById(`wa-${name}`);
  if (!$('panel')) return;
  const labels = {idle:'准备开始',queued:'准备中',running:'处理中',committing:'正在保存',waiting_input:'需要补充信息',waiting_approval:'待你确认',completed:'已完成',failed:'处理失败',stopping:'正在停止',stopped:'已停止'};
  function friendlyText(text) {
    if(text==='所选项目表述已确认并冻结，可继续生成申请草稿。')return '这些经历已确认并保存，可以用来生成简历和招呼语。';
    if(text==='正在依据原文整理项目背景、本人职责与简历表述')return '正在整理项目背景和你实际做过的工作';
    return text;
  }
  const toolLabels = {workspace_summary:'读取工作区',search_jobs:'搜索已有岗位',job_detail:'读取岗位详情',professional_profile:'读取专业资料',materials:'查找已确认材料',resume_versions:'读取简历版本',hr_records:'读取 HR 记录',interview_records:'读取面试记录',task_status:'读取任务状态',recommend_jobs:'推荐候选岗位',draft_application:'准备申请草稿',revise_application:'修改申请草稿',request_save:'准备保存预览',attachment:'整理补充材料'};
  let mode = state.mode, current = null, sessions = [], events = [], busy = false, epoch = 0, timer = null, selectedArtifact = null;
  let submitted = null, composing = false, compositionEnded = 0;
  let stream = null, streamSession = null, followMessages = true, eventsSnapshot = '';
  let noteTimer = null, noteSnapshot = '', noteEpoch = 0;
  let materialSubmission = null, materialSubmitting = false, availableMaterials = [];
  let materialSnapshot = '', retrySubmission = null;
  const storage = {get(key) { try {return localStorage.getItem(key);} catch {return null;} }, set(key,value) { try {localStorage.setItem(key,value);} catch {} }};
  const key = suffix => `offerpilot.workbench.${mode}.${suffix}`;
  const active = () => ['queued','running','committing','stopping'].includes(current?.status);
  const node = (tag,text,cls) => {const n=document.createElement(tag); if(text!==undefined)n.textContent=String(text); if(cls)n.className=cls; return n;};
  function button(text,fn) {const b=node('button',text,'button button-quiet button-small');b.type='button';b.addEventListener('click',()=>run(fn));return b;}
  function notice(text) {$('notice').textContent=text || '';}
  function keepInput() {storage.set(key(`draft.${current?.id || 'new'}`),$('input').value);}
  function tab(name) {
    // 02 对话助理是独立页面，只有对话面板；云端首页的「流程总览」页签未接入，缺失的元素直接跳过。
    if(!$('overview')||!$('tab-overview'))return;
    const chat=name==='chat'; $('panel').hidden=!chat; $('overview').hidden=chat;
    ['chat','overview'].forEach(t=>{$(`tab-${t}`).classList.toggle('is-active',t===name);$(`tab-${t}`).setAttribute('aria-pressed',String(t===name));});
  }
  async function api(path,payload,method) {
    const ticket=epoch;
    let r;try {r=await fetch(`/api/workbench-agent${path}${path.includes('?')?'&':'?'}mode=${mode}`,{
      method:method || (payload===undefined?'GET':'POST'),cache:'no-store',headers:{'Content-Type':'application/json'},
      ...(payload===undefined?{}:{body:JSON.stringify(payload)})});}catch{throw new Error('无法连接本机 Agent，请确认服务已启动后重试；未提交的材料仍保留。');}
    const data=await r.json(); if(ticket!==epoch)throw new Error('会话范围已切换');if(!r.ok)throw new Error(data.error || `请求失败 (${r.status})`);return data;
  }
  async function run(fn) {
    if(busy)return;busy=true;controls();const ticket=epoch;
    try {await fn();} catch(error) {if(ticket===epoch)notice(error.message);} finally {if(ticket===epoch){busy=false;controls();}}
  }
  function controls() {
    $('new').disabled=busy;
    $('send').disabled=busy || active(); $('upload').disabled=busy || active(); $('use-material').disabled=busy || active();
    $('upload').disabled=busy || active() || mode!=='user';
    $('stop').disabled=busy || !current || !['queued','running','waiting_approval'].includes(current.status);
    $('save').disabled=busy || active() || !current?.artifacts?.length || mode!=='user';
    $('status').textContent=labels[current?.status] || '准备开始';
    $('status').dataset.state=current?.status || 'idle';
    $('stop').hidden=!active() && current?.status!=='waiting_approval';
    $('send').hidden=active();
    $('send').disabled=busy || active() || !$('input').value.trim();
    $('panel').setAttribute('aria-busy',String(active()));
    $('activity').hidden=!active();
    const last=events.at(-1);
    $('activity-label').textContent=friendlyText(last?.message) || labels[current?.status] || '正在处理';
    const materialRun=materialSubmitting || current?.material_run?.run_id===current?.run_id;
    $('upload').textContent=materialSubmitting || (materialRun&&active())?'正在整理…':'整理并预览';
    renderMaterialProgress();
    $('approval').querySelectorAll('button').forEach(b=>{b.disabled=busy || active();});
    $('recommendations').querySelectorAll('button').forEach(b=>{b.disabled=busy || active();});
  }
  function renderSessions() {
    $('session-list').replaceChildren();
    sessions.forEach(s=>{const b=button(s.title,()=>open(s.id));b.className='wa-session';b.setAttribute('aria-current',String(current?.id===s.id));b.append(node('small',labels[s.status] || s.status));$('session-list').append(b);});
  }
  function reveal(target,text,animate) {
    if(!animate || matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.dataset.reduceMotion==='true') {target.append(document.createTextNode(text));return;}
    const graphemes=typeof Intl.Segmenter==='function'?[...new Intl.Segmenter('zh',{granularity:'grapheme'}).segment(text)].map(s=>s.segment):Array.from(text);
    const fragment=document.createDocumentFragment();
    for(let i=0;i<graphemes.length;i+=3){const part=node('span',graphemes.slice(i,i+3).join(''),'wa-ink');part.style.animationDelay=`${Math.min(i/3*24,192)}ms`;fragment.append(part);}
    target.append(fragment);
    if(!target.dataset.revealBound){target.dataset.revealBound='true';target.addEventListener('animationend',event=>{if(event.target.classList.contains('wa-ink'))event.target.replaceWith(document.createTextNode(event.target.textContent));});}
  }
  function renderMessages(animate=false) {
    const panel=$('messages');
    if(!current?.messages?.length) {
      $('jump').hidden=true;if(panel.querySelector('.wa-welcome'))return;
      const welcome=node('div',undefined,'wa-welcome'),mark=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS('http://www.w3.org/2000/svg','path');
      mark.setAttribute('viewBox','0 0 48 48');mark.setAttribute('aria-hidden','true');mark.classList.add('wa-welcome-mark');path.setAttribute('d','M24 3v12M24 33v12M3 24h12M33 24h12M9 9l9 9M30 30l9 9M9 39l9-9M30 18l9-9');path.setAttribute('stroke','currentColor');path.setAttribute('stroke-width','3');path.setAttribute('stroke-linecap','round');mark.append(path);
      welcome.append(mark,node('p','OFFERPILOT','wa-eyebrow'),node('h4','下一份机会，从这里开始。'));
      const prompts=node('div',undefined,'wa-prompts');
      [['找合适的岗位','从已有岗位里推荐 3 个上海后端岗'],['准备申请材料','帮我梳理已有材料，准备目标岗位的简历和招呼语'],['回顾求职进展','汇总我的岗位、HR 回复和面试准备状态']].forEach(([label,text])=>prompts.append(button(label,async()=>{$('input').value=text;keepInput();resizeInput();controls();$('input').focus();})));
      welcome.append(prompts);panel.replaceChildren(welcome);return;
    }
    panel.querySelector('.wa-welcome')?.remove();
    const messages=[...current.messages], partial=current.streaming_message;
    if(partial?.text)messages.push({role:'assistant',text:partial.text,streaming:true,stage:partial.stage});
    messages.forEach((m,index)=>{
      let row=panel.children[index];
      if(!row || row.dataset.role!==m.role){row=node('article',undefined,`wa-message wa-message-${m.role==='user'?'user':'assistant'}`);row.dataset.role=m.role;row.append(node('strong',m.role==='user'?'你':'OfferPilot'),node('p'));if(panel.children[index])panel.children[index].replaceWith(row);else panel.append(row);}
      const label=m.role==='user'?'你':m.streaming?(m.stage==='workbench_decide'?'OfferPilot　正在回复':'OfferPilot　正在生成，内容待核对'):m.state?'OfferPilot　回复未完成':'OfferPilot';
      if(row.querySelector('strong').textContent!==label)row.querySelector('strong').textContent=label;
      row.setAttribute('aria-busy',String(Boolean(m.streaming)));
      const body=row.querySelector('p'), previous=body.textContent, text=String(friendlyText(m.text) || '');
      if(previous!==text){if(text.startsWith(previous))reveal(body,text.slice(previous.length),animate&&m.role!=='user');else{body.replaceChildren();reveal(body,text,animate&&m.role!=='user');}}
    });
    while(panel.children.length>messages.length)panel.lastElementChild.remove();
    if(followMessages)panel.scrollTop=panel.scrollHeight;
    $('jump').hidden=followMessages;
  }
  function renderJobs() {
    $('recommendations').replaceChildren();
    (current?.recommendations || []).forEach(item=>{
      const job=item.job, section=node('section',undefined,'wa-job');
      section.append(node('h4',`${job.company} / ${job.title}`),node('small',`${job.city || '城市未提供'}　来源：${job.source_channel || '未提供'}　现有评分：${job.score ?? '未评分'}`),node('p',item.reason));
      if(item.gaps?.length)section.append(node('p','待补充：'+item.gaps.join('；')));
      if(job.risk?.level && job.risk.level!=='low')section.append(node('p',`岗位风险：${job.risk.level==='high'?'高风险，不能入队':'需要核实'}`));
      section.append(button(current.job_id===job.id?'已选此岗位':'为此岗位准备材料',()=>send({text:'为选定岗位准备简历和招呼语草稿',job_id:job.id})));
      $('recommendations').append(section);
    });
  }
  function renderContext() {
    $('context').replaceChildren(node('span',mode==='user'?'本机资料':'演示数据','wa-context-scope'));
    if(current?.job_id){const item=current.recommendations.find(r=>r.job_id===current.job_id);$('context').append(button(`${item?.job?.title || '目标岗位'} ×`,()=>send({text:'移除当前岗位，等待我重新选择',job_id:''})));}
    if(current?.material_id){const material=current.materials.find(m=>m.material_id===current.material_id);$('context').append(button(`${material?.name || '已确认材料'} ×`,()=>send({text:'移除当前材料，等待我重新选择',material_id:''})));}
    const select=$('existing-material'), previous=select.value;select.replaceChildren(new Option('选择已有项目或经历',''));
    (current?.materials || availableMaterials).forEach(m=>select.add(new Option(m.name || '项目材料',m.material_id)));
    select.value=previous || current?.material_id || '';
  }
  function renderApproval() {
    const panel=$('approval'), pending=current?.pending;panel.replaceChildren();panel.hidden=!pending;if(!pending)return;
    if(pending.kind==='confirm_material')$('material-approval-slot').append(panel);else $('material-progress').before(panel);
    panel.append(node('h4',{save_resume:'核对你的简历',save_profile:'核对你的个人资料',confirm_material:'核对你的经历内容'}[pending.kind] || '核对本次操作'));
    if(pending.kind==='save_resume')panel.append(node('p',`即将保存修订 ${pending.preview.revision}，旧版本保留。`),node('pre',pending.preview.text));
    if(pending.kind==='confirm_material') {
      (pending.preview.claims || []).forEach((c,index)=>{const label=node('label',undefined,'wa-check'),input=document.createElement('input');input.type='checkbox';input.value=c.claim_id;input.checked=false;input.dataset.waClaim='true';label.append(input,node('span',`${index+1}. ${c.text}`));panel.append(label);});
      panel.append(node('p','请勾选与你实际经历一致的内容，确认后保存。'));
    }
    if(pending.kind==='save_profile') {
      const p=pending.preview;panel.append(node('p',`姓名：${p.basic?.name || '未填写'}`));
      for(const [field,title] of [['education','教育'],['experiences','工作经历'],['projects','项目经历']]) {
        if(p[field]?.length){panel.append(node('strong',title));p[field].forEach(r=>panel.append(node('p',[r.school,r.company,r.title,r.name,r.role,r.start,r.end,r.summary].filter(Boolean).join(' / '))));}
      }
      panel.append(node('p','技能：'+[...(p.skills?.tools || []),...(p.skills?.strengths || [])].join('、')));
    }
    panel.append(button({save_resume:'确认并保存简历',save_profile:'确认并保存资料',confirm_material:'确认并保存经历'}[pending.kind] || '确认并保存',async()=>{
      const claimIds=[...panel.querySelectorAll('[data-wa-claim]:checked')].map(i=>i.value);
      if(pending.kind==='confirm_material'&&!claimIds.length)throw new Error('请至少勾选一项你实际做过的工作');
      await accept(await api(`/conversations/${current.id}/approvals`,{approval_id:pending.id,approved:true,...(pending.kind==='confirm_material'?{claim_ids:claimIds}:{})}));
    }),button('不提交，保留草稿',async()=>accept(await api(`/conversations/${current.id}/approvals`,{approval_id:pending.id,approved:false}))));
  }
  function artifact() {return current?.artifacts?.find(a=>a.id===selectedArtifact);}
  function materialResult() {
    if(current?.material_run?.kind==='experience')return current.material_run;
    if(current?.pending?.kind==='confirm_material')return {status:'waiting_approval',message:'整理成功，请核对后保存。',preview:current.pending.preview};
    return null;
  }
  function renderMaterialProgress() {
    const result=current?.material_run || materialResult();
    $('material-progress').hidden=!result&&!materialSubmitting;
    if(!result&&!materialSubmitting)return;
    const status=materialSubmitting?'submitting':result.status;
    $('material-progress').dataset.state=status;
    $('material-heading').textContent=({submitting:'正在提交材料',queued:'材料已收到',preparing:'正在整理材料',validating:'正在校验整理结果',waiting_approval:'整理成功 · 待你核对',saving:'正在保存材料',confirmed:'已确认并保存',failed:'材料处理失败',stopped:'材料整理已停止',rejected:'本次预览未保存',invalidated:'本次预览需要重新整理'})[status] || '材料整理';
    $('material-status').textContent=materialSubmitting?'正在提交原文或提取文件，请稍候。':result.message+(result.error_code?`（错误代码：${result.error_code}）`:'');
    const stages={queued:0,preparing:1,validating:1,waiting_approval:2,saving:3,confirmed:4,rejected:2,invalidated:2};
    const stage=stages[['failed','stopped'].includes(status)?result.failed_at:status] ?? -1;
    $('material-steps').replaceChildren();
    ['接收材料','整理与校验','核对内容',result?.kind==='profile'?'保存个人资料':'保存到经历库'].forEach((text,index)=>{
      const item=node('li',text);
      item.dataset.state=stage>index?'done':stage===index?'current':'pending';
      if(stage===index)item.setAttribute('aria-current','step');
      $('material-steps').append(item);
    });
    $('view-material').hidden=!materialResult()?.preview;
    $('retry-material').hidden=!['failed','stopped'].includes(result?.status)||!result?.run_id||!!current?.pending;
    $('retry-material').disabled=busy||active()||mode!=='user';
  }
  function renderMaterialDocument() {
    const result=materialResult(),snapshot=JSON.stringify(result);
    if(snapshot===materialSnapshot)return;materialSnapshot=snapshot;
    const panel=$('material-document');panel.replaceChildren();if(!result?.preview)return;
    const p=result.preview;
    panel.append(node('h2',p.name || result.name || '项目整理结果'),node('p',result.message || '请核对整理内容。'));
    [['project_overview','项目背景'],['summary','项目理解'],['positioning','岗位匹配方向']].forEach(([key,label])=>{if(p[key])panel.append(node('h3',label),node('p',p[key]));});
    panel.append(node('h3',`核心贡献 · ${p.claims?.length || 0} 条`));
    (p.claims || []).forEach((c,index)=>{
      const section=node('section',undefined,'wa-material-claim');section.append(node('h4',`${index+1}. ${c.pillar || '核心贡献'}`),node('p',c.text));
      [['fit_reason','岗位相关性'],['boundary','职责边界'],['risk','待核实项']].forEach(([key,label])=>{if(c[key])section.append(node('p',`${label}：${c[key]}`,'wa-material-meta'));});
      const details=node('details'),sources=(p.evidence || []).filter(e=>(c.evidence_ids || []).includes(e.evidence_id));
      details.append(node('summary','查看原文依据'));
      if(c.source_quote)details.append(node('blockquote',c.source_quote));
      sources.forEach(e=>details.append(node('p',e.label || e.path || '用户提供的原文'),node('pre',e.text)));
      if(!c.source_quote&&!sources.length)details.append(node('p','此历史预览未保留原文，请重新整理后核对。'));
      section.append(details);panel.append(section);
    });
    panel.append(node('p',result.status==='confirmed'?'经历已保存。下一步：选择具体岗位，再生成申请简历和招呼语。':'上述内容为整理预览，请逐条确认实际做过的工作后保存到经历库。','wa-material-meta'));
  }
  function documentView(text) {
    $('document').replaceChildren();
    String(text || '').split('\n').forEach(line=>{const heading=/^(#{1,3}) (.*)$/.exec(line);if(heading)$('document').append(node(`h${heading[1].length}`,heading[2]));else if(line.trim())$('document').append(node('p',line.startsWith('- ')?`• ${line.slice(2)}`:line));});
  }
  function showResults(show=true) {
    if(window.OfferPilotWorkbench?.enabled){window.OfferPilotWorkbench.showArtifact(show);return;}
    $('results').hidden=!show;$('panel').classList.toggle('wa-has-results',show);$('panel').classList.toggle('wa-mobile-results',show);
  }
  function renderArtifact() {
    const material=selectedArtifact==='material';$('material-result').hidden=!material;
    $('document').hidden=material;$('artifact-details').hidden=material;$('result-actions').hidden=material;
    renderMaterialDocument();
    const a=artifact();documentView(a?.text);
    const changes=(a?.diff || '').split('\n').filter(line=>!line.startsWith('--- ')&&!line.startsWith('+++ ')&&!line.startsWith('@@'))
      .filter(line=>line.startsWith('+')||line.startsWith('-')).map(line=>(line.startsWith('+')?'新增：':'删除：')+line.slice(1));
    $('diff').textContent=changes.join('\n\n') || '此修订没有正文差异。';$('sources').replaceChildren();
    if(!a)return;
    $('sources').append(node('p','以下来源用于核对事实，模型语义检查通过仍需本人复核。'));
    const refs=a.kind==='resume'?a.source_map.flatMap(b=>b.claim_ids):a.source_map;
    const claims=(current.materials.find(m=>m.material_id===a.material_id)?.claims || []).filter(c=>refs.includes(c.claim_id));
    claims.forEach(c=>$('sources').append(node('p',c.text)));
    $('save').hidden=a.kind!=='resume';$('delivery').hidden=a.kind!=='greeting';
    if(a.kind==='greeting')$('sources').append(node('p',window.OfferPilotWorkbench?.enabled?'发送前请核对文案并同步，最终以发送复核面板的内容为准。':'此文案尚未同步到原发送器，也没有发送。'));
  }
  function renderArtifacts() {
    const list=current?.artifacts || [], previous=$('artifact').value,material=materialResult()?.preview;
    $('artifact').replaceChildren();if(material)$('artifact').add(new Option('项目材料整理结果','material'));[...list].reverse().forEach(a=>$('artifact').add(new Option(`${a.kind==='resume'?'简历':'招呼语'} / 修订 ${a.revision}`,a.id)));
    if(!selectedArtifact || !(material&&selectedArtifact==='material')&&!list.some(a=>a.id===selectedArtifact))selectedArtifact=material?'material':list.at(-2)?.id || list.at(-1)?.id;
    if(previous&&(material&&previous==='material'||list.some(a=>a.id===previous)))selectedArtifact=previous;
    $('artifact').value=selectedArtifact || '';renderArtifact();
    $('versions').replaceChildren();(current?.saved_versions || []).forEach(v=>{
      const text=node('p','已保存版本 '+v.resume_version_id), link=node('a','打开打印 / PDF 导出');link.href=`/api/career-user/resumes/${encodeURIComponent(v.resume_version_id)}/print?mode=user`;link.target='_blank';link.rel='noopener';$('versions').append(text,link);
    });
  }
  function renderEvents() {
    const snapshot=JSON.stringify(events);if(snapshot===eventsSnapshot)return;eventsSnapshot=snapshot;
    const rows=[], pending=new Map();
    events.forEach(e=>{
      const id=`${e.run_id || ''}:${e.tool}`;
      if(e.type==='tool_completed' && pending.has(id)){const row=pending.get(id);row.dataset.state='completed';row.lastChild.textContent='已完成';pending.delete(id);return;}
      if(['failed','stopped','interrupted'].includes(e.type))for(const [key,row] of pending){if(key.startsWith(`${e.run_id || ''}:`)){row.dataset.state='failed';row.lastChild.textContent=e.type==='stopped'?'已停止':'未完成';pending.delete(key);}}
      const row=node('li',undefined,e.tool?'wa-tool':'wa-event');row.append(node('span',e.tool?(toolLabels[e.tool] || e.tool):friendlyText(e.message)));
      if(e.tool){row.dataset.state=e.type==='tool_started'?'running':'completed';row.append(node('span',e.type==='tool_started'?'进行中':'已完成'));if(e.type==='tool_started')pending.set(id,row);}
      rows.push(row);
    });
    $('event-count').textContent=rows.length?`${rows.length} 项`:'';$('events').replaceChildren(...rows.slice(-60));
    $('process').hidden=!rows.length;
  }
  function render(animate=false) {
    $('title').textContent=current?.title || '新的求职目标';renderMessages(animate);renderJobs();renderContext();renderApproval();renderArtifacts();renderEvents();renderSessions();controls();
  }
  async function accept(value,animate=true) {
    const grew=(value.artifacts?.length || 0)>(current?.artifacts?.length || 0);
    const materialReady=value.material_run?.preview && (value.id!==current?.id || value.material_run?.run_id!==current?.material_run?.run_id || !current?.material_run?.preview);
    const legacyReady=!value.material_run&&value.pending?.kind==='confirm_material'&&value.pending?.id!==current?.pending?.id;
    current=value;storage.set(key('conversation'),value.id);sessions=sessions.filter(s=>s.id!==value.id);sessions.unshift(value);
    if(grew){selectedArtifact=value.artifacts.at(-2)?.id;$('artifact').value='';if(animate||!window.OfferPilotWorkbench?.enabled)showResults();}
    if(materialReady||legacyReady){selectedArtifact='material';$('artifact').value='';if(animate||!window.OfferPilotWorkbench?.enabled)showResults();}
    if(value.material_run?.status==='failed'&&value.material_run?.run_id===value.run_id)$('process').open=true;
    render(animate);schedule();
    window.dispatchEvent(new CustomEvent('offerpilot:agent',{detail:{snapshot:value,animate}}));
  }
  function closeStream() {stream?.close();stream=null;streamSession=null;clearTimeout(timer);}
  function receive(data) {
    const cursor=events.at(-1)?.cursor || 0;events.push(...data.events.filter(e=>e.cursor>cursor));return accept(data.view);
  }
  function schedule() {
    clearTimeout(timer);if(!current || !active()){closeStream();return;}const ticket=epoch,sid=current.id;
    if(streamSession===sid)return;
    closeStream();
    if(typeof EventSource!=='function'){timer=setTimeout(poll,1000);return;}
    const source=new EventSource(`/api/workbench-agent/conversations/${sid}/stream?mode=${mode}&after=${events.at(-1)?.cursor || 0}`);
    stream=source;streamSession=sid;
    source.addEventListener('snapshot',event=>{if(ticket!==epoch||current?.id!==sid||stream!==source)return;receive(JSON.parse(event.data));});
    source.addEventListener('text_reset',event=>{if(ticket!==epoch||current?.id!==sid||stream!==source)return;current.streaming_message=JSON.parse(event.data).streaming_message;renderMessages(true);});
    source.addEventListener('text_delta',event=>{
      if(ticket!==epoch||current?.id!==sid||stream!==source)return;
      const data=JSON.parse(event.data),partial=current.streaming_message;
      if(!partial||partial.id!==data.id||partial.run_id!==data.run_id||[...partial.text].length!==data.offset){closeStream();poll();return;}
      partial.text+=data.delta;renderMessages(true);
    });
    source.addEventListener('settled',()=>{if(stream===source)closeStream();});
    const fallback=()=>{if(stream!==source)return;closeStream();if(ticket===epoch&&current?.id===sid)timer=setTimeout(poll,1000);};
    source.addEventListener('unavailable',fallback);source.onerror=fallback;
  }
  async function poll() {if(!current)return;const sid=current.id,ticket=epoch;try{const data=await api(`/conversations/${sid}/events?after=${events.at(-1)?.cursor || 0}`);if(ticket===epoch&&current?.id===sid)await receive(data);}catch(error){if(ticket===epoch){notice(error.message);timer=setTimeout(poll,3000);}}}
  async function open(sid) {
    keepInput();closeStream();const ticket=epoch;const data=await api(`/conversations/${sid}/events?after=0`);if(ticket!==epoch)return;
    current=null;selectedArtifact=null;events=data.events;$('messages').replaceChildren();followMessages=true;await accept(data.view,false);$('input').value=storage.get(key(`draft.${sid}`)) || '';resizeInput();submitted=null;notice('');
  }
  async function ensureConversation() {
    if(current)return;const title=$('input').value.trim().slice(0,60) || '新的求职目标';await accept(await api('/conversations',{title}));
  }
  async function send(override={}) {
    if(active())return;await ensureConversation();const text=override.text || $('input').value.trim();if(!text)return;
    const payload={event_id:crypto.randomUUID(),text,...override};
    if(!override.text && submitted?.text===text)payload.event_id=submitted.event_id;
    submitted=payload;const ticket=epoch;const value=await api(`/conversations/${current.id}/messages`,payload);
    if(ticket!==epoch)return;followMessages=true;await accept(value);if(!override.text){$('input').value='';keepInput();resizeInput();}submitted=null;notice('');
  }
  async function load() {
    const ticket=epoch;try {const data=await api('/conversations');if(ticket!==epoch)return;sessions=data.items;availableMaterials=data.materials || [];const sid=storage.get(key('conversation'));
      notice('');
      if(sessions.some(s=>s.id===sid))await open(sid);else {current=null;events=[];render();$('input').value=storage.get(key('draft.new')) || '';resizeInput();}
    } catch(error) {if(ticket===epoch){notice(error.message+'。可前往其他页面继续操作。');if(error.message.includes('已关闭'))tab('overview');}}
  }
  const noteReasons={unreachable:'网络不通或超时，稍后按退避周期检查',need_login:'需要登录或验证，已暂停',id_mismatch:'笔记 ID 不一致，已暂停',parse_error:'页面结构无法解析',empty_content:'未取得正文',rate_limited:'平台限流，稍后按退避周期检查',not_found:'页面返回不存在，已暂停',internal_error:'本地执行异常'};
  async function noteApi(path,payload) {
    const response=await fetch(`/api/career-user/notes${path}?mode=user`,{method:payload===undefined?'GET':'POST',cache:'no-store',headers:{'Content-Type':'application/json'},...(payload===undefined?{}:{body:JSON.stringify(payload)})});
    const value=await response.json();if(!response.ok)throw new Error(value.error || '面经服务不可用，请确认个人 Agent 已更新并运行');return value;
  }
  async function refreshNotes() {
    clearTimeout(noteTimer);const ticket=noteEpoch;
    $('note-inbox').hidden=mode!=='user';if(mode!=='user')return;
    try {
      const value=await noteApi('/inbox');if(ticket!==noteEpoch)return;
      $('note-count').textContent=`面经消息　${value.unread} 条未读`;
      const snapshot=JSON.stringify(value);if(snapshot!==noteSnapshot) {
        noteSnapshot=snapshot;$('note-messages').replaceChildren();
        if(!value.items.length)$('note-messages').append(node('p','暂无面经消息。可在 Agent 输入 /面经 查看用法。'));
        value.items.forEach(item=>{
          const row=node('section',undefined,'wa-note-message');
          row.append(node('strong',item.title || (item.kind==='subscription_paused'?'订阅已暂停':'采集未完成')),node('p',`${new Date(item.created*1000).toLocaleString()}　${item.read_at?'已读':'未读'}`));
          if(item.reason)row.append(node('p',noteReasons[item.reason] || item.reason));
          if(item.note_id)row.append(button('查看收藏正文',async()=>{
            const scope=noteEpoch,value=await noteApi(`/items/${encodeURIComponent(item.note_id)}`);if(scope!==noteEpoch)return;
            let content=row.querySelector('pre');if(!content){content=node('pre');row.append(content);}content.textContent=`${value.title}\n作者：${value.author}\n\n${value.content}`;
          }));
          if(item.source_url) {const link=node('a','打开原笔记');link.href=item.source_url;link.target='_blank';link.rel='noopener noreferrer';row.append(link);}
          if(!item.read_at)row.append(button('标记已读',async()=>{const scope=noteEpoch;await noteApi(`/inbox/${encodeURIComponent(item.id)}/read`,{});if(scope===noteEpoch)await refreshNotes();}));
          $('note-messages').append(row);
        });
      }
    } catch(error) {if(ticket===noteEpoch)$('note-count').textContent='面经消息　服务暂不可用';}
    finally {if(ticket===noteEpoch&&mode==='user')noteTimer=setTimeout(()=>{if(!document.hidden)refreshNotes();else noteTimer=setTimeout(refreshNotes,30000);},30000);}
  }
  $('note-help').addEventListener('click',()=>{$('input').value='/面经';keepInput();resizeInput();$('input').focus();});
  $('note-check').addEventListener('click',()=>run(async()=>{
    const ticket=noteEpoch;$('note-status').textContent='正在检查数据库、调度器和本地解析器…';
    try {const value=await noteApi('/self-check');if(ticket!==noteEpoch)return;$('note-status').textContent=`${value.ok?'本地自检通过':'本地自检发现问题'}；数据库${value.database_ok?'正常':'异常'}，调度器${value.scheduler_alive?'运行中':'未就绪'}，超期任务 ${value.overdue_jobs}，过期执行 ${value.expired_leases}，暂停订阅 ${value.paused_jobs}。小红书实站尚未验证。`;}
    catch(error){if(ticket===noteEpoch)$('note-status').textContent=error.message;}
  }));
  window.addEventListener('pagehide',()=>{closeStream();clearTimeout(noteTimer);});
  window.addEventListener('pageshow',event=>{if(event.persisted){schedule();refreshNotes();}});
  if($('tab-chat')&&$('tab-overview')){$('tab-chat').addEventListener('click',()=>tab('chat'));$('tab-overview').addEventListener('click',()=>tab('overview'));}
  $('new').addEventListener('click',()=>{keepInput();epoch++;closeStream();busy=false;current=null;events=[];submitted=null;selectedArtifact=null;followMessages=true;$('messages').replaceChildren();$('input').value=storage.get(key('draft.new')) || '';showResults(false);render();resizeInput();notice('');$('input').focus();});
  $('form').addEventListener('submit',event=>{event.preventDefault();run(()=>send());});
  function resizeInput() {const input=$('input');if(!CSS.supports('field-sizing','content')){input.style.height='auto';input.style.height=`${Math.min(input.scrollHeight,240)}px`;}controls();}
  $('input').addEventListener('input',()=>{keepInput();resizeInput();});
  $('messages').addEventListener('scroll',()=>{const p=$('messages');followMessages=p.scrollHeight-p.scrollTop-p.clientHeight<40;$('jump').hidden=followMessages;},{passive:true});
  $('jump').addEventListener('click',()=>{followMessages=true;$('messages').scrollTop=$('messages').scrollHeight;$('jump').hidden=true;});
  $('input').addEventListener('compositionstart',()=>{composing=true;});$('input').addEventListener('compositionend',()=>{composing=false;compositionEnded=Date.now();});
  $('input').addEventListener('keydown',event=>{if(event.key!=='Enter'||event.shiftKey)return;if(event.isComposing||composing||event.keyCode===229)return;event.preventDefault();if(compositionEnded&&Date.now()-compositionEnded<500){compositionEnded=0;return;}$('form').requestSubmit();});
  $('stop').addEventListener('click',()=>run(async()=>accept(await api(`/conversations/${current.id}/stop`,{}))));
  $('toggle-material').addEventListener('click',()=>{$('material-form').hidden=!$('material-form').hidden;$('toggle-material').setAttribute('aria-expanded',String(!$('material-form').hidden));});
  $('show-results').addEventListener('click',()=>{if(current?.artifacts?.length || materialResult()?.preview)showResults();else notice(current?.material_run?.message || '提交项目材料后，这里显示整理预览；确认材料并选择岗位后可生成简历和招呼语。');});
  $('view-material').addEventListener('click',()=>{selectedArtifact='material';$('artifact').value='material';renderArtifact();showResults();});
  $('retry-material').addEventListener('click',()=>run(async()=>{
    const runId=current?.material_run?.run_id;if(!runId)return;
    if(retrySubmission?.run_id!==runId)retrySubmission={run_id:runId,event_id:crypto.randomUUID()};
    await accept(await api(`/conversations/${current.id}/retry-material`,retrySubmission));retrySubmission=null;
  }));
  $('close-results').addEventListener('click',()=>showResults(false));
  $('artifact').addEventListener('change',()=>{selectedArtifact=$('artifact').value;renderArtifact();});
  $('use-material').addEventListener('click',()=>run(async()=>{const id=$('existing-material').value;if(!id)throw new Error('请选择已确认材料');await send({text:'选用这份已确认材料，为目标岗位准备申请草稿',material_id:id});$('material-form').hidden=true;$('toggle-material').setAttribute('aria-expanded','false');}));
  $('save').addEventListener('click',()=>run(async()=>{const a=artifact();if(!a)return;const latest=[...current.artifacts].reverse().find(x=>x.kind==='resume');if(a.id!==latest.id)throw new Error('请切换到最新简历修订后保存');await send({text:`请保存当前简历修订 ${a.revision}`});}));
  $('copy').addEventListener('click',()=>run(async()=>{if(artifact()){await navigator.clipboard.writeText(artifact().text);notice('草稿已复制。');}}));
  $('delivery').addEventListener('click',()=>{
    const a=artifact(),job=current?.recommendations?.find(r=>r.job_id===current.job_id)?.job;if(!a)return;
    if(window.OfferPilotWorkbench?.enabled){window.OfferPilotWorkbench.reviewGreeting(current.id,a.id);return;}
    showView('queue');let panel=document.getElementById('wa-handoff');if(!panel){panel=node('section',undefined,'wa-handoff');panel.id='wa-handoff';document.getElementById('wa-handoff-slot').append(panel);}
    panel.replaceChildren(node('strong',`${job?.company || '目标公司'} / ${job?.title || '目标岗位'}`),node('p','Agent 草稿未同步到原发送器，也未发送。请复制后在原流程核对；原有审批、文案与发送确认继续生效。'),node('p',a.text),button('复制 Agent 文案',async()=>{await navigator.clipboard.writeText(a.text);panel.append(node('p','已复制。'));}));
    const row=state.snapshot?.queue?.find(r=>String(r.id)===current.job_id&&r.status==='approved');if(row){state.queueApprovedSelection.add(current.job_id);renderQueue(state.snapshot);}
    panel.scrollIntoView({block:'start',behavior:'auto'});
  });
  $('open-github').addEventListener('click',()=>showView('resume'));
  $('material-form').addEventListener('submit',event=>{event.preventDefault();run(async()=>{
    if(mode!=='user')throw new Error('当前工作区不可用，暂时无法整理材料');
    if(!$('material-consent').checked)throw new Error('请核对模型处理授权');
    const file=$('material-file').files[0],text=$('material-text').value.trim();if(file&&text)throw new Error('请选择文件或粘贴文字其中一种');
    const kind=$('attachment-kind').value,materialId=$('existing-material').value;
    if(!file&&!text&&(!materialId||kind!=='experience'))throw new Error('请粘贴原文、上传文件，或选择一份已确认的经历材料');
    const name=$('material-name').value.trim(),role=$('material-role').value.trim();
    if(kind==='experience'&&(!role||(!name&&!materialId)))throw new Error('请填写经历名称和目标岗位');
    await ensureConversation();
    const payload={kind,name,role,model_consent:true};
    if(file){if(file.size>5*1024*1024)throw new Error('文件不能超过 5 MB');payload.filename=file.name;payload.content_base64=await readFileAsBase64(file);}else if(text)payload.text=text;else payload.material_id=materialId;
    const signature=JSON.stringify([mode,current.id,payload]);
    if(materialSubmission?.signature!==signature)materialSubmission={signature,event_id:crypto.randomUUID()};
    payload.event_id=materialSubmission.event_id;
    const ticket=epoch;materialSubmitting=true;notice('');controls();
    try {const value=await api(`/conversations/${current.id}/attachments`,payload);if(ticket!==epoch)return;await accept(value);materialSubmission=null;$('material-form').hidden=true;$('toggle-material').setAttribute('aria-expanded','false');}
    finally {materialSubmitting=false;controls();}
  });});
  document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>{queueMicrotask(()=>{if(mode===state.mode)return;keepInput();epoch++;closeStream();mode=state.mode;availableMaterials=[];current=null;events=[];busy=false;submitted=null;selectedArtifact=null;followMessages=true;$('messages').replaceChildren();showResults(false);$('material-form').hidden=true;$('input').value='';render();load();noteEpoch++;noteSnapshot='';$('note-messages').replaceChildren();$('note-status').textContent='';refreshNotes();});}));
  tab('chat');render();load().then(resizeInput);refreshNotes();
  window.OfferPilotAgent={
    snapshot:()=>current,
    send:overrides=>run(()=>send(overrides)),
    open:sid=>run(()=>open(sid)),
    selectContext:async values=>{if(busy||active())throw new Error('当前任务正在执行，请先停止后再切换选择。');busy=true;controls();try{await ensureConversation();await accept(await api(`/conversations/${current.id}/context`,values),false);}finally{busy=false;controls();}},
    material:()=>{ $('material-form').hidden=false;$('toggle-material').setAttribute('aria-expanded','true'); },
  };
})();
