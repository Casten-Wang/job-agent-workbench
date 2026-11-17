import { readFile, mkdir, writeFile, rename } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { root } from './agent.mjs';

const fields = ['material_id', 'source_commit', 'resume_version_id', 'project_snapshot_id'];
const pick = (value) => Object.fromEntries(fields.map((key) => [key, value[key]]));
const identifier = (value) => {
  if (!/^[A-Za-z0-9_-]{1,100}$/.test(value)) throw new Error('Invalid session identifier');
  return value;
};
function validateQuestions(material, value) {
  const ids = new Set();
  for (const q of value.questions) {
    const claim = material.claims.find((c) => c.claim_id === q.claim_id);
    if (ids.has(q.question_id) || !claim || !q.evidence_ids.length ||
      q.evidence_ids.some((id) => !claim.evidence_ids.includes(id) || !material.evidence.some((e) => e.evidence_id === id && e.commit_sha === material.source_commit))) {
      throw new Error('Questions must use distinct IDs and related frozen source evidence');
    }
    ids.add(q.question_id);
  }
}
function validateReferences(question, value) {
  if (!value.evidence_ids.length || value.evidence_ids.some((id) => !question.evidence_ids.includes(id))) {
    throw new Error('Decision cites evidence outside the current question');
  }
}

