import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, chmodSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Session, catalog, oracleDepthArgs, verifyConfig } from './session.mjs';
import { legalMoves } from './rules.mjs';

const config = { cli: '/unused', cliSha256: 'fixed', repoRoot: '/tmp', trained: null, oracle: null };
const strategic = { id: 'strategic', openingDepth: 2, midgameDepth: 4, exact: 16 };
function game(black = { id: 'human' }, white = { id: 'human' }, now) {
  const messages = [];
  const session = new Session({ black, white, seed: 42 }, config, message => messages.push(message), now);
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
  assert.throws(() => game({ ...strategic, exact: 31 }), /outside accepted/);
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

test('catalog and both player roles accept the same search boundaries without rounding', () => {
  assert.deepEqual(catalog(config).limits, { openingDepth: [1, 12], midgameDepth: [1, 16], exact: [0, 30] });
  for (const settings of [{ ...strategic, openingDepth: 1, midgameDepth: 1, exact: 0 },
    { ...strategic, openingDepth: 12, midgameDepth: 16, exact: 30 }]) {
    assert.deepEqual(game(settings).session.black, settings);
    assert.deepEqual(game({ id: 'human', advisor: settings }).session.black.advisor, settings);
  }
  for (const [field, invalid] of [['openingDepth', [0, 13, 1.5]], ['midgameDepth', [0, 17, 1.5]], ['exact', [-1, 31, 1.5]]]) {
    for (const value of invalid) {
      const settings = { ...strategic, [field]: value };
      assert.throws(() => game(settings), /outside accepted/);
      assert.throws(() => game({ id: 'human', advisor: settings }), /outside accepted/);
    }
  }
  for (const depth of [1, 12]) {
    const legacy = { id: 'strategic', depth, exact: 30 };
    const expected = { id: 'strategic', openingDepth: depth, midgameDepth: depth, exact: 30 };
    assert.deepEqual(game(legacy).session.black, expected);
    assert.deepEqual(game({ id: 'human', advisor: legacy }).session.black.advisor, expected);
  }
  for (const depth of [0, 13, 16]) {
    const legacy = { id: 'strategic', depth, exact: 0 };
    assert.throws(() => game(legacy), /outside accepted/);
    assert.throws(() => game({ id: 'human', advisor: legacy }), /outside accepted/);
  }
});

test('maximum settings reach match CLI and Advisor CLI and Oracle process arguments', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'reversi-search-settings-'));
  const sessions = [];
  try {
    const cli = join(directory, 'cli');
    writeFileSync(cli, `#!${process.execPath}\nif (process.argv.includes('--print-advisor-config-id')) console.log('project-ai-advisor-v1:0123456789abcdef'); else process.stdin.resume();\n`);
    chmodSync(cli, 0o755);
    const local = verifyConfig({ repoRoot: directory, cli, trained: null, oracle: null });
    const settings = { id: 'strategic', openingDepth: 12, midgameDepth: 16, exact: 30 };
    const expected = ['--opening-depth', '12', '--midgame-depth', '16', '--exact-solver-empty-squares', '30'];
    const match = new Session({ black: settings, white: { id: 'human' } }, local, () => {});
    sessions.push(match); match.open();
    assert.deepEqual(match.snapshot().thinkingTimeMs, { B: 0, W: 0 });
    assert.deepEqual(match.processes.B.child.spawnargs.slice(3, 9), expected);
    const advisor = new Session({ black: { id: 'human', advisor: settings }, white: { id: 'human' } }, local, () => {});
    sessions.push(advisor);
    await advisor.startAdvisorProcess('B');
    assert.deepEqual(advisor.advisorProcesses.B.child.spawnargs.slice(4, 10), expected);
    const oracleConfig = verifyConfig({ ...local, oracle: { binary: cli, dataDir: directory } });
    const oracle = new Session({ black: { ...settings, id: 'oracle' }, white: { id: 'human' } }, oracleConfig, () => {});
    sessions.push(oracle); oracle.open();
    assert.deepEqual(oracle.processes.B.child.spawnargs.slice(6, -2), oracleDepthArgs(settings));
    const oracleAdvisor = new Session({ black: { id: 'human', advisor: { ...settings, id: 'oracle' } }, white: { id: 'human' } }, oracleConfig, () => {});
    sessions.push(oracleAdvisor); await oracleAdvisor.startAdvisorProcess('B');
    assert.deepEqual(oracleAdvisor.advisorProcesses.B.child.spawnargs.slice(3, 9), expected);
    assert.deepEqual(oracleDepthArgs(settings).slice(0, 15),
      ['-depthprobrange', '1', '20', '12', '100', '-depthprobrange', '21', '30', '16', '100', '-depthprobrange', '31', '31', '30', '100']);
  } finally {
    for (const session of sessions) session.close();
    rmSync(directory, { recursive: true, force: true });
  }
});

