import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { runFixedReply, REPLY_TEXT } from './probe.mjs';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const appId = process.env.QQ_PROBE_APP_ID, secret = process.env.QQ_PROBE_APP_SECRET;
delete process.env.QQ_PROBE_APP_ID; delete process.env.QQ_PROBE_APP_SECRET;
if (!appId || !secret) { console.error('Use qq-reply-probe/start.ps1 for hidden local credential input.'); process.exitCode = 1; }
else {
  const dir = path.join(root, '.local/qq-fixed-reply'); fs.mkdirSync(dir, { recursive: true });
  const id = randomUUID(), expectedText = `qq-reply-${id}`;
  const file = path.join(dir, `run-${id}.json`);
  const controller = new AbortController(); const stop = () => controller.abort();
  process.once('SIGINT', stop); process.once('SIGTERM', stop);
  console.log(`One fixed QQ reply to the matching private-message sender. No dot.\nReply: ${REPLY_TEXT}\nEvidence: ${file}`);
  let result;
  try {
    result = await runFixedReply({ appId, secret, expectedText, dir, signal: controller.signal, report: record => {
      console.log(JSON.stringify(record));
      if (record.stage === 'ready') console.log(`READY. Send this exact text in QQ PRIVATE CHAT:\n${expectedText}`);
    } });
  } catch { result = { success: false, send_state: 'unknown', stage: 'unexpected_error', automatic_retry: false }; }
  fs.writeFileSync(file, JSON.stringify({ expected_text: expectedText, ...result, qq_client_receipt: 'PENDING_USER_CONFIRMATION' }, null, 2), { flag: 'wx', mode: 0o600 });
  console.log(`RESULT: ${result.success ? 'FIXED_REPLY_API_CONFIRMED' : 'NOT_VERIFIED'}; ${file}`);
  process.exitCode = result.success ? 0 : 2;
  process.removeListener('SIGINT', stop); process.removeListener('SIGTERM', stop);
}
