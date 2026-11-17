import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { root } from '../agent.mjs';
import { startLocalHub } from '../hub-client.mjs';
import { Interview } from '../interview.mjs';
import { contractAgent } from './contract-provider.mjs';

function requestInput(body) {
  const content = body.messages.find((message) => message.role === 'user').content;
  return JSON.parse(typeof content === 'string' ? content : content.filter((c) => c.type === 'text').map((c) => c.text).join('\n'));
}

export async function runFlow() {
  const directory = await mkdtemp(join(tmpdir(), 'resume-pi-contract-'));
  const db = join(directory, 'interview.db');
  const python = process.env.INTERVIEW_PYTHON || 'python';
  const imported = spawnSync(python, ['-X', 'utf8', '-m', 'interview_hub', 'import-demo', '--db', db],
    { cwd: root, windowsHide: true, encoding: 'utf8' });
  if (imported.status !== 0) throw new Error('公开项目样例导入失败；请先完成 GitHub/UA 样例提取并设置 INTERVIEW_PYTHON。');
  const materialId = JSON.parse(imported.stdout).material_id;
  const local = await startLocalHub({ python, db });
  const fixture = await contractAgent((stage, body) => {
    const input = requestInput(body);
    if (stage === 'plan') return { questions: input.material.questions.map((q, i) => ({ question_id: `pi_q${i + 1}`,
      claim_id: q.claim_id, text: `本地协议验证题 ${i + 1}：${q.text}`, evidence_ids: q.evidence_ids,
      intent: i === 2 ? 'failure_boundary' : 'implementation', reason: '确定性协议测试，非真实模型生成' })) };
    if (stage === 'intent') {
      const intents = { '给个提示': 'request_hint', '我先停一会儿': 'pause', '继续': 'resume',
        '这些是库的功能，我只负责接入': 'correct_contribution', '我讲的是另一个版本': 'correct_version',
        '到这里就结束并保存': 'finish' };
      return { intent: intents[input.user_text] || 'answer', reason: '确定性测试路由；不代表识别准确率', clarification: '' };
    }
    if (stage === 'hint') return { text: '先沿当前源码确认输入、拼接字段和返回值。', evidence_ids: input.question.evidence_ids };
    if (stage === 'observation') return { status: 'partial', gap_type: 'understanding',
      notes: '合成测试观察，待用户确认，不是能力评估。', evidence_ids: input.question.evidence_ids };
    throw new Error('Unexpected test stage');
  });
  const checks = [];
  const mark = (name, fn) => { fn(); checks.push({ name, passed: true }); };
  try {
    const first = new Interview(local.client, fixture.agent, join(directory, 'states'));
    const opened = await first.start({ materialId, sessionId: 'contract_round1', target: { role: '初级后端', round: '协议验证' } });
    mark('generated_plan_bound_to_frozen_source', () => {
      assert.equal(opened.question.question_id, 'pi_q1');
      assert.ok(first.state.question_plan_id);
    });
    await first.handle('给个提示');
    await first.handle('签名结果包含原消息以及签名。');
    mark('assisted_answer_keeps_assistance_flag', () => assert.equal(first.state.answers.pi_q1.assistance_mode, 'hinted'));
    const beforePause = fixture.requests.length;
    await first.handle('我先停一会儿');
    await first.handle('这是一个不能在暂停时被评估的回答');
    mark('paused_answer_cannot_trigger_evaluation', () => {
      assert.equal(first.state.status, 'paused');
      assert.equal(Object.keys(first.state.answers).length, 1);
      assert.equal(fixture.requests.length - beforePause, 4); // Two intent calls only.
    });
    const restored = new Interview(local.client, fixture.agent, join(directory, 'states'));
    await restored.start({ sessionId: 'contract_round1', resume: true });
    mark('restart_restores_pause_plan_and_answers', () => {
      assert.equal(restored.state.status, 'paused');
      assert.equal(restored.state.question_plan_id, first.state.question_plan_id);
      assert.equal(restored.state.answers.pi_q1.assistance_mode, 'hinted');
    });
    await restored.handle('继续');
    await restored.handle('这些是库的功能，我只负责接入');
    await restored.handle('继续');
    mark('contribution_correction_holds_judgement_and_cannot_resume', () => {
      assert.equal(restored.state.status, 'held');
      assert.equal(restored.state.observations.pi_q1.status, 'not_assessed');
      assert.equal(restored.state.correction.confirmed, false);
    });
    const done = await restored.handle('到这里就结束并保存');
    const saved = await local.client.request('/v1/sessions/contract_round1/results');
    mark('result_and_recap_preserve_plan_provenance_and_corrections', () => {
      assert.equal(done.status, 'completed');
      assert.equal(saved.payload.question_plan_id, restored.state.question_plan_id);
      assert.equal(done.recap.upstream_generation.kind, 'contract_test');
      assert.equal(done.recap.pending_corrections[0].confirmed, false);
      assert.equal(done.recap.ability_verdict, null);
      assert.equal(done.recap.applied_to_resume, false);
    });
    const second = new Interview(local.client, fixture.agent, join(directory, 'states'));
    await second.start({ materialId, sessionId: 'contract_round2', target: { role: '初级后端', round: '第二轮协议验证' } });
    mark('next_round_receives_prior_recap_reference', () => assert.equal(second.context.related_history[0].session_id, 'contract_round1'));
    await second.handle('本题只描述消息签名，不意味着加密。');
    await second.handle('/skip', 'skip');
    await second.handle('时间戳也参与签名，过期需要单独处理。');
    const final = await second.handle('/finish', 'finish');
    mark('skipped_answer_is_not_assessed_and_tasks_remain_drafts', () => {
      assert.ok(final.recap.not_assessed.some((q) => q.question_id === 'pi_q2'));
      assert.ok(final.recap.improvement_tasks.length > 0);
      assert.equal(final.recap.mastery_verified, false);
    });
    mark('evaluation_material_does_not_leak_into_intent_requests', () => {
      for (const request of fixture.requests.filter((r) => r.tools[0].function.name === 'submit_intent')) {
        const payload = requestInput(request);
        assert.equal(payload.evidence, undefined);
        assert.equal(payload.material, undefined);
        assert.equal(payload.expected_facts, undefined);
      }
      assert.ok(fixture.requests.every((r) => r.tools.length === 1 && r.tools[0].function.name.startsWith('submit_')));
    });
    const disk = JSON.parse(await readFile(join(directory, 'states', 'contract_round2.json'), 'utf8'));
    mark('final_state_survives_disk_reload', () => assert.equal(disk.status, 'completed'));
    let failObservation = true;
    const interruptedAgent = { generation: fixture.agent.generation, async decide(stage, input, validate) {
      if (stage === 'observation' && failObservation) { failObservation = false; throw new Error('simulated model outage'); }
      return fixture.agent.decide(stage, input, validate);
    } };
    const third = new Interview(local.client, interruptedAgent, join(directory, 'states'));
    await third.start({ materialId, sessionId: 'contract_round3', target: { role: '初级后端', round: '故障恢复验证' } });
    await third.handle('/ai-assisted', 'ai_assisted');
    await assert.rejects(third.handle('这是一条需要保留的待评估回答。'), /simulated model outage/);
    const pendingDisk = JSON.parse(await readFile(join(directory, 'states', 'contract_round3.json'), 'utf8'));
    mark('model_failure_preserves_raw_pending_answer_without_judgement', () => {
      assert.equal(pendingDisk.pending.text, '这是一条需要保留的待评估回答。');
      assert.equal(pendingDisk.pending.assistance_mode, 'ai_assisted');
      assert.equal(Object.keys(pendingDisk.observations).length, 0);
    });
    const retry = new Interview(local.client, fixture.agent, join(directory, 'states'));
    await retry.start({ sessionId: 'contract_round3', resume: true });
    await retry.handle('/retry', 'retry');
    mark('retry_evaluates_saved_answer_once_and_preserves_ai_assistance', () => {
      assert.equal(retry.state.pending, null);
      assert.equal(Object.keys(retry.state.answers).length, 1);
      assert.equal(retry.state.answers.pi_q1.assistance_mode, 'ai_assisted');
    });
    await retry.handle('我讲的是另一个版本');
    mark('version_correction_suspends_existing_observation', () => {
      assert.equal(retry.state.status, 'held');
      assert.equal(retry.state.observations.pi_q1.status, 'not_assessed');
      assert.equal(retry.state.source_commit, second.state.source_commit);
    });
    await retry.handle('/finish', 'finish');
    const completed = new Interview(local.client, fixture.agent, join(directory, 'states'));
    const replay = await completed.start({ sessionId: 'contract_round3', resume: true });
    mark('completed_session_restores_saved_recap', () => {
      assert.equal(replay.status, 'completed');
      assert.equal(replay.recap.pending_corrections[0].intent, 'correct_version');
    });
    return { ok: true, verification_kind: 'actual_pi_sdk_local_http_contract_test', real_model_called: false,
      public_demo_only: true, material_id: materialId, model_http_requests: fixture.requests.length,
      checks, artifacts_directory: directory, example_recap: final.recap };
  } catch (error) {
    error.cause = { fixture_errors: fixture.errors,
      last_tool_results: fixture.requests.flatMap((r) => r.messages.filter((m) => m.role === 'tool')).slice(-2) };
    throw error;
  } finally { await fixture.close(); await local.close(); }
}
