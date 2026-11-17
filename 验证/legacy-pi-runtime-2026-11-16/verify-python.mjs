// Hidden input is used only by the child verification process, never persisted.
import { createInterface } from 'node:readline';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
if (process.stdin.isTTY) process.stdin.setRawMode(true);
const input = createInterface({ input: process.stdin, terminal: false });
console.log('Hidden credential input ready.');
let key;
try { key = (await input[Symbol.asyncIterator]().next()).value?.trim(); }
finally { input.close(); if (process.stdin.isTTY) process.stdin.setRawMode(false); }
if (!key) throw new Error('No credential supplied');
const child = spawn(`${root}.venv-interview/Scripts/python.exe`, ['-X', 'utf8', '-m', 'interview_agent.verify'],
  { cwd: root, windowsHide: true, env: { ...process.env, PI_INTERVIEW_API_KEY: key }, stdio: ['ignore', 'inherit', 'inherit'] });
key = undefined;
process.exitCode = await new Promise((resolve) => child.once('exit', (code) => resolve(code ?? 1)));
