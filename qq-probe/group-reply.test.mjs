import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { runGroupReply } from './group-reply.mjs';

const event = { op: 0, t: 'GROUP_MESSAGE_CREATE', s: 2, d: {
  id: 'incoming-id', group_openid: 'bound-group', author: { member_openid: 'member-id' },
  content: 'unique-group-text', timestamp: '2026-10-11T12:00:00+08:00'
} };
function fixture(t, events = [event], sendReply = async () => ({ ok: true, status: 200, json: async () => ({ id: 'outgoing-id' }) })) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qq-group-reply-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const messages = [];
  const fetchImpl = async (url, options) => {
    let data;
    if (url.endsWith('/app/getAppAccessToken')) data = { access_token: 'fixture-token', expires_in: 7200 };
    else if (url.endsWith('/gateway')) data = { url: 'wss://api.bot.qq.com/' };
    else {
      messages.push({ url, body: JSON.parse(options.body) });
      return sendReply(options);
    }
    return { ok: true, status: 200, json: async () => data };
  };
  const socketFactory = () => {
    let closed = false;
    class Socket extends EventTarget {
      emit(packet) { if (!closed) this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(packet) })); }
      send(text) {
        const packet = JSON.parse(text);
        queueMicrotask(() => {
          if (packet.op === 2) this.emit({ op: 0, t: 'READY', d: { session_id: 'session' } });
          if (packet.op === 1) {
            this.emit({ op: 11 });
            for (const incoming of events) this.emit(incoming);
          }
        });
      }
      close() { closed = true; }
    }
    const socket = new Socket();
    queueMicrotask(() => socket.emit({ op: 10, d: { heartbeat_interval: 1000 } }));
    return socket;
  };
  return { dir, appId: '123', secret: 'fixture-secret', expectedText: 'unique-group-text',
    groupOpenid: 'bound-group', timeoutMs: 80, fetchImpl, socketFactory, messages };
}

test('ordinary group message receives the fixed text in its original group with its message ID', async t => {
  const f = fixture(t);
  await runGroupReply(f);
  assert.deepEqual(f.messages, [{ url: 'https://api.bot.qq.com/v2/groups/bound-group/messages',
    body: { msg_type: 0, content: 'QQ 群固定回复验证成功。', msg_id: 'incoming-id', msg_seq: 1 } }]);
});

test('a matching text in another group is ignored while the bound group remains eligible', async t => {
  const f = fixture(t, [{ ...event, d: { ...event.d, group_openid: 'other-group', id: 'other-id' } }, event]);
  await runGroupReply(f);
  assert.deepEqual(f.messages, [{ url: 'https://api.bot.qq.com/v2/groups/bound-group/messages',
    body: { msg_type: 0, content: 'QQ 群固定回复验证成功。', msg_id: 'incoming-id', msg_seq: 1 } }]);
});

test('the reply probe requires an explicit group binding', async t => {
  const f = fixture(t);
  await assert.rejects(runGroupReply({ ...f, groupOpenid: undefined }), /groupOpenid/);
});

test('duplicate delivery and a new invocation using the same ledger send only once', async t => {
  const f = fixture(t, [event, event]);
  await runGroupReply(f);
  await runGroupReply(f);
  assert.equal(f.messages.length, 1);
});

test('a group reply permission error is a failure with its stage and API code', async t => {
  const f = fixture(t, [event], async () => ({ ok: true, status: 200,
    json: async () => ({ code: 40054013, message: 'remote-sensitive-text' }) }));
  const r = await runGroupReply(f);
  assert.deepEqual({ success: r.success, state: r.send_state, stage: r.stage, code: r.api_error_code },
    { success: false, state: 'rejected', stage: 'reply_not_confirmed', code: 40054013 });
});

test('an uncertain network send retains a safe error code and is not retried on a new invocation', async t => {
  const f = fixture(t, [event], async () => { throw new Error('fixture-secret', { cause: { code: 'ETIMEDOUT' } }); });
  const r = await runGroupReply(f);
  await runGroupReply(f);
  assert.deepEqual({ success: r.success, state: r.send_state, stage: r.stage, code: r.network_error_code, attempts: f.messages.length },
    { success: false, state: 'unknown', stage: 'reply_result_unknown_no_retry', code: 'ETIMEDOUT', attempts: 1 });
});

test('HTTP success without a reply message ID remains unconfirmed', async t => {
  const f = fixture(t, [event], async () => ({ ok: true, status: 200, json: async () => ({}) }));
  const r = await runGroupReply(f);
  assert.deepEqual({ success: r.success, state: r.send_state, stage: r.stage },
    { success: false, state: 'unknown', stage: 'reply_response_missing_message_id' });
});

test('confirmed sending returns the reply ID and fixed text without copying arbitrary remote fields', async t => {
  const f = fixture(t, [event], async () => ({ ok: true, status: 200,
    json: async () => ({ id: 'outgoing-id', debug: 'fixture-token' }) }));
  const { receive, timing, ...send } = await runGroupReply(f);
  assert.deepEqual(Object.keys(timing), ['receive_finished_at', 'send_started_at', 'send_finished_at']);
  assert.deepEqual(send, { success: true, send_state: 'confirmed', stage: 'fixed_reply_api_confirmed',
    outgoing_message_id: 'outgoing-id', reply_text: 'QQ 群固定回复验证成功。', http_status: 200 });
});

