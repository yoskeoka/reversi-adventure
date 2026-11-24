import WebSocket from 'ws';
import assert from 'node:assert/strict';
import { INITIAL_BOARD, legalMoves, other, play } from './rules.mjs';

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
const catalog = await first.next(message => message.type === 'catalog');
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

function assertXot(snapshot, list) {
  assert.equal(snapshot.opening.kind, 'xot');
  assert.equal(snapshot.opening.list, list);
  assert.match(snapshot.opening.notation, /^(?:[a-h][1-8]){8}$/);
  const moves = snapshot.opening.notation.match(/../g);
  let board = INITIAL_BOARD, side = 'B';
  for (const move of moves) {
    board = play(board, side, move);
    side = other(side);
  }
  assert.equal(snapshot.board, board);
  assert.equal(snapshot.revision, 8);
  assert.equal(snapshot.turn, side);
  assert.deepEqual(snapshot.legal, legalMoves(board, side));
  assert.deepEqual(snapshot.lastMove, { side: 'W', move: moves.at(-1) });
  assert.equal(snapshot.lastPass, null);
  assert.deepEqual(snapshot.thinkingTimeMs, { B: 0, W: 0 });
}

const oracleAvailable = catalog.players.some(player => player.id === 'oracle' && player.available);
second.socket.send(JSON.stringify({ type: 'start', opening: { kind: 'xot' },
  black: { id: oracleAvailable ? 'oracle' : 'strategic', depth: 1, exact: 0 }, white: { id: 'human' } }));
const large = await second.next(message => message.type === 'snapshot' && message.token);
assertXot(large.snapshot, 'large');
const largeMove = await second.next(message => message.type === 'snapshot' &&
  message.snapshot.sessionId === large.snapshot.sessionId && (message.snapshot.revision > 8 || message.snapshot.error));
assert.equal(largeMove.snapshot.error, null);
assert.ok(largeMove.snapshot.thinkingTimeMs.B > 0);
assert.ok(large.snapshot.legal.includes(largeMove.snapshot.lastMove.move));

second.socket.send(JSON.stringify({ type: 'start', opening: { kind: 'xot', list: 'small' }, black: { id: 'human' }, white: { id: 'human' } }));
const small = await second.next(message => message.type === 'snapshot' && message.token);
assertXot(small.snapshot, 'small');
const smallMove = small.snapshot.legal[0];
second.socket.send(JSON.stringify({ type: 'move', sessionId: small.snapshot.sessionId, revision: 8, move: smallMove }));
const afterSmall = await second.next(message => message.type === 'snapshot' && message.snapshot.revision === 9);
assert.deepEqual(afterSmall.snapshot.opening, small.snapshot.opening);
assert.equal(afterSmall.snapshot.board, play(small.snapshot.board, 'B', smallMove));
second.socket.close();
await new Promise(resolve => second.socket.once('close', resolve));
const third = connect();
await new Promise(resolve => third.socket.once('open', resolve));
await third.next(message => message.type === 'catalog');
third.socket.send(JSON.stringify({ type: 'resume', token: small.token }));
const resumedXot = await third.next(message => message.type === 'snapshot' && message.token === small.token);
assert.deepEqual(resumedXot.snapshot, afterSmall.snapshot);
third.socket.close();
if (process.env.PLAYGROUND_TEST_EXPIRY === '1') {
  await new Promise(resolve => third.socket.once('close', resolve));
  await new Promise(resolve => setTimeout(resolve, 31000));
  const fourth = connect();
  await new Promise(resolve => fourth.socket.once('open', resolve));
  await fourth.next(message => message.type === 'catalog');
  fourth.socket.send(JSON.stringify({ type: 'resume', token: small.token }));
  const response = await fourth.next(message => message.type === 'error');
  if (!/expired/.test(response.message)) throw new Error('disconnected session did not expire');
  fourth.socket.close();
}
console.log(`human move, both AI colors, replacement, XOT large/small and reconnect${oracleAvailable ? ', XOT Oracle first move' : ''}${process.env.PLAYGROUND_TEST_EXPIRY === '1' ? ', 30-second expiry' : ''} passed`);
