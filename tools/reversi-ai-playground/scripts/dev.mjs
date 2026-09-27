import { spawn } from 'node:child_process';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const cli = resolve(process.env.CARGO_TARGET_DIR ?? resolve(root, 'target'), 'release/reversi-ai-cli');
function run(command, args, cwd, env = process.env) {
  return spawn(command, args, { cwd, env, stdio: 'inherit' });
}
const build = run('cargo', ['build', '--release', '-p', 'reversi-ai', '--bin', 'reversi-ai-cli'], root);
const exit = await new Promise(resolve => build.once('exit', resolve));
if (exit !== 0) process.exit(exit ?? 1);
const backend = run('node', ['server/index.mjs'], resolve(root, 'tools/reversi-ai-playground'), { ...process.env, PLAYGROUND_CLI: cli });
const frontend = run('pnpm', ['exec', 'vite', 'web', '--config', 'web/vite.config.ts'], resolve(root, 'tools/reversi-ai-playground'));
let stopping = false;
function stop() {
  if (stopping) return;
  stopping = true;
  backend.kill('SIGTERM'); frontend.kill('SIGTERM');
}
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, stop);
backend.once('exit', stop); frontend.once('exit', stop);
