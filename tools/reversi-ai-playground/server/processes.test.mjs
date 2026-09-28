import test from 'node:test';
import assert from 'node:assert/strict';
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
