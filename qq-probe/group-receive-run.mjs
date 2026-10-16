import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { receiveGroup } from './group-receive.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const dir = new URL('../.local/qq-group-receive/', import.meta.url);
fs.mkdirSync(dir, { recursive: true });
const id = randomUUID();
const expectedText = `qq-group-receive-${id}`;
const file = new URL(`run-${id}.json`, dir);
const config = JSON.parse(fs.readFileSync(new URL('../.local/qq-auth/config.json', import.meta.url), 'utf8').replace(/^\uFEFF/, ''));
const controller = new AbortController();
process.once('SIGINT', () => controller.abort());
process.once('SIGTERM', () => controller.abort());
const evidence = { scope: 'ordinary-group-receive-only', started_at: new Date().toISOString(),
  git_head: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
  command: 'node E:\\qq-bot\\qq-probe\\group-receive-run.mjs', expected_text: expectedText };
console.log(`Evidence: ${fileURLToPath(file)}`);
let result;
try {
  result = await receiveGroup({ appId: config.appId, secret: config.appSecret, expectedText, signal: controller.signal,
    report: record => {
      console.log(JSON.stringify(record));
      if (record.stage === 'ready') console.log(`READY. Send in the TEST GROUP ONLY, without @ or quote:\n${expectedText}`);
    } });
} catch { result = { success: false, stage: 'unexpected_error', qq_messages_sent: 0, dot_calls: 0 }; }
const exitStatus = result.success ? 0 : 2;
fs.writeFileSync(file, JSON.stringify({ ...evidence, ended_at: new Date().toISOString(), ...result, exit_status: exitStatus }, null, 2), { flag: 'wx' });
console.log(`RESULT: ${result.success ? 'ORDINARY_GROUP_MESSAGE_RECEIVED' : 'NOT_VERIFIED'}; ${fileURLToPath(file)}`);
process.exitCode = exitStatus;
