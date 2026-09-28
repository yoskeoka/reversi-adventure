import "./style.css";

type Color = "black" | "white";
type Player = { id: string; label?: string; available?: boolean; reason?: string };
type SearchSettings = { id: string; openingDepth: number; midgameDepth: number; exact: number };
type Seat = { id: string; openingDepth?: number; midgameDepth?: number; exact?: number; advisor?: SearchSettings | null };
type AdvisorState = { pending: boolean; scores: { move: string; value: number }[] | null; error: string | null; seat: "B" | "W" | null };
type Snapshot = {
  sessionId: string;
  revision: number;
  board: string[] | string;
  turn: Color | "B" | "W" | null;
  legal: string[];
  black: Seat;
  white: Seat;
  counts: { B: number; W: number };
  lastMove?: { side: "B" | "W"; move: string } | null;
  lastPass?: Color | string | null;
  thinking?: boolean | Color | null;
  result?: "B" | "W" | "draw" | null;
  error?: string | null;
  recoverable?: boolean;
  identities?: Record<string, unknown>;
  advisor?: AdvisorState | null;
};
type ServerMessage =
  | { type: "catalog"; players: Player[]; limits?: { depth?: [number, number]; exact?: [number, number] } }
  | { type: "snapshot"; snapshot: Snapshot; token?: string }
  | { type: "error"; error?: string; message?: string };

const tokenKey = "reversi-ai-playground-token";
const app = document.querySelector<HTMLDivElement>("#app")!;
app.innerHTML = `
  <main class="shell">
    <header class="masthead"><div><p class="eyebrow">LOCAL DEVELOPMENT</p><h1>Reversi AI Playground</h1></div><p id="connection" role="status">接続中…</p></header>
    <section class="setup" aria-labelledby="setup-title">
      <div class="section-heading"><h2 id="setup-title">新しい対局</h2><p>設定は次の対局から適用されます。</p></div>
      <div class="seats">
        <fieldset data-seat="black"><legend><span class="disc black"></span> 黒</legend><label>対局者 <select name="player"></select></label><div class="ai-settings search-settings"><label>序盤探索深さ（1〜20手） <input name="openingDepth" type="number" min="1" max="12" value="4"></label><label>中盤探索深さ（21〜60手） <input name="midgameDepth" type="number" min="1" max="12" value="4"></label><label>完全読み開始空き数 <input name="exact" type="number" min="0" max="16" value="12"></label></div><div class="advisor-settings"><label>Human Advisor <select name="advisor"></select></label><div class="ai-settings advisor-search-settings"><label>序盤探索深さ（1〜20手） <input name="advisorOpeningDepth" type="number" min="1" max="12" value="4"></label><label>中盤探索深さ（21〜60手） <input name="advisorMidgameDepth" type="number" min="1" max="12" value="4"></label><label>完全読み開始空き数 <input name="advisorExact" type="number" min="0" max="16" value="12"></label></div></div></fieldset>
        <fieldset data-seat="white"><legend><span class="disc white"></span> 白</legend><label>対局者 <select name="player"></select></label><div class="ai-settings search-settings"><label>序盤探索深さ（1〜20手） <input name="openingDepth" type="number" min="1" max="12" value="4"></label><label>中盤探索深さ（21〜60手） <input name="midgameDepth" type="number" min="1" max="12" value="4"></label><label>完全読み開始空き数 <input name="exact" type="number" min="0" max="16" value="12"></label></div><div class="advisor-settings"><label>Human Advisor <select name="advisor"></select></label><div class="ai-settings advisor-search-settings"><label>序盤探索深さ（1〜20手） <input name="advisorOpeningDepth" type="number" min="1" max="12" value="4"></label><label>中盤探索深さ（21〜60手） <input name="advisorMidgameDepth" type="number" min="1" max="12" value="4"></label><label>完全読み開始空き数 <input name="advisorExact" type="number" min="0" max="16" value="12"></label></div></div></fieldset>
      </div>
      <div class="start-row"><label>Random seed（任意）<input id="seed" inputmode="numeric" pattern="[0-9]*" placeholder="固定する場合に入力"></label><button id="start" type="button" disabled>対局を開始</button></div>
    </section>
    <section class="game" aria-label="対局">
      <div class="board-panel"><div class="board-labels" aria-hidden="true"><span></span><span>a</span><span>b</span><span>c</span><span>d</span><span>e</span><span>f</span><span>g</span><span>h</span></div><div class="board-with-ranks"><div class="ranks" aria-hidden="true"><span>1</span><span>2</span><span>3</span><span>4</span><span>5</span><span>6</span><span>7</span><span>8</span></div><div id="board" class="board" role="group" aria-label="Reversi 盤面"></div></div></div>
      <aside class="game-info"><p class="eyebrow">CURRENT GAME</p><h2 id="turn">対局を開始してください</h2><p id="activity" class="activity" aria-live="polite"></p><div class="score"><p><span class="disc black"></span> 黒 <strong id="black-count">2</strong></p><p><span class="disc white"></span> 白 <strong id="white-count">2</strong></p></div><dl><dt>黒</dt><dd><span id="black-seat">—</span> <span id="black-advisor-status" class="advisor-status" role="status"></span></dd><dt>白</dt><dd><span id="white-seat">—</span> <span id="white-advisor-status" class="advisor-status" role="status"></span></dd><dt>最後の着手</dt><dd id="last-move">—</dd></dl><p id="result" class="result" role="status"></p><p id="advisor-error" class="error" role="alert"></p><p id="error" class="error" role="alert"></p><details><summary>実行情報</summary><pre id="identities">—</pre></details></aside>
    </section>
  </main>`;

