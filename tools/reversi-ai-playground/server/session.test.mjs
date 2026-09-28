import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Session, oracleDepthArgs } from './session.mjs';

const config = { cli: '/unused', cliSha256: 'fixed', repoRoot: '/tmp', trained: null, oracle: null };
const strategic = { id: 'strategic', openingDepth: 2, midgameDepth: 4, exact: 16 };
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
  const { session } = game(strategic);
  session.query = async () => 'pass';
  await session.drive();
  assert.equal(session.revision, 0);
  assert.equal(session.board[27], 'W');
  assert.match(session.error, /invalid pass/);
});

test('stale AI response and oracle invalid pass cannot advance the board', async () => {
  const ai = game({ id: 'novice', openingDepth: 2, midgameDepth: 2, exact: 0 }).session;
  ai.query = async () => { ai.revision++; return 'd3'; };
  await ai.drive();
  assert.match(ai.error, /late AI response/);
  assert.equal(ai.board[19], '.');
  const oracleConfig = { ...config, oracle: { binary: '/unused-oracle', sha256: 'fixed', dataDir: '/tmp' } };
  const oracle = new Session({ black: { id: 'oracle', openingDepth: 2, midgameDepth: 4, exact: 0 }, white: { id: 'human' } }, oracleConfig, () => {});
  oracle.processes.B = { gtp: async () => ['= pass'], close() {} };
  await oracle.drive();
  assert.match(oracle.error, /invalid pass/);
  assert.equal(oracle.revision, 0);
});

test('unavailable seats and settings beyond accepted range are rejected', () => {
  assert.throws(() => game({ id: 'trained-baseline' }), /unavailable/);
  assert.throws(() => game({ ...strategic, openingDepth: 13 }), /outside accepted/);
  assert.throws(() => game({ ...strategic, exact: 20 }), /outside accepted/);
  const legacy = game({ id: 'strategic', depth: 4, exact: 12 }).session.black;
  assert.deepEqual(legacy, { id: 'strategic', openingDepth: 4, midgameDepth: 4, exact: 12 });
});

test('Oracle move phases and exact threshold use decision numbers', () => {
  assert.deepEqual(oracleDepthArgs({ openingDepth: 2, midgameDepth: 4, exact: 0 }),
    ['-depthprobrange', '1', '20', '2', '100', '-depthprobrange', '21', '60', '4', '100']);
  const exact = oracleDepthArgs({ openingDepth: 2, midgameDepth: 4, exact: 16 });
  assert.deepEqual(exact.slice(0, 10), ['-depthprobrange', '1', '20', '2', '100', '-depthprobrange', '21', '44', '4', '100']);
  assert.deepEqual(exact.slice(10, 15), ['-depthprobrange', '45', '45', '16', '100']);
});

test('Advisor publishes only a complete current-position score set and never blocks a human move', async () => {
  const { session, messages } = game({ id: 'human', advisor: strategic });
  let answer;
  let closed = false;
  session.advisorProcesses.B = { command: () => new Promise(resolve => { answer = resolve; }), close: () => { closed = true; } };
  session.beginAdvisor();
  assert.equal(session.snapshot().advisor.pending, true);
  assert.equal(session.snapshot().advisor.scores, null);
  await session.humanMove({ sessionId: session.sessionId, revision: 0, move: 'd3' });
  assert.equal(closed, true);
  answer(JSON.stringify({ schema_version: 1, position_id: `${session.sessionId}:0:advisor`, board: session.board,
    side: 'B', config_id: 'wrong', outcome: 'move', completed_depth: 1, exact: false, scores: [] }));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(session.snapshot().advisor, null);
  assert.equal(session.revision, 1);
  assert.ok(messages.some(message => message.snapshot?.advisor?.pending));
});

