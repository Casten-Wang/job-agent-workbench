// Local deterministic transport fixture; never contacts a model provider.
import { contractAgent } from './contract-provider.mjs';
const fixture = await contractAgent((stage, body) => {
  if (stage !== 'intent') throw new Error('Only intent contract expected');
  return { intent: 'answer', reason: 'local Python to Pi bridge contract', clarification: '' };
});
console.log(JSON.stringify({ base_url: fixture.baseUrl }));
process.stdin.resume();
process.stdin.on('end', async () => { await fixture.close(); });
