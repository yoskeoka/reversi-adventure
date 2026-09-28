import test from 'node:test';
import assert from 'node:assert/strict';
import { Session } from './session.mjs';

const config = { cli: '/unused', cliSha256: 'fixed', repoRoot: '/tmp', trained: null, oracle: null };
function game(black = { id: 'human' }, white = { id: 'human' }) {
  const messages = [];
  const session = new Session({ black, white, seed: 42 }, config, message => messages.push(message));
  return { session, messages };
}

test('human move advances revision and stale or illegal move leaves board unchanged', async () => {
  const { session, messages } = game();
  await session.humanMove({ sessionId: session.sessionId, revision: 0, move: 'd3' });
  assert.equal(session.revision, 1);
  assert.equal(session.turn, 'W');
  const board = session.board;
  await session.humanMove({ sessionId: session.sessionId, revision: 0, move: 'c3' });
  assert.equal(session.board, board);
  assert.equal(session.revision, 1);
  assert.match(messages.at(-1).snapshot.error, /stale/);
  assert.equal(session.error, null);
});

test('both random seats finish from a fixed seed', async () => {
  const first = game({ id: 'random' }, { id: 'random' });
  const second = game({ id: 'random' }, { id: 'random' });
  await first.session.drive(); await second.session.drive();
  assert.equal(first.session.revision, second.session.revision);
  assert.equal(first.session.board, second.session.board);
  assert.ok(first.session.result);
  assert.equal(first.session.board.includes('.'), false);
});

test('invalid AI answer reports error without advancing position', async () => {
  const { session } = game({ id: 'strategic', depth: 4, exact: 16 });
  session.query = async () => 'pass';
  await session.drive();
  assert.equal(session.revision, 0);
  assert.equal(session.board[27], 'W');
  assert.match(session.error, /invalid pass/);
});

test('stale AI response and oracle invalid pass cannot advance the board', async () => {
  const ai = game({ id: 'novice', depth: 2, exact: 0 }).session;
  ai.query = async () => { ai.revision++; return 'd3'; };
  await ai.drive();
  assert.match(ai.error, /late AI response/);
  assert.equal(ai.board[19], '.');
  const oracleConfig = { ...config, oracle: { binary: '/unused-oracle', sha256: 'fixed', dataDir: '/tmp' } };
  const oracle = new Session({ black: { id: 'oracle' }, white: { id: 'human' } }, oracleConfig, () => {});
  oracle.processes.B = { gtp: async () => ['= pass'], close() {} };
  await oracle.drive();
  assert.match(oracle.error, /invalid pass/);
  assert.equal(oracle.revision, 0);
});

test('unavailable seats and settings beyond accepted range are rejected', () => {
  assert.throws(() => game({ id: 'trained-baseline' }), /unavailable/);
  assert.throws(() => game({ id: 'strategic', depth: 13, exact: 16 }), /outside accepted/);
  assert.throws(() => game({ id: 'novice', depth: 4, exact: 20 }), /outside accepted/);
});