const connection = byId("connection");
const startButton = byId("start") as HTMLButtonElement;
const board = byId("board");
const fields = Object.fromEntries((["black", "white"] as const).map((color) => [color, document.querySelector<HTMLFieldSetElement>(`[data-seat="${color}"]`)!])) as Record<Color, HTMLFieldSetElement>;
const cells: HTMLButtonElement[] = [];
let socket: WebSocket | undefined;
let snapshot: Snapshot | undefined;
let players: Player[] = [];
let reconnectTimer: number | undefined;
let intentionalClose = false;

for (let row = 0; row < 8; row++) for (let col = 0; col < 8; col++) {
  const cell = document.createElement("button");
  const move = `${"abcdefgh"[col]}${row + 1}`;
  cell.type = "button";
  cell.className = "cell";
  cell.dataset.move = move;
  cell.setAttribute("aria-label", move);
  cell.disabled = true;
  cell.addEventListener("click", () => {
    if (!snapshot || !canMove(snapshot) || !snapshot.legal.includes(move)) return;
    send({ type: "move", sessionId: snapshot.sessionId, revision: snapshot.revision, move });
  });
  cells.push(cell);
  board.append(cell);
}

for (const field of Object.values(fields)) {
  field.querySelector<HTMLSelectElement>("[name=player]")!.addEventListener("change", () => updateSettings(field));
  field.querySelector<HTMLSelectElement>("[name=advisor]")!.addEventListener("change", () => updateSettings(field));
}
startButton.addEventListener("click", () => {
  const black = readSeat(fields.black);
  const white = readSeat(fields.white);
  if (!black || !white) return;
  const seed = (byId("seed") as HTMLInputElement).value.trim();
  if (seed && (!/^(0|[1-9][0-9]*)$/.test(seed) || !Number.isInteger(Number(seed)) || Number(seed) > 0xffffffff)) { showError("Random seed は 0〜4294967295 の整数を入力してください。"); return; }
  showError("");
  send({ type: "start", black, white, ...(seed ? { seed: Number(seed) } : {}) });
});

connect();

function connect() {
  const url = new URL("/ws", location.href);
  url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(url);
  connection.textContent = "接続中…";
  socket.addEventListener("open", () => {
    connection.textContent = "接続済み";
    startButton.disabled = players.length === 0;
    const token = localStorage.getItem(tokenKey);
    if (token) send({ type: "resume", token });
  });
  socket.addEventListener("message", (event) => {
    let message: ServerMessage;
    try { message = JSON.parse(event.data) as ServerMessage; } catch { showError("サーバーから不正な応答を受信しました。"); return; }
    if (message.type === "catalog") { players = message.players; renderCatalog(message); }
    else if (message.type === "snapshot") {
      if (message.token) localStorage.setItem(tokenKey, message.token);
      snapshot = message.snapshot;
      renderSnapshot(message.snapshot);
    } else if (message.type === "error") {
      showError(message.error ?? message.message ?? "サーバーエラー");
      if (localStorage.getItem(tokenKey)) localStorage.removeItem(tokenKey);
    }
  });
  socket.addEventListener("close", () => {
    connection.textContent = "切断。再接続中…";
    startButton.disabled = true;
    cells.forEach((cell) => { cell.disabled = true; });
    if (!intentionalClose) reconnectTimer = window.setTimeout(connect, 1000);
  });
  socket.addEventListener("error", () => { connection.textContent = "接続エラー"; });
}

window.addEventListener("beforeunload", () => { intentionalClose = true; if (reconnectTimer) clearTimeout(reconnectTimer); socket?.close(); });

