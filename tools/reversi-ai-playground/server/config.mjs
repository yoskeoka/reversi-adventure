import { readFileSync } from 'node:fs';

function readConfig(path) {
  if (!path) return {};
  const local = JSON.parse(readFileSync(path, 'utf8'));
  if (!local || typeof local !== 'object' || Array.isArray(local)) throw new Error('configuration must be a JSON object');
  return local;
}

export function loadLocalConfig(path, preparedPath) {
  let prepared;
  try {
    prepared = readConfig(preparedPath);
  } catch (error) {
    return { local: {}, error: String(error.message ?? error) };
  }
  try { return { local: { ...prepared, ...readConfig(path) }, error: null }; }
  catch (error) { return { local: prepared, error: String(error.message ?? error) }; }
}
