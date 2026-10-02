import { createHash, randomUUID } from 'node:crypto';
import { execFile } from 'node:child_process';
import { readFileSync, readdirSync, lstatSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { promisify } from 'node:util';
import { LineProcess } from './processes.mjs';
import { INITIAL_BOARD, advance, legalMoves, other, play } from './rules.mjs';

export const LIMITS = { openingDepth: [1, 12], midgameDepth: [1, 16], exact: [0, 30] };
const AI = new Set(['strategic', 'novice', 'trained-baseline']);
const ADVISORS = new Set([...AI, 'oracle']);
const IDS = new Set(['human', 'strategic', 'novice', 'trained-baseline', 'random', 'oracle']);
const LABELS = { human: 'Human', strategic: 'StrategicEvaluator', novice: 'NoviceEvaluator', 'trained-baseline': 'TrainedEvaluator (baseline)', random: 'Uniform random', oracle: 'External oracle' };
const digest = path => createHash('sha256').update(readFileSync(path)).digest('hex');
const execFileAsync = promisify(execFile);
function digestTree(root) {
  const hash = createHash('sha256');
  function visit(directory, prefix = '') {
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
      const path = join(directory, entry.name);
      if (lstatSync(path).isSymbolicLink()) throw new Error('oracle data contains a symlink');
      if (entry.isDirectory()) { hash.update(`d\0${relative}\0`); visit(path, relative); }
      else if (entry.isFile()) { hash.update(`f\0${relative}\0`); hash.update(readFileSync(path)); }
      else throw new Error('oracle data contains a special file');
    }
  }
  visit(root);
  return hash.digest('hex');
}
const identity = (path, sha256) => ({ path, sha256 });

export function catalog(config) {
  return {
    type: 'catalog', limits: LIMITS,
    players: [...IDS].map(id => ({ id, label: id === 'trained-baseline' && config.trained?.demo ? 'TrainedEvaluator (demo artifact, strength unverified)' : LABELS[id], available: id === 'trained-baseline' ? Boolean(config.trained) : id === 'oracle' ? Boolean(config.oracle) : true,
      reason: id === 'trained-baseline' && !config.trained ? config.unavailable?.trained ?? 'trained artifact is not configured' : id === 'oracle' && !config.oracle ? config.unavailable?.oracle ?? 'oracle is not configured' : null }))
  };
}

function validatedSeat(value, config) {
  if (!value || typeof value !== 'object' || !IDS.has(value.id)) throw new Error('unknown player ID');
  if (value.id === 'trained-baseline' && !config.trained) throw new Error('trained artifact is unavailable');
  if (value.id === 'oracle' && !config.oracle) throw new Error('oracle is unavailable');
  if (value.id === 'human') {
    if (value.advisor == null || value.advisor === 'none') return { id: 'human', advisor: null };
    if (!ADVISORS.has(value.advisor.id)) throw new Error('unknown Advisor ID');
    return { id: 'human', advisor: validatedSearch(value.advisor, config) };
  }
  if (ADVISORS.has(value.id)) return validatedSearch(value, config);
  return { id: value.id };
}

function validatedSearch(value, config) {
  if (value.id === 'trained-baseline' && !config.trained) throw new Error('trained artifact is unavailable');
  if (value.id === 'oracle' && !config.oracle) throw new Error('oracle is unavailable');
  const legacyDepth = value.depth !== undefined && value.openingDepth === undefined && value.midgameDepth === undefined;
  const openingDepth = legacyDepth ? value.depth : value.openingDepth;
  const midgameDepth = legacyDepth ? value.depth : value.midgameDepth;
  if (!Number.isInteger(openingDepth) || openingDepth < 1 || openingDepth > 12 ||
      !Number.isInteger(midgameDepth) || midgameDepth < 1 || midgameDepth > 16 ||
      !Number.isInteger(value.exact) || value.exact < 0 || value.exact > 30) throw new Error('search settings are outside accepted range');
  return { id: value.id, openingDepth, midgameDepth, exact: value.exact };
}

