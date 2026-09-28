import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadLocalConfig } from './config.mjs';

test('invalid optional config cannot prevent other players from loading', () => {
  const directory = mkdtempSync(join(tmpdir(), 'reversi-playground-config-'));
  try {
    const path = join(directory, 'config.json');
    assert.deepEqual(loadLocalConfig(path).local, {});
    assert.ok(loadLocalConfig(path).error);
    writeFileSync(path, '{invalid');
    assert.deepEqual(loadLocalConfig(path).local, {});
    assert.ok(loadLocalConfig(path).error);
    writeFileSync(path, 'null');
    assert.match(loadLocalConfig(path).error, /JSON object/);
    writeFileSync(path, '{"trained":{"artifact":"/tmp/example"}}');
    assert.equal(loadLocalConfig(path).local.trained.artifact, '/tmp/example');
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
