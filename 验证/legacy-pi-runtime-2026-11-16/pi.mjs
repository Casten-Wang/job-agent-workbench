// Project-local Pi CLI; do not modify the user's global Pi configuration.
import { fileURLToPath } from 'node:url';
const projectRoot = fileURLToPath(new URL('../', import.meta.url));
process.chdir(projectRoot);
process.env.PI_CODING_AGENT_DIR = fileURLToPath(new URL('../.pi/runtime/dev/', import.meta.url));
await import('./node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js');
