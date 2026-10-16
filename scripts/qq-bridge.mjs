import fs from 'node:fs';
import path from 'node:path';
import { loadConfig, root } from '../src/config.mjs';
const config = loadConfig();
const command = process.argv[2] ?? 'status';
if (!['status', 'start', 'stop'].includes(command)) throw new Error('Usage: node scripts/qq-bridge.mjs status|start|stop');
const response = await fetch(`http://127.0.0.1:${config.adminPort}/qq/${command}`, {
  method: command === 'status' ? 'GET' : 'POST', headers: { Authorization: `Bearer ${config.adminToken}` }, signal: AbortSignal.timeout(15000)
});
const data = await response.json();
if (!response.ok) { console.error(data.error); process.exitCode = 1; }
else {
  const evidence = path.join(root, 'evidence'); fs.mkdirSync(evidence, { recursive: true });
  const file = path.join(evidence, `qq-dot-${command}-${Date.now()}.json`);
  fs.writeFileSync(file, JSON.stringify({ at: new Date().toISOString(), command, data }, null, 2), { flag: 'wx' });
  console.log(JSON.stringify({ ...data, evidence_file: file }, null, 2));
}
