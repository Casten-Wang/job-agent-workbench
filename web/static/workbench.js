'use strict';

(() => {
  const $ = id => document.getElementById(`wb-${id}`);
  if (!$('shell')) return;
  const legacy = new URLSearchParams(location.search).get('workbench') === 'legacy';
  if (legacy) {
    const link = document.createElement('a');link.href='/';link.textContent='切回统一工作台';
    document.querySelector('.topbar').append(link);
    // 旧版模式也要让模拟面试三个页签可用（面板显隐由 CSS 的 data-iv-mode 控制）。
    const ivView = document.getElementById('view-interview');
    const setLegacyIvMode = mode => {
      if (!ivView) return;
      ivView.dataset.ivMode = mode;
      document.querySelectorAll('[data-iv-tab]').forEach(btn => {
        const active = btn.dataset.ivTab === mode;
        btn.classList.toggle('is-active', active);
        if (active) btn.setAttribute('aria-current', 'page'); else btn.removeAttribute('aria-current');
      });
      if (mode === 'tools') showInterviewModule(null);
      else if (mode === 'project') { const cu = document.getElementById('cu-interview-panel'); if (cu) cu.hidden = false; }
    };
    document.querySelectorAll('[data-iv-tab]').forEach(btn => btn.addEventListener('click', () => setLegacyIvMode(btn.dataset.ivTab || 'ci')));
    setLegacyIvMode('ci');
    return;
  }
  const node = (tag,text,cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
  // 线性图标（24×24，currentColor 描边）；用 DOM 创建，符合 CSP（不使用内联样式或 innerHTML）。
  const ICON_PATHS={
    search:['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z','M20 20l-4-4'],
    layers:['M12 3l9 5-9 5-9-5 9-5z','M3 13l9 5 9-5','M3 17l9 5 9-5'],
    file:['M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z','M14 3v5h5','M9 13h6','M9 17h4'],
    upload:['M12 16V4','M7 9l5-5 5 5','M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3'],
    download:['M12 4v12','M7 11l5 5 5-5','M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3'],
    docs:['M8 3h9a2 2 0 0 1 2 2v12','M5 7h9a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2z','M8 12h5','M8 16h5'],
    shield:['M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z','M8.5 12l2.5 2.5 4.5-5'],
    message:['M4 5h16v11H9l-5 4z','M8 9h8','M8 12h5'],
    user:['M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8z','M4 21c0-4 3.6-6 8-6s8 2 8 6'],
    code:['M8 7l-5 5 5 5','M16 7l5 5-5 5','M14 4l-4 16'],
    book:['M12 6c-2-1.5-5-2-8-1.5V19c3-.5 6 0 8 1.5','M12 6c2-1.5 5-2 8-1.5V19c-3-.5-6 0-8 1.5','M12 6v14.5'],
    fileSearch:['M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4','M13 3v5h5V11','M16 13a3 3 0 1 0 0 6 3 3 0 0 0 0-6z','M18.5 18.5L21 21'],
    swap:['M4 8h14','M14 4l4 4-4 4','M20 16H6','M10 12l-4 4 4 4'],
    headset:['M4 14v-2a8 8 0 0 1 16 0v2','M4 14h3v6H5a1 1 0 0 1-1-1z','M20 14h-3v6h2a1 1 0 0 0 1-1z'],
    laptop:['M5 5h14v10H5z','M3 19h18'],
    chat:['M4 5h16v11H9l-5 4z','M8 10.5h.01','M12 10.5h.01','M16 10.5h.01'],
    list:['M9 6h11','M9 12h11','M9 18h11','M4 6h.01','M4 12h.01','M4 18h.01'],
    wave:['M4 10v4','M8 7v10','M12 4v16','M16 7v10','M20 10v4'],
    database:['M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3z','M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6','M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6'],
    bookmark:['M6 3h12v18l-6-4-6 4z'],
    trend:['M3 17l5-5 4 4 8-8','M15 8h5v5'],
    bell:['M6 16V11a6 6 0 0 1 12 0v5l2 2H4z','M10 20a2 2 0 0 0 4 0'],
    sliders:['M4 7h9','M17 7h3','M15 5v4','M4 17h3','M11 17h9','M9 15v4'],
    calendar:['M4 6h16v14H4z','M4 10h16','M8 3v4','M16 3v4'],
    briefcase:['M4 8h16v11H4z','M9 8V5h6v3','M4 13h16'],
    grid:['M4 4h6v6H4z','M14 4h6v6h-6z','M4 14h6v6H4z','M14 14h6v6h-6z'],
    gear:['M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z','M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z'],
    plus:['M12 5v14','M5 12h14'],
    history:['M3 12a9 9 0 1 0 3-6.7','M3 4v4h4','M12 7v5l3 2'],
    paperclip:['M20 11l-8.5 8.5a5 5 0 0 1-7-7L13 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L14 7'],
    clipboard:['M9 4h6v3H9z','M9 5H6v16h12V5h-3'],
    folder:['M3 6h6l2 2h10v11H3z'],
    monitor:['M4 4h16v11H4z','M9 20h6','M12 15v5'],
  };
  function icon(name,cls='wb-icon'){
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');svg.setAttribute('class',cls);
    (ICON_PATHS[name] || ICON_PATHS.file).forEach(d=>{const p=document.createElementNS(ns,'path');p.setAttribute('d',d);svg.append(p);});
    return svg;
  }
  // 能力 → 图标；未列出的用 file。
  const CAP_ICON={profile_import:'download',profile:'user',experience:'layers',experience_details:'docs',github:'code',knowledge:'book',
    jobs:'layers',collect:'search',job_import:'upload',application:'docs',resume:'docs',ats:'fileSearch',variants:'swap',
    queue:'shield',mail:'message',interview:'headset',worksheet:'list',debrief:'wave',library:'database',notes:'bookmark',
    push:'bell',overview:'trend',data:'download',settings:'sliders'};
  // 「全部功能」按任务归类（概念稿 37）；目录里没有列出的能力追加到最后一组。
  const TOOL_GROUPS=[
    ['寻找与申请岗位',['collect','jobs','job_import','application','queue','mail']],
    ['资料与简历',['profile','profile_import','experience','experience_details','github','knowledge','resume','ats','variants']],
    ['面试与成长',['interview','worksheet','debrief','library','notes']],
    ['连接与工具',['overview','push','settings','data']],
  ];
  const button = (text,action,cls='button button-quiet') => {const b=node('button',text,cls);b.type='button';b.addEventListener('click',()=>guard(action,b));return b;};
  const statuses={idle:'准备开始',queued:'排队中',running:'进行中',committing:'正在提交',stopping:'正在停止',waiting_input:'待补充',waiting_approval:'待确认',completed:'已完成',failed:'未完成',stopped:'已停止',active:'面试中',paused:'已暂停',held:'待核对',ready_to_finish:'待复盘'};
  const noteReasons={success:'上次检查成功',unreachable:'暂时无法访问，请检查网络',need_login:'需要登录或验证，任务已暂停',invalid_url:'请提供有效的单条小红书笔记链接',parse_error:'暂时无法解析这条笔记',empty_content:'未取得正文',rate_limited:'平台限流，稍后再试',not_found:'笔记暂不可用',collector_busy:'已有面经正在处理，请稍后再试'};
  const panels=[...document.querySelectorAll('[data-view-panel]')].filter(p=>p.id!=='view-workbench');
  const mainSections=['start','jobs','review','home','tools','application','material','knowledge','notes','settings','business-result'];
  // 任务步骤：每个能力归入一个步骤；没有列出的能力（资料、设置、全部功能等）不显示步骤条。
  const STEPS=[['find','寻找岗位'],['prepare','准备材料'],['review','复核申请'],['interview','模拟面试']];
  const STEP_FOR={jobs:'find',collect:'find',job_import:'find',
    application:'prepare',experience:'prepare',experience_details:'prepare',github:'prepare',resume:'prepare',knowledge:'prepare',variants:'prepare',ats:'prepare',artifact:'prepare',
    queue:'review',business:'review',mail:'hr',push:'hr',
    interview:'interview',debrief:'interview',worksheet:'interview',library:'interview'};
  const STEP_ENTRY={find:'jobs',prepare:'application',review:'queue',interview:'interview'};
  // HR 消息任务有自己的四步（概念稿 W06）；mail 与 push 都归入这一流程。
  const HR_STEPS=[['hr-read','整理消息'],['hr-draft','起草回复'],['hr-send','确认发送'],['hr-prep','准备面试']];
  const HR_ENTRY={'hr-read':'mail','hr-draft':'mail','hr-send':'mail','hr-prep':'interview'};
  const JOB_STATE_LABEL={'已采集':'可准备','已过滤':'已过滤','简历已定制':'材料已备','已投递/已沟通':'已沟通','笔试/测评':'笔试','一面':'一面','二面/终面':'终面','Offer':'Offer','淘汰':'已结束'};
  let selectedJobId='', draftTab='resume', contextOpen=false, focusCollapsed=false;
  let current='home', overview=null, epoch=0, sequence=0, refreshTimer=null, pollTimer=null;
  let lastBusiness=null, lastSettled=null, handledActions=new Set(), notesOffset=0, notesNext=null, noteSubmission=null;
  let workspaceMode=state.mode, needsRestore=true;
  const readDrafts=mode=>{try{return JSON.parse(sessionStorage.getItem(`offerpilot.workbench.forms.${mode}`) || '{}');}catch{return {};}};
  let drafts=readDrafts(workspaceMode);
  function saveDrafts(){try{sessionStorage.setItem(`offerpilot.workbench.forms.${workspaceMode}`,JSON.stringify(drafts));}catch{}}
  function cacheProfileDraft(){
    drafts.profile=collectProfileForm();drafts.profile.truth_confirmed=false;
    for(const id of Object.keys(drafts.fields || {}))if(id.startsWith('profile-'))delete drafts.fields[id];
    saveDrafts();
  }
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

  function setToggleLabel(open){
    const b=$('assistant-toggle'),text=open?'收起任务对话':'展开任务对话';
    let label=b.querySelector('.wb-label');if(!label){label=node('span',undefined,'wb-label');[...b.childNodes].forEach(n=>{if(n.nodeType===3)n.remove();});b.append(label);}
    label.textContent=text;
  }
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
    setToggleLabel($('assistant-toggle').getAttribute('aria-expanded')==='true');
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
    else if(ivMode==='ci')Promise.resolve(window.OfferPilotComprehensive?.refreshSources?.()).then(prefillInterview);
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
    if(name==='workbench'||name==='home')name='start';
    if(name==='overview-home')name='home';
    if(name==='collect'&&!options.legacy){options={...options,jobsTab:'collect'};name='jobs';}
    const cap=capability(name), view=(name==='jobs'||cap?.view==='jobs')&&!options.legacy?'jobs-inplace':(cap?.view || name);
    if(view!=='jobs-inplace'){toggleJobEntry('');restoreBorrowed();}
    if(name!=='queue'&&state.queueDeliveryOpen&&!state.queueDeliveryBusy&&dom.queueDeliveryPanel?.parentElement===$('review-host'))closeDeliveryModal();
    if(name!=='mail'&&state.hrReplyModalOpen&&!state.hrReplyBusy&&dom.hrReplyConfirmPanel?.parentElement?.id==='wb-hr-confirm-host')closeHrReplyModal();
    if(name!=='mail')restoreHrReplyPanel();
    current=name;document.body.dataset.wbCapability=name;notice('');
    const root=document.getElementById('view-workbench');root.hidden=false;$('shell').hidden=false;
    mainSections.forEach(id=>$(id).hidden=true);
    panels.forEach(p=>p.hidden=p.dataset.viewPanel!==view);
    document.getElementById('wa-overview').hidden=view!=='overview';
    document.getElementById('wa-results').hidden=true;
    $('context').hidden=!((name==='interview'&&contextOpen)||(name==='application'&&(contextOpen||!openContext()?.job_id)));
    if(view==='jobs-inplace'){$('jobs').hidden=false;selectJobsTab(options.jobsTab || 'pool');renderJobPicker();if(name==='job_import'&&$('jobs-entry').dataset.kind!=='json')toggleJobEntry('json');}
    else if(name==='queue'){$('review').hidden=false;renderReviewGate();}
    else if(view==='experience'){$('material').hidden=false;window.OfferPilotAgent?.material();}
    else if(view==='application'){$('application').hidden=false;renderDraft();}
    else if(mainSections.includes(view))$(view).hidden=false;
    $('breadcrumb').textContent=name==='start'?'':cap?.label || ({tools:'全部功能',collect:'采集岗位',jobs:'寻找岗位',queue:'复核申请',mail:'HR 消息',profile:'我的资料',resume:'定制简历',interview:'模拟面试',push:'信息推送预览',data:'数据与设置',artifact:'草稿与结果',business:'处理结果',home:'工作总览'}[name] || name);
    if(STEP_FOR[name]&&openContext()?.messages?.length)$('breadcrumb').textContent=openContext().title || $('breadcrumb').textContent;
    else if(name==='jobs')$('breadcrumb').textContent='寻找岗位';
    renderTaskChrome();
    const hub=name==='start'||mainSections.includes(view)||['experience','overview','artifact','business','jobs-inplace'].includes(view)?'workbench':HUB_FOR_VIEW[view];
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
    const openCopilot=['jobs','application','experience','artifact','business','queue'].includes(name)||['application','experience','artifact','business','jobs-inplace'].includes(view);
    setAssistantOpen(openCopilot,false);
    const anchor=view==='jobs-inplace'?null:(options.anchor || cap?.anchor);
    if(anchor)requestAnimationFrame(()=>reveal(anchor));
    if(!options.noHash){const hash='#workbench/'+encodeURIComponent(name);if(location.hash!==hash)history.pushState({workbench:name},'',hash);}
    if(options.focus)$('main').focus({preventScroll:true});
    syncInterviewFocus();
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
    // 草稿在「准备材料」步骤内就地显示，不再切到单独的结果页。
    if(!show){navigate('application');return;}
    if(current!=='application')navigate('application');
    const id=document.getElementById('wa-artifact')?.value;
    const kind=openContext()?.artifacts?.find(a=>a.id===id)?.kind;
    if(id==='material'){navigate('artifact');document.getElementById('wa-results').hidden=false;return;}
    if(kind)draftTab=kind;
    renderDraft();
  }

  // ---- W06 HR 消息与日程（就地）----
  function hrStage(){
    if(state.hrReplyModalOpen)return 'hr-send';
    const id=String(state.hrSelectedId || '');
    if(id&&String(state.hrDrafts?.[id] || '').trim())return 'hr-draft';
    return 'hr-read';
  }
  function hrReplyHost(){
    if(current!=='mail'||!document.body.classList.contains('wb-task-shell'))return null;
    let host=document.getElementById('wb-hr-confirm-host');
    const form=document.getElementById('hr-reply-form');
    if(!host&&form){host=node('div',undefined,'wb-hr-confirm-host');host.id='wb-hr-confirm-host';form.after(host);}
    return host;
  }
  function restoreHrReplyPanel(){
    const panel=dom.hrReplyConfirmPanel,home=document.getElementById('hr-conversations-panel');
    if(panel&&home&&panel.parentElement?.id==='wb-hr-confirm-host')home.after(panel);
  }

  // ---- W05 面试专注模式：沿用任务上下文；面试进行中收起通用任务对话，只保留面试官一条对话 ----
  function prefillInterview(){
    const snap=openContext(),jobSel=document.getElementById('ci-job'),verSel=document.getElementById('ci-resume-version');
    const setIf=(sel,value)=>{if(sel&&value&&!sel.value&&[...sel.options].some(o=>o.value===String(value))){sel.value=String(value);sel.dispatchEvent(new Event('change',{bubbles:true}));}};
    setIf(jobSel,snap?.job_id || selectedJobId);
    setIf(verSel,snap?.resume_version_id || snap?.saved_versions?.at(-1)?.resume_version_id);
    syncInterviewFocus();
  }
  function interviewLive(){const stage=document.getElementById('ci-stage');return Boolean(stage&&!stage.hidden);}
  function syncInterviewFocus(){
    const focus=current==='interview'&&interviewLive();
    $('shell').classList.toggle('wb-interview-focus',focus);
    // 进入面试时收起一次；用户之后手动展开则尊重其选择。
    if(focus&&!focusCollapsed){focusCollapsed=true;setAssistantOpen(false,false);}
    if(!focus)focusCollapsed=false;
  }

  // ---- W03 材料协作编辑（就地）----
  function draftArtifacts(){
    const snap=openContext(),list=snap?.artifacts || [];
    return {snap,resume:[...list].reverse().find(a=>a.kind==='resume'),greeting:[...list].reverse().find(a=>a.kind==='greeting')};
  }
  function renderDraft(){
    const {snap,resume,greeting}=draftArtifacts(),panel=$('draft');
    const has=Boolean(resume||greeting);panel.hidden=!has;
    $('application-lede').textContent=has?'草稿已生成。选中一段文字可以针对它提修改；修改由助手完成并保留事实来源。':'选择目标岗位和已确认经历，助手会准备简历与招呼语草稿。';
    $('prepare').textContent=has?'重新生成草稿':'准备简历与招呼语';
    if(!has)return;
    if(draftTab==='resume'&&!resume)draftTab='greeting';
    if(draftTab==='greeting'&&!greeting)draftTab='resume';
    panel.querySelectorAll('[data-wb-draft]').forEach(b=>{const on=b.dataset.wbDraft===draftTab;b.setAttribute('aria-selected',String(on));b.disabled=(b.dataset.wbDraft==='resume'&&!resume)||(b.dataset.wbDraft==='greeting'&&!greeting);});
    const host=$('draft-host');host.replaceChildren();
    const art=draftTab==='greeting'?greeting:resume;
    if(draftTab==='sources'){
      const refs=new Set([...(resume?.source_map || []).flatMap(b=>b.claim_ids || []),...(greeting?.source_map || [])]);
      const claims=(snap.materials || []).flatMap(m=>(m.claims || []).map(c=>({...c,material:m.name}))).filter(c=>refs.has(c.claim_id));
      host.append(node('p','以下是草稿引用的已确认经历。模型检查通过后仍需本人复核。','wb-sub'));
      if(!claims.length)host.append(node('p','这份草稿没有记录引用来源。','wb-empty'));
      claims.forEach(c=>{const row=node('div',undefined,'wb-source-row');row.append(node('small',c.material || '已确认经历'),node('p',c.text));host.append(row);});
    }else{
      const paper=node('article',undefined,'wb-paper');paper.tabIndex=0;paper.setAttribute('aria-label',draftTab==='resume'?'简历草稿正文':'招呼语正文');
      String(art?.text || '').split('\n').forEach(line=>{
        const heading=/^(#{1,3}) (.*)$/.exec(line);
        if(heading)paper.append(node(`h${Math.min(heading[1].length+1,4)}`,heading[2]));
        else if(line.trim())paper.append(node('p',line.startsWith('- ')?`• ${line.slice(2)}`:line));
      });
      host.append(paper);
      if(art?.diff){
        const changes=art.diff.split('\n').filter(l=>/^[+-][^+-]/.test(l)).map(l=>(l[0]==='+'?'新增：':'删除：')+l.slice(1));
        if(changes.length){const d=node('details',undefined,'wb-draft-diff');d.append(node('summary',`本次修订改动 ${changes.length} 处`));changes.slice(0,40).forEach(c=>d.append(node('p',c)));host.append(d);}
      }
    }
    const saved=(snap.saved_versions || []).length;
    $('draft-state').textContent=art?`${draftTab==='resume'?'简历':'招呼语'}修订 ${art.revision}${saved?` / 已保存 ${saved} 个正式版本`:''}`:'';
    $('draft-save').hidden=draftTab!=='resume'||!resume;
    const job=jobById(snap.job_id);
    $('draft-review').disabled=!greeting;
    $('draft-summary').textContent=greeting?(job?.offerpilot_id?'核对后同步为发送文案，再进入复核。':'这个岗位没有关联平台记录，复核时可复制文案人工申请。'):'生成招呼语后可以进入复核申请。';
    $('draft-revise').hidden=true;
  }
  function selectedDraftText(){
    const sel=window.getSelection(),paper=$('draft-host').querySelector('.wb-paper');
    if(!sel||sel.isCollapsed||!paper||!paper.contains(sel.anchorNode))return '';
    return sel.toString().trim().slice(0,300);
  }
  function onDraftSelection(){
    if($('draft').hidden)return;
    const text=selectedDraftText();$('draft-revise').hidden=!text;
    if(text)$('draft-quote').textContent=`已选中：「${text.length>40?text.slice(0,40)+'…':text}」`;
  }
  function reviseSelection(){
    const text=selectedDraftText() || $('draft-quote').textContent.replace(/^已选中：「|」$/g,'');
    const input=document.getElementById('wa-input');
    input.value=`请修改${draftTab==='greeting'?'招呼语':'简历'}中这一段：「${text}」。修改要求：`;
    setAssistantOpen(true,true);input.focus();input.setSelectionRange(input.value.length,input.value.length);
    input.dispatchEvent(new Event('input',{bubbles:true}));
  }
  async function draftToReview(){
    const {snap,greeting}=draftArtifacts();
    if(!greeting){notice('还没有招呼语草稿。');return;}
    await reviewGreeting(snap.id,greeting.id);
  }

  // ---- W04 就地发送复核 ----
  const REVIEW_PHRASE='确认发送';
  function deliveryGateOpen(){return $('review-checked').checked&&$('review-phrase').value.trim()===REVIEW_PHRASE;}
  function deliveryHost(){return current==='queue'&&document.body.classList.contains('wb-task-shell')?$('review-host'):null;}
  function renderReviewGate(){
    const open=Boolean(state.queueDeliveryOpen&&dom.queueDeliveryPanel?.parentElement===$('review-host'));
    $('review-gate').hidden=!open;
    // 确认区放在原复核面板的发送按钮之前；关闭时放回任务区。
    const actions=open?dom.queueDeliveryPanel.querySelector('.queue-delivery-actions'):null;
    if(actions&&$('review-gate').nextElementSibling!==actions)actions.before($('review-gate'));
    if(!open&&$('review-gate').parentElement!==$('review'))$('review').append($('review-gate'));
    // 关闭后把原复核面板放回审批队列中的原位置，避免清空任务区时把它删掉。
    if(!open&&dom.queueDeliveryPanel?.parentElement===$('review-host')){
      const results=document.getElementById('queue-delivery-results');
      if(results)results.before(dom.queueDeliveryPanel);else document.getElementById('view-queue')?.append(dom.queueDeliveryPanel);
    }
    $('review-title').textContent=open?'核对本次发送':'复核申请';
    if(!open&&!$('review-host').querySelector('.wb-review-empty')){
      $('review-host').replaceChildren(node('p','在下方「已通过，可以联系」中勾选岗位，生成招呼语后点击「查看并发送」，复核内容会出现在这里。也可以从「准备材料」核对完招呼语后直接进入。','wb-review-empty wb-sub'));
    }
    if(open)$('review-host').querySelector('.wb-review-empty')?.remove();
  }
  function deliveryOpened(){
    $('review-checked').checked=false;$('review-phrase').value='';
    if(current!=='queue')navigate('queue');
    renderReviewGate();updateDeliveryStartState();
    $('main').scrollTop=0;
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
    const filter=$('tool-filter').value.trim().toLowerCase(),caps=overview?.capabilities || [],byId=new Map(caps.map(c=>[c.id,c]));
    const listed=new Set(TOOL_GROUPS.flatMap(g=>g[1])),groups=TOOL_GROUPS.map(([title,ids])=>[title,ids.map(id=>byId.get(id)).filter(Boolean)]);
    const extra=caps.filter(c=>!listed.has(c.id));if(extra.length)groups[groups.length-1][1].push(...extra);
    $('tool-list').replaceChildren();let shown=0;
    groups.forEach(([title,items])=>{
      items=items.filter(c=>!filter||`${c.label}${c.group}${title}`.toLowerCase().includes(filter));if(!items.length)return;
      const group=node('section',undefined,'wb-tool-section');group.append(node('h3',title));
      const ul=node('ul',undefined,'wb-tool-items');
      items.forEach(c=>{
        const li=node('li'),b=node('button',undefined,'wb-tool-item');b.type='button';
        b.append(icon(CAP_ICON[c.id] || 'file'),node('span',c.label));b.disabled=!c.available;if(c.reason)b.title=c.reason;
        b.addEventListener('click',()=>guard(()=>openCapability(c.id),b));li.append(b);ul.append(li);shown++;
      });
      group.append(ul);$('tool-list').append(group);
    });
    if(!shown)$('tool-list').append(node('p','没有匹配功能，请换个关键词。','wb-empty'));
  }
  function renderSettings() {
    const settings=overview?.setup.model;if(!settings)return;
    $('model-status').textContent=settings.message;
    $('platform-status').textContent=overview.setup.platform_connected?'本机岗位组件已就绪，采集前将检查平台连接与必要资料。':overview.setup.platform_error || '本机岗位组件暂未就绪。';
  }

  // ---- 任务式外壳：任务侧栏、步骤条、上下文条 ----
  function jobsList(){return state.snapshot?.mode===state.mode?(state.snapshot.jobs || []):[];}
  function jobById(id){return id?jobsList().find(j=>String(j.id)===String(id)):null;}
  function renderTaskChrome() {
    const step=STEP_FOR[current], snap=openContext();
    $('taskbar').hidden=!step;
    $('shell').dataset.wbStep=step || '';
    if(step){
      const hr=step==='hr', steps=hr?HR_STEPS:STEPS, entry=hr?HR_ENTRY:STEP_ENTRY;
      const order=steps.map(s=>s[0]), at=hr?order.indexOf(hrStage()):order.indexOf(step);
      $('stepper').replaceChildren(...steps.map(([key,label],index)=>{
        const li=node('li',undefined,'wb-step'),b=node('button',undefined,'wb-step-button');b.type='button';
        const state=index<at?'done':index===at?'current':'todo';li.dataset.state=state;
        b.append(node('span',state==='done'?'✓':String(index+1),'wb-step-mark'),node('span',label,'wb-step-label'));
        if(state==='current')b.setAttribute('aria-current','step');
        b.addEventListener('click',()=>guard(()=>openCapability(entry[key])));li.append(b);return li;
      }));
      const job=jobById(snap?.job_id || selectedJobId);
      $('strip-job').textContent=job?`${job.title} / ${job.company}`:'未选择';
      const conv=hr?state.hrThread?.conversation:null;
      if(hr)$('strip-job').textContent=conv?[conv.title,conv.company].filter(Boolean).join(' / ') || '当前会话':'未选择会话';
      const version=(overview?.versions || []).find(v=>v.resume_version_id===snap?.resume_version_id);
      $('strip-version').textContent=version?`${version.job_snapshot?.role || '简历'} ${version.created_at?.slice(5,10) || ''}`.trim():`${overview?.versions?.length || 0} 个版本可选`;
      const material=(overview?.materials || []).find(m=>m.material_id===snap?.material_id);
      $('strip-material').textContent=material?(material.name || '已确认经历'):`${overview?.materials?.length || 0} 段已确认`;
    }
    const taskState=snap?.status&&snap.status!=='idle'?statuses[snap.status] || '':'';
    $('task-state').textContent=taskState;$('task-state').hidden=!taskState||!step;
    renderTaskNav();
  }
  function renderTaskNav() {
    const list=$('task-list'),snap=openContext(),items=[];
    (window.OfferPilotAgent?.sessions?.() || []).slice(0,6).forEach(s=>items.push({key:'c:'+s.id,title:s.title || '求职任务',status:statuses[s.status] || '',open:()=>window.OfferPilotAgent.open(s.id).then(()=>openCapability(snapStep())),current:snap?.id===s.id}));
    (overview?.tasks || []).filter(t=>t.capability==='interview').slice(0,3).forEach(t=>items.push({key:'t:'+t.id,icon:'headset',title:t.title,status:statuses[t.status] || '',open:()=>openCapability(t.capability,t),current:false}));
    list.replaceChildren();
    if(!items.length){list.append(node('li','还没有任务，从「新任务」开始。','wb-task-empty'));return;}
    items.forEach(item=>{
      const li=node('li'),b=node('button',undefined,'wb-task-item');b.type='button';
      const text=node('span',undefined,'wb-task-text');text.append(node('span',item.title,'wb-task-title'));if(item.status)text.append(node('small',item.status,'wb-task-status'));
      b.append(icon(item.icon || 'briefcase'),text);
      if(item.current)b.setAttribute('aria-current','true');
      b.addEventListener('click',()=>guard(item.open,b));li.append(b);list.append(li);
    });
  }
  function snapStep(){
    const snap=openContext();
    if(snap?.artifacts?.length)return 'application';
    if(snap?.job_id)return 'application';
    return 'jobs';
  }

  // ---- W01 开始任务 ----
  function renderStart() {
    const continueList=$('continue-list');continueList.replaceChildren();
    const rows=[];
    (window.OfferPilotAgent?.sessions?.() || []).filter(s=>!['completed','stopped'].includes(s.status)).slice(0,2).forEach(s=>rows.push({title:s.title || '求职任务',sub:statuses[s.status] || '',open:()=>window.OfferPilotAgent.open(s.id).then(()=>openCapability(snapStep()))}));
    [...(overview?.pending || []),...(overview?.tasks || [])].slice(0,Math.max(0,3-rows.length)).forEach(t=>rows.push({icon:t.capability==='interview'?'headset':t.capability==='mail'?'message':'file',title:t.title,sub:statuses[t.status] || t.kind || '',open:()=>openCapability(t.capability,t)}));
    if(!rows.length)continueList.append(node('p','暂无未完成的任务。','wb-empty'));
    rows.forEach(r=>{const row=node('div',undefined,'wb-continue-row'),text=node('div');text.append(node('strong',r.title),node('small',r.sub));row.append(icon(r.icon || 'file','wb-icon wb-icon-lg'),text,button('继续',r.open,'button button-quiet button-small'));continueList.append(row);});
    const mats=$('side-materials');mats.replaceChildren();
    const versions=overview?.versions || [],materials=overview?.materials || [];
    const sideRow=(name,text)=>{const li=node('li',undefined,'wb-side-row');li.append(icon(name),node('span',text));return li;};
    if(versions.length)mats.append(sideRow('file',`简历版本 ${versions.length} 个（最近：${versions[0].job_snapshot?.role || '简历'}）`));
    if(materials.length)mats.append(sideRow('layers',`${materials.length} 段已确认经历`));
    const profileName=state.snapshot?.profile?.name;if(profileName)mats.append(sideRow('user','个人资料已填写'));
    if(!mats.children.length)mats.append(node('li',overview?'还没有可用资料，先补充简历或经历。':'正在读取…','wb-empty'));
    const conn=$('side-connections');conn.replaceChildren();
    if(overview){
      const setup=overview.setup || {};
      [['monitor','招聘平台',setup.platform_connected?'已就绪':'未就绪'],['sliders','模型服务',setup.model?.configured?'已配置':'未配置'],['folder','本机资料',overview.partial?'部分可用':'可用']].forEach(([name,label,value])=>{const li=node('li',undefined,'wb-side-row');li.append(icon(name),node('span',label),node('span',value,'wb-side-value'));conn.append(li);});
    }
  }
  function startTask(intent) {
    const map={jobs:'jobs',application:'application',interview:'interview',notes:'notes'};
    return openCapability(map[intent] || intent);
  }
  async function submitGoal(){
    const text=$('goal-input').value.trim();
    if(!text){$('goal-input').focus();notice('先写下这次想推进的目标。');return;}
    if(window.OfferPilotAgent?.snapshot()?.messages?.length)document.getElementById('wa-new').click();
    await window.OfferPilotAgent.send({text});
    $('goal-input').value='';
    navigate('jobs');setAssistantOpen(true,true);
  }

  // ---- W02 岗位筛选（就地）----
  // 借用原业务节点：粘贴 JD / 导入 JSON 表单与采集面板临时搬进当前任务，离开时放回原处，保留 id、事件与表单值。
  const borrowed=new Map();
  function borrow(id,host){
    const el=document.getElementById(id);if(!el||el.parentElement===host)return el;
    if(!borrowed.has(id))borrowed.set(id,{parent:el.parentElement,next:el.nextSibling});
    host.append(el);return el;
  }
  function restoreBorrowed(only){
    for(const [id,{parent,next}] of borrowed){
      if(only&&!only.includes(id))continue;
      const el=document.getElementById(id);borrowed.delete(id);if(!el)continue;
      if(next&&next.parentNode===parent)parent.insertBefore(el,next);else parent.append(el);
    }
  }
  function selectJobsTab(tab){
    const collect=tab==='collect';
    $('jobs-tab-pool').setAttribute('aria-selected',String(!collect));$('jobs-tab-collect').setAttribute('aria-selected',String(collect));
    $('jobs-pool').hidden=collect;$('jobs-collect').hidden=!collect;
    const grid=document.querySelector('.sg-collect-grid');
    if(grid)grid.id ||= 'wb-borrow-collect-grid';
    if(!collect){if(grid)restoreBorrowed([grid.id]);return;}
    if(grid)borrow(grid.id,$('jobs-collect'));
    if(state.offerpilotConnected&&!state.offerpilotJobsLoaded)loadOfferPilotJobs();
    if(state.offerpilotConnected)maybeRunOfferPilotPreflight();
  }
  function toggleJobEntry(kind){
    const host=$('jobs-entry'),key=host.dataset.kind===kind&&!host.hidden?'':kind;
    restoreBorrowed(['jd-form','jd-result','import-form','import-result']);
    host.hidden=!key;host.dataset.kind=key;
    $('jobs-paste').setAttribute('aria-expanded',String(key==='jd'));$('jobs-json').setAttribute('aria-expanded',String(key==='json'));
    if(key==='jd'){const form=borrow('jd-form',host);borrow('jd-result',host);form?.querySelector('textarea')?.focus();}
    if(key==='json'){const form=borrow('import-form',host);borrow('import-result',host);form?.querySelector('textarea')?.focus();}
  }
  function jobMatches(job){
    const kw=$('jobs-keyword').value.trim().toLowerCase(),city=$('jobs-city').value.trim().toLowerCase();
    if(kw&&!`${job.title} ${job.company} ${job.raw_text || ''}`.toLowerCase().includes(kw))return false;
    if(city&&!String(job.city || '').toLowerCase().includes(city))return false;
    return true;
  }
  function jobStatus(job){
    if(job.risk?.level==='high')return '高风险';
    if(job.approval==='approved')return '已通过';
    if(job.approval==='pending')return '待确认';
    return JOB_STATE_LABEL[job.state] || job.state || '待核对';
  }
  function renderJobPicker(){
    const all=jobsList(),rows=all.filter(jobMatches),body=$('jobs-rows');
    const snap=openContext();if(!selectedJobId&&snap?.job_id)selectedJobId=String(snap.job_id);
    $('jobs-count').textContent=all.length?`显示 ${rows.length} / ${all.length} 个`:'';
    body.replaceChildren();
    if(!all.length){const tr=node('tr'),td=node('td','还没有岗位。可以切换到「平台采集」，或在下方粘贴 JD、导入 JSON。','wb-empty');td.colSpan=6;tr.append(td);body.append(tr);}
    else if(!rows.length){const tr=node('tr'),td=node('td','没有符合条件的岗位，换个关键词试试。','wb-empty');td.colSpan=6;tr.append(td);body.append(tr);}
    rows.slice(0,200).forEach(job=>{
      const id=String(job.id),tr=node('tr');tr.dataset.jobId=id;
      const radio=node('input');radio.type='radio';radio.name='wb-job-choice';radio.value=id;radio.checked=id===selectedJobId;radio.id='wb-job-'+id.replace(/[^\w-]/g,'_');radio.setAttribute('aria-label',`选择 ${job.company} ${job.title}`);
      radio.addEventListener('change',()=>{selectedJobId=id;renderJobPicker();});
      const pick=node('td');pick.append(radio);
      const title=node('td');const label=node('label',job.title || '未命名岗位');label.htmlFor=radio.id;title.append(label);
      tr.append(pick,title,node('td',job.company || ''),node('td',[job.city,job.salary_label].filter(Boolean).join(' / ') || '未提供'),node('td',formatJobScore(job)),node('td',jobStatus(job)));
      if(id===selectedJobId)tr.classList.add('is-selected');
      tr.addEventListener('click',event=>{if(event.target!==radio&&event.target.tagName!=='LABEL'){radio.checked=true;radio.dispatchEvent(new Event('change'));}});
      body.append(tr);
    });
    const job=jobById(selectedJobId)&&rows.some(j=>String(j.id)===selectedJobId)?jobById(selectedJobId):null;
    $('jobs-continue').disabled=!job;
    const detail=$('job-detail');detail.hidden=!job;detail.replaceChildren();
    if(job){
      detail.append(node('h3',`岗位要点 / ${job.company} ${job.title}`));
      const points=jobPoints(job);
      if(points.length){const ul=node('ul');points.forEach(p=>ul.append(node('li',p)));detail.append(ul);}
      else detail.append(node('p','岗位原文较短，没有提炼出要点。','wb-sub'));
      const notes=[...(job.hard_filter || []),...(job.warnings || [])].filter(Boolean);
      if(notes.length)detail.append(node('p','提醒：'+notes.join('；'),'wb-sub'));
      if(job.risk?.level&&job.risk.level!=='low')detail.append(node('p',job.risk.level==='high'?'岗位风险：高风险，不能加入申请队列。':'岗位风险：需要核实。','wb-sub'));
      const more=node('details');more.append(node('summary','查看岗位原文'),node('pre',job.raw_text || '没有保存原文。'));detail.append(more);
    }
  }
  function jobPoints(job){
    const text=String(job.raw_text || '');
    const lines=text.split(/\n|；|;/).map(s=>s.replace(/^[\s\d、.．)）•·\-*]+/,'').trim()).filter(s=>s.length>=6&&s.length<=80);
    const keyed=lines.filter(s=>/要求|负责|熟悉|掌握|经验|能力|优先|职责|参与/.test(s));
    return (keyed.length?keyed:lines).slice(0,3);
  }
  async function continueWithJob(){
    const job=jobById(selectedJobId);if(!job){notice('请先选择一个岗位。');return;}
    await window.OfferPilotAgent.selectContext({job_id:String(job.id)});
    await openCapability('application');
  }
  async function refresh() {
    const ticket=epoch, seq=++sequence;
    try{const data=await request('overview');if(ticket!==epoch||seq!==sequence)return;overview=data;window.OfferPilotAgent?.setToolLabels(data.tool_labels || {});window.OfferPilotAgent?.setOverview(data);renderHome();renderStart();renderContext();renderTaskChrome();if(current==='tools')renderTools();renderSettings();}
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
  document.body.classList.add('wb-enabled','wb-task-shell');$('shell').hidden=false;
  // 静态按钮前加图标（概念稿：任务栏、意图按钮、资料与连接区都带线性图标）。
  for(const [id,name] of [['new-task','plus'],['nav-profile','user'],['all-tools','grid'],['settings-button','gear'],['history-button','history'],
    ['goal-material','paperclip'],['goal-paste-job','clipboard'],['side-add','plus'],['side-manage','sliders'],['jobs-paste','clipboard'],['jobs-json','upload']]){
    const el=$(id);if(el&&!el.querySelector('svg'))el.prepend(icon(name));
  }
  document.querySelectorAll('[data-wb-intent]').forEach(b=>{if(!b.querySelector('svg'))b.prepend(icon({jobs:'search',application:'file',interview:'headset',notes:'bookmark'}[b.dataset.wbIntent],'wb-icon wb-icon-lg'));});
  $('assistant-toggle').prepend(icon('chat'));
  // 原侧栏在任务外壳中隐藏；外观切换搬进「设置」，保留原按钮与事件。
  {const theme=document.querySelector('.sidebar .sidebar-block');if(theme){const section=node('section');section.append(node('h3','外观'),theme);$('settings').append(section);}}
  window.OfferPilotWorkbench={enabled:true,navigate,open:openCapability,showArtifact,refresh,confirmed,reviewGreeting,onMutation,
    projectInterview:()=>{document.body.dataset.wbInterview='project';$('context').hidden=true;$('breadcrumb').textContent='项目与版本面试';setInterviewMode('project');},
    careerNotice:text=>{if(['resume','github','experience_details','interview'].includes(current))notice(text);},
    deliveryPreview:ids=>request('delivery-preview',{ids}),
    deliveryHost,deliveryGateOpen,deliveryOpened,deliveryClosed:()=>renderReviewGate(),hrReplyHost};

  $('home-button').addEventListener('click',()=>navigate('start', {focus:true}));$('all-tools').addEventListener('click',()=>navigate('tools', {focus:true}));
  $('settings-button').addEventListener('click',()=>navigate('settings', {focus:true}));$('tool-filter').addEventListener('input',renderTools);
  $('nav-profile').addEventListener('click',()=>guard(()=>openCapability('profile')));
  $('new-task').addEventListener('click',()=>{document.getElementById('wa-new').click();selectedJobId='';navigate('start',{focus:true});$('goal-input').focus();});
  $('history-button').addEventListener('click',()=>navigate('overview-home',{focus:true}));
  $('goal-form').addEventListener('submit',event=>{event.preventDefault();guard(submitGoal,$('goal-start'),'正在开始任务…');});
  $('goal-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('goal-form').requestSubmit();}});
  $('goal-material').addEventListener('click',()=>guard(()=>openCapability('experience')));
  $('goal-paste-job').addEventListener('click',()=>{navigate('jobs');if($('jobs-entry').hidden)toggleJobEntry('jd');});
  document.querySelectorAll('[data-wb-intent]').forEach(b=>b.addEventListener('click',()=>guard(()=>startTask(b.dataset.wbIntent),b)));
  $('side-add').addEventListener('click',()=>guard(()=>openCapability('experience')));
  $('side-manage').addEventListener('click',()=>navigate('settings',{focus:true}));
  $('strip-edit').addEventListener('click',()=>{const target=current==='interview'?'interview':'application';contextOpen=!(current===target&&contextOpen);navigate(target);if(contextOpen)requestAnimationFrame(()=>$('context-job').focus());});
  $('jobs-tab-pool').addEventListener('click',()=>selectJobsTab('pool'));$('jobs-tab-collect').addEventListener('click',()=>selectJobsTab('collect'));
  for(const id of ['jobs-keyword','jobs-city'])$(id).addEventListener('input',renderJobPicker);
  $('jobs-paste').addEventListener('click',()=>toggleJobEntry('jd'));$('jobs-json').addEventListener('click',()=>toggleJobEntry('json'));
  $('jobs-continue').addEventListener('click',()=>guard(continueWithJob,$('jobs-continue')));
  document.querySelectorAll('[data-wb-draft]').forEach(b=>b.addEventListener('click',()=>{draftTab=b.dataset.wbDraft;renderDraft();}));
  document.addEventListener('selectionchange',onDraftSelection);
  $('draft-revise-button').addEventListener('click',reviseSelection);
  $('draft-save').addEventListener('click',()=>document.getElementById('wa-save').click());
  $('draft-review').addEventListener('click',()=>guard(draftToReview,$('draft-review')));
  for(const type of ['input','change'])for(const id of ['review-checked','review-phrase'])$(id).addEventListener(type,()=>updateDeliveryStartState());
  $('review-back').addEventListener('click',()=>{if(!state.queueDeliveryBusy)closeDeliveryModal();navigate('application');});
  window.addEventListener('offerpilot:agent-sessions',()=>{renderTaskNav();renderStart();});
  {const mail=document.getElementById('view-mail');if(mail)for(const type of ['input','click'])mail.addEventListener(type,()=>{if(current==='mail')requestAnimationFrame(renderTaskChrome);});
   const hrPanel=document.getElementById('hr-reply-confirm-panel');if(hrPanel)new MutationObserver(()=>{if(current==='mail')renderTaskChrome();}).observe(hrPanel,{attributes:true,attributeFilter:['hidden']});}
  {const stage=document.getElementById('ci-stage');if(stage)new MutationObserver(syncInterviewFocus).observe(stage,{attributes:true,attributeFilter:['hidden']});}
  $('next').addEventListener('click',()=>guard(()=>openCapability(overview.next_action.capability,overview.next_action),$('next')));
  $('refresh').addEventListener('click',()=>guard(refresh,$('refresh')));
  $('assistant-toggle').addEventListener('click',()=>{
    const isMobile=window.matchMedia('(max-width: 960px)').matches;
    if(isMobile){
      const show=$('shell').classList.toggle('wb-show-assistant');
      $('assistant-toggle').setAttribute('aria-expanded',String(show));
      setToggleLabel(show);
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
  window.addEventListener('offerpilot:state',()=>{restoreDrafts();scheduleRefresh();if(current==='jobs')renderJobPicker();renderTaskChrome();});
  window.addEventListener('offerpilot:profile-draft',cacheProfileDraft);
  for(const type of ['input','change'])document.addEventListener(type,event=>{
    if(event.target.closest?.('#profile-form')){cacheProfileDraft();return;}
    const field=event.target;if(!draftField(field))return;
    drafts.fields ||= {};drafts.fields[field.id]=field.type==='checkbox'?field.checked:field.value;
    saveDrafts();
  });
  window.addEventListener('offerpilot:agent',event=>{
    const {snapshot,animate}=event.detail;renderContext(snapshot);renderTaskChrome();
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
    selectedJobId='';navigate('start');renderContext(null);notice('');refresh();
  })));
  window.addEventListener('popstate',()=>{const key=decodeURIComponent(location.hash.replace(/^#workbench\//,''));if(['home','start','tools','overview-home'].includes(key)||capability(key))navigate(key,{noHash:true});});
  window.addEventListener('pagehide',()=>{clearTimeout(refreshTimer);clearTimeout(pollTimer);});
  if(state.snapshot?.mode===workspaceMode)restoreDrafts();
  {const key=decodeURIComponent(location.hash.replace(/^#workbench\//,''));navigate(['jobs','tools','settings','overview-home','application','notes','knowledge'].includes(key)?key:'start',{noHash:true});}
  refresh();
})();
