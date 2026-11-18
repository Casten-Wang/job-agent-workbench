'use strict';

(() => {
  const $ = (id) => document.getElementById(`cu-${id}`);
  const key = (name) => `offerpilot.career.user.${name}`;
  let mode = null, epoch = 0, busy = false, configured = false, connected = false;
  let project = null, current = null, draft = null, version = null, failedEvent = null;
  let resumeTemplate = safeLocalGet(key('template')) === 'classic' ? 'classic' : 'professional';
  let sessionId = safeLocalGet(key('session'));
  if (!/^opuser_[A-Za-z0-9_-]{1,64}$/.test(sessionId || '')) sessionId = null;
  let authTimer = null, projectTimer = null, nextPage = null, tree = null;
  let knowledgeTimer = null, knowledgeEpoch = 0;
  let sourceMode = safeLocalGet(key('source')) === 'github' ? 'github' : 'manual';
  const experienceFields = ['kind','name','organization','position','start','end','role','jd','context','contribution','outcome','source_text','portfolio_url'];
  const exp = field => $(`exp-${field.replaceAll('_','-')}`);
  const commands = [...document.querySelectorAll('[data-cu-command]')];
  const statusLabels = {active:'面试中',paused:'已暂停',held:'职责或版本待核实',ready_to_finish:'已答完，待复盘',completed:'复盘已保存'};

  function node(tag, text, className) {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = String(text);
    if (className) n.className = className;
    return n;
  }
  function button(text, action) {
    const n = node('button', text, 'button button-quiet'); n.type = 'button';
    n.addEventListener('click', () => run(action)); return n;
  }
  function appendLinkedText(parent,text) {
    const pattern=/https?:\/\/[^\s<>"'|，。；、（）【】]+/g;
    let end=0;
    for(const match of text.matchAll(pattern)) {
      const url=match[0].replace(/[.,;:!?\])}]+$/g,'');
      let parsed;try{parsed=new URL(url);}catch{continue;}
      if(!['http:','https:'].includes(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password)continue;
      parent.append(text.slice(end,match.index));
      const a=node('a',url);a.href=url;a.target='_blank';a.rel='noopener noreferrer';parent.append(a);
      end=match.index+url.length;
    }
    parent.append(text.slice(end));
  }
  function renderResume(markdown) {
    const document = $('markdown');
    document.replaceChildren();
    document.dataset.resumeTemplate=resumeTemplate;
    let section=false, previous='';
    const role=(draft || version)?.job_snapshot?.role;
    markdown.split('\n').forEach(raw => {
      const line=raw.replace(/`([^`]+)`/g,'$1').trim();
      if(!line)return;
      const heading = /^(#{1,3}) (.*)$/.exec(line);
      if (heading) {
        previous=`h${heading[1].length}`; section=section || previous==='h2';
        document.append(node(previous,heading[2],`resume-${previous}`));
        if(previous==='h1' && role)document.append(node('p',`求职意向 · ${role}`,'resume-role'));
      } else if (line.startsWith('- ')) {
        const p=node('p',undefined,'resume-bullet'), dot=node('span','•','resume-dot'), text=node('span');
        dot.setAttribute('aria-hidden','true');
        const label=/^([^：:]{1,24}[：:])(.*)$/.exec(line.slice(2));
        if(label){text.append(node('b',label[1]));appendLinkedText(text,label[2]);}else appendLinkedText(text,line.slice(2));
        p.append(dot,text);document.append(p);previous='bullet';
      } else {
        const kind=!section ? 'contact' : previous==='h3' && /^(?:(?:19|20)\d{2}|至今)/.test(line) ? 'meta' : /^(作品集|项目链接)：/.test(line) ? 'link':'body';
        const p=node('p',undefined,`resume-${kind}`);appendLinkedText(p,line);document.append(p);previous=kind;
      }
    });
  }
  function controls() {
    const personal = state.mode === 'user';
    $('connect').disabled = busy || !configured;
    $('disconnect').hidden = !connected;
    $('prepare').disabled = busy || !connected || project?.status === 'preparing';
    $('prepare').textContent = project?.status === 'failed' ? '重试整理经历' : '读取项目并整理经历';
    $('prepare-experience').disabled = busy || project?.status === 'preparing';
    $('extract-text').disabled = busy || project?.status === 'preparing';
    $('experience-form').querySelectorAll('input,textarea,select').forEach(input=>{input.disabled=busy || project?.status==='preparing';});
    document.querySelectorAll('[name="cu-source-type"]').forEach(input=>{input.disabled=busy || project?.status==='preparing';});
    $('start-readiness').disabled = busy || project?.status !== 'ready';
    $('save-version').disabled = busy || !draft;
    $('regenerate').disabled = busy || !version;
    $('download').disabled = busy || !version;
    $('print').disabled = busy || !version;
    $('download-pdf').disabled = busy || !version;
    document.querySelectorAll('[name="cu-template"]').forEach(input=>{input.disabled=busy;input.checked=input.value===resumeTemplate;});
    $('start-formal').disabled = busy || !version;
    $('start-formal').hidden = !window.OfferPilotWorkbench?.enabled || !version;
    $('reload').disabled = busy;
    $('more-repositories').disabled = busy;
    const active = personal && current?.status === 'active' && !current.pending_evaluation;
    $('answer').disabled = busy || !active || Boolean(failedEvent);
    $('submit').disabled = busy || !active || Boolean(failedEvent);
    if (!$('submit').dataset.defaultText) $('submit').dataset.defaultText = $('submit').textContent;
    $('submit').textContent = busy && active ? '正在整理反馈…' : $('submit').dataset.defaultText;
    $('refresh-session').disabled = busy || !sessionId;
    commands.forEach(b => {
      const c = b.dataset.cuCommand;
      b.hidden = c === 'resume' ? current?.status !== 'paused' : c === 'retry'
        ? !(failedEvent || current?.pending_evaluation || current?.last_error) : false;
      b.disabled = busy || !current || current.status === 'completed'
        || (!['resume','retry','finish'].includes(c) && !active) || (Boolean(failedEvent) && c !== 'retry');
    });
    $('to-draft').hidden = current?.status !== 'completed' || current?.interview_mode === 'mock_interview';
    $('to-draft').disabled = busy;
    ['project-form','experience-form','answer-form'].forEach(id => $(id).setAttribute('aria-busy', String(busy)));
  }
  function showSource(source) {
    sourceMode=source; safeLocalSet(key('source'),source);
    $('github-panel').hidden=source!=='github'; $('experience-panel').hidden=source!=='manual';
    document.querySelectorAll('[name="cu-source-type"]').forEach(input=>{input.checked=input.value===source;});
    $('connection').textContent=source==='manual' ? '自主导入（无需 GitHub）' : connected ? 'GitHub 已连接' : 'GitHub 项目';
  }
  function message(text) { $('message').textContent = text; $('interview-message').textContent = text;window.OfferPilotWorkbench?.careerNotice(text); }
  function renderEmptyResumePreview() {
    const doc = $('markdown');
    if (!doc) return;
    doc.replaceChildren(
      node('p', '右侧实时预览区已就绪。在左侧整理并确认项目经历后，点击“生成简历预览”，A4 排版效果会实时展示在这里。', 'hint')
    );
  }
  function clearResume() {
    draft=null; version=null;
    if (window.OfferPilotWorkbench?.enabled) {
      $('resume-preview').hidden=false;
      renderEmptyResumePreview();
    } else {
      $('resume-preview').hidden=true;
    }
    $('saved-resume').hidden=true;
    $('save-confirmed').checked=false;
    safeLocalSet(key('version'), '');
  }
  async function checkProfile(valid) {
    const response=await fetch('/api/profile?mode=user', {cache:'no-store'});
    const data=await response.json();
    if (!response.ok) throw new Error(data.error || '个人资料读取失败，请重试。');
    if (!valid()) return false;
    if (!data.profile?.truth_confirmed || !data.profile?.basic?.name || state.profileDirty) {
      message('请填写姓名、核对真实性并保存个人资料，再返回定制简历继续；项目选择已保留。');
      showView('profile');
      setStatus('请填写姓名、确认真实性并保存，然后返回定制简历继续。', 'warn');
      return false;
    }
    return true;
  }
  async function api(path, data) {
    const separator = path.includes('?') ? '&' : '?';
    const r = await fetch(`/api/career-user${path}${separator}mode=user`, {method:data ? 'POST':'GET', cache:'no-store',
      headers:{Accept:'application/json', ...(data ? {'Content-Type':'application/json'}:{})},
      ...(data ? {body:JSON.stringify({...data,mode:'user'})}:{})});
    const value = await r.json();
    if (!r.ok || value.ok !== true) throw new Error(value.error || '操作未完成，请刷新后重试。');
    return value;
  }
  async function knowledgeStatus(valid) {
    const data = await api('/knowledge/sources?limit=100');
    if (!valid()) return;
    const pending = data.items.filter(item => ['pending','queued','building'].includes(item.status)).length;
    const available = data.items.filter(item => item.snapshot_id).length;
    const limited = data.items.filter(item => item.status === 'partial').length;
    const failed = data.items.filter(item => ['failed','interrupted'].includes(item.status)).length;
    const attachments = data.items.reduce((total,item) => {
      const reasons = item.coverage?.exclusion_reasons || {};
      return total + (reasons.non_text_attachment || 0) + (reasons.binary || 0);
    }, 0);
    const documentCount = data.items.reduce((total,item) => total + (item.coverage?.document_files || 0),0);
    const documentUnits = data.items.reduce((total,item) => total + (item.coverage?.document_text_units || 0),0);
    const ocrUnits = data.items.reduce((total,item) => total + (item.coverage?.document_ocr_units || 0),0);
    $('knowledge-status').textContent = `本机项目资料：${available} 项可用${limited ? `（${limited} 项覆盖不完整）` : ''}${pending ? `，${pending} 项正在后台准备` : ''}${failed ? `，${failed} 项未完成，可刷新重试` : ''}。${documentCount ? `文档：${documentCount} 份，${documentUnits} 页/张文字可检索${ocrUnits ? `（${ocrUnits} 页/张经 OCR 识别，需核对）` : ''}。` : ''}${attachments ? `${attachments} 个附件或二进制文件未纳入文本索引。` : ''}${data.total > data.items.length ? `共 ${data.total} 项，当前显示前 ${data.items.length} 项状态。` : ''}`;
    $('knowledge-status').hidden = false;
    if (pending) knowledgeTimer = setTimeout(() => knowledgeStatus(valid).catch(error => {
      if (valid()) $('knowledge-status').textContent = error.message;
    }), 2000);
  }
  function warmKnowledge(data) {
    clearTimeout(knowledgeTimer);
    const start = ++knowledgeEpoch;
    const valid = () => start === knowledgeEpoch && state.mode === 'user';
    // Independent of the form's busy state: opening Web starts preparation.
    api(data ? '/knowledge/sources' : '/knowledge/warmup', data || {})
      .then(() => knowledgeStatus(valid)).catch(error => {
        if (valid()) { $('knowledge-status').textContent = `项目资料暂未就绪：${error.message}`; $('knowledge-status').hidden = false; }
      });
  }
  async function run(action) {
    if (busy || state.mode !== 'user') return;
    const startEpoch = epoch;
    const valid = () => epoch === startEpoch && state.mode === 'user';
    busy = true; controls(); message('正在处理，马上就好…');
    try { await action(valid);if(valid())window.OfferPilotWorkbench?.careerNotice(''); } catch(e) { if (valid()) message(e.message); }
    finally { if (valid()) { busy = false; controls(); } }
  }
  function sourceLink(item) {
    const label = item.verification_scope==='user_supplied' ? item.label : `${item.path} · L${item.line_start}–${item.line_end}`;
    try {
      const url = new URL(item.source_url);
      if (url.protocol !== 'https:' || url.hostname !== 'github.com' || !url.pathname.includes(`/blob/${item.commit_sha || project?.source_commit || ''}/`)) return node('span',label);
      const a = node('a',label); a.href = url.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
    } catch { return node('span',label); }
  }
  async function loadRepositories(valid, page=1) {
    const data = await api(`/github/repositories?page=${page}`);
    if (!valid()) return;
    if (page === 1) $('repositories').replaceChildren();
    data.items.forEach(repo => {
      const row = node('div',undefined,'career-task cu-repo-row');
      const description = node('div');
      description.append(node('strong',repo.full_name), node('p',`${repo.private?'私有':'公开'}${repo.fork?' · Fork':''} · ${repo.language || '未标记语言'}`,'hint'));
      if (repo.description) description.append(node('p',repo.description));
      const actions = node('div',undefined,'career-actions');
      actions.append(button('选择此项目',async () => { if(project?.status==='preparing')throw new Error('当前项目正在准备，请完成后再选择其他项目。');clearResume();safeLocalSet(key('project'),'');project=null;$('project-review').hidden=true;$('contribution').value='';$('repository').value=repo.full_name; $('project-form').hidden=false; $('repository-section').open=false; $('contribution-confirmed').checked=false; $('model-consent').checked=false; warmKnowledge({repository:repo.full_name}); message(`已选择 ${repo.full_name}，请说明目标岗位和个人职责。`); $('role').focus(); }),
        button('浏览文件',v => browse(repo.full_name,1,v)));
      row.append(description,actions); $('repositories').append(row);
    });
    nextPage=data.next_page; $('more-repositories').hidden=!nextPage; $('repository-section').hidden=false;
    message(data.items.length ? '仓库列表已载入。选择项目后再读取源码，不会自动分析全部仓库。':'当前授权未返回仓库，请核对 GitHub 的仓库与组织授权。');
  }
  async function browse(repository,page,valid) {
    const data=await api(`/github/tree?repository=${encodeURIComponent(repository)}&page=${page}`);
    if (!valid()) return;
    tree={repository,commit:data.source_commit,next:data.next_page};
    $('browser').hidden=false; $('browser').open=true; $('browser-title').textContent=`${repository} · 文件清单（${data.total} 项）`;
    if (page===1) { $('files').replaceChildren(); $('file-text').hidden=true; }
    data.items.forEach(item => $('files').append(button(item.path,async v => {
      const file=await api(`/github/file?repository=${encodeURIComponent(repository)}&commit=${data.source_commit}&path=${encodeURIComponent(item.path)}`);
      if (v()) { $('file-text').textContent=file.path+'\n\n'+file.text+(file.truncated?'\n\n（预览已截断）':''); $('file-text').hidden=false; }
    })));
    $('more-files').hidden=!tree.next;
  }
  async function connectState(valid) {
    await loadVersions(valid);
    const saved=safeLocalGet(key('version'));
    if (saved && /^resume_[a-f0-9]{24}$/.test(saved)) {
      const value=await api(`/resumes/${saved}`); if(valid())showVersion(value);
    }
    const id=safeLocalGet(key('project'));
    if (id && /^project_[a-f0-9]{32}$/.test(id)) await projectStatus(id,valid);
    if (!valid() || sourceMode==='manual') {
      if(valid() && !project)message('可直接填写实习、工作、项目或作品集，无需连接 GitHub。');
      return;
    }
    const data=await api('/github/status'); if (!valid()) return;
    configured=data.configured; connected=data.connected;
    $('connection').textContent=connected ? `已连接 ${data.login}` : configured ? '等待 GitHub 授权':'首次配置';
    $('setup').open=!configured;
    message(connected ? 'GitHub 已连接。' : configured ? '点击连接 GitHub，按页面验证码完成授权。':'先创建一次 GitHub 登录应用，再在下方保存公开的 Client ID。');
    if (connected) await loadRepositories(valid);
    else { $('repository-section').hidden=true; $('repositories').replaceChildren(); $('browser').hidden=true; }
  }
  async function pollAuth(ticket,valid) {
    if (!valid()) return;
    try {
      const data=await api('/github/poll',{ticket}); if (!valid()) return;
      if (data.status==='connected') { $('device').hidden=true; await connectState(valid); controls(); return; }
      if (data.status!=='pending') { $('device-status').textContent='授权已取消或过期，请重新连接。'; return; }
      authTimer=setTimeout(()=>pollAuth(ticket,valid),Math.max(5,data.interval)*1000);
    } catch(e) { if(valid()) $('device-status').textContent=e.message+'；请重新连接。'; }
  }
  function showProject(value) {
    project=value;
    const manual=value.source_type==='manual'; showSource(manual ? 'manual':'github');
    if(manual)experienceFields.forEach(field=>{exp(field).value=value.experience[field] || '';});
    if (value.status!=='ready') {
      if(value.status==='failed') {
        if(manual) {
          experienceFields.forEach(field=>{exp(field).value=value.experience[field] || '';});
          $('exp-confirmed').checked=false; $('exp-consent').checked=false;
        } else {
          $('repository').value=value.repository; $('role').value=value.role; $('jd').value=value.jd || ''; $('contribution').value=value.contribution;
          $('project-form').hidden=false; $('repository-section').open=false;
          $('contribution-confirmed').checked=false; $('model-consent').checked=false;
        }
        $('project-review').hidden=true;
      }
      const phase = {'冻结仓库版本并读取源码':'正在读取项目内容','整理源码证据与待确认表述':'正在整理项目经历'}[value.phase] || value.phase;
      message(value.error || `${phase}…`); controls(); return;
    }
    $('project-review').hidden=false;
    $('project-positioning').textContent=value.positioning ? `岗位定位：${value.positioning}` : '';
    $('project-summary').textContent=value.project_name && value.project_overview
      ? `${value.project_name}：${value.project_overview}` : value.summary;
    $('coverage').textContent=manual ? `材料版本 ${value.source_commit.slice(0,12)}；整理了 ${value.coverage.read_fragments} 段原文。来源为本人提供，未经独立核验。`
      : `固定提交 ${value.source_commit.slice(0,12)}；下载 ${value.coverage.downloaded} 个文件，本轮阅读 ${value.coverage.read_fragments} 个片段。未读取的内容不推定已覆盖。`;
    const selected=new Set([...$('claims').querySelectorAll('input:checked')].map(i=>i.value));
    $('claims').replaceChildren();
    value.claims.forEach(claim => {
      const row=node('div',undefined,'career-task'); const label=node('label',undefined,'cu-check'); const input=node('input'); input.type='checkbox'; input.value=claim.claim_id; input.checked=selected.has(claim.claim_id);
      const body=node('span',claim.pillar ? `${claim.pillar}：${claim.text}` : claim.text);
      const notes=[claim.fit_reason ? `岗位相关：${claim.fit_reason}` : '', claim.boundary ? `职责边界：${claim.boundary}` : '', claim.risk ? `待确认：${claim.risk}` : ''].filter(Boolean).join(' / ');
      if (notes) body.append(node('small',notes,'career-claim-note'));
      label.append(input,body); row.append(label);
      const evidence=(value.evidence || []).filter(item=>claim.evidence_ids.includes(item.evidence_id));
      if (evidence.length) {
        const sources=node('details'); sources.append(node('summary',manual ? '对照原文':'查看来源'));
        evidence.forEach(item=>{const p=node('p');p.append(sourceLink(item));sources.append(p);if(manual)sources.append(node('pre',item.text,'career-code'));});
        row.append(sources);
      }
      $('claims').append(row);
    });
    message('经历已整理，请逐条核对并确认实际属于你的工作。'); controls();
  }
  async function projectStatus(id,valid) {
    if (!valid()) return;
    const value=await api(`/projects/${id}`); if (!valid()) return;
    showProject(value);
    if (value.status==='preparing') projectTimer=setTimeout(()=>projectStatus(id,valid).catch(e=>{if(valid())message(e.message);}),2000);
  }
  async function startInterview(materialId,kind,valid) {
    const retrying=!current && sessionId && safeLocalGet(key('session-material'))===materialId && safeLocalGet(key('session-kind'))===kind;
    const id=retrying ? sessionId:`opuser_${crypto.randomUUID().replaceAll('-','')}`;
    sessionId=id; safeLocalSet(key('session'),id);
    safeLocalSet(key('session-material'),materialId); safeLocalSet(key('session-kind'),kind);
    const data=await api('/interviews',{material_id:materialId,session_id:id,interview_mode:kind});
    if (!valid()) return;
    failedEvent=null; $('answer').value=''; renderSession(data); showView('interview');$('interview-panel').hidden=false;window.OfferPilotWorkbench?.projectInterview();$('question').focus();
  }
  function renderRecap(value) {
    const out=$('recap'); out.replaceChildren(node('h4','本轮复盘（待确认）'));
    out.append(node('p','以下是对本轮回答的反馈。辅助作答不等于独立掌握；建议不会自动改写已保存简历。','notice'));
    const labels={consistent:'与证据一致',partial:'需要补充',conflict:'存在待核实差异',insufficient_evidence:'证据不足'};
    [...value.what_went_well,...value.needs_review].forEach(item=>out.append(node('h5',`${item.question_id} | ${labels[item.status] || item.status}`),node('p',item.notes,'career-message'),node('p',`作答方式：${{independent:'独立作答',hinted:'提示后作答',open_book:'查阅资料',ai_assisted:'AI辅助'}[item.assistance_mode] || item.assistance_mode}；掌握程度仍待确认。`,'hint')));
    out.append(node('p',`未评估：${value.not_assessed.length} 题。跳过或缺少反馈不记成答错。`));
    value.improvement_tasks.forEach(task=>{
      const card=node('div',undefined,'career-task'); card.append(node('p',task.action),node('p',`完成标准：${task.completion_criterion}`),node('p',`复测：${task.retest.prompt}`));
      task.materials.forEach(item=>{const p=node('p');p.append(sourceLink({...item,commit_sha:value.source_commit}));card.append(p);});out.append(card);
    });
    out.hidden=false;
  }
  function renderSession(data) {
    current=data.view;
    $('session-status').textContent=statusLabels[current.status] || current.status;
    $('session-meta').textContent=`${current.interview_mode==='mock_interview'?'正式模拟面试':'项目前置核验'} | 已记录 ${current.answered}/${current.total} 题${current.resume_version_id?' | 简历 '+current.resume_version_id:''}`;
    $('question').textContent=current.question?.text || '本轮题目已完成，请结束保存复盘。';
    $('interview-message').textContent=current.message || '请回答当前问题。';
    $('source').hidden=true;
    if (current.last_error) $('interview-message').textContent+='\n上次反馈未完成，回答已暂存。';
    $('recap').hidden=!current.recap;
    if (current.recap) renderRecap(current.recap);
    current.evidence=data.evidence || [];
    controls();
  }
  async function recover(valid) {
    if (!sessionId) return;
    const data=await api(`/interviews/${sessionId}`); if (valid()) renderSession(data);
  }
  async function send(command,valid) {
    const text=command ? `/${command}`:$('answer').value.trim(); if (!text) throw new Error('请输入回答，或选择跳过。');
    const event=command==='retry' && failedEvent ? failedEvent : {event_id:`evt_${crypto.randomUUID().replaceAll('-','')}`,text,...(command?{command}:{})};
    failedEvent=event;
    const data=await api(`/interviews/${sessionId}/turns`,event); if (!valid()) return;
    failedEvent=null; renderSession(data);
    if (!command || command==='retry') $('answer').value='';
    if (command==='open_book') {
      $('source').replaceChildren(); const refs=current.question?.evidence_ids || [];
      current.evidence.filter(e=>refs.includes(e.evidence_id)).forEach(e=>{const p=node('p');p.append(sourceLink(e));$('source').append(p,node('pre',e.text,'career-code'));});
      $('source').hidden=false;
    }
  }
  async function makeDraft(valid,materialId) {
    if (!await checkProfile(valid)) return;
    const value=await api('/resume-drafts',materialId ? {material_id:materialId}:{session_id:sessionId}); if (!valid()) return;
    draft=value; renderResume(value.markdown); $('resume-preview').hidden=false; $('save-confirmed').checked=false;
    version=null; $('saved-resume').hidden=true; $('save-version').hidden=false; $('save-confirmed').closest('label').hidden=false;
    message('已根据导入材料和你确认的经历生成简历预览。请核对资料与表述后保存版本。');
    showView('resume'); $('resume-preview').scrollIntoView({block:'start'});
  }
  function showVersion(value) {
    draft=null; version=value; safeLocalSet(key('version'),value.resume_version_id); $('saved-resume').hidden=false; $('version-label').textContent=`${value.resume_version_id} | ${new Date(value.created_at).toLocaleString()} | ${value.source_type==='manual'?'材料':'源码'} ${value.source_commit.slice(0,12)}`;
    $('project-review').hidden=true;
    renderResume(value.markdown); $('resume-preview').hidden=false; $('repository-section').open=false;
    $('save-version').hidden=true; $('save-confirmed').closest('label').hidden=true; controls();
  }
  async function loadVersions(valid) {
    const data=await api('/resumes'); if (!valid()) return;
    $('versions').replaceChildren(); $('history').hidden=!data.items.length;
    data.items.forEach(item=>$('versions').append(button(`${item.job_snapshot.role} | ${new Date(item.created_at).toLocaleString()} | ${item.resume_version_id.slice(-8)}`,async v=>{const value=await api(`/resumes/${item.resume_version_id}`);if(v())showVersion(value);})));
  }
  function resetMode() {
    if (mode===state.mode) return; mode=state.mode; epoch++;
    clearTimeout(authTimer); clearTimeout(projectTimer);
    clearTimeout(knowledgeTimer); knowledgeEpoch++; $('knowledge-status').hidden = true;
    busy=false; configured=false; connected=false; project=null; current=null; draft=null; version=null; failedEvent=null;
    const personal=mode==='user';
    $('personal').hidden=!personal; $('interview-panel').hidden=true;
    document.querySelectorAll('.career-panel').forEach(p=>{p.hidden=true;});
    ['repositories','files','claims','recap','source','versions'].forEach(id=>$(id).replaceChildren());
    ['project-review','project-form','saved-resume','repository-section','browser','device','recap'].forEach(id=>{$(id).hidden=true;});
    if (window.OfferPilotWorkbench?.enabled) {
      $('resume-preview').hidden=false;
      renderEmptyResumePreview();
    } else {
      $('resume-preview').hidden=true;
    }
    ['answer','contribution','jd','role','repository','client-id'].forEach(id=>{$(id).value='';});
    $('experience-form').reset(); $('extract-status').textContent=''; showSource(sourceMode);
    $('question').textContent=''; $('session-meta').textContent='在定制简历页选择并确认项目后开始。';
    $('save-version').hidden=false; $('save-confirmed').closest('label').hidden=false;
    controls(); if (personal) { warmKnowledge(); run(connectState); }
  }
  document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',resetMode));
  $('config-form').addEventListener('submit',e=>{e.preventDefault();run(async valid=>{await api('/github/config',{client_id:$('client-id').value.trim()});if(valid()){ $('client-id').value='';await connectState(valid);}});});
  $('reload').addEventListener('click',()=>run(connectState));
  $('connect').addEventListener('click',()=>run(async valid=>{clearTimeout(authTimer);const data=await api('/github/start',{});if(!valid())return;$('device-code').textContent=data.user_code;$('device').hidden=false;$('device-status').textContent='等待你在 GitHub 确认，本页将自动检查状态。';authTimer=setTimeout(()=>pollAuth(data.ticket,valid),data.interval*1000);message('请在 GitHub 授权页面输入验证码并确认。');}));
  $('disconnect').addEventListener('click',()=>run(async valid=>{clearTimeout(authTimer);await api('/github/disconnect',{});if(valid())await connectState(valid);}));
  $('more-repositories').addEventListener('click',()=>run(v=>loadRepositories(v,nextPage)));
  $('more-files').addEventListener('click',()=>run(v=>browse(tree.repository,tree.next,v)));
  document.querySelectorAll('[name="cu-source-type"]').forEach(input=>input.addEventListener('change',()=>{
    if(!input.checked)return;
    project=null;safeLocalSet(key('project'),'');$('project-review').hidden=true;
    showSource(input.value); clearTimeout(authTimer);
    if(sourceMode==='github')run(async valid=>{
      const data=await api('/github/status'); if(!valid())return;
      configured=data.configured; connected=data.connected; $('setup').open=!configured;
      $('connection').textContent=connected ? `已连接 ${data.login}`:'GitHub 待连接';
      if(connected)await loadRepositories(valid); else message('请连接 GitHub 后选择项目；自主导入无需连接。');
    }); else message('填写一段真实经历，补充说明个人工作与实际交付。');
    controls();
  }));
  $('extract-text').addEventListener('click',()=>run(async valid=>{
    const file=$('exp-file').files[0];
    if(!file)throw new Error('请先选择经历或作品集文字文件。');
    if(file.size>5*1024*1024)throw new Error('文件不能超过 5 MB。');
    $('extract-status').textContent='正在本机提取文字…';
    const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败，请重新选择。'));reader.readAsDataURL(file);});
    const data=await api('/experience-text',{filename:file.name,content_base64:content}); if(!valid())return;
    const combined=[exp('source_text').value,data.text].filter(Boolean).join('\n\n');
    if(combined.length>20000)throw new Error('合并后的原文超过 20000 字符，请先精简已有材料。');
    exp('source_text').value=combined; $('exp-file').value='';
    $('extract-status').textContent=`已提取 ${file.name}，请核对下方原文。`;
    message('文字已在本机提取，请核对后再整理经历。');
  }));
  $('experience-form').addEventListener('submit',e=>{e.preventDefault();run(async valid=>{
    const data=Object.fromEntries(experienceFields.map(field=>[field,exp(field).value]));
    data.confirmed=$('exp-confirmed').checked;data.model_consent=$('exp-consent').checked;
    const value=await api('/experience-import',data);if(!valid())return;
    clearResume();safeLocalSet(key('project'),value.project_id);$('project-review').hidden=true;await projectStatus(value.project_id,valid);
  });});
  $('project-form').addEventListener('submit',e=>{e.preventDefault();run(async valid=>{
    clearResume();
    const value=await api('/projects',{repository:$('repository').value,role:$('role').value,jd:$('jd').value,contribution:$('contribution').value,confirmed:$('contribution-confirmed').checked,model_consent:$('model-consent').checked});
    if(valid()){safeLocalSet(key('project'),value.project_id);$('project-review').hidden=true;await projectStatus(value.project_id,valid);}
  });});
  $('start-readiness').addEventListener('click',()=>run(async valid=>{const ids=[...$('claims').querySelectorAll('input:checked')].map(i=>i.value);if(!ids.length)throw new Error('请至少确认一条实际属于你的工作。');if(!await checkProfile(valid))return;const value=await api(`/projects/${project.project_id}/confirm`,{claim_ids:ids,confirmed:true});if(valid()){window.OfferPilotWorkbench?.onMutation('confirm_material',value);await makeDraft(valid,value.material_id);}}));
  $('answer-form').addEventListener('submit',e=>{e.preventDefault();run(v=>send(null,v));});
  commands.forEach(b=>b.addEventListener('click',()=>run(v=>send(b.dataset.cuCommand,v))));
  $('refresh-session').addEventListener('click',()=>run(recover));
  $('to-draft').addEventListener('click',()=>run(makeDraft));
  $('save-version').addEventListener('click',()=>run(async valid=>{if(!$('save-confirmed').checked)throw new Error('请核对预览并勾选保存确认。');const value=await api(`/resume-drafts/${draft.draft_id}/save`,{confirmed:true});if(valid()){showVersion(value);await loadVersions(valid);window.OfferPilotWorkbench?.onMutation('save_version',value);message('简历版本已保存，可以下载或打印；后续修改会保存为新版本。');}}));
  $('start-formal').addEventListener('click',()=>run(v=>startInterview(version.interview_material_id,'mock_interview',v)));
  $('regenerate').addEventListener('click',()=>run(v=>makeDraft(v,version.material_id)));
  $('download').addEventListener('click',()=>{if(!version)return;const url=URL.createObjectURL(new Blob([version.markdown],{type:'text/markdown;charset=utf-8'}));const a=node('a');a.href=url;a.download=`${version.resume_version_id}.md`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  document.querySelectorAll('[name="cu-template"]').forEach(input=>input.addEventListener('change',()=>{
    if(!input.checked)return;resumeTemplate=input.value;safeLocalSet(key('template'),resumeTemplate);
    $('markdown').dataset.resumeTemplate=resumeTemplate;
    message(`已切换${resumeTemplate==='classic'?'经典黑白':'专业墨蓝'}模板，打印与 PDF 导出将使用当前样式。`);
  }));
  $('download-pdf').addEventListener('click',()=>{if(!version)return;const a=node('a');a.href=`/api/career-user/resumes/${version.resume_version_id}/pdf?mode=user&template=${resumeTemplate}`;a.download=`${version.resume_version_id}_${resumeTemplate}.pdf`;a.click();});
  $('print').addEventListener('click',()=>{if(version)window.open(`/api/career-user/resumes/${version.resume_version_id}/print?mode=user&template=${resumeTemplate}`,'_blank','noopener');});
  resetMode();
  window.OfferPilotCareer={
    refreshVersions:()=>{const ticket=epoch;return loadVersions(()=>ticket===epoch&&state.mode==='user');},
    openVersion:id=>run(async valid=>{const value=await api(`/resumes/${encodeURIComponent(id)}`);if(valid())showVersion(value);}),
    openInterview:id=>run(async valid=>{const data=await api(`/interviews/${encodeURIComponent(id)}`);if(valid()){sessionId=id;safeLocalSet(key('session'),id);$('interview-panel').hidden=false;renderSession(data);window.OfferPilotWorkbench?.projectInterview();}}),
  };
})();
