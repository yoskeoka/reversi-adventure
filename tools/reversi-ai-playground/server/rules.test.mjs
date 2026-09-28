import test from 'node:test';
import assert from 'node:assert/strict';
import { INITIAL_BOARD, advance, legalMoves, play } from './rules.mjs';

test('standard opening uses project board coordinates and flips', () => {
  assert.equal(INITIAL_BOARD.length, 64);
  assert.deepEqual(legalMoves(INITIAL_BOARD, 'B'), ['d3', 'c4', 'f5', 'e6']);
  const board = play(INITIAL_BOARD, 'B', 'd3');
  assert.equal(board[19], 'B');
  assert.equal(board[27], 'B');
  assert.equal(advance(board, 'B').turn, 'W');
  assert.throws(() => play(INITIAL_BOARD, 'B', 'a1'), /illegal/);
});

test('forced pass keeps mover and terminal scoring uses actual stones', () => {
  const board = 'B'.repeat(62) + 'W.';
  assert.deepEqual(legalMoves(board, 'B'), ['h8']);
  assert.deepEqual(legalMoves(board, 'W'), []);
  const finished = advance(play(board, 'B', 'h8'), 'B');
  assert.equal(finished.result, 'B');
  assert.equal(finished.passed, 'W');
});