test('server failure is an uncertain send, not a confirmed rejection, and is not retried', async t => {
  const f = fixture(t, [event], async () => ({ ok: false, status: 503, json: async () => ({ code: 50001 }) }));
  const r = await runGroupReply(f);
  await runGroupReply(f);
  assert.deepEqual({ state: r.send_state, status: r.http_status, attempts: f.messages.length },
    { state: 'unknown', status: 503, attempts: 1 });
});

test('cancellation after receive confirmation prevents a reply', async t => {
  const f = fixture(t), controller = new AbortController();
  await runGroupReply({ ...f, signal: controller.signal,
    report: record => { if (record.stage === 'group_receive_verified') controller.abort(); } });
  assert.deepEqual(f.messages, []);
});

test('cancelling an in-flight HTTP send stops waiting and records an uncertain result', async t => {
  const controller = new AbortController();
  const f = fixture(t, [event], ({ signal }) => new Promise((resolve, reject) => {
    signal?.addEventListener('abort', () => reject(signal.reason), { once: true });
    setTimeout(() => controller.abort(), 10);
  }));
  const deadline = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('send did not observe cancellation')), 200);
    t.after(() => clearTimeout(timer));
  });
  const r = await Promise.race([runGroupReply({ ...f, signal: controller.signal }), deadline]);
  assert.deepEqual({ success: r.success, state: r.send_state }, { success: false, state: 'unknown' });
});

test('the local entry writes a successful API result with matching exit status and pending human receipt', async t => {
  const { runGroupReplyCommand } = await import('./group-reply-run.mjs');
  const f = fixture(t);
  const configFile = path.join(f.dir, 'config.json'), bindingFile = path.join(f.dir, 'binding.json');
  fs.writeFileSync(configFile, JSON.stringify({ appId: '123', appSecret: 'fixture-secret' }));
  fs.writeFileSync(bindingFile, JSON.stringify({ group_openid: 'bound-group' }));
  const { file, exitStatus } = await runGroupReplyCommand({ ...f, configFile, bindingFile, write: () => {} });
  const saved = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.deepEqual({ exitStatus, savedExit: saved.exit_status, group: saved.group_openid,
    text: saved.expected_text, state: saved.send_state, receipt: saved.qq_client_receipt,
    version: /^[a-f0-9]{40}$/.test(saved.git_head), credential: JSON.stringify(saved).includes('fixture-secret') },
  { exitStatus: 0, savedExit: 0, group: 'bound-group', text: 'unique-group-text', state: 'confirmed',
    receipt: 'PENDING_USER_CONFIRMATION', version: true, credential: false });
});

test('the local entry records a missing configuration as a failed run without exposing its contents', async t => {
  const { runGroupReplyCommand } = await import('./group-reply-run.mjs');
  const f = fixture(t);
  const { file, exitStatus } = await runGroupReplyCommand({ ...f,
    configFile: path.join(f.dir, 'absent.json'), bindingFile: path.join(f.dir, 'binding.json'), write: () => {} });
  const saved = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.deepEqual({ exitStatus, savedExit: saved.exit_status, stage: saved.stage, code: saved.error_code, messages: f.messages },
    { exitStatus: 2, savedExit: 2, stage: 'configuration_failed', code: 'ENOENT', messages: [] });
});

test('the command-line entry actually runs and exits 2 when its isolated configuration is absent', t => {
  const root = fileURLToPath(new URL('../', import.meta.url));
  const dir = fs.mkdtempSync(path.join(root, '.local/group-command-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const generated = new Set(['.git', '.local', '.tools', '.agent', 'evidence', 'node_modules']);
  for (const entry of fs.readdirSync(root)) {
    if (!generated.has(entry)) fs.cpSync(path.join(root, entry), path.join(dir, entry), { recursive: true });
  }
  const child = spawnSync(process.execPath, [path.join(dir, 'qq-probe/group-reply-run.mjs')], { encoding: 'utf8', timeout: 5000 });
  assert.equal(child.status, 2, child.stdout + child.stderr);
});

test('a non-JSON HTTP failure retains the known status and parsing stage without retry', async t => {
  const f = fixture(t, [event], async () => ({ ok: false, status: 502,
    json: async () => { throw new SyntaxError('remote-sensitive-text'); } }));
  const r = await runGroupReply(f);
  await runGroupReply(f);
  assert.deepEqual({ success: r.success, stage: r.stage, status: r.http_status, state: r.send_state, attempts: f.messages.length },
    { success: false, stage: 'reply_response_invalid_json', status: 502, state: 'unknown', attempts: 1 });
});

test('existing text matching also prevents sends through the group reply public entry', async t => {
  const f = fixture(t, [{ ...event, d: { ...event.d, content: 'unrelated-text' } }]);
  const r = await runGroupReply(f);
  assert.deepEqual({ success: r.success, messages: f.messages }, { success: false, messages: [] });
});

test('fixed reply reports receive completion, send start and request finish on success and failure', async t => {
  for (const fail of [false,true]) {
    const f=fixture(t,[event],async()=>{if(fail)throw new Error('network');return {ok:true,status:200,json:async()=>({id:'sent'})};});
    const r=await runGroupReply(f);
    assert.ok(Number.isFinite(Date.parse(r.timing.receive_finished_at)));
    assert.ok(Date.parse(r.timing.send_started_at)>=Date.parse(r.timing.receive_finished_at));
    assert.ok(Date.parse(r.timing.send_finished_at)>=Date.parse(r.timing.send_started_at));
    assert.ok(r.receive.records.some(e=>e.stage==='matching_ordinary_group_message'));
  }
});