function searchArgs(seat) {
  return ['--opening-depth', String(seat.openingDepth), '--midgame-depth', String(seat.midgameDepth),
    '--exact-solver-empty-squares', String(seat.exact)];
}

export function oracleDepthArgs(seat) {
  const firstExact = seat.exact ? 61 - seat.exact : 61;
  const ranges = [];
  for (const [start, end, depth] of [[1, Math.min(20, firstExact - 1), seat.openingDepth],
    [21, Math.min(60, firstExact - 1), seat.midgameDepth]]) {
    if (start <= end) ranges.push(start, end, depth, '100');
  }
  for (let move = firstExact; move <= 60; move++) ranges.push(move, move, 61 - move, '100');
  const args = [];
  for (let i = 0; i < ranges.length; i += 4) args.push('-depthprobrange', ...ranges.slice(i, i + 4).map(String));
  return args;
}

export function oracleConfigId(advisor) {
  const firstExact = advisor.exact ? 61 - advisor.exact : 61;
  const ranges = [];
  for (const [start, end, depth] of [[1, Math.min(20, firstExact - 1), advisor.openingDepth],
    [21, Math.min(60, firstExact - 1), advisor.midgameDepth]]) if (start <= end) ranges.push([start, end, depth, '100']);
  for (let move = firstExact; move <= 60; move++) ranges.push([move, move, 61 - move, '100']);
  const settings = { book: false, depth_ranges: ranges, exact_empty_squares: advisor.exact, hash_level: 25,
    midgame_depth: advisor.midgameDepth, opening_depth: advisor.openingDepth, oracle_version: '7.8.1',
    schema_version: 1, source_sha256: '173af642276216a284498f8d7e32de23dbb9dc6611686c370b0de3eddbc1238b', threads: 1 };
  return `oracle-advisor-v1:${createHash('sha256').update(JSON.stringify(settings)).digest('hex')}`;
}