function renderCatalog(message: Extract<ServerMessage, { type: "catalog" }>) {
  for (const field of Object.values(fields)) {
    const select = field.querySelector<HTMLSelectElement>("[name=player]")!;
    const advisor = field.querySelector<HTMLSelectElement>("[name=advisor]")!;
    const previous = select.value;
    const previousAdvisor = advisor.value;
    select.replaceChildren();
    advisor.replaceChildren(new Option("なし", "none"));
    for (const player of message.players) {
      const option = new Option(`${player.label ?? player.id}${player.available === false ? `（利用不可: ${player.reason ?? "未設定"}）` : ""}`, player.id);
      option.disabled = player.available === false;
      select.add(option);
      if (["strategic", "novice", "trained-baseline", "oracle"].includes(player.id)) {
        const advisorOption = new Option(option.text, player.id);
        advisorOption.disabled = option.disabled;
        advisor.add(advisorOption);
      }
    }
    if (players.some((player) => player.id === previous && player.available !== false)) select.value = previous;
    else select.value = players.find((player) => player.id === "human" && player.available !== false)?.id ?? players.find((player) => player.available !== false)?.id ?? "";
    advisor.value = players.some((player) => player.id === previousAdvisor && player.available !== false) ? previousAdvisor : "none";
    for (const name of ["openingDepth", "midgameDepth", "advisorOpeningDepth", "advisorMidgameDepth"]) {
      const input = field.querySelector<HTMLInputElement>(`[name=${name}]`)!;
      input.min = String(message.limits?.depth?.[0] ?? 1); input.max = String(message.limits?.depth?.[1] ?? 12);
    }
    for (const name of ["exact", "advisorExact"]) {
      const input = field.querySelector<HTMLInputElement>(`[name=${name}]`)!;
      input.min = String(message.limits?.exact?.[0] ?? 0); input.max = String(message.limits?.exact?.[1] ?? 16);
    }
    updateSettings(field);
  }
  startButton.disabled = socket?.readyState !== WebSocket.OPEN || !players.some((player) => player.available !== false);
}

function updateSettings(field: HTMLFieldSetElement) {
  const player = field.querySelector<HTMLSelectElement>("[name=player]")!.value;
  const advisor = field.querySelector<HTMLSelectElement>("[name=advisor]")!.value;
  field.querySelector<HTMLElement>(".search-settings")!.hidden = !["strategic", "novice", "trained-baseline", "oracle"].includes(player);
  field.querySelector<HTMLElement>(".advisor-settings")!.hidden = player !== "human";
  field.querySelector<HTMLElement>(".advisor-search-settings")!.hidden = player !== "human" || advisor === "none";
}

function readSeat(field: HTMLFieldSetElement): Seat | undefined {
  const id = field.querySelector<HTMLSelectElement>("[name=player]")!.value;
  if (!id || players.find((player) => player.id === id)?.available === false) { showError("利用可能な対局者を選んでください。"); return; }
  if (id === "human") {
    const advisorId = field.querySelector<HTMLSelectElement>("[name=advisor]")!.value;
    if (advisorId === "none") return { id, advisor: null };
    if (!["strategic", "novice", "trained-baseline", "oracle"].includes(advisorId) || players.find((player) => player.id === advisorId)?.available !== true) {
      showError("利用可能な Advisor を選んでください。"); return;
    }
    const settings = readSearchSettings(field, advisorId, "advisor");
    return settings ? { id, advisor: settings } : undefined;
  }
  if (!["strategic", "novice", "trained-baseline", "oracle"].includes(id)) return { id };
  return readSearchSettings(field, id, "player");
}

function readSearchSettings(field: HTMLFieldSetElement, id: string, role: "player" | "advisor"): SearchSettings | undefined {
  const names = role === "advisor" ? ["advisorOpeningDepth", "advisorMidgameDepth", "advisorExact"] : ["openingDepth", "midgameDepth", "exact"];
  const inputs = names.map((name) => field.querySelector<HTMLInputElement>(`[name=${name}]`)!);
  const values = inputs.map((input) => Number(input.value));
  if (inputs.some((input, index) => input.value.trim() === "" || !Number.isInteger(values[index]) || values[index] < Number(input.min) || values[index] > Number(input.max))) {
    showError("探索設定が許可範囲外です。"); return;
  }
  return { id, openingDepth: values[0], midgameDepth: values[1], exact: values[2] };
}

