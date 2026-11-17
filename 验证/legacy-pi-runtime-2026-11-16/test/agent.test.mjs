import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { createDecisionAgent, runtimeFromEnv } from '../agent.mjs';
import { HubClient } from '../hub-client.mjs';
import { contractAgent } from './contract-provider.mjs';

test('Pi SDK performs a real local HTTP tool-call roundtrip with only the decision tool', async () => {
  const fixture = await contractAgent(() => ({ intent: 'answer', reason: 'local deterministic test', clarification: '' }));
  try {
    const result = await fixture.agent.decide('intent', { user_text: '我来解释这段代码', status: 'active' });
    assert.equal(result.intent, 'answer');
    assert.equal(fixture.requests.length, 2);
    assert.deepEqual(fixture.requests[0].tools.map((t) => t.function.name), ['submit_intent']);
    assert.equal(fixture.agent.generation.kind, 'contract_test');
  } finally { await fixture.close(); }
});

test('host rejects a model decision citing unrelated evidence', async () => {
  const fixture = await contractAgent(() => ({ text: 'test hint', evidence_ids: ['foreign_evidence'] }));
  try {
    await assert.rejects(fixture.agent.decide('hint', {}, (value) => {
      if (!value.evidence_ids.includes('allowed')) throw new Error('Unrelated evidence');
    }), /Pi 未完成有效决策/);
  } finally { await fixture.close(); }
});

test('missing model configuration is explicit and does not choose an account silently', async () => {
  await assert.rejects(runtimeFromEnv({}, {}), /PI_INTERVIEW_PROVIDER/);
});

test('the production environment setup path reaches a compatible local provider through Pi', async () => {
  const fixture = await contractAgent(() => ({ intent: 'pause', reason: 'local contract test', clarification: '' }));
  try {
    const runtime = await runtimeFromEnv({ PI_INTERVIEW_PROVIDER: 'local-contract', PI_INTERVIEW_MODEL: 'local-contract',
      PI_INTERVIEW_BASE_URL: fixture.baseUrl, PI_INTERVIEW_API: 'openai-completions', PI_INTERVIEW_API_KEY: 'local-contract-test-only' }, {});
    const agent = createDecisionAgent({ ...runtime, kind: 'contract_test' });
    assert.equal((await agent.decide('intent', { user_text: '暂停' })).intent, 'pause');
  } finally { await fixture.close(); }
});

test('Hub adapter rejects remote origins, embedded credentials and redirects', () => {
  for (const url of ['https://example.com', 'http://localhost:18746', 'http://user:pass@127.0.0.1', 'http://127.0.0.1/base', 'http://127.0.0.1/?token=x']) {
    assert.throws(() => new HubClient(url, 'test'), /loopback/);
  }
  assert.equal(new HubClient('http://127.0.0.1:18746', 'test').url, 'http://127.0.0.1:18746');
});

test('Responses protocol executes the Pi decision tool and returns its result', async () => {
  const fixture = await contractAgent(() => ({ intent: 'answer', reason: 'Responses protocol contract', clarification: '' }), 'openai-responses');
  try {
    const runtime = await runtimeFromEnv({ PI_INTERVIEW_PROVIDER: 'gpt-proxy-test', PI_INTERVIEW_MODEL: 'local-contract',
      PI_INTERVIEW_BASE_URL: fixture.baseUrl, PI_INTERVIEW_API: 'openai-responses', PI_INTERVIEW_API_KEY: 'local-contract-test-only' }, {});
    const agent = createDecisionAgent({ ...runtime, kind: 'contract_test' });
    assert.equal((await agent.decide('intent', { user_text: '这是一条测试回答' })).intent, 'answer');
    assert.equal(fixture.requests.length, 2);
    assert.equal(fixture.requests[0].tools[0].name, 'submit_intent');
    assert.ok(fixture.requests[1].input.some((item) => item.type === 'function_call_output'));
  } finally { await fixture.close(); }
});

test('Step Plan preset uses Chat Completions, low reasoning and the fixed tool-call contract', async () => {
  const preset = JSON.parse(await readFile(new URL('../stepfun-plan.json', import.meta.url), 'utf8'));
  assert.equal(preset.base_url, 'https://api.stepfun.com/step_plan/v1');
  assert.equal(preset.api, 'openai-completions');
  const fixture = await contractAgent(() => ({ intent: 'answer', reason: 'Step Plan protocol contract', clarification: '' }), 'openai-completions', true);
  try {
    const runtime = await runtimeFromEnv({ PI_INTERVIEW_BASE_URL: fixture.baseUrl, STEP_API_KEY: 'local-contract-test-only' }, preset);
    assert.equal(runtime.model.id, 'step-5-preview');
    assert.equal(runtime.model.contextWindow, 1000000);
    assert.equal(runtime.model.reasoning, true);
    const agent = createDecisionAgent({ ...runtime, kind: 'contract_test' });
    assert.equal((await agent.decide('intent', { user_text: '这是测试回答' })).intent, 'answer');
    assert.equal(fixture.requests.length, 2);
    const request = fixture.requests[0];
    assert.equal(request.reasoning_effort, 'low');
    assert.equal(request.max_tokens, 8192);
    assert.ok(!request.messages.some((m) => m.role === 'developer'));
    assert.ok(fixture.requests[1].messages.some((m) => m.role === 'tool'));
  } finally { await fixture.close(); }
});
