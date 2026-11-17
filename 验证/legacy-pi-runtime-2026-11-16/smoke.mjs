import { mkdir, writeFile } from 'node:fs/promises';
import { runFlow } from './test/interview-flow.mjs';

const report = await runFlow();
await mkdir(new URL('../outputs/pi-interview/', import.meta.url), { recursive: true });
await writeFile(new URL('../outputs/pi-interview/contract-verification.json', import.meta.url), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ ...report, example_recap: undefined }, null, 2));