test('query time accumulates separately for both colors through termination and snapshot republication', async () => {
  let clock = 100;
  const { session, messages } = game({ id: 'random' }, { id: 'random' }, () => clock);
  const initial = session.snapshot();
  const expected = { B: 0, W: 0 };
  const query = session.query.bind(session);
  session.query = async (...args) => {
    const duration = args[0] === 'B' ? 2.5 : 4.25;
    clock += duration; expected[args[0]] += duration;
    return query(...args);
  };
  await session.drive();
  assert.ok(session.result);
  assert.ok(expected.B > 2.5 && expected.W > 4.25);
  assert.deepEqual(session.snapshot().thinkingTimeMs, expected);
  assert.deepEqual(initial.thinkingTimeMs, { B: 0, W: 0 });
  session.publish(true);
  assert.deepEqual(messages.at(-1).snapshot.thinkingTimeMs, expected);
  assert.equal(messages.at(-1).token, session.token);
  assert.deepEqual(game().session.snapshot().thinkingTimeMs, { B: 0, W: 0 });
});

test('query failures and timeouts add elapsed time once before publishing the error', async () => {
  for (const failure of ['query failed', 'process response timed out']) {
    let clock = 10;
    const { session, messages } = game(strategic, { id: 'human' }, () => clock);
    session.query = async () => { clock += 37; throw new Error(failure); };
    await session.drive();
    assert.equal(session.error, failure);
    assert.deepEqual(messages.at(-1).snapshot.thinkingTimeMs, { B: 37, W: 0 });
    await session.drive(); session.publish();
    assert.deepEqual(session.snapshot().thinkingTimeMs, { B: 37, W: 0 });
  }
});

test('forced pass never requests or times the passed color', async () => {
  let clock = 0;
  const { session } = game({ id: 'random' }, { id: 'random' }, () => clock);
  session.board = 'B'.repeat(62) + 'W.';
  const queried = [];
  session.query = async side => { queried.push(side); clock += 8; return 'h8'; };
  await session.drive();
  assert.deepEqual(queried, ['B']);
  assert.equal(session.lastPass, 'W');
  assert.equal(session.result, 'B');
  assert.deepEqual(session.snapshot().thinkingTimeMs, { B: 8, W: 0 });
});

test('Human waiting and completed Advisor analysis are excluded from thinking totals', async () => {
  let clock = 0;
  const { session } = game({ id: 'human', advisor: strategic }, { id: 'human' }, () => clock);
  session.advisorConfigIds.B = 'project-ai-advisor-v1:0123456789abcdef';
  session.advisorProcesses.B = { command: async () => {
    clock += 100;
    return JSON.stringify({ schema_version: 1, position_id: `${session.sessionId}:0:advisor`, board: session.board,
      side: 'B', config_id: session.advisorConfigIds.B, outcome: 'move', completed_depth: 2, exact: false,
      scores: legalMoves(session.board, 'B').map(move => ({ move, value: 0, completed_depth: 2, exact: false })) });
  }, close() {} };
  session.beginAdvisor();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(session.advisor.pending, false);
  clock += 1000;
  await session.humanMove({ sessionId: session.sessionId, revision: 0, move: 'd3' });
  assert.deepEqual(session.snapshot().thinkingTimeMs, { B: 0, W: 0 });
});

test('Oracle opponent synchronization is excluded from the next color query time', async () => {
  let clock = 0;
  const local = { ...config, oracle: { binary: '/unused-oracle', sha256: 'fixed', dataDir: '/tmp' } };
  const session = new Session({ black: { id: 'human' }, white: { id: 'oracle', openingDepth: 1, midgameDepth: 1, exact: 0 } }, local, () => {}, () => clock);
  session.processes.W = { gtp: async input => {
    if (input.startsWith('play ')) { clock += 500; return ['=']; }
    clock += 7;
    return [`= ${legalMoves(session.board, 'W')[0]}`];
  }, close() {} };
  await session.humanMove({ sessionId: session.sessionId, revision: 0, move: 'd3' });
  while (session.busy) await new Promise(resolve => setImmediate(resolve));
  assert.equal(session.revision, 2);
  assert.deepEqual(session.snapshot().thinkingTimeMs, { B: 0, W: 7 });
});

test('a closed session late query completion cannot affect a replacement or publish', async () => {
  let clock = 0;
  const old = game(strategic, { id: 'human' }, () => clock);
  let finish;
  old.session.query = () => new Promise(resolve => { finish = resolve; });
  const pending = old.session.drive();
  const messageCount = old.messages.length;
  old.session.close();
  const replacement = game({ id: 'human' }, { id: 'human' }, () => clock);
  clock += 55; finish('d3'); await pending;
  assert.equal(old.session.revision, 0);
  assert.equal(old.messages.length, messageCount);
  assert.deepEqual(replacement.session.snapshot().thinkingTimeMs, { B: 0, W: 0 });
});
