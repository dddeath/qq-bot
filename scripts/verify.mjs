import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { root } from '../src/config.mjs';
const records = [];
function run(binary, args) {
  const r = spawnSync(binary, args, { cwd: root, encoding: 'utf8', windowsHide: true, timeout: 120000 });
  records.push({ command: [binary, ...args], cwd: root, exit_status: r.status, stdout: r.stdout ?? '', stderr: r.stderr ?? '' });
  console.log(`${args.join(' ')}: exit=${r.status}`);
  return r.status === 0;
}
const suites = ['test', 'qq-probe', 'qq-reply-probe'].flatMap(dir => fs.readdirSync(path.join(root, dir)).filter(f => f.endsWith('.test.mjs')).map(f => `${dir}/${f}`));
const checks = [run('git', ['diff', '--check']), run(process.execPath, ['--test', ...suites])];
const dir = path.join(root, 'evidence'); fs.mkdirSync(dir, { recursive: true });
const file = path.join(dir, `verification-${Date.now()}.json`);
fs.writeFileSync(file, JSON.stringify({ at: new Date().toISOString(), local_verified: checks.every(Boolean), live_network: 'NOT_RUN', records }, null, 2), { flag: 'wx' });
console.log(file);
if (!checks.every(Boolean)) process.exitCode = 1;
