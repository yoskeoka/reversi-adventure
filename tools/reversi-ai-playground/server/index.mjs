import { createServer } from 'node:http';
import { accessSync, constants, realpathSync } from 'node:fs';
import { resolve, dirname, isAbsolute, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer, WebSocket } from 'ws';
import { Session, catalog, verifyConfig } from './session.mjs';
import { loadLocalConfig } from './config.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, '../../..');
const checkout = realpathSync(repoRoot);
function external(path) {
  if (typeof path !== 'string' || !isAbsolute(path)) throw new Error('configured artifact/oracle path must be absolute');
  const real = realpathSync(path);
  if (real === checkout || real.startsWith(checkout + sep)) throw new Error('artifact/oracle path must be outside checkout');
  return real;
}
const unavailable = {};
const { local, error: configError } = loadLocalConfig(process.env.PLAYGROUND_CONFIG);
if (configError) {
  unavailable.trained = `optional config unavailable: ${configError}`;
  unavailable.oracle = `optional config unavailable: ${configError}`;
  console.error(unavailable.trained);
}
function optional(name, create) {
  try { return create(); }
  catch (error) { unavailable[name] = String(error.message); console.error(`${name} unavailable: ${error.message}`); return null; }
}
const config = verifyConfig({ repoRoot, unavailable,
  cli: realpathSync(process.env.PLAYGROUND_CLI ?? resolve(repoRoot, 'target/release/reversi-ai-cli')),
  trained: null, oracle: null });
config.trained = local.trained?.artifact ? optional('trained', () => {
  const artifact = external(local.trained.artifact);
  return verifyConfig({ cli: config.cli, trained: { artifact } }).trained;
}) : null;
config.oracle = local.oracle?.binary && local.oracle?.dataDir ? optional('oracle', () => {
  const binary = external(local.oracle.binary), dataDir = external(local.oracle.dataDir);
  accessSync(binary, constants.X_OK);
  return verifyConfig({ cli: config.cli, oracle: { binary, dataDir } }).oracle;
}) : null;
const sessions = new Map();
const server = createServer((request, response) => {
  response.writeHead(200, { 'Content-Type': 'text/plain' }); response.end('Reversi AI playground');
});
const wss = new WebSocketServer({ server, path: '/ws', maxPayload: 4096,
  verifyClient: ({ origin }) => !origin || origin === 'http://127.0.0.1:5173' || origin === `http://127.0.0.1:${process.env.PLAYGROUND_PORT ?? 8787}` });
const send = (socket, message) => { if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message)); };

wss.on('connection', socket => {
  let current = null;
  send(socket, catalog(config));
  socket.on('message', data => {
    let request;
    try { request = JSON.parse(String(data)); }
    catch { send(socket, { type: 'error', message: 'invalid JSON' }); return; }
    if (!request || typeof request !== 'object') { send(socket, { type: 'error', message: 'invalid request' }); return; }
    if (request.type === 'resume') {
      const record = sessions.get(request.token);
      if (!record || record.socket || record.session.closed) { send(socket, { type: 'error', message: 'session expired or already connected' }); return; }
      if (current) { current.session.close(); sessions.delete(current.session.token); }
      current = record; record.socket = socket;
      clearTimeout(record.timer); record.timer = null;
      record.session.send = message => send(record.socket, message);
      record.session.publish(true); return;
    }
    if (request.type === 'start') {
      if (current) { current.session.close(); sessions.delete(current.session.token); }
      current = null;
      try {
        const session = new Session(request, config, message => send(socket, message));
        try { session.open(); } catch (error) { session.close(); throw error; }
        current = { session, socket, timer: null };
        sessions.set(session.token, current);
        session.publish(true); session.drive();
      } catch (error) { send(socket, { type: 'error', message: String(error.message ?? error) }); }
      return;
    }
    if (request.type === 'move' && current?.socket === socket) { void current.session.humanMove(request); return; }
    send(socket, { type: 'error', message: 'unknown request or no active session' });
  });
  socket.on('close', () => {
    if (!current || current.socket !== socket) return;
    current.socket = null;
    current.timer = setTimeout(() => {
      if (!current.socket) { current.session.close(); sessions.delete(current.session.token); }
    }, 30000);
  });
});

const port = Number(process.env.PLAYGROUND_PORT ?? 8787);
server.listen(port, '127.0.0.1', () => console.error(`playground backend http://127.0.0.1:${port}`));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
  for (const record of sessions.values()) record.session.close();
  wss.close(); server.close();
});
