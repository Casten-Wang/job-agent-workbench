import { spawnSync } from 'node:child_process';
import { mkdir, writeFile, rename } from 'node:fs/promises';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { root, createDecisionAgent, runtimeFromEnv, loadProviderConfig } from './agent.mjs';
import { startLocalHub } from './hub-client.mjs';
import { Interview } from './interview.mjs';

const output = join(root, 'outputs/pi-interview');
await mkdir(output, { recursive: true });
const file = join(output, 'live-verification.json');
const report = { started_at: new Date().toISOString(), status: 'starting', ok: false,
  verification_kind: 'live_endpoint_public_project_synthetic_answer', synthetic_answers: true,
  real_user_assessment: false, completed_model_stages: [] };
const save = async () => { await writeFile(`${file}.tmp`, JSON.stringify(report, null, 2)); await rename(`${file}.tmp`, file); };
let local;
try {
  await save();
  if (process.argv.includes('--key-stdin')) {
    if (process.stdin.isTTY) process.stdin.setRawMode(true);
    const input = createInterface({ input: process.stdin, terminal: false });
    console.log('Hidden credential input ready.');
    let line;
    try { line = await input[Symbol.asyncIterator]().next(); }
    finally { input.close(); if (process.stdin.isTTY) process.stdin.setRawMode(false); }
    if (line.done || !line.value.trim()) throw new Error('missing_credential');
    process.env.PI_INTERVIEW_API_KEY = line.value.trim();
  }
  const runtime = await runtimeFromEnv();
  const config = await loadProviderConfig();
  report.generation = { provider: runtime.model.provider, model: runtime.model.id, kind: 'live_model' };
  report.api = runtime.model.api;
  report.endpoint_host = new URL(process.env.PI_INTERVIEW_BASE_URL || config.base_url || runtime.model.baseUrl).host;
  const sdkAgent = createDecisionAgent(runtime);
  const agent = { generation: sdkAgent.generation, async decide(stage, input, validate) {
    report.status = `calling_${stage}`;
    await save();
    console.log(`正在验证 ${stage}…`);
    const decision = await sdkAgent.decide(stage, input, validate);
    report.completed_model_stages.push(stage);
    await save();
    return decision;
  } };
  const runDirectory = join(output, `live-${Date.now()}`);
  await mkdir(runDirectory, { recursive: true });
  const db = join(runDirectory, 'interview.db');
  const python = process.env.INTERVIEW_PYTHON || 'python';
  const seeded = spawnSync(python, ['-X', 'utf8', '-m', 'interview_hub', 'import-demo', '--db', db],
    { cwd: root, windowsHide: true, encoding: 'utf8' });
  if (seeded.status !== 0) throw new Error('public_demo_import_failed');
  const materialId = JSON.parse(seeded.stdout).material_id;
  local = await startLocalHub({ python, db });
  const interview = new Interview(local.client, agent, join(runDirectory, 'states'));
  const view = await interview.start({ materialId, target: { role: '初级后端开发', round: '模型接口验证，合成回答' } });
  report.session_id = view.session_id;
  report.question_plan_id = interview.state.question_plan_id;
  report.source_commit = interview.state.source_commit;
  report.questions = interview.context.material.questions;
  // Synthetic provenance belongs to the harness metadata, not the candidate utterance.
  await interview.handle('签名结果保留原消息，并附上计算得到的签名；消息本身没有被加密。验签会拆分并核对签名。');
  if (!['plan', 'intent', 'observation'].every((stage) => report.completed_model_stages.includes(stage)) ||
    Object.keys(interview.state.observations).length !== 1) throw new Error('required_model_stage_missing');
  while (interview.question()) await interview.handle('/skip', 'skip');
  const completed = await interview.handle('/finish', 'finish');
  if (completed.status !== 'completed' || completed.recap.applied_to_resume || completed.recap.ability_verdict !== null) throw new Error('recap_invariant_failed');
  report.ok = true;
  report.status = 'completed';
  report.artifacts_directory = runDirectory;
  report.example_recap = completed.recap;
  console.log('真实接口的出题、意图识别、观察与入库复盘验证完成。所有回答均为合成样例。');
} catch (error) {
  report.status = 'failed';
  report.error = { name: error.name, code: error.code ?? null, status: error.status ?? null };
  if (error.status) console.error(`接口返回 HTTP ${error.status}；错误正文未写入日志。`);
  console.error('验证未完成。请核对接口根地址、准确模型 ID、协议及工具调用支持、访问凭据；已完成阶段保留在验证记录。');
  process.exitCode = 1;
} finally {
  if (process.argv.includes('--key-stdin')) delete process.env.PI_INTERVIEW_API_KEY;
  await local?.close();
  report.finished_at = new Date().toISOString();
  await save();
}
