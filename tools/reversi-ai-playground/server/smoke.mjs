import WebSocket from 'ws';
import assert from 'node:assert/strict';

const url = process.env.PLAYGROUND_WS ?? 'ws://127.0.0.1:8787/ws';
function connect() {
  const socket = new WebSocket(url);
  const messages = [];
  let waiter;
  socket.on('message', data => {
    const message = JSON.parse(String(data));
    if (waiter) { const resolve = waiter; waiter = null; resolve(message); }
    else messages.push(message);
  });
  const next = async predicate => {
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      const message = messages.length ? messages.shift() : await new Promise((resolve, reject) => {
        const timer = setTimeout(() => { waiter = null; reject(new Error('smoke timeout')); }, deadline - Date.now());
        waiter = value => { clearTimeout(timer); resolve(value); };
      });
      if (predicate(message)) return message;
    }
    throw new Error('smoke timeout');
  };
  return { socket, next };
}

const first = connect();
await new Promise(resolve => first.socket.once('open', resolve));
await first.next(message => message.type === 'catalog');
first.socket.send(JSON.stringify({ type: 'start', black: { id: 'human' }, white: { id: 'strategic', depth: 1, exact: 0 } }));
const started = await first.next(message => message.type === 'snapshot' && message.token);
const { token, snapshot } = started;
assert.deepEqual(snapshot.thinkingTimeMs, { B: 0, W: 0 });
first.socket.send(JSON.stringify({ type: 'move', sessionId: snapshot.sessionId, revision: 0, move: 'd3' }));
const afterHuman = await first.next(message => message.type === 'snapshot' && message.snapshot.revision === 1);
const afterAI = await first.next(message => message.type === 'snapshot' && message.snapshot.revision >= 2);
if (afterHuman.snapshot.board === snapshot.board || afterAI.snapshot.board === afterHuman.snapshot.board) throw new Error('moves did not advance board');
assert.equal(afterHuman.snapshot.thinkingTimeMs.B, 0);
assert.equal(afterAI.snapshot.thinkingTimeMs.B, 0);
assert.ok(afterAI.snapshot.thinkingTimeMs.W > 0);
first.socket.close();
await new Promise(resolve => first.socket.once('close', resolve));
const second = connect();
await new Promise(resolve => second.socket.once('open', resolve));
await second.next(message => message.type === 'catalog');
second.socket.send(JSON.stringify({ type: 'resume', token }));
const resumed = await second.next(message => message.type === 'snapshot' && message.token === token);
if (resumed.snapshot.sessionId !== snapshot.sessionId || resumed.snapshot.revision < 2) throw new Error('resume lost state');
assert.deepEqual(resumed.snapshot.thinkingTimeMs, afterAI.snapshot.thinkingTimeMs);
second.socket.send(JSON.stringify({ type: 'start', black: { id: 'novice', depth: 1, exact: 0 }, white: { id: 'human' } }));
const noviceStart = await second.next(message => message.type === 'snapshot' && message.token && message.snapshot.revision === 0);
assert.deepEqual(noviceStart.snapshot.thinkingTimeMs, { B: 0, W: 0 });
const noviceMove = await second.next(message => message.type === 'snapshot' && message.snapshot.sessionId === noviceStart.snapshot.sessionId && message.snapshot.revision >= 1);
if (noviceMove.snapshot.board === noviceStart.snapshot.board) throw new Error('black novice did not move');
assert.ok(noviceMove.snapshot.thinkingTimeMs.B > 0);
assert.equal(noviceMove.snapshot.thinkingTimeMs.W, 0);
second.socket.send(JSON.stringify({ type: 'resume', token }));
const expired = await second.next(message => message.type === 'error');
if (!/expired/.test(expired.message)) throw new Error('replaced session token remained active');
second.socket.close();
if (process.env.PLAYGROUND_TEST_EXPIRY === '1') {
  await new Promise(resolve => second.socket.once('close', resolve));
  await new Promise(resolve => setTimeout(resolve, 31000));
  const third = connect();
  await new Promise(resolve => third.socket.once('open', resolve));
  await third.next(message => message.type === 'catalog');
  third.socket.send(JSON.stringify({ type: 'resume', token: noviceStart.token }));
  const response = await third.next(message => message.type === 'error');
  if (!/expired/.test(response.message)) throw new Error('disconnected session did not expire');
  third.socket.close();
}
console.log(`human move, both AI colors, reconnect, replacement${process.env.PLAYGROUND_TEST_EXPIRY === '1' ? ', and 30-second expiry' : ''} passed`);
