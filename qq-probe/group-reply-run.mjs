import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { runGroupReply } from './group-reply.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));

export async function runGroupReplyCommand({
  configFile = path.join(root, '.local/qq-auth/config.json'),
  bindingFile = path.join(root, '.local/qq-group-receive/test-group.json'),
  dir = path.join(root, '.local/qq-group-reply'),
  expectedText = `qq-group-reply-${randomUUID()}`, write = console.log,
  fetchImpl, socketFactory, signal, timeoutMs = 600000
} = {}) {
  const started = new Date().toISOString();
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `run-${randomUUID()}.json`);
  let binding, result, stage = 'configuration';
  try {
    const config = JSON.parse(fs.readFileSync(configFile, 'utf8').replace(/^\uFEFF/, ''));
    binding = JSON.parse(fs.readFileSync(bindingFile, 'utf8').replace(/^\uFEFF/, ''));
    stage = 'probe';
    result = await runGroupReply({ appId: config.appId, secret: config.appSecret,
      groupOpenid: binding.group_openid, expectedText, dir, fetchImpl, socketFactory, signal, timeoutMs,
      report: record => {
        write(JSON.stringify(record));
        if (record.stage === 'ready') write(`READY. Send only in group ${binding.group_openid}, without @ or quote:\n${expectedText}`);
      } });
  } catch (error) {
    result = { success: false, stage: `${stage}_failed`,
      ...(typeof error.code === 'string' && /^[A-Z_0-9]+$/.test(error.code) ? { error_code: error.code } : {}) };
  }
  const exitStatus = result.success ? 0 : 2;
  const evidence = { scope: 'bound-group-fixed-reply-only', started_at: started, ended_at: new Date().toISOString(),
    git_head: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
    command: `node ${fileURLToPath(import.meta.url)}`, group_openid: binding?.group_openid,
    expected_text: expectedText, ...result, exit_status: exitStatus, qq_client_receipt: 'PENDING_USER_CONFIRMATION' };
  fs.writeFileSync(file, JSON.stringify(evidence, null, 2), { flag: 'wx', mode: 0o600 });
  write(`RESULT: ${result.success ? 'GROUP_FIXED_REPLY_API_CONFIRMED' : 'NOT_VERIFIED'}; ${file}`);
  return { file, exitStatus };
}

if (import.meta.main) {
  const controller = new AbortController();
  const stop = () => controller.abort();
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  try {
    process.exitCode = (await runGroupReplyCommand({ signal: controller.signal })).exitStatus;
  } catch {
    console.error('RESULT: EVIDENCE_WRITE_OR_RUNTIME_FAILED');
    process.exitCode = 2;
  } finally {
    process.removeListener('SIGINT', stop);
    process.removeListener('SIGTERM', stop);
  }
}