function renderSnapshot(state: Snapshot) {
  const discs = typeof state.board === "string" ? [...state.board] : state.board;
  if (discs.length !== 64) { showError("盤面データが不正です。"); return; }
  const legal = new Set(state.legal);
  const interactive = canMove(state);
  const advisorScores = scoreMap(state);
  cells.forEach((cell, index) => {
    const move = cell.dataset.move!;
    const disc = discs[index];
    cell.replaceChildren();
    if (disc === "B" || disc === "W") { const piece = document.createElement("span"); piece.className = `piece ${disc === "B" ? "black" : "white"}`; cell.append(piece); }
    else if (legal.has(move)) {
      const hint = document.createElement("span");
      const score = advisorScores?.get(move);
      hint.className = score === undefined ? "hint" : "hint-score";
      hint.textContent = score === undefined ? "●" : signedScore(score);
      cell.append(hint);
    }
    cell.classList.toggle("last", move === state.lastMove?.move);
    cell.disabled = !interactive || !legal.has(move);
    cell.setAttribute("aria-label", `${move}${disc === "B" ? " 黒" : disc === "W" ? " 白" : legal.has(move) ? ` 合法手${advisorScores?.has(move) ? ` Advisor ${signedScore(advisorScores.get(move)!)}` : ""}` : " 空き"}${move === state.lastMove?.move ? " 最後の着手" : ""}`);
  });
  byId("black-count").textContent = String(state.counts.B);
  byId("white-count").textContent = String(state.counts.W);
  byId("black-seat").textContent = seatLabel(state.black);
  byId("white-seat").textContent = seatLabel(state.white);
  for (const [color, side] of [["black", "B"], ["white", "W"]] as const) {
    byId(`${color}-advisor-status`).textContent = state.advisor?.seat === side && state.advisor.pending ? "Advisor 思考中…" : "";
  }
  byId("advisor-error").textContent = state.advisor?.error ? `Advisor: ${state.advisor.error}` : "";
  byId("last-move").textContent = state.lastMove ? `${colorLabel(state.lastMove.side)} ${state.lastMove.move}` : "—";
  byId("turn").textContent = state.result ? "対局終了" : `${colorLabel(state.turn)}の手番`;
  byId("activity").textContent = state.lastPass ? `${colorLabel(state.lastPass)}がパスしました。` : state.result ? "" : state.thinking ? `${colorLabel(state.turn)}が思考中…` : interactive ? "緑の候補を選んで着手してください。" : "相手の着手を待っています。";
  byId("result").textContent = state.result === "draw" ? "引き分け" : state.result ? `${colorLabel(state.result)}の勝ち` : "";
  byId("identities").textContent = state.identities ? JSON.stringify(state.identities, null, 2) : "—";
  showError(state.error ?? "");
}

function canMove(state: Snapshot) {
  const turn = normalizeColor(state.turn);
  return socket?.readyState === WebSocket.OPEN && !state.result && (!state.error || state.recoverable) && !state.thinking && turn !== null && state[turn]?.id === "human";
}

function seatLabel(seat: Seat) {
  const name = players.find((player) => player.id === seat.id)?.label ?? seat.id;
  const search = seat.openingDepth !== undefined ? ` · 序盤 ${seat.openingDepth} · 中盤 ${seat.midgameDepth} · 完全読み開始空き数 ${seat.exact}` : "";
  const advisorName = seat.advisor ? players.find((player) => player.id === seat.advisor?.id)?.label ?? seat.advisor.id : null;
  const advisor = seat.advisor ? ` · Advisor ${advisorName}（序盤 ${seat.advisor.openingDepth}・中盤 ${seat.advisor.midgameDepth}・完全読み開始空き数 ${seat.advisor.exact}）` : "";
  return `${name}${search}${advisor}`;
}

function scoreMap(state: Snapshot): Map<string, number> | null {
  const advisor = state.advisor;
  if (!advisor || advisor.pending || advisor.error || advisor.seat !== state.turn || !Array.isArray(advisor.scores)) return null;
  if (advisor.scores.length !== state.legal.length) return null;
  const scores = new Map<string, number>();
  for (const entry of advisor.scores) {
    if (!entry || !state.legal.includes(entry.move) || !Number.isFinite(entry.value) || scores.has(entry.move)) return null;
    scores.set(entry.move, entry.value);
  }
  return scores;
}

function signedScore(value: number): string {
  const rounded = Math.sign(value) * Math.round(Math.abs(value));
  return rounded < 0 ? String(rounded) : `+${rounded}`;
}

function normalizeColor(value: Snapshot["turn"] | string | null | undefined): Color | null {
  return value === "black" || value === "B" ? "black" : value === "white" || value === "W" ? "white" : null;
}

function colorLabel(value: Snapshot["turn"] | string | null | undefined) { const color = normalizeColor(value); return color === "black" ? "黒" : color === "white" ? "白" : "次"; }
function showError(value: string) { byId("error").textContent = value; }
function send(value: object) { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(value)); }
function byId(id: string) { return document.getElementById(id)!; }
