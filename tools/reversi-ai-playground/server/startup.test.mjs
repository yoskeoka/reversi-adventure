import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { on, once } from 'node:events';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import WebSocket from 'ws';

const index = fileURLToPath(new URL('./index.mjs', import.meta.url));
const humanStart = { type: 'start', black: { id: 'human' }, white: { id: 'human' } };

test('WebSocket validates before replacement and cancels superseded or disconnected XOT initialization', { timeout: 10000 }, async t => {
  const signal = AbortSignal.timeout(9000);
  const directory = mkdtempSync(join(tmpdir(), 'reversi-xot-websocket-'));
  const started = join(directory, 'started');
  const canceled = join(directory, 'canceled');
  const cli = join(directory, 'cli');
  writeFileSync(cli, `#!${process.execPath}
    const { writeFileSync } = require('node:fs');
    if (process.argv[2] !== '--xot-opening' || process.argv[3] === 'small') process.exit(2);
    process.on('SIGTERM', () => {
      writeFileSync(${JSON.stringify(canceled)}, '');
      console.log('{}');
      process.exit(0);
    });
    writeFileSync(${JSON.stringify(started)}, '');
    setInterval(() => {}, 1000);
  `, { mode: 0o755 });
  const child = spawn(process.execPath, [index], { env: {
    ...process.env, PLAYGROUND_PORT: '0', PLAYGROUND_CLI: cli, PLAYGROUND_CONFIG: '', PLAYGROUND_PREPARED_CONFIG: ''
  }, stdio: ['ignore', 'ignore', 'pipe'] });
  const logs = createInterface({ input: child.stderr });
  let socket;
  t.after(async () => {
    socket?.terminate();
    logs.close();
    if (child.exitCode === null && child.signalCode === null) {
      child.kill();
      await once(child, 'exit', { signal: AbortSignal.timeout(2000) });
    }
    rmSync(directory, { recursive: true, force: true });
  });
  const [ready] = await once(logs, 'line', { signal });
  const address = ready.match(/http:\/\/127\.0\.0\.1:(\d+)/);
  assert.ok(address, ready);
  socket = new WebSocket(`ws://127.0.0.1:${address[1]}/ws`);
  const frames = on(socket, 'message', { signal });
  t.after(() => frames.return());
  await once(socket, 'open', { signal });
  const send = message => socket.send(JSON.stringify(message));
  const next = async type => {
    const event = await frames.next();
    const message = JSON.parse(String(event.value[0]));
    assert.equal(message.type, type, JSON.stringify(message));
    return message;
  };
  const waitFor = async path => {
    while (!existsSync(path)) await delay(10, null, { signal });
  };

  await next('catalog');
  send(humanStart);
  const first = await next('snapshot');
  assert.equal(first.snapshot.revision, 0);
  send({ ...humanStart, opening: { kind: 'standard', list: 'large' } });
  const rejected = await next('error');
  assert.equal(rejected.request, 'start');
  assert.equal(rejected.replaced, undefined);
  send({ type: 'move', sessionId: first.snapshot.sessionId, revision: 0, move: 'd3' });
  assert.equal((await next('snapshot')).snapshot.revision, 1);

  send({ ...humanStart, opening: { kind: 'xot' } });
  await waitFor(started);
  send({ ...humanStart, opening: { kind: 'xot', list: 'small' } });
  const failed = await next('error');
  assert.equal(failed.request, 'start');
  assert.equal(failed.replaced, true);
  assert.match(failed.message, /XOT initialization failed/);
  await waitFor(canceled);

  send(humanStart);
  const replacement = await next('snapshot');
  assert.notEqual(replacement.token, first.token);
  send({ type: 'resume', token: first.token });
  const expired = await next('error');
  assert.equal(expired.request, 'resume');
  assert.match(expired.message, /expired/);

  rmSync(started);
  rmSync(canceled);
  send({ ...humanStart, opening: { kind: 'xot' } });
  await waitFor(started);
  socket.close();
  await once(socket, 'close', { signal });
  await waitFor(canceled);
});
