import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { McpClient, StreamableHttpTransport } from '@earendil-works/pi-mcp';

const root = fileURLToPath(new URL('../', import.meta.url));
const config = JSON.parse(await readFile(new URL('../.pi/mcp.json', import.meta.url), 'utf8'));
const client = new McpClient({ name: 'resume-interview-context7-check', version: '0.1.0', requestTimeoutMs: 55000 });
const report = { checked_at: new Date().toISOString(), endpoint: config.mcpServers.context7.url,
  client: '@earendil-works/pi-mcp@1.5.2', authenticated: Boolean(process.env.CONTEXT7_API_KEY), ok: false };
const text = (result) => result.content?.filter((c) => c.type === 'text').map((c) => c.text).join('\n') ?? '';
try {
  await client.connect(new StreamableHttpTransport({ url: report.endpoint, openGetStream: false,
    headers: process.env.CONTEXT7_API_KEY ? { Authorization: `Bearer ${process.env.CONTEXT7_API_KEY}` } : {},
    fetch: (url, options) => fetch(url, { ...options,
      signal: AbortSignal.any([options?.signal ?? new AbortController().signal, AbortSignal.timeout(55000)]) }) }));
  report.server = client.serverInfo;
  report.tools = (await client.listTools()).map((tool) => tool.name);
  const query = 'Pi coding agent SDK createAgentSession customTools ModelRuntime structured tool output';
  const resolved = await client.callTool('resolve-library-id', { libraryName: 'pi coding agent', query });
  report.resolve = { query, is_error: Boolean(resolved.isError), text: text(resolved) };
  const match = report.resolve.text.match(/Context7-compatible library ID:\s*(\/[^\s`]+)/i);
  if (match && !resolved.isError) {
    const docs = await client.callTool('query-docs', { libraryId: match[1], query });
    report.docs = { library_id: match[1], is_error: Boolean(docs.isError), text: text(docs) };
  }
  report.ok = !report.resolve.is_error && Boolean(report.docs && !report.docs.is_error && report.docs.text.trim());
} catch (error) {
  // Keep provider responses and credentials out of the report on failure.
  report.error = { name: error.name, status: error.status ?? null };
  process.exitCode = 1;
} finally {
  await client.close();
  await mkdir(new URL('../outputs/pi-interview/', import.meta.url), { recursive: true });
  await writeFile(new URL('../outputs/pi-interview/context7-verification.json', import.meta.url), JSON.stringify(report, null, 2));
}
console.log(JSON.stringify({ ...report, resolve: report.resolve && { ...report.resolve, text: report.resolve.text.slice(0, 1400) },
  docs: report.docs && { ...report.docs, text: report.docs.text.slice(0, 1400) }, root }, null, 2));
