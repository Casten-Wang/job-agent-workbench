'use strict';

(() => {
  const $ = (id) => document.getElementById(`ci-${id}`);
  const STORAGE_KEY = 'offerpilot.comprehensive.session_id';

  const MOVE_LABELS = {
    opening: '开场',
    follow_up: '顺着问一句',
    scaffold: '给你个小线索',
    challenge: '再深挖一点',
    advance_topic: '换个话题',
    use_overflow: '加聊一题',
    candidate_qa: '反问时间',
    ready_to_end: '收尾',
    open_book: '翻了下资料',
    ai_assisted: '借助资料',
    pause: '暂停中',
    resume: '继续',
    paused_guard: '温馨提示',
    correct_contribution: '已澄清分工',
    correct_version: '已澄清版本',
  };

  const USER_CMD_LABELS = {
    request_hint: '想要点提示',
    skip: '先过这题',
    force_skip: '换下一题',
    open_book: '刚翻了下资料',
    ai_assisted: '借助了资料',
    pause: '暂停一下',
    resume: '继续面试',
    early_terminate: '先到这里',
    finish: '结束看复盘',
    clarify_case: '先明确下需求边界',
  };

  const FROZEN_REASON_LABELS = {
    awaiting_first: '待开场',
    paused: '已暂停',
    streaming: '出题中',
    evaluating: '思考中',
    retrieving: '翻看资料',
    completed: '已结束',
  };

  const READINESS_LABELS = {
    ready: '整体聊得很扎实，可以投递实战了',
    almost_ready: '底子不错，把几处卡点顺一下会更稳',
    needs_practice: '思路是对的，关键细节还可以多练几轮',
    insufficient_evidence: '这轮聊得还不多，建议多答几轮再看全貌',
  };

  const SEVERITY_LABELS = {
    red_flag: '需要留心',
    hire_bar_signal: '聊得挺亮眼',
  };

  const RESUME_ACTION_LABELS = {
    keep_verified: '这段经历很扎实，建议保留',
    enrich_highlight: '亮点还可以写得更透',
    needs_evidence_or_downgrade: '缺少过程或结果细节，建议补充实例或先收窄写法',
    resolve_conflict: '口述和简历上的细节有点对不上，建议核对一下',
  };

  let sessionId = safeGet(STORAGE_KEY) || '';
  let currentView = null;
  let busy = false;
  let composing = false;
  let compositionEnded = 0;
  let tickTimer = null;
  let transitionTimer = null;
  let localTickOffset = 0;
  let currentDrillAttempt = 0;

  function safeGet(k) {
    try { return window.localStorage.getItem(k); } catch { return null; }
  }
  function safeSet(k, v) {
    try { if (v) window.localStorage.setItem(k, v); else window.localStorage.removeItem(k); } catch {}
  }

  function node(tag, text, className) {
    const el = document.createElement(tag);
    if (text !== undefined && text !== null) el.textContent = String(text);
    if (className) el.className = className;
    return el;
  }

  function mode() {
    return window.state?.mode || 'user';
  }

  function setStatusNotice(text, isError = false) {
    const val = text || '';
    const err = isError ? 'true' : 'false';
    ['status-msg', 'setup-inline-status', 'stage-inline-status', 'drill-inline-status'].forEach((id) => {
      const el = $(id);
      if (!el) return;
      el.textContent = val;
      el.dataset.error = err;
    });
  }

  function setBusyState(flag, buttonLabel = '') {
    busy = Boolean(flag);
    const startBtn = $('start');
    if (startBtn) {
      if (!startBtn.dataset.defaultLabel) startBtn.dataset.defaultLabel = startBtn.textContent;
      startBtn.disabled = busy;
      startBtn.textContent = (busy && buttonLabel && !$('setup')?.hidden) ? buttonLabel : startBtn.dataset.defaultLabel;
    }
    const submitBtn = $('submit-answer');
    if (submitBtn) {
      if (!submitBtn.dataset.defaultLabel) submitBtn.dataset.defaultLabel = submitBtn.textContent;
      submitBtn.disabled = busy;
      submitBtn.textContent = (busy && buttonLabel && !$('stage')?.hidden) ? buttonLabel : submitBtn.dataset.defaultLabel;
    }
    document.querySelectorAll('[data-ci-cmd]').forEach((btn) => {
      btn.disabled = busy;
    });
    const drillBtn = $('drill-submit');
    if (drillBtn) {
      if (!drillBtn.dataset.defaultLabel) drillBtn.dataset.defaultLabel = drillBtn.textContent;
      drillBtn.disabled = busy;
      drillBtn.textContent = (busy && buttonLabel && !$('debrief-section')?.hidden) ? buttonLabel : drillBtn.dataset.defaultLabel;
    }
  }

  function stopTransitionTimer() {
    if (transitionTimer) {
      clearInterval(transitionTimer);
      transitionTimer = null;
    }
  }

  function makeTypingBubble(label) {
    const box = node('div', undefined, 'ci-typing-bubble');
    const row = node('div', undefined, 'ci-typing-row');
    const dots = node('span', undefined, 'ci-typing-dots');
    dots.setAttribute('aria-hidden', 'true');
    dots.append(document.createElement('i'), document.createElement('i'), document.createElement('i'));
    row.append(node('span', label), dots);
    const bar = node('div', undefined, 'ci-skeleton-bar');
    box.append(row, bar);
    return box;
  }

  function showOpeningTransition(stepIndex, startedAtMs) {
    stopTransitionTimer();
    if ($('setup')) $('setup').hidden = true;
    if ($('stage')) $('stage').hidden = false;
    if ($('composer')) $('composer').hidden = true;
    if ($('debrief-section')) $('debrief-section').hidden = true;
    if ($('status-badge')) $('status-badge').textContent = '准备进场';
    if ($('section-label')) $('section-label').textContent = '面试间已连线，正在熟悉你的资料';

    const logEl = $('transcript');
    if (!logEl) return;

    const renderCard = () => {
      const elapsed = Math.max(0, Math.floor((Date.now() - startedAtMs) / 1000));
      const card = node('div', undefined, 'ci-transition-card');
      const head = node('div', undefined, 'ci-transition-head');
      const title = stepIndex === 1
        ? '面试官正在翻看你的简历与项目资料…'
        : '资料已经看完，面试官正在准备第一句开场白…';
      head.append(node('span', title), node('span', `已等待 ${elapsed}s`, 'hint'));

      const steps = node('div', undefined, 'ci-transition-steps');
      const s1 = node('span', stepIndex >= 2 ? '✓ 1. 简历与项目资料就位' : '● 1. 翻阅简历与项目资料', `ci-step-item ${stepIndex >= 2 ? 'is-done' : 'is-active'}`);
      const s2 = node('span', stepIndex >= 2 ? '● 2. 构思本场聊天切入点' : '○ 2. 构思本场聊天切入点', `ci-step-item ${stepIndex >= 2 ? 'is-active' : ''}`);
      const s3 = node('span', '○ 3. 开场提问', 'ci-step-item');
      steps.append(s1, s2, s3);

      const bar = node('div', undefined, 'ci-skeleton-bar');
      card.replaceChildren(head, steps, bar);
      logEl.replaceChildren(card);
    };

    renderCard();
    transitionTimer = setInterval(renderCard, 1000);
  }

  function appendOptimisticTurn(text, commandOverride, thinkingLabel) {
    const logEl = $('transcript');
    if (!logEl) return;
    if (text || commandOverride) {
      const cmdLabel = commandOverride ? (USER_CMD_LABELS[commandOverride] || commandOverride) : '';
      const who = cmdLabel ? `我（${cmdLabel}）` : '我';
      const msg = node('div', undefined, 'ci-msg is-user');
      msg.append(node('div', who, 'ci-msg-meta'), node('div', text || cmdLabel));
      logEl.append(msg);
    }
    if (thinkingLabel) {
      logEl.append(makeTypingBubble(thinkingLabel));
    }
    logEl.scrollTop = logEl.scrollHeight;
  }

  async function api(method, path, body) {
    const sep = path.includes('?') ? '&' : '?';
    const url = `/api/career-user${path}${sep}mode=user`;
    const init = {
      method,
      headers: { Accept: 'application/json' },
    };
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify({ ...body, mode: 'user' });
    }
    const resp = await fetch(url, init);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.error || data.message || `请求没成功 (${resp.status})`);
    }
    return data;
  }

  async function refreshSources() {
    if (!$('panel') || mode() !== 'user') return;
    try {
      const snapResp = await fetch('/api/state?mode=user');
      if (snapResp.ok) {
        const snap = await snapResp.json();
        const jobSel = $('job');
        if (jobSel && Array.isArray(snap.jobs)) {
          const prev = jobSel.value;
          jobSel.replaceChildren(new Option('不限岗位（自由发挥 / 贴 JD）', ''));
          snap.jobs.forEach((j) => {
            jobSel.add(new Option(`${j.company || '公司'} - ${j.title || j.role || '岗位'}`, String(j.id)));
          });
          jobSel.value = prev || '';
        }
      }
      const resResp = await api('GET', '/resumes').catch(() => ({ items: [] }));
      const verSel = $('resume-version');
      if (verSel) {
        const prev = verSel.value;
        verSel.replaceChildren(new Option('自动用我最新的简历', ''));
        (resResp.items || []).forEach((r) => {
          verSel.add(new Option(`${r.job_snapshot?.role || '简历'} (${(r.created_at || '').slice(0, 10)})`, r.resume_version_id));
        });
        verSel.value = prev || '';
      }
      const kbResp = await api('GET', '/knowledge/sources').catch(() => ({ items: [] }));
      const kbBox = $('knowledge-list');
      if (kbBox) {
        kbBox.replaceChildren();
        const items = kbResp.items || [];
        if (!items.length) {
          kbBox.append(node('span', '暂时还没导入代码或文档快照，可以直接基于你的简历与口述经历开聊。', 'hint'));
        } else {
          items.forEach((src) => {
            const label = node('label', undefined, 'checkbox-label');
            const chk = document.createElement('input');
            chk.type = 'checkbox';
            chk.name = 'ci-knowledge';
            chk.value = src.snapshot_id;
            chk.checked = true;
            const kindLabel = src.kind === 'source' ? '源码' : '资料';
            label.append(chk, ` ${src.title || src.repository || src.snapshot_id} (${kindLabel})`);
            kbBox.append(label);
          });
        }
      }
    } catch {
      // 允许静态离线浏览时不报错
    }
  }

  function formatDuration(sec) {
    const s = Math.max(0, Math.floor(sec));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
  }

  function syncTimerDisplay() {
    const badge = $('timer-badge');
    if (!badge || !currentView?.timer) return;
    badge.hidden = false;
    const t = currentView.timer;
    const ticking = currentView.status === 'active' && !t.frozen_reason;
    const elapsed = Number(t.active_elapsed_seconds || 0) + (ticking ? localTickOffset : 0);
    const remaining = Math.max(0, Number(t.remaining_seconds || 0) - (ticking ? localTickOffset : 0));
    const frozenLabel = t.frozen_reason ? (FROZEN_REASON_LABELS[t.frozen_reason] || t.frozen_reason) : '';
    const frozenText = frozenLabel ? `（${frozenLabel}）` : '';
    const qaText = t.qa_window_active ? ' | 反问时间' : '';
    badge.textContent = `已聊 ${formatDuration(elapsed)} / 还剩 ${formatDuration(remaining)}${frozenText}${qaText}`;
    badge.classList.toggle('is-frozen', Boolean(t.frozen_reason));
    badge.classList.toggle('is-qa', Boolean(t.qa_window_active));
  }

  function startClockSync() {
    clearInterval(tickTimer);
    localTickOffset = 0;
    syncTimerDisplay();
    if (currentView && currentView.status === 'active' && !currentView.timer?.frozen_reason) {
      tickTimer = setInterval(() => {
        localTickOffset += 1;
        syncTimerDisplay();
      }, 1000);
    }
  }

  function renderView(view, streamingText = null) {
    stopTransitionTimer();
    currentView = view;
    if (!view) return;
    sessionId = view.session_id;
    safeSet(STORAGE_KEY, sessionId);

    const statusBadge = $('status-badge');
    if (statusBadge) {
      const labels = {
        awaiting_first: '准备开场',
        active: '面试中',
        paused: '暂停中',
        completed: '已复盘',
        early_terminated: '提前结束并复盘',
      };
      statusBadge.textContent = labels[view.status] || view.status;
    }

    const setupEl = $('setup');
    const stageEl = $('stage');
    const ended = view.status === 'completed' || view.status === 'early_terminated';
    if (setupEl) setupEl.hidden = Boolean(view);
    if (stageEl) stageEl.hidden = !view;

    const q = view.current_question;
    const sectionEl = $('section-label');
    if (sectionEl) {
      sectionEl.textContent = q
        ? `当前话题：${q.section_title || q.section_id}`
        : (ended ? '本场模拟面试已经结束' : '');
    }

    const clarifyEl = $('clarify-banner');
    if (clarifyEl) clarifyEl.hidden = !(q && q.requires_clarify && !ended);
    const codeWrap = $('code-wrap');
    if (codeWrap) codeWrap.hidden = !(q && q.requires_code_box && !ended);

    const incEl = $('incomplete-banner');
    if (incEl) {
      incEl.hidden = !view.has_incomplete_stream;
      if (view.has_incomplete_stream) {
        $('incomplete-preview').textContent = view.incomplete_partial_text || '刚才那句没说完，点右边「重新生成这句」就能接上。';
      }
    }

    const logEl = $('transcript');
    if (logEl) {
      logEl.replaceChildren();
      (view.turns || []).forEach((t) => {
        const box = node('div', undefined, `ci-msg ${t.role === 'interviewer' ? 'is-interviewer' : 'is-user'}`);
        let who;
        if (t.role === 'interviewer') {
          const mLabel = t.move ? (MOVE_LABELS[t.move] || '') : '';
          who = mLabel ? `面试官 | ${mLabel}` : '面试官';
        } else {
          const cLabel = t.command ? (USER_CMD_LABELS[t.command] || '') : '';
          who = cLabel ? `我（${cLabel}）` : '我';
        }
        const bodyText = t.text || (t.command ? (USER_CMD_LABELS[t.command] || '') : '');
        box.append(node('div', who, 'ci-msg-meta'), node('div', bodyText));
        logEl.append(box);
      });
      if (streamingText) {
        const box = node('div', undefined, 'ci-msg is-interviewer');
        box.append(node('div', '面试官 | 正在输入…', 'ci-msg-meta'), node('div', streamingText));
        logEl.append(box);
      } else if (view.status === 'awaiting_first' && !(view.turns || []).length) {
        logEl.append(makeTypingBubble('面试官正在准备第一句开场白…'));
      }
      logEl.scrollTop = logEl.scrollHeight;
    }

    const composer = $('composer');
    if (composer) composer.hidden = ended || view.status === 'awaiting_first';
    const resumeBtn = $('cmd-resume');
    const pauseBtn = $('cmd-pause');
    if (resumeBtn) resumeBtn.hidden = view.status !== 'paused';
    if (pauseBtn) pauseBtn.hidden = view.status === 'paused' || ended;

    startClockSync();
    if (ended && view.debrief_ready) {
      loadRecap();
    } else if ($('debrief-section')) {
      $('debrief-section').hidden = true;
    }
  }

  async function runStream(intent, startedAtMs = Date.now()) {
    if (!sessionId) return;
    setBusyState(true, '面试官正在开口...');
    setStatusNotice('面试官正在整理开场白，马上开始…');
    if (intent === 'first' && (!currentView?.turns?.length)) {
      showOpeningTransition(2, startedAtMs);
    }
    try {
      const resp = await fetch(`/api/career-user/comprehensive-interviews/${sessionId}/stream?mode=user`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify({ event_id: crypto.randomUUID(), intent, mode: 'user' }),
      });
      if (!resp.ok || !resp.body) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.error || `网络有点卡住了 (${resp.status})，点上面按钮再试一次就行`);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buf = '';
      let partial = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop() || '';
        for (const block of parts) {
          let evName = 'message';
          let dataRaw = '';
          for (const line of block.split('\n')) {
            if (line.startsWith('event:')) evName = line.slice(6).trim();
            else if (line.startsWith('data:')) dataRaw += line.slice(5).trim();
          }
          if (!dataRaw) continue;
          const payload = JSON.parse(dataRaw);
          if (evName === 'token') {
            partial = payload.text || (partial + (payload.delta || ''));
            renderView(currentView, partial);
          } else if (evName === 'done') {
            renderView(payload.view, null);
            setStatusNotice('');
          } else if (evName === 'error') {
            if (payload.view) renderView(payload.view, null);
            setStatusNotice(payload.error || '刚才说到一半网络断了，点「重新生成这句」就能接上', true);
          }
        }
      }
    } catch (err) {
      setStatusNotice(err.message, true);
    } finally {
      stopTransitionTimer();
      setBusyState(false);
    }
  }

  async function startInterview(event) {
    event.preventDefault();
    if (busy || mode() !== 'user') {
      if (mode() !== 'user') setStatusNotice('请先切换到个人 user 模式后再开始模拟面试哦。', true);
      return;
    }
    const startedAtMs = Date.now();
    setBusyState(true, '正在进场...');
    setStatusNotice('正在结合你的简历与项目准备这场面试…');
    showOpeningTransition(1, startedAtMs);
    try {
      const kIds = [...document.querySelectorAll('input[name="ci-knowledge"]:checked')].map((el) => el.value);
      const body = {
        role_family: $('role-family').value,
        round: $('round').value,
        duration_minutes: Number($('duration').value),
        job_id: $('job').value || null,
        jd_text: $('jd').value.trim(),
        resume_version_id: $('resume-version').value || null,
        knowledge_snapshot_ids: kIds,
        previous_session_id: $('prev-session').value.trim() || null,
        cold_start_mode: $('cold-start').value,
      };
      const res = await api('POST', '/comprehensive-interviews', body);
      renderView(res.view);
      await runStream('first', startedAtMs);
    } catch (err) {
      stopTransitionTimer();
      if ($('setup')) $('setup').hidden = false;
      if ($('stage')) $('stage').hidden = true;
      if ($('status-badge')) $('status-badge').textContent = '准备开始';
      setStatusNotice(err.message, true);
      setBusyState(false);
    }
  }

  async function submitTurn(commandOverride = null) {
    if (busy || !sessionId) return;
    const ansInput = $('answer');
    const codeInput = $('code-box');
    let text = ansInput ? ansInput.value.trim() : '';
    const codeText = (codeInput && !$('code-wrap').hidden) ? codeInput.value.trim() : '';
    if (codeText) {
      text = text ? `${text}\n\n[代码/思路草稿]\n${codeText}` : `[代码/思路草稿]\n${codeText}`;
    }
    if (!text && !commandOverride) {
      setStatusNotice('先写两句你的想法，或者点下面的「给点提示」/「先过这题」也行。', true);
      return;
    }
    const localActions = {
      pause: '好，正准备帮你暂停…',
      resume: '正在恢复计时，马上继续…',
      open_book: '收到，记下你翻了下资料…',
      request_hint: '面试官正在想一个合适的提示…',
      skip: '没关系，面试官正在看下一道题…',
      force_skip: '正在帮你切换下一题…',
    };
    const thinkingMsg = commandOverride ? (localActions[commandOverride] || '面试官正在看…') : '面试官正在认真听你的回答，思考下一句…';
    setBusyState(true, commandOverride ? '处理中...' : '面试官思考中...');
    setStatusNotice(thinkingMsg);
    appendOptimisticTurn(text, commandOverride, thinkingMsg);
    try {
      const res = await api('POST', `/comprehensive-interviews/${sessionId}/turns`, {
        event_id: crypto.randomUUID(),
        text,
        command: commandOverride,
        input_channel: 'text',
      });
      if (!commandOverride || commandOverride === 'clarify_case') {
        if (ansInput) ansInput.value = '';
        if (codeInput) codeInput.value = '';
      }
      renderView(res.view);
      setStatusNotice('');
    } catch (err) {
      renderView(currentView);
      setStatusNotice(err.message, true);
    } finally {
      setBusyState(false);
    }
  }

  async function finishInterview(early = false) {
    if (busy || !sessionId) return;
    const label = '正在翻看整场对话，整理你的复盘建议…';
    setBusyState(true, '正在整理复盘...');
    setStatusNotice(label);
    appendOptimisticTurn('', early ? 'early_terminate' : 'finish', label);
    try {
      const res = await api('POST', `/comprehensive-interviews/${sessionId}/finish`, { early });
      renderView(res.view);
      setStatusNotice('复盘整理好了，往下拉就能看！');
    } catch (err) {
      renderView(currentView);
      setStatusNotice(err.message, true);
    } finally {
      setBusyState(false);
    }
  }

  async function loadRecap() {
    if (!sessionId) return;
    try {
      const data = await api('GET', `/comprehensive-interviews/${sessionId}/recap`);
      const debrief = data.recap;
      const box = $('debrief-section');
      if (!box || !debrief) return;
      box.hidden = false;

      const readinessText = READINESS_LABELS[debrief.readiness] || debrief.readiness;
      $('debrief-summary').textContent = `整体判断：${readinessText}。${debrief.readiness_reason}（说明：这里只帮你做真实练习诊断，不代表最终录用结果。）`;
      $('debrief-top-fix').textContent = `眼下最值得先改的一点：${debrief.top_priority_fix}`;

      const dimsEl = $('debrief-dims');
      dimsEl.replaceChildren();
      (debrief.dimensions || []).forEach((d) => {
        const card = node('div', undefined, 'ci-card');
        const scoreLabel = (d.evidence_insufficient || d.score === null) ? '这部分还没聊展开，暂不打分' : `${d.score} / 5`;
        card.append(node('strong', `${d.label}（${scoreLabel}）`), node('p', d.comment));
        (d.evidence_quotes || []).forEach((q) => card.append(node('blockquote', `你当时说：「${q}」`, 'ci-quote')));
        if (d.missing_evidence) card.append(node('p', `可以补全的地方：${d.missing_evidence}`, 'hint'));
        dimsEl.append(card);
      });

      const flagsEl = $('debrief-flags');
      flagsEl.replaceChildren();
      (debrief.red_flags_and_signals || []).forEach((rf) => {
        const sevLabel = SEVERITY_LABELS[rf.severity] || rf.severity;
        flagsEl.append(node('li', `【${sevLabel}】${rf.summary}${rf.evidence_quote ? `（原话：「${rf.evidence_quote}」）` : ''}`));
      });

      const draftsEl = $('debrief-resume-drafts');
      draftsEl.replaceChildren();
      (debrief.resume_suggestions || []).forEach((s) => {
        const actLabel = RESUME_ACTION_LABELS[s.action] || s.action;
        draftsEl.append(node('li', `${actLabel}（仅供你手动参考，不会自动改简历）：${s.rationale}`));
      });

      const drillSel = $('drill-question');
      if (drillSel) {
        const qIds = (debrief.drill_question_ids && debrief.drill_question_ids.length)
          ? debrief.drill_question_ids
          : ['q_proj_1'];
        drillSel.replaceChildren(...qIds.map((qid, i) => new Option(`第 ${i + 1} 个待打磨问题 (${qid})`, qid)));
      }
    } catch (err) {
      setStatusNotice(err.message, true);
    }
  }

  async function submitDrill(event) {
    event.preventDefault();
    if (busy || !sessionId) return;
    const answer = $('drill-answer').value.trim();
    if (!answer) {
      setStatusNotice('先试着重新讲一遍，再点提交看看反馈。', true);
      return;
    }
    setBusyState(true, '教练正在点评...');
    setStatusNotice('正在对照你刚才的回答看看哪里讲透了…');
    try {
      const qid = $('drill-question').value;
      const res = await api('POST', `/comprehensive-interviews/${sessionId}/drill`, {
        event_id: crypto.randomUUID(),
        question_id: qid,
        answer,
      });
      const fb = res.feedback;
      currentDrillAttempt = fb.attempt;
      const out = $('drill-result');
      out.hidden = false;
      out.replaceChildren(
        node('p', `第 ${fb.attempt} 遍练习 | 本次重点：${fb.target_gap}${fb.switched_perspective ? '（换了个新角度再练一遍）' : ''}`),
        node('p', `这次讲清楚了：${fb.added_evidence || '正在积累中'}`),
        node('p', `还可以补一点：${fb.remaining_gap || '关键要素基本齐了'}`),
        node('p', `教练建议：${fb.prompt}`),
        fb.recast_example ? node('blockquote', `参考这样讲更顺（只保留了你真实提过的数字）：${fb.recast_example}`, 'ci-quote') : node('span', ''),
      );
      setStatusNotice('');
    } catch (err) {
      setStatusNotice(err.message, true);
    } finally {
      setBusyState(false);
    }
  }

  async function openSession(sid) {
    if (!sid || mode() !== 'user') return;
    try {
      const res = await api('GET', `/comprehensive-interviews/${sid}`);
      renderView(res.view);
    } catch (err) {
      safeSet(STORAGE_KEY, '');
      setStatusNotice(err.message, true);
    }
  }

  function bindEvents() {
    if (!$('panel')) return;
    $('setup-form')?.addEventListener('submit', startInterview);
    $('submit-answer')?.addEventListener('click', () => submitTurn(null));
    $('retry-stream')?.addEventListener('click', () => runStream('retry'));
    $('export-md')?.addEventListener('click', () => {
      if (!sessionId) return;
      window.open(`/api/career-user/comprehensive-interviews/${sessionId}/export?mode=user&format=markdown`, '_blank', 'noopener');
    });
    $('new-session')?.addEventListener('click', () => {
      stopTransitionTimer();
      clearInterval(tickTimer);
      currentView = null;
      sessionId = '';
      safeSet(STORAGE_KEY, '');
      if ($('setup')) $('setup').hidden = false;
      if ($('stage')) $('stage').hidden = true;
      if ($('debrief-section')) $('debrief-section').hidden = true;
      if ($('timer-badge')) $('timer-badge').hidden = true;
      if ($('status-badge')) $('status-badge').textContent = '准备开始';
      setBusyState(false);
      setStatusNotice('');
      refreshSources();
    });

    document.querySelectorAll('[data-ci-cmd]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const cmd = btn.getAttribute('data-ci-cmd');
        if (cmd === 'finish') finishInterview(false);
        else if (cmd === 'early_terminate') finishInterview(true);
        else submitTurn(cmd);
      });
    });

    $('drill-form')?.addEventListener('submit', submitDrill);

    const ans = $('answer');
    if (ans) {
      ans.addEventListener('compositionstart', () => { composing = true; });
      ans.addEventListener('compositionend', () => { composing = false; compositionEnded = performance.now(); });
      ans.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' || event.shiftKey) return;
        if (event.isComposing || composing || event.keyCode === 229) return;
        if (compositionEnded && performance.now() - compositionEnded < 500) {
          compositionEnded = 0;
          return;
        }
        event.preventDefault();
        submitTurn(null);
      });
    }

    refreshSources();
    if (sessionId && mode() === 'user') openSession(sessionId);
  }

  window.OfferPilotComprehensive = { openSession, refreshSources };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindEvents);
  } else {
    bindEvents();
  }
})();
