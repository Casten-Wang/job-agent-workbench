import test from 'node:test';
import { runFlow } from './interview-flow.mjs';

test('Pi -> Hub -> SQLite -> recap end-to-end, with pause, correction, assistance and restart', { timeout: 60000 }, async () => {
  await runFlow();
});
