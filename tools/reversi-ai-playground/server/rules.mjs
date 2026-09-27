export const INITIAL_BOARD = '...........................WB......BW...........................';
export const other = side => side === 'B' ? 'W' : 'B';
export const coordinate = index => String.fromCharCode(97 + index % 8) + (Math.floor(index / 8) + 1);
export const indexOf = move => /^[a-h][1-8]$/.test(move) ? (Number(move[1]) - 1) * 8 + move.charCodeAt(0) - 97 : -1;
const directions = [-1, 0, 1].flatMap(dr => [-1, 0, 1].filter(dc => dr || dc).map(dc => [dr, dc]));

export function flips(board, side, index) {
  if (index < 0 || index >= 64 || board[index] !== '.') return [];
  const row = Math.floor(index / 8), col = index % 8, captured = [];
  for (const [dr, dc] of directions) {
    const line = [];
    let r = row + dr, c = col + dc;
    while (r >= 0 && r < 8 && c >= 0 && c < 8 && board[r * 8 + c] === other(side)) {
      line.push(r * 8 + c); r += dr; c += dc;
    }
    if (line.length && r >= 0 && r < 8 && c >= 0 && c < 8 && board[r * 8 + c] === side) captured.push(...line);
  }
  return captured;
}

export function legalMoves(board, side) {
  const moves = [];
  for (let i = 0; i < 64; i++) if (flips(board, side, i).length) moves.push(coordinate(i));
  return moves;
}

export function play(board, side, move) {
  const index = indexOf(move), captured = flips(board, side, index);
  if (!captured.length) throw new Error('illegal move');
  const cells = [...board];
  cells[index] = side;
  for (const square of captured) cells[square] = side;
  return cells.join('');
}

export function advance(board, side) {
  const next = other(side);
  if (legalMoves(board, next).length) return { turn: next, passed: null, result: null };
  const counts = { B: [...board].filter(cell => cell === 'B').length, W: [...board].filter(cell => cell === 'W').length };
  if (!legalMoves(board, side).length) return { turn: null, passed: next, result: counts.B === counts.W ? 'draw' : counts.B > counts.W ? 'B' : 'W' };
  return { turn: side, passed: next, result: null };
}
