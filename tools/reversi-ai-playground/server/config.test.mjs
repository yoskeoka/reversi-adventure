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

test('explicit player overrides replace only their prepared player', () => {
  const directory = mkdtempSync(join(tmpdir(), 'reversi-playground-config-'));
  try {
    const prepared = join(directory, 'prepared.json');
    const override = join(directory, 'override.json');
    writeFileSync(prepared, JSON.stringify({ trained: { artifact: '/tmp/demo', demo: true }, oracle: { binary: '/tmp/oracle', dataDir: '/tmp/data' } }));
    writeFileSync(override, JSON.stringify({ trained: { artifact: '/tmp/real' } }));
    const loaded = loadLocalConfig(override, prepared);
    assert.equal(loaded.error, null);
    assert.deepEqual(loaded.local.trained, { artifact: '/tmp/real' });
    assert.deepEqual(loaded.local.oracle, { binary: '/tmp/oracle', dataDir: '/tmp/data' });
    writeFileSync(override, JSON.stringify({ oracle: { binary: '/tmp/missing' } }));
    assert.deepEqual(loadLocalConfig(override, prepared).local.oracle, { binary: '/tmp/missing' });
    writeFileSync(override, '{invalid');
    assert.ok(loadLocalConfig(override, prepared).error);
    assert.equal(loadLocalConfig(override, prepared).local.trained.artifact, '/tmp/demo');
    assert.equal(loadLocalConfig(override, prepared).local.oracle.binary, '/tmp/oracle');
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
