import fs from 'node:fs';
import path from 'node:path';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export function loadConfig() {
  const dir = path.join(root, '.local');
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'config.json');
  if (!fs.existsSync(file)) {
    fs.writeFileSync(file, JSON.stringify({
      mcpPort: 8787, adminPort: 8788,
      mcpToken: randomBytes(32).toString('hex'),
      adminToken: randomBytes(32).toString('hex'),
      tunnelId: 'tunnel_REPLACE_WITH_YOUR_ID'
    }, null, 2), { mode: 0o600, flag: 'wx' });
  }
  return { ...JSON.parse(fs.readFileSync(file, 'utf8')), dir };
}
