import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { runFixedReply, REPLY_TEXT } from './probe.mjs';
import { API } from '../qq-probe/probe.mjs';
function fixture(t, { missingAuthor = false, sendMode = 'success', wrongText = false, groupOnly = false } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qq-reply-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const posts = [], packets = [];
  const expectedText = 'qq-reply-unique', appId = '12345', secret = 'secret-for-test';
  const fetchImpl = async (url, options) => {
    const ok = data => ({ ok: true, status: 200, json: async () => data });
    if (url === API + '/app/getAppAccessToken') return ok({ access_token: 'private-token', expires_in: 7200 });
    if (url === API + '/gateway') return ok({ url: 'wss://api.sgroup.qq.com/websocket/' });
    posts.push({ url, options });
    assert.equal(url, API + '/v2/users/sender-openid/messages');
    assert.equal(options.redirect, 'error');
    assert.equal(options.headers.Authorization, 'QQBot private-token');
    assert.deepEqual(JSON.parse(options.body), { msg_type: 0, content: REPLY_TEXT, msg_id: 'incoming-id', msg_seq: 1 });
    if (sendMode === 'timeout') throw new Error('secret-for-test');
    if (sendMode === 'rejected') return ok({ code: 40054013, message: 'private-token' });
    if (sendMode === 'malformed') return ok({});
    if (sendMode === 'server_error') return { ok: false, status: 503, json: async () => ({}) };
    return ok({ id: 'outgoing-id', timestamp: '2026-10-11T00:00:00+08:00' });
  };
  const socketFactory = () => {
    let closed = false;
    class Socket extends EventTarget {
      emit(packet) { if (!closed) this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(packet) })); }
      send(text) {
        const p = JSON.parse(text); packets.push(p);
        queueMicrotask(() => {
          if (p.op === 2) this.emit({ op: 0, t: 'READY', s: 1, d: { session_id: 'session' } });
          if (p.op === 1) {
            this.emit({ op: 11 });
            const message = { op: 0, t: groupOnly ? 'GROUP_AT_MESSAGE_CREATE' : 'C2C_MESSAGE_CREATE', s: 2,
              d: { id: 'incoming-id', content: wrongText ? 'unrelated-private-text' : expectedText, author: missingAuthor ? {} : { user_openid: 'sender-openid' } } };
            this.emit(message); this.emit(message);
          }
        });
      }
      close() { closed = true; }
    }
    const socket = new Socket(); queueMicrotask(() => socket.emit({ op: 10, d: { heartbeat_interval: 40 } }));
    return socket;
  };
  return { dir, appId, secret, expectedText, fetchImpl, socketFactory, posts, packets, timeoutMs: 85 };
}
test('one fixed reply to original C2C sender with original msg_id; no dot or arbitrary text', async t => {
  const f = fixture(t); const r = await runFixedReply(f);
  assert.equal(r.success, true); assert.equal(r.confirmed_messages_sent, 1); assert.equal(r.dot_calls, 0);
  assert.equal(r.outgoing_message_id, 'outgoing-id'); assert.equal(f.posts.length, 1);
  assert.ok(f.packets.every(p => [1, 2].includes(p.op)));
  assert.equal(JSON.parse(fs.readFileSync(r.ledger_file)).state, 'confirmed');
  for (const value of ['secret-for-test', 'private-token', 'sender-openid']) assert.ok(!JSON.stringify(r).includes(value));
});
test('persisted reservation prevents a second send after duplicate delivery or restart', async t => {
  const f = fixture(t); await runFixedReply(f); const again = await runFixedReply(f);
  assert.equal(f.posts.length, 1); assert.equal(again.success, false);
  assert.equal(again.records.at(-1).stage, 'duplicate_send_blocked');
});
test('timeout, API rejection, malformed success and 5xx never automatically retry', async t => {
  for (const mode of ['timeout', 'rejected', 'malformed', 'server_error']) {
    const f = fixture(t, { sendMode: mode }); const r = await runFixedReply(f);
    assert.equal(r.success, false); assert.equal(r.send_attempts, 1); assert.equal(f.posts.length, 1);
    assert.equal(r.send_state, mode === 'rejected' ? 'rejected' : 'unknown');
    await runFixedReply(f); assert.equal(f.posts.length, 1);
    assert.ok(!JSON.stringify(r).includes('private-token'));
  }
});
test('missing author never falls back to a guessed user or another conversation', async t => {
  const f = fixture(t, { missingAuthor: true }); const r = await runFixedReply(f);
  assert.equal(f.posts.length, 0); assert.equal(r.records.at(-1).stage, 'missing_or_mismatched_reply_target');
});
test('nonmatching private messages and group messages do not trigger replies', async t => {
  for (const options of [{ wrongText: true }, { groupOnly: true }]) {
    const f = fixture(t, options); const r = await runFixedReply(f);
    assert.equal(r.success, false); assert.equal(f.posts.length, 0);
    assert.ok(!JSON.stringify(r).includes('unrelated-private-text'));
  }
});
test('abort after receive confirmation but before sending sends nothing', async t => {
  const f = fixture(t), controller = new AbortController();
  const r = await runFixedReply({ ...f, signal: controller.signal, report: r => { if (r.stage === 'receive_verified') controller.abort(); } });
  assert.equal(f.posts.length, 0); assert.equal(r.records.at(-1).stage, 'cancelled_before_send');
});
