import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { randomBytes } from 'node:crypto';
import { root } from './agent.mjs';

export class HubClient {
  constructor(url, token) {
    const parsed = new URL(url);
    if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1' || parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== '/') {
      throw new Error('Interview Hub must be a loopback HTTP origin');
    }
    this.url = parsed.origin;
    this.token = token;
  }
  async request(path, data) {
    if (!path.startsWith('/v1/') && path !== '/health') throw new Error('Unsupported Hub path');
    const response = await fetch(this.url + path, { method: data === undefined ? 'GET' : 'POST', redirect: 'error',
      headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' },
      body: data === undefined ? undefined : JSON.stringify(data), signal: AbortSignal.timeout(15000) });
    const body = await response.json();
    if (!response.ok) { const error = new Error(`Interview Hub request failed (${response.status})`); error.status = response.status; throw error; }
    return body;
  }
}

export async function startLocalHub({ python = process.env.INTERVIEW_PYTHON || 'python', db = 'outputs/interview-hub/interview.db', owner = 'local-demo' } = {}) {
  const token = randomBytes(32).toString('base64url');
  const child = spawn(python, ['-X', 'utf8', '-m', 'interview_hub', 'serve', '--port', '0', '--db', db, '--owner', owner],
    { cwd: root, windowsHide: true, env: { ...process.env, INTERVIEW_HUB_TOKEN: token }, stdio: ['ignore', 'pipe', 'pipe'] });
  // Startup output contains only the local URL. Tokens travel through the child environment.
  const lines = createInterface({ input: child.stdout });
  try {
    const url = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Interview Hub startup timed out')), 10000);
      child.once('error', () => { clearTimeout(timer); reject(new Error('无法启动 Python；请设置 INTERVIEW_PYTHON。')); });
      child.once('exit', () => { clearTimeout(timer); reject(new Error('Interview Hub exited before startup')); });
      lines.once('line', (line) => { clearTimeout(timer); try { resolve(JSON.parse(line).url); } catch { reject(new Error('Invalid Hub startup response')); } });
    });
    return { client: new HubClient(url, token), close: async () => { lines.close(); if (child.exitCode === null) { child.kill(); await new Promise((resolve) => child.once('exit', resolve)); } } };
  } catch (error) { lines.close(); child.kill(); throw error; }
}
