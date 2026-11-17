// Deterministic local provider for transport and state tests. No real inference.
import { createServer } from 'node:http';
import { InMemoryCredentialStore } from '@earendil-works/pi-ai';
import { ModelRuntime } from '@earendil-works/pi-coding-agent';
import { createDecisionAgent } from '../agent.mjs';

export async function contractAgent(decide, api = 'openai-completions', emitReasoning = false) {
  const requests = [];
  const errors = [];
  const server = createServer(async (req, res) => {
    let raw = '';
    for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw);
    requests.push(body);
    const last = api === 'openai-responses' ? body.input.at(-1) : body.messages.at(-1);
    const tool = api === 'openai-responses' ? body.tools?.[0]?.name : body.tools?.[0]?.function.name;
    let value;
    try { if (last.role !== 'tool' && last.type !== 'function_call_output') value = await decide(tool.replace('submit_', ''), body); }
    catch (error) { errors.push(error.message); res.writeHead(500); res.end('{}'); return; }
    if (api === 'openai-responses') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
      let seq = 0;
      const send = (type, payload) => res.write(`event: ${type}\ndata: ${JSON.stringify({ type, sequence_number: seq++, ...payload })}\n\n`);
      const response = { id: `resp_${requests.length}`, object: 'response', created_at: 1, model: 'local-contract', status: 'in_progress', output: [] };
      send('response.created', { response });
      const item = value ? { id: 'fc_test', type: 'function_call', call_id: `call_${requests.length}`, name: tool, arguments: '', status: 'in_progress' }
        : { id: 'msg_test', type: 'message', role: 'assistant', content: [], status: 'in_progress' };
      send('response.output_item.added', { output_index: 0, item });
      const done = value ? { ...item, arguments: JSON.stringify(value), status: 'completed' }
        : { ...item, content: [{ type: 'output_text', text: '决策已提交。', annotations: [] }], status: 'completed' };
      if (value) {
        send('response.function_call_arguments.delta', { output_index: 0, item_id: item.id, delta: done.arguments });
        send('response.function_call_arguments.done', { output_index: 0, item_id: item.id, arguments: done.arguments });
      }
      send('response.output_item.done', { output_index: 0, item: done });
      send('response.completed', { response: { ...response, status: 'completed', output: [done], usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 } } });
      res.end();
      return;
    }
    const delta = value ? { role: 'assistant', tool_calls: [{ index: 0, id: `call_${requests.length}`, type: 'function',
      function: { name: tool, arguments: JSON.stringify(value) } }] } : { role: 'assistant', content: '决策已提交。' };
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
    if (emitReasoning) res.write(`data: ${JSON.stringify({ id: 'contract_response', object: 'chat.completion.chunk', created: 1,
      model: 'local-contract', choices: [{ index: 0, delta: { role: 'assistant', reasoning: 'synthetic reasoning fixture' }, finish_reason: null }] })}\n\n`);
    for (const [part, finish] of [[delta, null], [{}, value ? 'tool_calls' : 'stop']]) {
      res.write(`data: ${JSON.stringify({ id: 'contract_response', object: 'chat.completion.chunk', created: 1,
        model: 'local-contract', choices: [{ index: 0, delta: part, finish_reason: finish }] })}\n\n`);
    }
    res.end('data: [DONE]\n\n');
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const runtime = await ModelRuntime.create({ credentials: new InMemoryCredentialStore(), modelsPath: null,
    refreshOnCreate: false, allowModelNetwork: false });
  runtime.registerProvider('local-contract', { baseUrl: `http://127.0.0.1:${server.address().port}/v1`,
    api, apiKey: 'local-contract-test-only', models: [{ id: 'local-contract', name: 'Local contract test',
      input: ['text'], reasoning: false, contextWindow: 64000, maxTokens: 3000,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] });
  return { agent: createDecisionAgent({ modelRuntime: runtime, model: runtime.getModel('local-contract', 'local-contract'), kind: 'contract_test', timeoutMs: 12000 }),
    requests, errors, baseUrl: `http://127.0.0.1:${server.address().port}/v1`,
    close: async () => { server.closeAllConnections(); await new Promise((resolve) => server.close(resolve)); } };
}
