// Stateless JSONL bridge. Python owns all interview state and business writes.
import { createInterface } from 'node:readline';
import { createDecisionAgent, runtimeFromEnv } from './agent.mjs';

const input = createInterface({ input: process.stdin, terminal: false });
let agent;
for await (const line of input) {
  let request;
  try {
    request = JSON.parse(line);
    if (!agent) agent = createDecisionAgent(await runtimeFromEnv());
    const result = request.method === 'info' ? agent.generation
      : request.method === 'decide' ? await agent.decide(request.stage, request.input)
        : (() => { throw new Error('Unsupported method'); })();
    process.stdout.write(JSON.stringify({ id: request.id, result }) + '\n');
  } catch (error) {
    process.stdout.write(JSON.stringify({ id: request?.id ?? null,
      error: { code: error.code || 'pi_execution_failed', status: error.status || null } }) + '\n');
  }
}
