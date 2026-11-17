// Same pinned upstream Vite dashboard; process-local settings only.
import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(process.argv[2] ?? join(here, '../../outputs/understand-anything/itsdangerous-672971d66a2e/project'));
const graphPath = join(projectRoot, '.ua/knowledge-graph.json');
if (!existsSync(graphPath)) throw new Error('No validated knowledge graph is present; finish analysis first.');
const graph = JSON.parse(readFileSync(graphPath, 'utf8'));
if (!Array.isArray(graph.nodes) || graph.nodes.length === 0) throw new Error('Refusing to open an empty graph.');
const dashboard = join(here, 'source/understand-anything-plugin/packages/dashboard');
process.env.GRAPH_DIR = projectRoot;
const { createServer } = await import(pathToFileURL(join(dashboard, 'node_modules/vite/dist/node/index.js')).href);
const server = await createServer({
  root: dashboard,
  configFile: join(dashboard, 'vite.config.ts'),
  server: { host: '127.0.0.1', port: 18745, strictPort: true, open: false },
});
await server.listen();
server.printUrls();
