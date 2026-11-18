'use strict';

(() => {
  const $ = id => document.getElementById(`wb-${id}`);
  if (!$('shell')) return;
  const legacy = new URLSearchParams(location.search).get('workbench') === 'legacy';
  if (legacy) {
    const link = document.createElement('a');link.href='/';link.textContent='切回统一工作台';
    document.querySelector('.topbar').append(link);return;
  }
  const node = (tag,text,cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
  const button = (text,action,cls='button button-quiet') => {const b=node('button',text,cls);b.type='button';b.addEventListener('click',()=>guard(action,b));return b;};
  const statuses={idle:'准备开始',queued:'排队中',running:'进行中',committing:'正在提交',stopping:'正在停止',waiting_input:'待补充',waiting_approval:'待确认',completed:'已完成',failed:'未完成',stopped:'已停止',active:'面试中',paused:'已暂停',held:'待核对',ready_to_finish:'待复盘'};
  const noteReasons={success:'上次检查成功',unreachable:'暂时无法访问，请检查网络',need_login:'需要登录或验证，任务已暂停',invalid_url:'请提供有效的单条小红书笔记链接',parse_error:'暂时无法解析这条笔记',empty_content:'未取得正文',rate_limited:'平台限流，稍后再试',not_found:'笔记暂不可用',collector_busy:'已有面经正在处理，请稍后再试'};
  const panels=[...document.querySelectorAll('[data-view-panel]')].filter(p=>p.id!=='view-workbench');
  const mainSections=['home','tools','application','material','knowledge','notes','settings','business-result'];
  let current='home', overview=null, epoch=0, sequence=0, refreshTimer=null, pollTimer=null;
  let lastBusiness=null, lastSettled=null, handledActions=new Set(), notesOffset=0, notesNext=null, noteSubmission=null;
  let workspaceMode=state.mode, needsRestore=true;
  const readDrafts=mode=>{try{return JSON.parse(sessionStorage.getItem(`offerpilot.workbench.forms.${mode}`) || '{}');}catch{return {};}};
  let drafts=readDrafts(workspaceMode);
  function saveDrafts(){try{sessionStorage.setItem(`offerpilot.workbench.forms.${workspaceMode}`,JSON.stringify(drafts));}catch{}}
  function draftField(field) {return field?.id&&field.matches('input,textarea,select')&&field.closest('#wb-main')
    &&!field.matches('[type="password"],[type="file"],[type="hidden"],[type="radio"]')
    &&!field.closest('#wa-approval,#wa-material-approval-slot,#queue-delivery-panel')
    &&!/^wb-context-/.test(field.id)&&!/(confirm|consent|truth|risk|api-?key|model-key|token|secret|password|client-id|answer)/i.test(field.id);}
  function restoreDrafts(){
    if(!needsRestore||state.mode!==workspaceMode)return;needsRestore=false;
    if(drafts.profile){populateProfileForm(drafts.profile);state.profileDirty=true;renderProfile(state.snapshot?.profile || {});}
    for(const [id,value] of Object.entries(drafts.fields || {})){const field=document.getElementById(id);if(draftField(field)){if(field.type==='checkbox')field.checked=value===true;else field.value=value;}}
  }
  function milestoneFor(action,result){
    const map={
      'save-profile':{summary:'已保存个人资料',actions:[{label:'整理项目经历',kind:'material',primary:true},{label:'让助手推荐下一步',kind:'prompt',text:'我已在工作区保存好个人资料，请检查当前进度并告诉我下一步'}]},
      'import-profile-cv':{summary:'已从简历提取资料草稿（请核对后保存）',actions:[{label:'前往个人资料核对保存',kind:'capability',capability:'profile',primary:true}]},
      'parse-jd':{summary:'已解析并录入新岗位',actions:[{label:'让助手评估匹配度并准备材料',kind:'prompt',text:'我刚在工作区录入了新岗位，请帮我查看匹配度并准备申请材料',primary:true}]},
      'import-jobs':{summary:'已导入岗位数据',actions:[{label:'让助手推荐 3 个匹配岗位',kind:'prompt',text:'从已有岗位中结合我的资料推荐 3 个最匹配的岗位',primary:true}]},
      'import-offerpilot-jobs':{summary:'已导入平台采集岗位',actions:[{label:'让助手推荐 3 个匹配岗位',kind:'prompt',text:'从已有岗位中结合我的资料推荐 3 个最匹配的岗位',primary:true}]},
      'confirm':{summary:'已确认审批队列中的岗位',actions:[{label:'去生成并复核招呼语',kind:'prompt',text:'我已确认审批队列中的岗位，请帮我准备或复核申请材料',primary:true}]},
      'sync-greeting':{summary:'已同步核对后的招呼语到发送队列',actions:[{label:'打开发送复核窗口',kind:'capability',capability:'queue',primary:true}]},
      'offerpilot-deliver':{summary:'已提交本批受控投递',actions:[{label:'查看投递任务状态',kind:'prompt',text:'请帮我查看当前投递任务状态，并安排下一步面试准备',primary:true}]},
      'confirm_material':{summary:'已确认并保存项目经历',actions:[{label:'为目标岗位生成简历与招呼语',kind:'prompt',text:'我已确认保存一段项目经历，请结合目标岗位帮我生成简历与招呼语草稿',primary:true}]},
      'save_version':{summary:`已保存正式简历版本${result?.resume_version_id?'：'+result.resume_version_id:''}`,actions:[
        ...(result?.resume_version_id?[{label:'基于此简历模拟面试',kind:'prompt',text:`基于简历版本 ${result.resume_version_id} 开始一场模拟面试`,primary:true}]:[]),
        {label:'去复核并发送招呼语',kind:'capability',capability:'queue'},
      ]},
    };
    return map[action] || null;
  }
  function onMutation(action,result){
    if(result.ok===false)return;
    const form={'save-profile':'profile-form','parse-jd':'jd-form','import-jobs':'import-form','worksheet':'worksheet-form','debrief':'debrief-form','add-variant':'variant-form','add-question':'bank-form'}[action];
    if(action==='save-profile')delete drafts.profile;
    if(action==='import-profile-cv'&&result.profile){drafts.profile={...result.profile,truth_confirmed:false};for(const id of Object.keys(drafts.fields || {}))if(id.startsWith('profile-'))delete drafts.fields[id];}
    if(form)for(const id of Object.keys(drafts.fields || {}))if(document.getElementById(id)?.closest('form')?.id===form)delete drafts.fields[id];
    saveDrafts();scheduleRefresh();
    const milestone=milestoneFor(action,result);
    if(milestone)window.OfferPilotAgent?.notifyGuiMilestone(milestone);
  }

  async function guard(action,control,waitText='') {
    if(control?.disabled)return;
    const prevText=control?control.textContent:'';
    if(control){
      control.disabled=true;control.setAttribute('aria-busy','true');
      if(waitText)control.textContent='处理中…';
    }
    if(waitText)notice(waitText);
    let failed=false;
    try{return await action();}catch(error){failed=true;notice(error.message);}finally{
      if(control){
        control.disabled=false;control.removeAttribute('aria-busy');
        if(waitText&&prevText)control.textContent=prevText;
      }
      if(waitText&&!failed&&$('notice').textContent===waitText)notice('');
    }
  }
  function notice(text) {$('notice').textContent=text || '';$('notice').hidden=!text;}
  async function request(path,payload) {
    const ticket=epoch, mode=state.mode;
    let response;
    try{response=await fetch(`/api/workbench/${path}?mode=${mode}`,{method:payload===undefined?'GET':'POST',cache:'no-store',headers:{'Content-Type':'application/json'},...(payload===undefined?{}:{body:JSON.stringify(payload)})});}
    catch{throw new Error('无法连接本机工作台，未提交的内容仍保留。');}
    const result=await response.json();if(ticket!==epoch||mode!==state.mode)throw new Error('数据范围已切换，请在当前工作区继续。');
    if(!response.ok)throw new Error(result.error || '本次操作未完成');return result;
  }
  function action(tool,args={},id=crypto.randomUUID()) {return request('actions',{tool,arguments:args,operation_id:id});}
  async function confirmed(action,args) {
    const mode=state.mode,ticket=epoch;
    const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify([mode,action,args])));
    if(mode!==state.mode||ticket!==epoch)throw new Error('数据范围已切换，请重新核对当前操作。');
    const hash=[...new Uint8Array(bytes)].map(v=>v.toString(16).padStart(2,'0')).join('');
    const key='offerpilot.workbench.pending.'+hash;
    let id;try{id=sessionStorage.getItem(key);}catch{}
    id ||= crypto.randomUUID();try{sessionStorage.setItem(key,id);}catch{}
    const result=await request('confirmed-action',{action,arguments:args,operation_id:id});
    try{sessionStorage.removeItem(key);}catch{}onMutation(action,result);return result;
  }
  function capability(id) {return overview?.capabilities.find(c=>c.id===id);}
  function openContext() {return window.OfferPilotAgent?.snapshot();}

  function setAssistantOpen(open, mobileShow=false) {
    const isMobile=window.matchMedia('(max-width: 960px)').matches;
    if(isMobile){
      $('shell').classList.toggle('wb-show-assistant',Boolean(mobileShow));
      $('assistant-toggle').setAttribute('aria-expanded',String(Boolean(mobileShow)));
    }else{
      $('shell').classList.toggle('wb-assistant-collapsed',!open);
      $('shell').classList.remove('wb-show-assistant');
      $('assistant-toggle').setAttribute('aria-expanded',String(Boolean(open)));
    }
  }
  function setInterviewMode(ivMode, toolModule=null) {
    const viewEl=document.getElementById('view-interview');if(!viewEl)return;
    viewEl.dataset.ivMode=ivMode;
    document.querySelectorAll('[data-iv-tab]').forEach(btn=>{
      const active=btn.dataset.ivTab===ivMode;
      btn.classList.toggle('is-active',active);
      if(active)btn.setAttribute('aria-current','page');else btn.removeAttribute('aria-current');
    });
    if(ivMode==='tools')showInterviewModule(toolModule);
    else if(ivMode==='project'){const cuPanel=document.getElementById('cu-interview-panel');if(cuPanel)cuPanel.hidden=false;}
    else if(ivMode==='ci')window.OfferPilotComprehensive?.refreshSources?.();
  }
  function setResumeMode(resMode) {
    const viewEl=document.getElementById('view-resume');if(!viewEl)return;
    viewEl.dataset.resumeMode=resMode;
    document.querySelectorAll('[data-resume-tab]').forEach(btn=>{
      const active=btn.dataset.resumeTab===resMode;
      btn.classList.toggle('is-active',active);
      if(active)btn.setAttribute('aria-current','page');else btn.removeAttribute('aria-current');
    });
  }

  function navigate(name,options={}) {
    if(name==='agent'){setAssistantOpen(true,true);document.getElementById('wa-input').focus();return;}
    if(name==='workbench')name='home';
    const cap=capability(name), view=cap?.view || name;
    current=name;document.body.dataset.wbCapability=name;notice('');
    const root=document.getElementById('view-workbench');root.hidden=false;$('shell').hidden=false;
    mainSections.forEach(id=>$(id).hidden=true);
    panels.forEach(p=>p.hidden=p.dataset.viewPanel!==view);
    document.getElementById('wa-overview').hidden=view!=='overview';
    document.getElementById('wa-results').hidden=true;
    $('context').hidden=!['application','interview'].includes(name);
    if(view==='experience'){$('material').hidden=false;window.OfferPilotAgent?.material();}
    else if(mainSections.includes(view))$(view).hidden=false;
    else if(view==='application')$('application').hidden=false;
    $('breadcrumb').textContent=name==='home'?'':cap?.label || ({tools:'全部工具',collect:'采集岗位',jobs:'岗位池',queue:'审批与发送复核',mail:'HR 回复',profile:'个人资料',resume:'定制简历',interview:'模拟面试',push:'信息推送预览',data:'数据与设置',artifact:'草稿与结果',business:'处理结果'}[name] || name);
    const hub=name==='home'||mainSections.includes(view)||['experience','overview','artifact','business'].includes(view)?'workbench':HUB_FOR_VIEW[view];
    dom.navItems.forEach(b=>{const active=b.dataset.hub===hub;b.classList.toggle('is-active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    document.querySelectorAll('.ui-hub-tab').forEach(b=>{const selected=b.dataset.view===view;b.classList.toggle('is-active',selected);if(selected)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
    if(dom.filterBar)dom.filterBar.hidden=true;
    if(view==='interview'){
      if(['worksheet','debrief','library'].includes(name))setInterviewMode('tools',name);
      else if(options.ivMode==='project')setInterviewMode('project');
      else setInterviewMode('ci');
      document.body.dataset.wbInterview='legacy';
    }
    if(view==='resume'){
      setResumeMode(['ats','variants'].includes(name)?'tools':'craft');
      if(state.mode==='user')guard(()=>window.OfferPilotCareer?.refreshVersions());
    }
    if(view==='collect'&&state.offerpilotConnected&&!state.offerpilotJobsLoaded)loadOfferPilotJobs();
    if(view==='collect'&&state.offerpilotConnected)maybeRunOfferPilotPreflight();
    if(view==='profile')maybeAutoPrefillProfile();
    if(view==='mail')ensureHrConversationsLoaded();
    if(name==='notes')guard(()=>loadNotes());
    if(name==='knowledge')guard(loadKnowledge);
    if(name==='settings')renderSettings();
    if(name==='tools')renderTools();
    $('main').scrollTop=0;
    const openCopilot=['home','application','experience','artifact','business'].includes(name)||['application','experience','artifact','business'].includes(view);
    setAssistantOpen(openCopilot,false);
    const anchor=options.anchor || cap?.anchor;
    if(anchor)requestAnimationFrame(()=>reveal(anchor));
    if(!options.noHash){const hash='#workbench/'+encodeURIComponent(name);if(location.hash!==hash)history.pushState({workbench:name},'',hash);}
    if(options.focus)$('main').focus({preventScroll:true});
  }
  function reveal(id) {
    const target=document.getElementById(id);if(!target)return;
    for(let p=target;p&&p!==$('main');p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;
    target.scrollIntoView({block:'start',behavior:'auto'});
  }
  async function openCapability(id,options={}) {
    const cap=capability(id);
    if(cap&&!cap.available){notice(cap.reason);return;}
    if(options.conversation_id)await window.OfferPilotAgent.open(options.conversation_id);
    const context={};for(const key of ['job_id','material_id','resume_version_id'])if(options[key])context[key]=options[key];
    if(options.interview_id&&options.interview_kind!=='comprehensive')context.interview_id=options.interview_id;
    if(Object.keys(context).length)await window.OfferPilotAgent.selectContext(context);
    navigate(id);
    if(options.artifact_id)window.OfferPilotAgent.showArtifact(options.artifact_id);
    if(options.resume_version_id){navigate('resume');await window.OfferPilotCareer?.openVersion(options.resume_version_id);}
    if(options.interview_kind==='project'&&options.interview_id){navigate('interview');await window.OfferPilotCareer?.openInterview(options.interview_id);}
    if(options.interview_kind==='comprehensive'&&options.interview_id){navigate('interview');await window.OfferPilotComprehensive?.openSession(options.interview_id);}
    if(id==='github'){
      const radio=document.querySelector('[name="cu-source-type"][value="github"]');if(radio&&!radio.checked){radio.checked=true;radio.dispatchEvent(new Event('change',{bubbles:true}));}
      reveal('cu-github-panel');
    }
    if(id==='experience_details'){
      const radio=document.querySelector('[name="cu-source-type"][value="manual"]');if(radio&&!radio.checked){radio.checked=true;radio.dispatchEvent(new Event('change',{bubbles:true}));}
    }
    if(id==='resume'&&openContext()?.resume_version_id)await window.OfferPilotCareer?.openVersion(openContext().resume_version_id);
    if(id==='resume'&&overview&&!overview.partial&&!overview.versions.length){notice('还没有保存的简历版本，可以先准备申请材料。');$('notice').append(button('准备申请材料',()=>openCapability('application')));}
    if(['application','experience','profile_import'].includes(id)&&overview&&!overview.setup.model.configured)notice('此任务需要模型连接，可在“连接与设置”中完成配置，也可以先手动完善个人资料。');
  }
  function showArtifact(show) {
    if(!show){navigate('application');return;}
    navigate('artifact');document.getElementById('wa-results').hidden=false;
  }
  function fillSelect(id,rows,value,empty) {
    const select=$(id);const selected=value??select.value;select.replaceChildren(new Option(empty,''));
    rows.forEach(([key,text])=>select.add(new Option(text,key)));select.value=selected || '';
  }
  function renderContext(snapshot=openContext()) {
    const jobs=state.snapshot?.mode===state.mode?(state.snapshot.jobs || []):[];
    fillSelect('context-job',jobs.map(j=>[String(j.id),`${j.company} / ${j.title}`]),snapshot?.job_id || '','选择岗位');
    fillSelect('context-material',(overview?.materials || []).map(m=>[m.material_id,m.name || '已确认经历']),snapshot?.material_id || '','选择已确认经历');
    fillSelect('context-version',(overview?.versions || []).map(v=>[v.resume_version_id,`${v.job_snapshot?.role || '简历'} / ${v.created_at?.slice(0,10) || ''}`]),snapshot?.resume_version_id || '','暂不选择');
    const session=overview?.interview_session;
    fillSelect('context-interview',session?.id?[[session.id,`本场面试 / ${session.user_status || '已记录'}`]]:[],snapshot?.interview_id || '','暂不选择');
    const active=['queued','running','committing','stopping'].includes(snapshot?.status);
    for(const id of ['context-job','context-material','context-version','context-interview'])$(id).disabled=active;
  }
  function list(container,items,empty,render) {
    container.replaceChildren();if(!items.length){container.append(node('p',empty,'wb-empty'));return;}
    items.forEach(item=>container.append(render(item)));
  }
  function entry(item) {
    const row=node('div',undefined,'wb-entry');row.append(node('span',item.title),button(item.status?statuses[item.status] || item.status:'打开',()=>openCapability(item.capability,item)));
    return row;
  }
  function renderHome() {
    if(!overview)return;
    $('next-title').textContent=overview.next_action.title;$('next').disabled=false;
    $('counts').replaceChildren();for(const [key,label] of [['jobs','岗位'],['materials','已确认经历'],['resumes','简历版本'],['mails','HR 回复']]){
      const item=node('div');item.append(node('strong',overview.counts[key] ?? '—'),node('span',label));$('counts').append(item);
    }
    $('shortcuts').replaceChildren();['profile_import','jobs','experience','application','interview','notes'].forEach(id=>{
      const cap=capability(id);if(!cap)return;const b=button(cap.label,()=>openCapability(id),'wb-shortcut');b.disabled=!cap.available;if(cap.reason)b.title=cap.reason;$('shortcuts').append(b);
    });
    list($('tasks'),overview.tasks,'暂无进行中的任务',entry);list($('pending'),overview.pending,'暂无待确认事项',entry);
    list($('results'),overview.results,'完成任务后，结果会保存在这里',item=>{const row=entry(item);row.prepend(node('small',item.kind));return row;});
    $('setup-hint').hidden=!overview.partial&&overview.setup.model.configured;
    $('setup-hint').replaceChildren(node('span',overview.partial?'部分服务暂未连接，已有本地功能仍可使用。':'模型尚未配置，可以先录入资料和岗位。'),button('打开连接设置',()=>openCapability('settings')));
  }
  function renderTools() {
    const filter=$('tool-filter').value.trim().toLowerCase(), groups=new Map();$('tool-list').replaceChildren();
    (overview?.capabilities || []).filter(c=>!filter||`${c.label}${c.group}`.toLowerCase().includes(filter)).forEach(c=>{if(!groups.has(c.group))groups.set(c.group,[]);groups.get(c.group).push(c);});
    groups.forEach((items,title)=>{const group=node('section');group.append(node('h3',title));const buttons=node('div',undefined,'wb-tool-group');items.forEach(c=>{const b=button(c.label,()=>openCapability(c.id));b.disabled=!c.available;if(c.reason)b.title=c.reason;buttons.append(b);});group.append(buttons);$('tool-list').append(group);});
    if(!groups.size)$('tool-list').append(node('p','没有匹配功能，请换个关键词。','wb-empty'));
  }
  function renderSettings() {
    const settings=overview?.setup.model;if(!settings)return;
    $('model-status').textContent=settings.message;
    $('platform-status').textContent=overview.setup.platform_connected?'本机岗位组件已就绪，采集前将检查平台连接与必要资料。':overview.setup.platform_error || '本机岗位组件暂未就绪。';
  }
  async function refresh() {
    const ticket=epoch, seq=++sequence;
    try{const data=await request('overview');if(ticket!==epoch||seq!==sequence)return;overview=data;window.OfferPilotAgent?.setToolLabels(data.tool_labels || {});window.OfferPilotAgent?.setOverview(data);renderHome();renderContext();if(current==='tools')renderTools();renderSettings();}
    catch(error){if(ticket===epoch&&seq===sequence){$('next-title').textContent='本机工作区暂时无法读取';notice(error.message);}}
    clearTimeout(pollTimer);if(ticket===epoch)pollTimer=setTimeout(refresh,overview?.tasks.length||overview?.setup.model.pending?3000:15000);
  }
  function scheduleRefresh(){clearTimeout(refreshTimer);refreshTimer=setTimeout(refresh,200);}

  function sourceLink(url,label) {
    let parsed;try{parsed=new URL(url);}catch{return node('span',label);}
    if(!['https:','http:'].includes(parsed.protocol)||parsed.username||parsed.password)return node('span',label);
    const a=node('a',label);a.href=parsed.href;a.target='_blank';a.rel='noopener noreferrer';a.referrerPolicy='no-referrer';return a;
  }
  function showNote(note) {
    const body=note.note || note;const panel=$('note-document');panel.replaceChildren(node('h3',body.title || '收藏面经'));
    if(body.author)panel.append(node('p',typeof body.author==='string'?body.author:body.author.name || ''));
    panel.append(node('p',body.content || body.message || '尚未取得正文'));
    if(body.source_url)panel.append(sourceLink(body.source_url,'查看原始笔记'));panel.hidden=false;
  }
  async function loadNotes(append=false) {
    if(state.mode!=='user')return;
    const ticket=epoch;
    const [subscriptions,inbox]=await Promise.all([action('note_subscriptions'),action('note_inbox',{offset:append?notesNext || 0:0})]);
    if(ticket!==epoch)return;
    list($('note-subscriptions'),subscriptions.items || [],'还没有订阅，可在上方粘贴一条面经链接。',item=>{
      const row=node('section',undefined,'wb-note-row'),enabled=item.enabled===true||item.enabled===1;
      row.append(sourceLink(item.url || item.source_url,item.title || '单条笔记'),node('p',`${enabled?'已启用':'已暂停'}，每 ${item.interval_hours} 小时检查${item.last_reason?'，'+(noteReasons[item.last_reason] || item.last_reason):''}`),button(enabled?'暂停':'恢复',async()=>{await action(enabled?'pause_note_subscription':'resume_note_subscription',{subscription_id:item.id});await loadNotes();}));return row;
    });
    if(!append)$('note-inbox').replaceChildren();
    const items=inbox.items || [];if(!append&&!items.length)$('note-inbox').append(node('p','暂无面经消息','wb-empty'));
    items.forEach(item=>{const row=node('section',undefined,'wb-note-row'),payload=item.payload || {};row.append(node('strong',payload.title || item.title || '面经更新'),node('p',payload.content || item.message || (item.kind==='note_updated'?'笔记内容有更新，已保存到本机。':'查看已保存的更新内容')));
      const noteId=item.note_id || payload.note_id;if(noteId)row.append(button('阅读正文',async()=>showNote(await action('read_note',{note_id:noteId}))));
      if(!item.read_at&&!item.is_read)row.append(button('标记已读',async()=>{await action('mark_note_read',{message_id:item.id});await loadNotes();}));$('note-inbox').append(row);
    });
    notesOffset=append?notesNext || 0:0;notesNext=inbox.next_offset??(notesOffset+items.length<(inbox.total || 0)?notesOffset+items.length:null);$('note-more').hidden=notesNext===null;
  }
  async function submitNote(subscribe) {
    if(!$('note-form').reportValidity())return;
    const args={url:$('note-url').value.trim()};if(subscribe){args.interval_hours=Number($('note-hours').value);args.keywords=$('note-keywords').value.split(/[,，]/).map(t=>t.trim()).filter(Boolean);}
    const tool=subscribe?'subscribe_note':'collect_note', signature=JSON.stringify([state.mode,tool,args]);
    if(noteSubmission?.signature!==signature)noteSubmission={signature,id:crypto.randomUUID()};
    $('note-status').textContent=subscribe?'正在建立订阅…':'正在读取这条面经…';
    const ticket=epoch,result=await action(tool,args,noteSubmission.id);if(ticket!==epoch)return;
    $('note-status').textContent=result.ok===false?(noteReasons[result.reason] || '本次未完成，请检查链接后继续。'):subscribe?'订阅已建立，只检查这条笔记的更新。':'面经已收藏。';
    if(!subscribe&&result.ok!==false)showNote(result);
    await loadNotes();scheduleRefresh();
  }
  async function loadKnowledge(){
    if(state.mode!=='user')return;
    const ticket=epoch,rows=[];let offset=0;
    do{const page=await action('knowledge_sources',{offset});if(ticket!==epoch)return;rows.push(...(page.items || []));offset=page.next_offset??null;}while(offset!==null);
    $('knowledge-status').textContent=rows.length?`本机共有 ${rows.length} 项项目资料。`:'还没有项目资料。整理经历或导入 GitHub 项目后，会显示在这里。';
    const previous=$('knowledge-project').value;$('knowledge-project').replaceChildren(new Option('选择可检索的项目',''));
    const labels={queued:'排队中',building:'正在整理',ready:'可检索',partial:'部分可用',empty:'暂无可索引内容',failed:'整理失败',interrupted:'整理已中断',waiting_for_source:'待补充来源'};
    list($('knowledge-sources'),rows,'',row=>{
      const item=node('section',undefined,'wb-note-row'),title=row.repository || row.name || (row.source_type==='manual'?'手动经历资料':'项目资料');
      item.append(node('h3',title),node('p',labels[row.status] || row.status));
      if(row.source_commit)item.append(node('small','资料版本 '+row.source_commit.slice(0,10)));
      if(row.snapshot_id){$('knowledge-project').add(new Option(title,row.snapshot_id));item.append(button('查看资料覆盖',async()=>renderCoverage(await action('project_knowledge_context',{snapshot_id:row.snapshot_id}))));}
      return item;
    });
    $('knowledge-project').value=previous;$('knowledge-search').disabled=!rows.some(r=>r.snapshot_id);
  }
  function renderCoverage(value){
    const panel=$('knowledge-coverage');panel.replaceChildren(node('h3','资料覆盖范围'));
    const files=value.files || [];panel.append(node('p',`已记录 ${files.length} 个文件的资料范围。`));
    const list=node('ul');panel.append(list);let shown=0;
    const more=button('显示更多文件',()=>append());
    function append(){files.slice(shown,shown+50).forEach(file=>list.append(node('li',file.path || file.name || String(file))));shown+=50;more.hidden=shown>=files.length;}
    append();panel.append(more);panel.scrollIntoView({block:'start',behavior:'auto'});
  }
  async function searchKnowledge(){
    const id=$('knowledge-project').value;if(!id){notice('请选择已有可用资料的项目。');return;}
    const value=await action('search_project_knowledge',{snapshot_ids:[id],query:$('knowledge-query').value.trim()});
    const panel=$('knowledge-results');panel.replaceChildren(node('h3','找到的项目依据'));
    if(!value.items?.length){panel.append(node('p','没有匹配依据，可换个说法，或检查项目资料覆盖范围。'));return;}
    value.items.forEach(item=>{const section=node('article',undefined,'wb-note-row');section.append(node('h4',`${item.path}，第 ${item.line_start}–${item.line_end} 行`),node('pre',item.text));if(item.source_url)section.append(sourceLink(item.source_url,'查看固定版本原文'));panel.append(section);});
  }
  function renderBusiness(item,activate=true) {
    const panel=$('business-result'),value=item.result || {};panel.replaceChildren(node('h2',item.title));
    if(value.message)panel.append(node('p',value.message));
    if(value.ok===false)panel.append(node('p',noteReasons[value.reason] || '操作未完成，请核对输入与当前状态。'));
    if(value.worksheet)String(value.worksheet).split('\n').filter(Boolean).forEach(text=>panel.append(node('p',text.replace(/^#+\s*/,''))));
    if(value.title)panel.append(node('h3',value.title));if(value.content)panel.append(node('p',value.content));
    const card=value.card || value.classification;
    if(card)for(const [key,label] of [['summary','摘要'],['intent','回复类型'],['event_time','时间'],['company','公司'],['title','岗位'],['weakness_tags','待加强项']])if(card[key])panel.append(node('p',`${label}：${Array.isArray(card[key])?card[key].join('、'):card[key]}`));
    if(value.download){const link=node('a','下载本次结果');link.href=`/api/download/${state.mode}/${encodeURIComponent(value.download)}`;link.download='';panel.append(link);}
    if(value.download_url){const link=node('a','下载 / 打开简历');link.href=value.download_url;panel.append(link);}
    if(value.items?.length)value.items.forEach(row=>{const section=node('section',undefined,'wb-entry');section.append(node('span',row.title || row.name || row.repository || row.content || row.status || '已保存记录'));panel.append(section);});
    if(value.view?.session_id){
      const view=value.view;if(view.question?.text)panel.append(node('p',view.question.text));
      panel.append(button('继续本场面试',async()=>{navigate('interview');await window.OfferPilotCareer?.openInterview(view.session_id);}));
    }else if(item.tool.includes('interview'))panel.append(button('继续面试操作',async()=>{await loadState();await openCapability('interview');}));
    if(item.tool==='review_transcript')panel.append(button('查看复盘',()=>openCapability('debrief')));
    if(item.tool.includes('note'))panel.append(button('打开收藏与订阅',()=>openCapability('notes')));
    if(item.tool.includes('knowledge'))panel.append(button('打开项目知识库',()=>openCapability('knowledge')));
    if(activate){navigate('business');panel.hidden=false;}
  }
  async function reviewGreeting(sid,artifactId) {
    const snapshot=openContext(),artifact=snapshot?.artifacts.find(a=>a.id===artifactId&&a.kind==='greeting');
    if(!artifact||snapshot.id!==sid){notice('请重新选择当前会话的招呼语草稿。');return;}
    navigate('business');const panel=$('business-result');panel.hidden=false;
    panel.replaceChildren(node('h2','核对申请文案'),node('p',artifact.text));
    panel.append(button('复制文案',()=>navigator.clipboard.writeText(artifact.text)));
    const job=(state.snapshot?.jobs || []).find(j=>String(j.id)===snapshot.job_id);
    if(!job?.offerpilot_id){panel.append(node('p','这个岗位没有关联平台采集记录，可复制文案用于人工申请。'));return;}
    panel.append(node('p','确认后将此稿同步为目标岗位的发送文案，再进入最终发送复核。此步不会发送消息。'));
    panel.append(button('确认同步并继续复核',async()=>{
      const result=await confirmed('sync-greeting',{conversation_id:sid,artifact_id:artifactId});
      await loadState();navigate('queue');state.queueApprovedSelection.clear();state.queueApprovedSelection.add(result.job_id);renderQueue(state.snapshot);await openDeliveryPanel();
    },'button'));
  }
  async function handleUI(ui) {
    if(handledActions.has(ui.id))return;handledActions.add(ui.id);
    await openCapability(ui.capability);
    const values=ui.values || {};
    if(ui.operation==='collect_jobs'){
      dom.offerpilotMode.value='collect';dom.offerpilotMode.dispatchEvent(new Event('change',{bubbles:true}));
      for(const [key,id] of [['keywords','collect-keywords'],['city','collect-cities'],['max_pages','collect-pages']]){const field=document.getElementById(id);if(field&&values[key]!==undefined){field.value=values[key];field.dispatchEvent(new Event('input',{bubbles:true}));}}
    }
    if(ui.operation==='prepare_github_project')for(const [key,id] of [['repository','cu-repository'],['role','cu-role'],['contribution','cu-contribution']]){const field=document.getElementById(id);if(field)field.value=values[key] || '';}
    if(['approve_jobs','review_delivery'].includes(ui.operation)){
      const snapshot=openContext(),greeting=snapshot?.artifacts?.filter(a=>a.kind==='greeting').at(-1);
      if(ui.operation==='review_delivery'&&greeting&&values.ids?.length===1&&values.ids[0]===snapshot.job_id){await reviewGreeting(snapshot.id,greeting.id);return;}
      await loadState();if(state.mode!=='user')return;
      const selection=ui.operation==='review_delivery'?state.queueApprovedSelection:state.queueSelection;selection.clear();(values.ids || []).forEach(id=>selection.add(id));renderQueue(state.snapshot);
      if(ui.operation==='review_delivery')await openDeliveryPanel();
    }
  }

  // Reparent original nodes once: IDs, form values and existing event handlers survive.
  const charts = [document.getElementById('pipeline')?.closest('section'), document.getElementById('belt')?.closest('section'),
    document.getElementById('kpi-row')?.closest('section'), document.getElementById('channel-chart')?.closest('.chart-grid'),
    document.getElementById('activity-overview')?.closest('section')];
  charts.filter(Boolean).forEach(panel=>document.getElementById('wa-overview').append(panel));
  panels.forEach(p=>$('content-host').append(p));$('content-host').append(document.getElementById('wa-overview'));
  $('result-host').append(document.getElementById('wa-results'));
  $('assistant-host').append(document.getElementById('wa-panel'));
  $('history').append(document.querySelector('.wa-sessions'));
  $('material-host').append(document.getElementById('wa-material-form'));
  document.getElementById('view-interview').append(document.getElementById('cu-interview-panel'));
  $('approval-slot').append(document.getElementById('wa-approval'));
  $('progress-slot').append(document.getElementById('wa-material-progress'));
  $('main').insertBefore($('context'),$('approval-slot'));
  document.body.classList.add('wb-enabled');$('shell').hidden=false;
  window.OfferPilotWorkbench={enabled:true,navigate,open:openCapability,showArtifact,refresh,confirmed,reviewGreeting,onMutation,
    projectInterview:()=>{document.body.dataset.wbInterview='project';$('context').hidden=true;$('breadcrumb').textContent='项目与版本面试';setInterviewMode('project');},
    careerNotice:text=>{if(['resume','github','experience_details','interview'].includes(current))notice(text);},
    deliveryPreview:ids=>request('delivery-preview',{ids})};

  $('home-button').addEventListener('click',()=>navigate('home', {focus:true}));$('all-tools').addEventListener('click',()=>navigate('tools', {focus:true}));
  $('settings-button').addEventListener('click',()=>navigate('settings', {focus:true}));$('tool-filter').addEventListener('input',renderTools);
  $('next').addEventListener('click',()=>guard(()=>openCapability(overview.next_action.capability,overview.next_action),$('next')));
  $('refresh').addEventListener('click',()=>guard(refresh,$('refresh')));
  $('assistant-toggle').addEventListener('click',()=>{
    const isMobile=window.matchMedia('(max-width: 960px)').matches;
    if(isMobile){
      const show=$('shell').classList.toggle('wb-show-assistant');
      $('assistant-toggle').setAttribute('aria-expanded',String(show));
      if(show)document.getElementById('wa-input').focus();
    }else{
      const nextOpen=$('shell').classList.contains('wb-assistant-collapsed');
      setAssistantOpen(nextOpen,false);
      if(nextOpen)document.getElementById('wa-input').focus();
    }
  });
  $('show-main').addEventListener('click',()=>{setAssistantOpen(false,false);$('main').focus();});
  document.querySelectorAll('[data-iv-tab]').forEach(btn=>btn.addEventListener('click',()=>{
    const tab=btn.dataset.ivTab || 'ci';
    setInterviewMode(tab,tab==='tools'?null:null);
    document.body.dataset.wbInterview=tab==='project'?'project':'legacy';
  }));
  document.querySelectorAll('[data-resume-tab]').forEach(btn=>btn.addEventListener('click',()=>{
    const tab=btn.dataset.resumeTab || 'craft';
    if(tab==='craft'&&['ats','variants'].includes(current))navigate('resume');
    else setResumeMode(tab);
  }));
  for(const [id,field] of [['context-job','job_id'],['context-material','material_id'],['context-version','resume_version_id'],['context-interview','interview_id']])$(id).addEventListener('change',()=>guard(()=>window.OfferPilotAgent.selectContext({[field]:$(id).value})));
  $('prepare').addEventListener('click',()=>guard(async()=>{
    await window.OfferPilotAgent.contextReady();
    const selected=openContext();
    if(!selected?.job_id){notice('请先选择一个目标岗位，或录入 JD。');$('context-job').focus();return;}
    if(!selected?.material_id){notice('请先选择一份已确认经历，或点击补充经历。');$('context-material').focus();return;}
    await window.OfferPilotAgent.send({text:'为当前选定的岗位和已确认经历准备简历与招呼语草稿'});
  },$('prepare')));
  $('add-experience').addEventListener('click',()=>openCapability('experience'));$('add-job').addEventListener('click',()=>openCapability('jobs'));
  $('detailed-experience').addEventListener('click',()=>openCapability('experience_details'));
  document.getElementById('wa-toggle-material').addEventListener('click',()=>{if(!document.getElementById('wa-material-form').hidden)navigate('experience');});
  $('note-form').addEventListener('submit',event=>{event.preventDefault();guard(()=>submitNote(false),$('note-collect'),'正在读取并保存这条面经…');});
  $('note-subscribe').addEventListener('click',()=>guard(()=>submitNote(true),$('note-subscribe'),'正在建立更新订阅…'));
  $('note-refresh').addEventListener('click',()=>guard(()=>loadNotes(),$('note-refresh'),'正在刷新订阅与消息…'));$('note-more').addEventListener('click',()=>guard(()=>loadNotes(true),$('note-more'),'正在加载更多消息…'));
  $('note-check').addEventListener('click',()=>guard(async()=>{const value=await action('note_self_check');$('note-status').textContent=value.ok?'本机面经服务自检通过。此结果不代表平台当前可访问。':'本机面经服务需要检查，请查看服务状态或稍后重新自检。';},$('note-check'),'正在运行面经服务自检…'));
  $('knowledge-refresh').addEventListener('click',()=>guard(loadKnowledge,$('knowledge-refresh'),'正在刷新项目资料列表…'));
  $('knowledge-form').addEventListener('submit',event=>{event.preventDefault();guard(searchKnowledge,$('knowledge-search'),'正在翻阅项目源码与文档…');});
  document.querySelector('[aria-labelledby="cu-knowledge-title"] a')?.addEventListener('click',event=>{event.preventDefault();openCapability('knowledge');});
  $('connect-github').addEventListener('click',()=>openCapability('github'));$('connect-platform').addEventListener('click',()=>openCapability('collect'));
  $('model-settings').addEventListener('click',()=>navigate('data',{anchor:'ai-settings-panel'}));
  window.addEventListener('offerpilot:state',()=>{restoreDrafts();scheduleRefresh();});
  for(const type of ['input','change'])document.addEventListener(type,event=>{
    const field=event.target;if(!draftField(field))return;
    drafts.fields ||= {};drafts.fields[field.id]=field.type==='checkbox'?field.checked:field.value;
    if(field.closest('#profile-form')){drafts.profile=collectProfileForm();drafts.profile.truth_confirmed=false;}
    saveDrafts();
  });
  window.addEventListener('offerpilot:agent',event=>{
    const {snapshot,animate}=event.detail;renderContext(snapshot);
    const item=snapshot.business_results?.at(-1);
    if(item&&item.id!==lastBusiness){lastBusiness=item.id;if(animate){renderBusiness(item);loadState();}}
    if(animate)(snapshot.ui_actions || []).forEach(ui=>guard(()=>handleUI(ui)));
    else (snapshot.ui_actions || []).forEach(ui=>handledActions.add(ui.id));
    if(!['queued','running','committing','stopping'].includes(snapshot.status))scheduleRefresh();
    if(snapshot.status==='completed'&&snapshot.run_id&&lastSettled!==snapshot.run_id){lastSettled=snapshot.run_id;loadState();}
  });
  document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>queueMicrotask(()=>{
    if(workspaceMode===state.mode)return;
    for(const id of Object.keys(drafts.fields || {})){const field=document.getElementById(id);if(draftField(field)){if(field.type==='checkbox')field.checked=field.defaultChecked;else field.value=field.defaultValue || '';}}
    $('main').querySelectorAll('input[type="file"]').forEach(field=>field.value='');
    workspaceMode=state.mode;drafts=readDrafts(workspaceMode);needsRestore=true;
    epoch++;sequence++;overview=null;lastBusiness=null;lastSettled=null;handledActions=new Set();noteSubmission=null;notesNext=null;
    $('note-keywords').value='';$('note-url').value='';$('note-status').textContent='';$('note-document').replaceChildren();$('note-document').hidden=true;
    for(const id of ['note-subscriptions','note-inbox','results','tasks','pending','counts','business-result','knowledge-sources','knowledge-results','knowledge-coverage'])$(id).replaceChildren();
    navigate('home');renderContext(null);notice('');refresh();
  })));
  window.addEventListener('popstate',()=>{const key=decodeURIComponent(location.hash.replace(/^#workbench\//,''));if(key==='home'||capability(key)||key==='tools')navigate(key,{noHash:true});});
  window.addEventListener('pagehide',()=>{clearTimeout(refreshTimer);clearTimeout(pollTimer);});
  if(state.snapshot?.mode===workspaceMode)restoreDrafts();
  navigate('home',{noHash:true});refresh();
})();
