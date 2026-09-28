import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { LineProcess } from './processes.mjs';

test('persistent line child answers multiple positions and exits on close', async () => {
  const child = new LineProcess(process.execPath, ['-e', `process.stdin.setEncoding('utf8'); let buf=''; process.stdin.on('data', c => { buf += c; while (buf.includes('\\n')) { const n=buf.indexOf('\\n'); const line=buf.slice(0,n); buf=buf.slice(n+1); process.stdout.write(line+'\\n'); } });`], process.cwd(), 2000);
  try {
    assert.equal(await child.command('position-1'), 'position-1');
    assert.equal(await child.command('position-2'), 'position-2');
  } finally { child.close(); }
});

test('silent process times out within its bound', async () => {
  const child = new LineProcess(process.execPath, ['-e', 'process.stdin.resume()'], process.cwd(), 100);
  try { await assert.rejects(child.command('position'), /timed out/); }
  finally { child.close(); }
});

test('closing a process group also cancels its grandchild', { skip: process.platform === 'win32' }, async () => {
  const directory = mkdtempSync(join(tmpdir(), 'reversi-advisor-group-'));
  const marker = join(directory, 'grandchild-finished');
  const grandchild = `setTimeout(() => require('node:fs').writeFileSync(${JSON.stringify(marker)}, 'done'), 500)`;
  const wrapper = `require('node:child_process').spawn(process.execPath, ['-e', ${JSON.stringify(grandchild)}], {stdio:'ignore'}); console.log('ready'); setInterval(() => {}, 1000)`;
  const child = new LineProcess(process.execPath, ['-e', wrapper], process.cwd(), 2000, true);
  try {
    assert.equal(await child.line(), 'ready');
    child.close();
    await new Promise(resolve => setTimeout(resolve, 700));
    assert.equal(existsSync(marker), false);
  } finally { child.close(); rmSync(directory, { recursive: true, force: true }); }
});
