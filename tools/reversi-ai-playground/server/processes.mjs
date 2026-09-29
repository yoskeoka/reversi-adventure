import { spawn } from 'node:child_process';
import { performance } from 'node:perf_hooks';

export class LineProcess {
  constructor(binary, args, cwd, timeoutMs = 15000, killGroup = false) {
    this.child = spawn(binary, args, { cwd, stdio: ['pipe', 'pipe', 'pipe'], detached: killGroup });
    this.killGroup = killGroup;
    this.timeoutMs = timeoutMs;
    this.buffer = '';
    this.lines = [];
    this.waiter = null;
    this.error = null;
    this.closed = false;
    this.child.stdout.setEncoding('utf8');
    this.child.stdout.on('data', chunk => {
      this.buffer += chunk;
      if (this.buffer.length > 16384) this.fail(new Error('process output too large'));
      while (this.buffer.includes('\n')) {
        const end = this.buffer.indexOf('\n');
        const line = this.buffer.slice(0, end).replace(/\r$/, '');
        this.buffer = this.buffer.slice(end + 1);
        if (this.waiter) { const waiter = this.waiter; this.waiter = null; waiter.resolve(line); }
        else this.lines.push(line);
        if (this.lines.length > 64) this.fail(new Error('unsolicited process output'));
      }
    });
    this.child.stderr.on('data', () => {});
    this.child.on('error', error => this.fail(error));
    this.child.on('exit', (code, signal) => this.fail(new Error(`process exited (${code ?? signal})`)));
  }
  fail(error) {
    this.error ??= error;
    if (this.waiter) { const waiter = this.waiter; this.waiter = null; waiter.reject(this.error); }
  }
  async line(timeoutMs = this.timeoutMs) {
    if (this.error) throw this.error;
    if (this.lines.length) return this.lines.shift();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.waiter = null; reject(new Error('process response timed out')); }, timeoutMs);
      this.waiter = { resolve: value => { clearTimeout(timer); resolve(value); }, reject: error => { clearTimeout(timer); reject(error); } };
    });
  }
  async command(input) {
    if (this.error || this.closed) throw this.error ?? new Error('process closed');
    this.child.stdin.write(input + '\n');
    return this.line();
  }
  async gtp(input) {
    if (this.error || this.closed) throw this.error ?? new Error('process closed');
    this.child.stdin.write(input + '\n');
    const deadline = performance.now() + this.timeoutMs;
    const read = () => {
      const remaining = deadline - performance.now();
      if (remaining <= 0) throw new Error('oracle response timed out');
      return this.line(remaining);
    };
    const first = await read();
    if (!/^[=?]/.test(first)) throw new Error(`invalid oracle response: ${first}`);
    const response = [first];
    for (let i = 0; i < 32; i++) {
      const line = await read();
      if (!line) {
        if (first[0] === '?') throw new Error(`oracle rejected ${input}: ${first}`);
        return response;
      }
      response.push(line);
    }
    throw new Error('oracle response too long');
  }
  close() {
    if (this.closed) return;
    this.closed = true;
    this.fail(new Error('process closed'));
    this.child.stdin.end();
    const signal = name => {
      try {
        if (this.killGroup && this.child.pid) process.kill(-this.child.pid, name);
        else this.child.kill(name);
      } catch (error) { if (error.code !== 'ESRCH') throw error; }
    };
    signal('SIGTERM');
    const timer = setTimeout(() => signal('SIGKILL'), 2000);
    timer.unref();
    if (!this.killGroup) this.child.once('exit', () => clearTimeout(timer));
  }
}
