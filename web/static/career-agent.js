'use strict';

/* Public demo only. The shared shell owns state.mode and showView(). */
(() => {
  const byId = (id) => document.getElementById(`career-${id}`);
  const storageKey = 'offerpilot.career.public-session';
  const commands = Array.from(document.querySelectorAll('[data-career-command]'));
  const labels = { active: '练习中', paused: '已暂停', held: '待核实材料', ready_to_finish: '已答完，待复盘',
    completed: '复盘已保存', finalizing: '正在生成复盘' };
  const observations = { consistent: '与证据一致', partial: '需要补充', conflict: '存在待核实差异',
    insufficient_evidence: '证据不足', not_assessed: '未评估' };
  let sessionId = safeLocalGet(storageKey);
  if (sessionId && !/^opdemo_[A-Za-z0-9_-]{1,64}$/.test(sessionId)) sessionId = null;
  let current = null;
  let ready = false;
  let busy = false;
  let epoch = 0;
  let failedEvent = null;
  let evidence = [];
  let observedMode = null;

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  }

  function controls() {
    const demo = state.mode === 'demo';
    byId('start').disabled = !demo || !ready || busy || (current && current.status !== 'completed');
    byId('start').textContent = busy && !current ? '正在准备核验…'
      : current?.status === 'completed' ? '开始新一轮核验' : '开始项目核验';
    byId('continue').hidden = !demo || !sessionId;
    byId('continue').disabled = busy;
    byId('refresh').disabled = !demo || !sessionId || busy;
    byId('connect').disabled = busy || !demo;
    byId('demo-mode').hidden = demo;
    const active = demo && current?.status === 'active' && !current.pending_evaluation;
    byId('answer').disabled = !active || busy || Boolean(failedEvent);
    byId('submit').disabled = !active || busy || Boolean(failedEvent);
    commands.forEach((button) => {
      const command = button.dataset.careerCommand;
      const retry = command === 'retry';
      button.hidden = command === 'resume' ? current?.status !== 'paused' : retry
        ? !(failedEvent || current?.pending_evaluation || current?.last_error) : false;
      button.disabled = !demo || !current || busy || current.status === 'completed'
        || (!['resume', 'retry', 'finish'].includes(command) && !active)
        || (Boolean(failedEvent) && !retry);
    });
    byId('answer-form').setAttribute('aria-busy', String(busy));
  }

  async function request(path, payload) {
    const response = await fetch(`${path}?mode=demo`, {
      method: payload ? 'POST' : 'GET', cache: 'no-store',
      headers: { Accept: 'application/json', ...(payload ? { 'Content-Type': 'application/json' } : {}) },
      ...(payload ? { body: JSON.stringify({ ...payload, mode: 'demo' }) } : {})
    });
    const data = await response.json();
    if (!response.ok || data.ok !== true) {
      const error = new Error(data.error || '服务暂不可用，请刷新恢复本轮。');
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function run(action) {
    if (busy || state.mode !== 'demo') return;
    const startedEpoch = epoch;
    busy = true;
    controls();
    byId('message').textContent = '正在处理，请稍候…';
    byId('resume-note').textContent = '正在准备核验，请稍候；可以在当前页面等待，无需重复点击。';
    const started = Date.now();
    const timer = setInterval(() => {
      if (startedEpoch === epoch) {
        const message = `正在处理（${Math.floor((Date.now() - started) / 1000)} 秒），请勿重复提交。`;
        byId('message').textContent = message;
        byId('resume-note').textContent = message;
      }
    }, 1000);
    try {
      await action(() => startedEpoch === epoch && state.mode === 'demo');
    } catch (error) {
      if (startedEpoch === epoch) {
        byId('message').textContent = error.message;
        byId('resume-note').textContent = error.message;
        if (!current) byId('connection').textContent = '连接 / 初始化未完成';
      }
    } finally {
      clearInterval(timer);
      if (startedEpoch === epoch) { busy = false; controls(); }
    }
  }

  function sourceLink(item) {
    const line = `${item.path || ''} · L${item.line_start}–${item.line_end}`;
    const url = String(item.source_url || '');
    if (!url.startsWith('https://github.com/pallets/itsdangerous/blob/672971d66a2ef9f85151e53283113f33d642dabd/')) return node('span', line);
    const link = node('a', line);
    link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    return link;
  }

  function renderRecap(recap) {
    const container = byId('recap');
    container.replaceChildren(node('h4', '本轮复盘 · 待确认'));
    container.append(node('p', '公开样例不计入个人经历；本轮反馈没有修改简历，也不代表独立掌握。', 'notice'));
    const items = [...(recap.what_went_well || []), ...(recap.needs_review || [])];
    items.forEach((item) => {
      container.append(node('h5', `${item.question_id} · ${observations[item.status] || item.status}`));
      container.append(node('p', item.notes || '请结合源码复核。', 'career-message'));
      container.append(node('p', item.independent_readiness_verified ? '独立作答记录，仍待确认' : '保留辅助作答与证据边界，未认定独立掌握', 'hint'));
    });
    container.append(node('h5', `未评估：${(recap.not_assessed || []).length} 题`));
    (recap.not_assessed || []).forEach((item) => container.append(node('p', `${item.question_id}：跳过、缺答或缺少反馈，保持未评估。`, 'hint')));
    container.append(node('h5', '补强与复测建议'));
    if (!(recap.improvement_tasks || []).length) container.append(node('p', '本轮没有形成补强任务；这不等于已掌握全部项目。'));
    (recap.improvement_tasks || []).forEach((task) => {
      const card = node('div', undefined, 'career-task');
      card.append(node('p', task.action), node('p', `完成标准：${task.completion_criterion}`));
      if (task.retest?.prompt) card.append(node('p', `复测：${task.retest.prompt}`));
      (task.materials || []).forEach((item) => { const p = node('p'); p.append(sourceLink(item)); card.append(p); });
      container.append(card);
    });
    const suggestions = { clarify_scope_pending_confirmation: '先确认个人职责，再决定简历表述',
      collect_evidence: '补充实现、版本或成果证据', review_source_and_version: '核对源码与版本差异，再调整表述',
      preserve_fact_and_prepare: '保留已确认事实，补强项目理解与表达' };
    if ((recap.resume_suggestions || []).length) {
      container.append(node('h5', '简历处理建议（尚未应用）'));
      recap.resume_suggestions.forEach((item) => container.append(node('p', suggestions[item.action] || item.action)));
    }
    container.hidden = false;
  }

  function render(data) {
    current = data.view;
    evidence = data.evidence || [];
    byId('connection').textContent = '已连接 · 公开样例';
    byId('session').hidden = false;
    byId('session-status').textContent = labels[current.status] || current.status;
    byId('session-meta').textContent = `已记录 ${current.answered} / ${current.total} 题 · ${current.session_id}`;
    byId('question').textContent = current.question?.text || '本轮问题已完成，请结束并保存复盘。';
    byId('evidence-range').textContent = evidence.map((e) => `${e.path} L${e.line_start}–${e.line_end}`).join('；');
    byId('source').hidden = true;
    byId('message').textContent = current.message || '请回答当前问题，也可以查看源码、暂停或跳过。';
    if (current.last_error) byId('message').textContent += '\n上次反馈未完成，回答已暂存，请重试未完成操作。';
    byId('resume-note').textContent = `本轮${labels[current.status] || current.status}，可在模拟面试页继续查看。`;
    byId('recap').hidden = !current.recap;
    if (current.recap) renderRecap(current.recap);
    controls();
  }

  async function recover(valid) {
    if (!sessionId) return;
    const data = await request(`/api/interview-agent/sessions/${sessionId}`);
    if (!valid()) return;
    render(data);
    if (current.status === 'completed' && !current.recap) {
      const result = await request(`/api/interview-agent/sessions/${sessionId}/recap`);
      if (valid()) renderRecap(result.recap);
    }
  }

  async function connect(valid) {
    const data = await request('/api/resume-agent/materials');
    if (!valid()) return;
    ready = data.items.length > 0;
    byId('connection').textContent = ready ? '公开样例已就绪' : '缺少样例材料';
    byId('resume-note').textContent = ready ? '公开项目体验，仅使用演示材料。回答会发送至 Step 模型，请勿填写个人信息。' : '样例尚未导入，请使用公开样例启动脚本。';
    if (sessionId) await recover(valid);
  }

  function start() {
    run(async (valid) => {
      if (!sessionId || current?.status === 'completed') {
        sessionId = `opdemo_${crypto.randomUUID().replaceAll('-', '')}`;
        safeLocalSet(storageKey, sessionId);
      }
      byId('connection').textContent = '正在准备核验';
      const data = await request('/api/interview-agent/sessions', { session_id: sessionId });
      if (!valid()) return;
      failedEvent = null;
      byId('answer').value = '';
      render(data); showView('interview'); byId('question').focus();
    });
  }

  function send(command) {
    run(async (valid) => {
      const text = command ? `/${command}` : byId('answer').value.trim();
      if (!text) throw new Error('请填写回答，或选择跳过本题。');
      const event = command === 'retry' && failedEvent ? failedEvent : {
        event_id: `evt_${crypto.randomUUID().replaceAll('-', '')}`, text, ...(command ? { command } : {})
      };
      failedEvent = event;
      const data = await request(`/api/interview-agent/sessions/${sessionId}/turns`, event);
      if (!valid()) return;
      failedEvent = null;
      if (!command || command === 'retry') byId('answer').value = '';
      render(data);
      if (command === 'open_book') {
        byId('source').replaceChildren();
        evidence.forEach((item) => {
          const p = node('p'); p.append(sourceLink(item));
          byId('source').append(p, node('pre', item.text || '', 'career-code'));
        });
        byId('source').hidden = false;
      }
    });
  }

  function resetMode() {
    if (observedMode === state.mode) return;
    observedMode = state.mode;
    epoch += 1; current = null; busy = false; ready = false; failedEvent = null;
    byId('answer').value = '';
    ['session', 'recap', 'source'].forEach((id) => { byId(id).hidden = true; });
    byId('session-status').textContent = '尚未开始';
    byId('message').textContent = '请在演示模式开始或恢复公开样例核验。';
    byId('connection').textContent = state.mode === 'demo' ? '检查连接中' : '仅演示模式';
    byId('resume-note').textContent = '本期公开样例仅在演示 demo 模式使用，不读取个人资料。';
    controls();
    // Interview UI is deferred; keep the API and saved sessions without auto-resuming.
  }

  byId('start').addEventListener('click', start);
  byId('continue').addEventListener('click', () => { showView('interview'); run(recover); });
  byId('refresh').addEventListener('click', () => run(recover));
  byId('connect').addEventListener('click', () => run(connect));
  byId('demo-mode').addEventListener('click', () => document.querySelector('[data-mode="demo"]').click());
  byId('answer-form').addEventListener('submit', (event) => { event.preventDefault(); send(); });
  commands.forEach((button) => button.addEventListener('click', () => send(button.dataset.careerCommand)));
  document.querySelectorAll('[data-mode]').forEach((button) => button.addEventListener('click', resetMode));
  resetMode();
})();