test('Advisor rejects incomplete and non-finite results without stopping play', async () => {
  const { session } = game({ id: 'human', advisor: strategic });
  session.advisorProcesses.B = { command: async () => JSON.stringify({ schema_version: 1,
    position_id: `${session.sessionId}:0:advisor`, board: session.board, side: 'B',
    config_id: 'wrong', outcome: 'move', completed_depth: 1, exact: false,
    scores: [{ move: 'd3', value: Infinity, completed_depth: 1, exact: false }] }), close() {} };
  session.beginAdvisor();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(session.advisor.error, /invalid Advisor/);
  assert.equal(session.error, null);
  await session.humanMove({ sessionId: session.sessionId, revision: 0, move: 'd3' });
  assert.equal(session.revision, 1);
});

test('Advisor atomically accepts the exact legal set and reconnect snapshot retains it', async () => {
  const { session, messages } = game({ id: 'human', advisor: strategic });
  session.advisorConfigIds.B = 'project-ai-advisor-v1:0123456789abcdef';
  const scores = session.snapshot().legal.map((move, index) => ({ move, value: index - 1.5, completed_depth: 2, exact: false }));
  session.advisorProcesses.B = { command: async () => JSON.stringify({ schema_version: 1,
    position_id: `${session.sessionId}:0:advisor`, board: session.board, side: 'B',
    config_id: session.advisorConfigIds.B, outcome: 'move', completed_depth: 2, exact: false, scores }), close() {} };
  session.beginAdvisor();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(session.advisor.pending, false);
  assert.deepEqual(session.snapshot().advisor.scores.map(({ move }) => move), session.snapshot().legal);
  assert.equal(messages.filter(message => message.snapshot?.advisor?.scores).length, 1);
  session.publish(true);
  assert.deepEqual(messages.at(-1).snapshot.advisor, session.advisor);
});

test('Advisor rejects a repeated move even with the right number of scores', async () => {
  const { session } = game({ id: 'human', advisor: strategic });
  session.advisorConfigIds.B = 'project-ai-advisor-v1:0123456789abcdef';
  const scores = session.snapshot().legal.map(() => ({ move: 'd3', value: 0, completed_depth: 2, exact: false }));
  session.advisorProcesses.B = { command: async () => JSON.stringify({ schema_version: 1,
    position_id: `${session.sessionId}:0:advisor`, board: session.board, side: 'B',
    config_id: session.advisorConfigIds.B, outcome: 'move', completed_depth: 2, exact: false, scores }), close() {} };
  session.beginAdvisor();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(session.advisor.error, /invalid Advisor score/);
});

test('Advisor process startup failure reports an error without stopping the game', async () => {
  const { session } = game({ id: 'human', advisor: strategic });
  session.startAdvisorProcess = () => { throw new Error('advisor executable failed'); };
  session.beginAdvisor();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(session.advisor.pending, false);
  assert.match(session.advisor.error, /advisor executable failed/);
  assert.equal(session.error, null);
  await session.humanMove({ sessionId: session.sessionId, revision: 0, move: 'd3' });
  assert.equal(session.revision, 1);
});

test('Human move cancels an asynchronous Advisor startup without blocking play', async () => {
  const { session } = game({ id: 'human', advisor: strategic });
  let aborted = false;
  session.startAdvisorProcess = () => new Promise((resolve, reject) => {
    const controller = new AbortController();
    session.advisorStarts.B = controller;
    controller.signal.addEventListener('abort', () => { aborted = true; reject(new Error('aborted')); });
  });
  session.beginAdvisor();
  await session.humanMove({ sessionId: session.sessionId, revision: 0, move: 'd3' });
  assert.equal(session.revision, 1);
  assert.equal(aborted, true);
  assert.equal(session.advisor, null);
});

test('Oracle Advisor refuses a binary changed after configuration verification', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'reversi-oracle-advisor-'));
  try {
    const binary = join(directory, 'oracle');
    writeFileSync(binary, 'changed');
    const oracleConfig = { ...config, oracle: { binary, sha256: 'old-digest', dataDir: directory } };
    const session = new Session({ black: { id: 'human', advisor: { id: 'oracle', openingDepth: 1, midgameDepth: 1, exact: 0 } },
      white: { id: 'human' } }, oracleConfig, () => {});
    session.beginAdvisor();
    await new Promise(resolve => setImmediate(resolve));
    assert.match(session.advisor.error, /oracle binary digest changed/);
    assert.equal(session.error, null);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