export class Interview {
  constructor(client, agent, stateDir = join(root, 'outputs/pi-interview/sessions')) {
    this.client = client;
    this.agent = agent;
    this.stateDir = stateDir;
  }
  async start({ materialId, sessionId = `pi_${randomUUID().replaceAll('-', '')}`, target = {}, resume = false }) {
    this.sessionId = identifier(sessionId);
    this.file = join(this.stateDir, `${this.sessionId}.json`);
    if (resume) {
      this.state = JSON.parse(await readFile(this.file, 'utf8'));
      if (this.state.session_id !== this.sessionId) throw new Error('Local state belongs to another session');
    } else {
      await this.client.request('/v1/sessions', { session_id: this.sessionId, material_id: materialId, mode: 'resume_readiness', target });
    }
    let context = await this.client.request(this.path('context'));
    if (!resume) {
      if (context.session.state !== 'in_progress' || context.material.question_plan_id) throw new Error('Use resume for an existing interview');
      const plan = await this.agent.decide('plan', { session: context.session, material: context.material, related_history: context.related_history },
        (value) => validateQuestions(context.material, value));
      await this.client.request(this.path('question-plan'), { ...pick(context.material), ...plan, generation: this.agent.generation });
      context = await this.client.request(this.path('context'));
      this.state = { schema_version: 1, session_id: this.sessionId, ...pick(context.material),
        question_plan_id: context.material.question_plan_id, generation: this.agent.generation,
        status: 'active', index: 0, answers: {}, observations: {}, assistance: {}, pending: null, events: [] };
      await this.save();
    }
    if (fields.some((key) => this.state[key] !== context.material[key]) || this.state.question_plan_id !== context.material.question_plan_id ||
      JSON.stringify(this.state.generation) !== JSON.stringify(this.agent.generation)) {
      throw new Error('Resume requires the same source, material, question plan and model');
    }
    this.context = context;
    if (this.state.status === 'completed') {
      const recap = await this.client.request(this.path('recap'));
      return { ...this.view('已恢复保存的复盘。'), recap: recap.payload };
    }
    return this.view();
  }
  path(suffix) { return `/v1/sessions/${this.sessionId}/${suffix}`; }
  question() { return this.context.material.questions[this.state.index]; }
  view(message) {
    return { session_id: this.sessionId, status: this.state.status, message,
      question: this.question() ?? null, answered: Object.keys(this.state.answers).length,
      total: this.context.material.questions.length, is_demo: this.context.material.is_demo };
  }
  async save() {
    await mkdir(this.stateDir, { recursive: true });
    await writeFile(`${this.file}.tmp`, JSON.stringify(this.state, null, 2), { mode: 0o600 });
    await rename(`${this.file}.tmp`, this.file);
  }
  async handle(text, command) {
    if (typeof text !== 'string' || !text.trim() || text.length > 12000) throw new Error('请输入 1 至 12000 字符的回答。');
    if (this.state.status === 'completed') return this.view('本轮已经保存；重新核验请创建新的一轮。');
    if (command === 'retry') return this.state.pending ? this.evaluatePending() : this.view('当前没有需要重试的评估。');
    this.state.events.push({ seq: this.state.events.length + 1, intent: 'user_received', user_text: text,
      question_id: this.question()?.question_id ?? null });
    await this.save();
    const decision = command ? { intent: command, reason: 'explicit_user_command', clarification: '' }
      : await this.agent.decide('intent', { user_text: text, status: this.state.status, question: this.question(),
        recent_events: this.state.events.slice(-6).map((e) => ({ user_text: e.user_text, intent: e.intent })) });
    this.state.events.push({ seq: this.state.events.length + 1, user_text: text, ...decision, question_id: this.question()?.question_id ?? null });
    const q = this.question();
    if (decision.intent === 'finish') return this.finish();
    if (this.state.pending && !['correct_contribution', 'correct_version', 'pause', 'resume', 'clarify'].includes(decision.intent)) {
      await this.save();
      return this.view('上次回答已暂存，评估未完成。请用 /retry 重试，或 /finish 以未评估状态结束。');
    }
    if (decision.intent === 'pause') this.state.status = this.state.status === 'held' ? 'held' : 'paused';
    else if (decision.intent === 'resume') {
      if (this.state.status === 'paused') this.state.status = q ? 'active' : 'ready_to_finish';
      else { await this.save(); return this.view(this.state.status === 'held' ? '职责或版本需要补充材料确认，请在新材料上开始新一轮，或结束本轮。' : '当前没有暂停的提问。'); }
    } else if (['correct_contribution', 'correct_version'].includes(decision.intent)) {
      this.state.status = 'held';
      this.state.correction = { intent: decision.intent, text, claim_id: q?.claim_id ?? null, confirmed: false };
      if (this.state.pending) {
        this.state.answers[this.state.pending.question_id] = this.state.pending;
        this.state.pending = null;
      }
      // Preserve the original observations in the event log, but suspend affected conclusions.
      for (const question of this.context.material.questions) {
        const old = this.state.observations[question.question_id];
        if (old && (decision.intent === 'correct_version' || !q || question.claim_id === q.claim_id)) {
          this.state.events.push({ seq: this.state.events.length + 1, intent: 'observation_suspended', previous: old });
          this.state.observations[question.question_id] = { question_id: question.question_id, status: 'not_assessed',
            gap_type: decision.intent === 'correct_version' ? 'material_coverage' : 'responsibility',
            notes: '用户提出职责或版本修正；原观察暂停，需补充同版本材料确认。', evidence_ids: question.evidence_ids };
        }
      }
      await this.save();
      return this.view('已记录修正并暂停相关判断；原资料和简历未改动。补充并确认新材料后开始新一轮，或 /finish 保存本轮待复核记录。');
    } else if (decision.intent === 'clarify') {
      await this.save(); return this.view(decision.clarification || '请说明是继续回答、暂停，还是结束本轮。');
    } else if (this.state.status !== 'active' || !q) {
      await this.save(); return this.view('当前不接收技术作答。暂停后用 /resume 继续；本轮问完后用 /finish 保存复盘。');
    } else if (decision.intent === 'request_hint') {
      const hint = await this.agent.decide('hint', { question: q, evidence: this.evidence(q) }, (value) => validateReferences(q, value));
      this.markAssistance(q.question_id, 'hinted');
      this.state.events.push({ seq: this.state.events.length + 1, intent: 'hint_delivered', ...hint });
      await this.save(); return this.view(`提示：${hint.text}\n本题将记录为提示后作答。`);
    } else if (['open_book', 'ai_assisted'].includes(decision.intent)) {
      this.markAssistance(q.question_id, decision.intent);
      await this.save();
      return this.view('已记录本题的辅助方式，请继续回答。');
    } else if (decision.intent === 'skip') {
      this.state.answers[q.question_id] = { question_id: q.question_id, text: '', skipped: true,
        assistance_mode: this.state.assistance[q.question_id] || 'independent' };
      this.state.index++;
    } else if (decision.intent === 'answer') {
      if (decision.assistance_mode) this.markAssistance(q.question_id, decision.assistance_mode);
      this.state.pending = { question_id: q.question_id, text, skipped: false,
        assistance_mode: this.state.assistance[q.question_id] || 'independent' };
      await this.save();
      return this.evaluatePending();
    } else throw new Error('Unsupported conversational intent');
    if (!this.question() && this.state.status === 'active') this.state.status = 'ready_to_finish';
    await this.save();
    return this.view();
  }
  markAssistance(questionId, mode) {
    const rank = { independent: 0, open_book: 1, hinted: 2, ai_assisted: 3 };
    const previous = this.state.assistance[questionId] || 'independent';
    if (rank[mode] > rank[previous]) this.state.assistance[questionId] = mode;
  }
  evidence(question) { return this.context.material.evidence.filter((e) => question.evidence_ids.includes(e.evidence_id)); }
  async evaluatePending() {
    const q = this.question();
    if (!q || this.state.status !== 'active' || this.state.pending?.question_id !== q.question_id) throw new Error('No pending answer for this question');
    const evaluation = await this.client.request(this.path('evaluation-context'));
    const draft = evaluation.material.questions.find((question) => question.question_id === q.question_id);
    const observation = await this.agent.decide('observation', { question: draft, answer: this.state.pending,
      claim: evaluation.material.claims.find((c) => c.claim_id === q.claim_id), evidence: this.evidence(q),
      source_commit: this.state.source_commit, prior_corrections: this.state.correction ?? null },
    (value) => {
      validateReferences(q, value);
      if (value.status === 'conflict' && this.evidence(q).filter((e) => value.evidence_ids.includes(e.evidence_id))
        .some((e) => (e.extraction_kind ?? 'extracted') !== 'extracted' || !['source_text', 'source_code', 'code'].includes(e.source_kind ?? 'source_text'))) {
        throw new Error('Conflict requires direct original source evidence');
      }
    });
    this.state.answers[q.question_id] = this.state.pending;
    this.state.observations[q.question_id] = { question_id: q.question_id, ...observation };
    this.state.events.push({ seq: this.state.events.length + 1, intent: 'observation_draft', question_id: q.question_id, ...observation });
    this.state.pending = null;
    this.state.index++;
    this.state.status = this.question() ? 'active' : 'ready_to_finish';
    await this.save();
    return this.view('回答已记录，模型观察会在结束后作为待复核草稿汇总。');
  }
  async finish() {
    if (this.state.pending) {
      this.state.answers[this.state.pending.question_id] = this.state.pending;
      this.state.pending = null;
    }
    this.state.status = 'finalizing';
    await this.save();
    const result = { ...pick(this.state), question_plan_id: this.state.question_plan_id,
      answers: Object.values(this.state.answers), observations: Object.values(this.state.observations),
      assessment_generation: this.state.generation, corrections: this.state.correction ? [this.state.correction] : [],
      summary: 'Pi 生成的逐题观察草稿；不代表独立掌握、本人贡献或整体能力，简历改动须另行确认。' };
    await this.client.request(this.path('results'), result);
    const recap = await this.client.request(this.path('recap'), {});
    this.state.status = 'completed';
    await this.save();
    return { ...this.view('本轮结果与复盘已保存，反馈和补强建议均待确认。'), recap: recap.payload };
  }
}
