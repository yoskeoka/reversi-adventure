import { createHash, randomUUID } from 'node:crypto';
import { readFileSync, readdirSync, lstatSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { LineProcess } from './processes.mjs';
import { INITIAL_BOARD, advance, legalMoves, other, play } from './rules.mjs';

export const LIMITS = { depth: [1, 12], exact: [0, 16] };
const AI = new Set(['strategic', 'novice', 'trained-baseline']);
const IDS = new Set(['human', 'strategic', 'novice', 'trained-baseline', 'random', 'oracle']);
const LABELS = { human: 'Human', strategic: 'StrategicEvaluator', novice: 'NoviceEvaluator', 'trained-baseline': 'TrainedEvaluator (baseline)', random: 'Uniform random', oracle: 'External oracle' };
const digest = path => createHash('sha256').update(readFileSync(path)).digest('hex');
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
    players: [...IDS].map(id => ({ id, label: LABELS[id], available: id === 'trained-baseline' ? Boolean(config.trained) : id === 'oracle' ? Boolean(config.oracle) : true,
      reason: id === 'trained-baseline' && !config.trained ? config.unavailable?.trained ?? 'trained artifact is not configured' : id === 'oracle' && !config.oracle ? config.unavailable?.oracle ?? 'oracle is not configured' : null }))
  };
}

function validatedSeat(value, config) {
  if (!value || typeof value !== 'object' || !IDS.has(value.id)) throw new Error('unknown player ID');
  if (value.id === 'trained-baseline' && !config.trained) throw new Error('trained artifact is unavailable');
  if (value.id === 'oracle' && !config.oracle) throw new Error('oracle is unavailable');
  if (AI.has(value.id)) {
    if (!Number.isInteger(value.depth) || value.depth < 1 || value.depth > 12 || !Number.isInteger(value.exact) || value.exact < 0 || value.exact > 16) throw new Error('search settings are outside accepted range');
    return { id: value.id, depth: value.depth, exact: value.exact };
  }
  return { id: value.id };
}

export class Session {
  constructor(request, config, send) {
    this.config = config;
    this.send = send;
    this.black = validatedSeat(request.black, config);
    this.white = validatedSeat(request.white, config);
    if (request.seed !== undefined && (!Number.isInteger(request.seed) || request.seed < 0 || request.seed > 0xffffffff)) throw new Error('seed must be an unsigned 32-bit integer');
    this.randomState = (request.seed ?? Math.floor(Math.random() * 0xffffffff)) >>> 0;
    this.seed = this.randomState;
    this.sessionId = randomUUID(); this.token = randomUUID();
    this.revision = 0; this.board = INITIAL_BOARD; this.turn = 'B';
    this.lastMove = null; this.lastPass = null; this.result = null; this.error = null; this.thinking = false;
    this.processes = {}; this.closed = false; this.busy = false;
    this.identities = { cli: identity(config.cli, config.cliSha256), trained: config.trained ? identity(config.trained.artifact, config.trained.sha256) : null,
      oracle: config.oracle ? { ...identity(config.oracle.binary, config.oracle.sha256), dataDir: config.oracle.dataDir, dataSha256: config.oracle.dataSha256 } : null };
  }
  seat(side) { return side === 'B' ? this.black : this.white; }
  snapshot() {
    return { sessionId: this.sessionId, revision: this.revision, board: this.board, turn: this.turn,
      legal: this.turn ? legalMoves(this.board, this.turn) : [], black: this.black, white: this.white,
      counts: { B: [...this.board].filter(cell => cell === 'B').length, W: [...this.board].filter(cell => cell === 'W').length },
      lastMove: this.lastMove, lastPass: this.lastPass, thinking: this.thinking, result: this.result, error: this.error,
      identities: this.identities, seed: this.seed };
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
          '--opening-depth', String(seat.depth), '--midgame-depth', String(seat.depth), '--endgame-depth', String(seat.depth),
          '--exact-solver-empty-squares', String(seat.exact), '--time-limit-ms', '10000'];
        if (seat.id === 'trained-baseline') args.push('--trained-artifact', this.config.trained.artifact);
        this.processes[side] = new LineProcess(this.config.cli, args, this.config.repoRoot, 12000);
      } else if (seat.id === 'oracle') {
        if (digest(this.config.oracle.binary) !== this.config.oracle.sha256) throw new Error('oracle binary digest changed');
        this.processes[side] = new LineProcess(this.config.oracle.binary,
          ['-nobook', '-thread', '1', '-hash', '16', '-level', '10', '-gtp', '-quiet'], this.config.oracle.dataDir, 15000);
      }
    }
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    for (const process of Object.values(this.processes)) process.close();
  }
  fail(error) {
    if (this.closed) return;
    this.thinking = false; this.error = String(error?.message ?? error);
    for (const process of Object.values(this.processes)) process.close();
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
  }
  async drive() {
    if (this.closed || this.busy || this.error || !this.turn || this.seat(this.turn).id === 'human') return;
    this.busy = true;
    try {
      while (!this.closed && !this.error && this.turn && this.seat(this.turn).id !== 'human') {
        const side = this.turn, revision = this.revision, board = this.board;
        const positionId = `${this.sessionId}:${revision}`;
        this.thinking = true; this.publish();
        const move = await this.query(side, positionId);
        if (this.closed) return;
        if (revision !== this.revision || board !== this.board || side !== this.turn) throw new Error('late AI response');
        await this.apply(side, move);
      }
    } catch (error) { this.fail(error); }
    finally { this.busy = false; }
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
