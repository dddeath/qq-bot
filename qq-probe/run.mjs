import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { runProbe } from './probe.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const appId = process.env.QQ_PROBE_APP_ID;
const secret = process.env.QQ_PROBE_APP_SECRET;
delete process.env.QQ_PROBE_APP_ID; delete process.env.QQ_PROBE_APP_SECRET;
if (!appId || !secret) {
  console.error('Use qq-probe/start.ps1 for local credential input.'); process.exitCode = 1;
} else {
  const dir = path.join(root, '.local/qq-ws-probe'); fs.mkdirSync(dir, { recursive: true });
  const id = randomUUID();
  const expectedText = `qq-probe-${id}`;
  const file = path.join(dir, `run-${id}.json`);
  const controller = new AbortController();
  const stop = () => controller.abort();
  process.once('SIGINT', stop); process.once('SIGTERM', stop);
  console.log('Receive-only QQ probe. No QQ replies, no dot calls. Maximum wait: 10 minutes.');
  console.log(`Evidence: ${file}`);
  let result;
  try {
    result = await runProbe({ appId, secret, expectedText, signal: controller.signal,
      report: record => {
        console.log(JSON.stringify(record));
        if (record.stage === 'ready') console.log(`READY. Send this exact text to the bot in QQ PRIVATE CHAT:\n${expectedText}`);
      } });
  } catch {
    result = { success: false, stage: 'unexpected_error', qq_messages_sent: 0, dot_calls: 0 };
  }
  fs.writeFileSync(file, JSON.stringify({ scope: 'qq-websocket-private-receive-only', expected_text: expectedText, ...result }, null, 2), { flag: 'wx', mode: 0o600 });
  console.log(`RESULT: ${result.success ? 'PRIVATE_MESSAGE_RECEIVED' : 'NOT_VERIFIED'}; ${file}`);
  process.exitCode = result.success ? 0 : 2;
  process.removeListener('SIGINT', stop); process.removeListener('SIGTERM', stop);
}
