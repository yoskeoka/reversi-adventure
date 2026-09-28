import { readFileSync } from 'node:fs';

export function loadLocalConfig(path) {
  if (!path) return { local: {}, error: null };
  try {
    const local = JSON.parse(readFileSync(path, 'utf8'));
    if (!local || typeof local !== 'object' || Array.isArray(local)) throw new Error('configuration must be a JSON object');
    return { local, error: null };
  } catch (error) {
    return { local: {}, error: String(error.message ?? error) };
  }
}