export class Session {
  constructor(request, config, send, now = () => performance.now()) {
    this.config = config;
    this.send = send;
    this.now = now;
    this.thinkingTimeMs = { B: 0, W: 0 };
    this.black = validatedSeat(request.black, config);
    this.white = validatedSeat(request.white, config);
    if (request.seed !== undefined && (!Number.isInteger(request.seed) || request.seed < 0 || request.seed > 0xffffffff)) throw new Error('seed must be an unsigned 32-bit integer');
    this.randomState = (request.seed ?? Math.floor(Math.random() * 0xffffffff)) >>> 0;
    this.seed = this.randomState;
    this.sessionId = randomUUID(); this.token = randomUUID();
    this.revision = 0; this.board = INITIAL_BOARD; this.turn = 'B';
    this.lastMove = null; this.lastPass = null; this.result = null; this.error = null; this.thinking = false;
    this.processes = {}; this.advisorProcesses = {}; this.advisorStarts = {}; this.advisorConfigIds = {}; this.advisor = null; this.closed = false; this.busy = false;
    this.identities = { cli: identity(config.cli, config.cliSha256), trained: config.trained ? { ...identity(config.trained.artifact, config.trained.sha256), demo: Boolean(config.trained.demo) } : null,
      oracle: config.oracle ? { ...identity(config.oracle.binary, config.oracle.sha256), dataDir: config.oracle.dataDir, dataSha256: config.oracle.dataSha256 } : null };
  }
  seat(side) { return side === 'B' ? this.black : this.white; }
  snapshot() {
    return { sessionId: this.sessionId, revision: this.revision, board: this.board, turn: this.turn,
      legal: this.turn ? legalMoves(this.board, this.turn) : [], black: this.black, white: this.white,
      counts: { B: [...this.board].filter(cell => cell === 'B').length, W: [...this.board].filter(cell => cell === 'W').length },
      lastMove: this.lastMove, lastPass: this.lastPass, thinking: this.thinking, result: this.result, error: this.error,
      thinkingTimeMs: { ...this.thinkingTimeMs },
      identities: this.identities, seed: this.seed, advisor: this.advisor };
  }
  publish(withToken = false) { if (!this.closed) this.send({ type: 'snapshot', snapshot: this.snapshot(), ...(withToken ? { token: this.token } : {}) }); }
  open() {
    if (digest(this.config.cli) !== this.config.cliSha256) throw new Error('CLI digest changed');
    if (this.config.trained && digest(this.config.trained.artifact) !== this.config.trained.sha256) throw new Error('trained artifact digest changed');
    if (this.config.oracle && digestTree(this.config.oracle.dataDir) !== this.config.oracle.dataSha256) throw new Error('oracle data digest changed');
    for (const side of ['B', 'W']) {
      const seat = this.seat(side);
      if (AI.has(seat.id)) {
        const args = ['--evaluator', seat.id === 'trained-baseline' ? 'trained' : seat.id,
          ...searchArgs(seat), '--decision-move-phases', '--time-limit-ms', '10000'];
        if (seat.id === 'trained-baseline') args.push('--trained-artifact', this.config.trained.artifact);
        this.processes[side] = new LineProcess(this.config.cli, args, this.config.repoRoot, 12000);
      } else if (seat.id === 'oracle') {
        if (digest(this.config.oracle.binary) !== this.config.oracle.sha256) throw new Error('oracle binary digest changed');
        this.processes[side] = new LineProcess(this.config.oracle.binary,
          ['-nobook', '-thread', '1', '-hash', '16', ...oracleDepthArgs(seat), '-gtp', '-quiet'], this.config.oracle.dataDir, 15000);
      }
    }
  }
  async startAdvisorProcess(side) {
    const advisor = this.seat(side).advisor;
    if (!advisor) return;
    if (advisor.id === 'oracle') {
      if (digest(this.config.oracle.binary) !== this.config.oracle.sha256) throw new Error('oracle binary digest changed');
      this.advisorProcesses[side] = new LineProcess('python3',
        [join(this.config.repoRoot, 'tools/reversi-ai-oracle/oracle.py'), 'analyze-position',
          ...searchArgs(advisor), '--binary', this.config.oracle.binary, '--data-dir', this.config.oracle.dataDir,
          '--timeout', '300'], this.config.repoRoot, 310000, true);
    } else {
      const args = ['--advisor-analysis', '--evaluator', advisor.id === 'trained-baseline' ? 'trained' : advisor.id,
        ...searchArgs(advisor), '--time-limit-ms', '10000'];
      if (advisor.id === 'trained-baseline') args.push('--trained-artifact', this.config.trained.artifact);
      if (!this.advisorConfigIds[side]) {
        const controller = new AbortController();
        this.advisorStarts[side] = controller;
        try {
          const descriptor = await execFileAsync(this.config.cli, [...args, '--print-advisor-config-id'],
            { cwd: this.config.repoRoot, encoding: 'utf8', timeout: 12000, maxBuffer: 1024, signal: controller.signal });
          if (controller.signal.aborted || this.closed) return;
          const configId = descriptor.stdout.trim();
          if (!/^project-ai-advisor-v1:[0-9a-f]{16}$/.test(configId)) throw new Error('invalid Advisor configuration identity');
          this.advisorConfigIds[side] = configId;
        } finally {
          if (this.advisorStarts[side] === controller) delete this.advisorStarts[side];
        }
      }
      if (this.closed) return;
      this.advisorProcesses[side] = new LineProcess(this.config.cli, args, this.config.repoRoot, 12000);
    }
    return this.advisorProcesses[side];
  }
  cancelAdvisor() {
    if (this.advisor?.pending) {
      const side = this.advisor.seat;
      this.advisorStarts[side]?.abort();
      delete this.advisorStarts[side];
      this.advisorProcesses[side]?.close();
      delete this.advisorProcesses[side];
    }
    this.advisor = null;
  }
  beginAdvisor() {
    if (this.closed || this.error || !this.turn || this.seat(this.turn).id !== 'human' || !this.seat(this.turn).advisor || this.advisor) return;
    const side = this.turn, revision = this.revision, board = this.board, sessionId = this.sessionId;
    const moves = legalMoves(board, side);
    if (!moves.length) return;
    const positionId = `${sessionId}:${revision}:advisor`;
    this.advisor = { seat: side, pending: true, scores: null, error: null };
    this.publish();
    let process;
    void (async () => {
      process = this.advisorProcesses[side] ?? await this.startAdvisorProcess(side);
      if (this.closed || this.revision !== revision || this.board !== board || this.turn !== side || !this.advisor?.pending || !process) return;
      const line = await process.command(`${positionId}\t${board}\t${side}`);
      if (this.closed || this.revision !== revision || this.board !== board || this.turn !== side || !this.advisor?.pending) return;
      const result = JSON.parse(line);
      if (result.schema_version !== 1 || result.position_id !== positionId || result.board !== board || result.side !== side ||
          result.outcome !== 'move' || !Number.isInteger(result.completed_depth) || result.completed_depth < 1 ||
          typeof result.exact !== 'boolean' || !Array.isArray(result.scores) || result.scores.length !== moves.length ||
          result.config_id !== (this.seat(side).advisor.id === 'oracle' ? oracleConfigId(this.seat(side).advisor) : this.advisorConfigIds[side])) throw new Error('invalid Advisor response');
      const seen = new Set();
      for (const score of result.scores) {
        const child = moves.includes(score.move) ? play(board, side, score.move) : null;
        const terminal = child && !legalMoves(child, other(side)).length && !legalMoves(child, side).length;
        if (!moves.includes(score.move) || seen.has(score.move) || !Number.isFinite(score.value) ||
            !Number.isInteger(score.completed_depth) || score.completed_depth < 0 || typeof score.exact !== 'boolean' ||
            (terminal ? (!score.exact || score.completed_depth !== 1) :
              (score.completed_depth !== result.completed_depth || score.exact !== result.exact))) throw new Error('invalid Advisor score');
        seen.add(score.move);
      }
      if (result.exact !== result.scores.every(score => score.exact)) throw new Error('invalid Advisor exactness');
      this.advisor = { seat: side, pending: false, scores: result.scores.map(({ move, value }) => ({ move, value })), error: null };
      this.publish();
    })().catch(error => {
      if (this.closed || this.revision !== revision || this.board !== board || this.turn !== side || !this.advisor?.pending) return;
      process?.close(); delete this.advisorProcesses[side];
      this.advisor = { seat: side, pending: false, scores: null, error: String(error?.message ?? error) };
      this.publish();
    });
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    for (const controller of Object.values(this.advisorStarts)) controller.abort();
    for (const process of Object.values(this.processes)) process.close();
    for (const process of Object.values(this.advisorProcesses)) process.close();
  }
  fail(error) {
    if (this.closed) return;
    this.thinking = false; this.error = String(error?.message ?? error);
    for (const controller of Object.values(this.advisorStarts)) controller.abort();
    for (const process of Object.values(this.processes)) process.close();
    for (const process of Object.values(this.advisorProcesses)) process.close();
    this.advisor = null;
    this.publish();
  }
  randomMove(moves) {
    const limit = Math.floor(0x100000000 / moves.length) * moves.length;
    do { this.randomState = (Math.imul(this.randomState, 1664525) + 1013904223) >>> 0; }
    while (this.randomState >= limit);
    return moves[this.randomState % moves.length];
  }
  async query(side, positionId) {
    const seat = this.seat(side), process = this.processes[side];
    if (seat.id === 'random') return this.randomMove(legalMoves(this.board, side));
    if (seat.id === 'oracle') {
      const response = await process.gtp(`genmove ${side === 'B' ? 'black' : 'white'}`);
      const move = response[0].slice(1).trim().toLowerCase();
      if (!/^(pass|[a-h][1-8])$/.test(move)) throw new Error('invalid oracle move response');
      return move;
    }
    const response = await process.command(`${positionId}\t${this.board}\t${side}`);
    const fields = response.split('\t');
    if (fields.length !== 2 || fields[0] !== positionId || !/^(pass|[a-h][1-8])$/.test(fields[1])) throw new Error('invalid or stale CLI response');
    return fields[1];
  }
  async apply(side, move) {
    if (this.closed || this.error || this.turn !== side) return;
    const moves = legalMoves(this.board, side);
    if (move === 'pass' && moves.length) throw new Error('invalid pass');
    if (move !== 'pass' && !moves.includes(move)) throw new Error(`illegal move: ${move}`);
    this.cancelAdvisor();
    if (move !== 'pass') this.board = play(this.board, side, move);
    this.revision++;
    this.lastMove = move === 'pass' ? null : { side, move };
    const next = advance(this.board, side);
    this.turn = next.turn; this.result = next.result; this.lastPass = next.passed;
    if (next.passed) this.revision++;
    this.thinking = false;
    this.publish();
    for (const oracleSide of ['B', 'W']) {
      if (this.seat(oracleSide).id !== 'oracle' || (oracleSide === side && move !== 'pass')) continue;
      await this.processes[oracleSide].gtp(`play ${side === 'B' ? 'black' : 'white'} ${move === 'pass' ? 'PASS' : move}`);
      if (next.passed) await this.processes[oracleSide].gtp(`play ${next.passed === 'B' ? 'black' : 'white'} PASS`);
    }
    this.beginAdvisor();
  }
  async drive() {
    if (this.closed || this.busy || this.error || !this.turn || this.seat(this.turn).id === 'human') return;
    this.busy = true;
    try {
      while (!this.closed && !this.error && this.turn && this.seat(this.turn).id !== 'human') {
        const side = this.turn, revision = this.revision, board = this.board;
        const positionId = `${this.sessionId}:${revision}`;
        this.thinking = true; this.publish();
        const started = this.now();
        let move;
        try { move = await this.query(side, positionId); }
        finally { this.thinkingTimeMs[side] += this.now() - started; }
        if (this.closed) return;
        if (revision !== this.revision || board !== this.board || side !== this.turn) throw new Error('late AI response');
        await this.apply(side, move);
      }
    } catch (error) { this.fail(error); }
    finally { this.busy = false; }
    this.beginAdvisor();
  }
  async humanMove(request) {
    if (this.closed || this.error || this.busy || request.sessionId !== this.sessionId || request.revision !== this.revision || !this.turn || this.seat(this.turn).id !== 'human') {
      this.reject('stale session, revision, or turn'); return;
    }
    if (typeof request.move !== 'string' || !legalMoves(this.board, this.turn).includes(request.move)) {
      this.reject('illegal human move'); return;
    }
    this.busy = true;
    try { await this.apply(this.turn, request.move); }
    catch (error) { this.fail(error); }
    finally { this.busy = false; }
    this.drive();
  }
  reject(reason) {
    if (this.closed) return;
    this.send({ type: 'snapshot', snapshot: { ...this.snapshot(), error: reason, recoverable: true } });
  }
}

export function verifyConfig(config) {
  statSync(config.cli);
  config.cliSha256 = digest(config.cli);
  if (config.trained) { statSync(config.trained.artifact); config.trained.sha256 = digest(config.trained.artifact); }
  if (config.oracle) { statSync(config.oracle.binary); if (!statSync(config.oracle.dataDir).isDirectory()) throw new Error('oracle dataDir is not a directory'); config.oracle.sha256 = digest(config.oracle.binary); config.oracle.dataSha256 = digestTree(config.oracle.dataDir); }
  return config;
}
