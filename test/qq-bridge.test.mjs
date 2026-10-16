import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { QQBridge, BridgeRouter, QQ_EVENT, CHANNEL } from '../src/qq-bridge.mjs';
import { API } from '../qq-probe/probe.mjs';
const digest = s => createHash('sha256').update(s).digest('hex');
const subscription = () => ({ name: QQ_EVENT.name, arguments: { channel_id: CHANNEL }, delivery: { mode: 'webhook', url: 'https://callback.example.com/events', secret: 'whsec_' + Buffer.alloc(32, 7).toString('base64') } });
function fixture(t, sendMode = 'success') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qq-bridge-test-'));
  const posts = [], callbacks = [], acceptResults = [];
  const settings = { appId: '12345', appSecret: 'private-secret', allowedRecipientHash: digest('only-test-user') };
  const options = {
    settings: () => settings,
    send: async (_url, body) => {
      const p = JSON.parse(body); callbacks.push(p);
      return { status: 200, body: JSON.stringify(p.type === 'verification' ? { challenge: p.challenge } : {}) };
    },
    fetchImpl: async (url, opts) => {
      if (url === API + '/app/getAppAccessToken') return { ok: true, status: 200, json: async () => ({ access_token: 'secret-token', expires_in: 7200 }) };
      posts.push({ url, body: JSON.parse(opts.body) });
      assert.equal(url, API + '/v2/users/only-test-user/messages');
      if (sendMode === 'timeout') throw new Error('private-network-error');
      return { ok: sendMode === 'success', status: sendMode === 'success' ? 200 : 403,
        json: async () => sendMode === 'success' ? { id: 'qq-outgoing' } : { code: 40054013, message: 'do-not-log' } };
    },
    receive: async opts => {
      await (await opts.fetchImpl(API + '/app/getAppAccessToken', {})).json();
      opts.report({ stage: 'ready' });
      const good = { id: 'qq-incoming', content: 'What is 17 plus 25?', author: { user_openid: 'only-test-user' } };
      acceptResults.push(opts.acceptMessage({ ...good, author: { user_openid: 'intruder' } }));
      const accepted = opts.acceptMessage(good); acceptResults.push(accepted);
      if (accepted) opts.onMessage(good);
      await new Promise(resolve => opts.signal.addEventListener('abort', resolve, { once: true }));
      return { success: accepted, matched_message: { message_id: good.id, content: good.content } };
    }
  };
  const bridge = new QQBridge(dir, options);
  t.after(async () => { bridge.stop(); await bridge.receiveTask; fs.rmSync(dir, { recursive: true, force: true }); });
  return { dir, posts, callbacks, options, settings, acceptResults, bridge };
}
const call = (b, name, args) => b.rpc('tools/call', { name, arguments: args });
async function prepare(b) { await b.rpc('events/subscribe', subscription()); b.start(); await new Promise(resolve => setImmediate(resolve)); return b.state.messages[b.state.active_message_id]; }
test('allowlisted QQ message -> original event delivery -> list/get/reply once to original chat', async t => {
  const f = fixture(t), b = f.bridge; const m = await prepare(b);
  assert.deepEqual(f.acceptResults, [false, true]);
  assert.equal(f.callbacks[1].name, 'qq.message.created');
  assert.equal(f.callbacks[1].data.message_id, m.message_id);
  assert.ok(!JSON.stringify(f.callbacks).includes('only-test-user'));
  const before = JSON.stringify({ messages: b.state.messages, replies: b.state.replies });
  const pending = await call(b, 'qq_list_pending_messages', { channel_id: CHANNEL });
  assert.equal(pending.structuredContent.messages[0].message_id, m.message_id);
  const message = await call(b, 'qq_get_message', { message_id: m.message_id });
  assert.equal(message.structuredContent.text, m.text);
  assert.equal(JSON.stringify({ messages: b.state.messages, replies: b.state.replies }), before);
  const reply = await call(b, 'qq_reply_message', { message_id: m.message_id, text: '42' });
  assert.equal(reply.structuredContent.state, 'confirmed');
  assert.deepEqual(f.posts[0].body, { msg_type: 0, content: '42', msg_id: 'qq-incoming', msg_seq: 1 });
  assert.deepEqual((await call(b, 'qq_list_pending_messages', { channel_id: CHANNEL })).structuredContent.messages, []);
  const all = JSON.stringify(b.status());
  for (const secret of ['only-test-user', 'private-secret', 'secret-token']) assert.ok(!all.includes(secret));
});
test('concurrent and restarted duplicate replies do not resend', async t => {
  const f = fixture(t), m = await prepare(f.bridge);
  await Promise.all([call(f.bridge, 'qq_reply_message', { message_id: m.message_id, text: '42' }), call(f.bridge, 'qq_reply_message', { message_id: m.message_id, text: '42' })]);
  const restarted = new QQBridge(f.dir, f.options);
  assert.equal((await call(restarted, 'qq_reply_message', { message_id: m.message_id, text: '42' })).structuredContent.duplicate, true);
  assert.equal((await call(restarted, 'qq_reply_message', { message_id: m.message_id, text: 'different' })).isError, true);
  assert.equal(f.posts.length, 1);
});
test('unknown sends and rejections remain non-success with no retries', async t => {
  for (const mode of ['timeout', 'rejected']) {
    const f = fixture(t, mode), m = await prepare(f.bridge);
    const r = await call(f.bridge, 'qq_reply_message', { message_id: m.message_id, text: '42' });
    assert.equal(r.isError, true); assert.equal(r.structuredContent.state, mode === 'timeout' ? 'unknown' : 'rejected');
    await call(f.bridge, 'qq_reply_message', { message_id: m.message_id, text: '42' });
    assert.equal(f.posts.length, 1);
  }
});
test('stop, expiration and changed allowlist block sending', async t => {
  for (const mode of ['stop', 'expired', 'revoked']) {
    const f = fixture(t), m = await prepare(f.bridge);
    if (mode === 'stop') f.bridge.stop();
    if (mode === 'expired') m.created_at = new Date(Date.now() - 301000).toISOString();
    if (mode === 'revoked') f.settings.allowedRecipientHash = digest('different-user');
    assert.equal((await call(f.bridge, 'qq_reply_message', { message_id: m.message_id, text: '42' })).isError, true);
    assert.equal(f.posts.length, 0);
  }
});
test('channel validation, explicit arming and destination argument rejection', async t => {
  const f = fixture(t), b = f.bridge;
  assert.throws(() => b.start(), /Subscribe/);
  const sub = subscription(); sub.arguments.channel_id = 'wrong';
  await assert.rejects(b.rpc('events/subscribe', sub));
  const m = await prepare(b);
  await assert.rejects(call(b, 'qq_reply_message', { message_id: m.message_id, text: '42', openid: 'intruder' }));
  assert.equal((await call(b, 'qq_reply_message', { message_id: m.message_id, text: 'x'.repeat(1001) })).isError, true);
  assert.throws(() => b.start(), /already running/);
  assert.equal(f.posts.length, 0);
});
test('router preserves original tools/events and stores QQ state separately', async t => {
  const f = fixture(t), router = new BridgeRouter(f.dir, f.options);
  assert.equal((await router.rpc('tools/list')).tools.length, 9);
  assert.deepEqual((await router.rpc('events/list')).events.map(e => e.name), ['probe.message.created', 'qq.message.created', 'qq.group.message.created']);
  await router.rpc('events/subscribe', subscription());
  assert.equal(Object.keys(router.probe.state.subscriptions).length, 0);
  const old = subscription(); old.name = 'probe.message.created'; old.arguments.channel_id = 'phase1';
  await router.rpc('events/subscribe', old);
  const m = router.inject({ channel_id: 'phase1', text: 'old synthetic' });
  await router.rpc('tools/call', { name: 'reply_message', arguments: { message_id: m.message_id, text: 'local ACK' } });
  assert.equal(router.probe.state.replies[m.message_id].text, 'local ACK');
  assert.equal(f.posts.length, 0);
  assert.equal(Object.keys(router.qq.state.messages).length, 0);
});

test('continuous receiver returns only the current question, retains records, deduplicates and stays enabled after replies', async t => {
  const f = fixture(t), b = f.bridge, first = await prepare(b);
  await call(b, 'qq_reply_message', {message_id:first.message_id,text:'42'});
  assert.equal(b.enabled,true); assert.equal(b.receiving,true);
  const second = {id:'qq-second',content:'And plus three?',author:{user_openid:'only-test-user'}};
  b.incoming(second); b.incoming(second);
  b.incoming({...second,id:'intruder-message',author:{user_openid:'intruder'}});
  const third = {...second,id:'qq-third',content:'Then plus four?'};
  b.incoming(third);
  const pending = (await call(b,'qq_list_pending_messages',{channel_id:CHANNEL})).structuredContent.messages;
  assert.equal(pending.length,2);
  const next = (await call(b,'qq_get_message',{message_id:pending[0].message_id})).structuredContent;
  assert.deepEqual(next,b.publicMessage(b.state.messages[pending[0].message_id]));
  assert.equal(Object.hasOwn(next,'history'),false);
  await call(b,'qq_reply_message',{message_id:pending[0].message_id,text:'45'});
  const last = (await call(b,'qq_get_message',{message_id:pending[1].message_id})).structuredContent;
  assert.deepEqual(last,b.publicMessage(b.state.messages[pending[1].message_id]));
  assert.equal(Object.hasOwn(last,'history'),false);
  await call(b,'qq_reply_message',{message_id:pending[1].message_id,text:'49'});
  assert.equal(f.posts.length,3); assert.equal(b.enabled,true);
  assert.deepEqual(f.posts.map(p=>p.body.msg_id),['qq-incoming','qq-second','qq-third']);
  b.stop(); await b.receiveTask;
  b.incoming({...third,id:'after-stop'});
  assert.equal(Object.keys(b.state.messages).length,3);
  const restored = new QQBridge(f.dir,f.options);
  assert.deepEqual(restored.state.messages,b.state.messages);
  assert.deepEqual(restored.state.replies,b.state.replies);
  const reread = await call(restored,'qq_get_message',{message_id:pending[1].message_id});
  assert.deepEqual(reread.structuredContent,last);
  assert.deepEqual(JSON.parse(reread.content[0].text),last);
  assert.deepEqual(Object.values(restored.state.replies).map(r=>r.text),['42','45','49']);
});
test('receiver reconnects with renewed credentials and stop interrupts reconnect delay', async t => {
 const f=fixture(t); let sessions=0, tokens=0;
 f.bridge.receive = async opts => {
   sessions++; await (await opts.fetchImpl(API+'/app/getAppAccessToken',{})).json(); tokens++;
   opts.report({stage:'websocket_closed'});
 };
 f.bridge.reconnectDelay=5;
 await f.bridge.rpc('events/subscribe',subscription()); f.bridge.start();
 while(sessions<2) await new Promise(r=>setTimeout(r,5));
 f.bridge.stop(); await f.bridge.receiveTask;
 assert.equal(tokens,sessions); assert.ok(sessions>=2); assert.equal(f.bridge.receiving,false);
 const stopped=sessions; await new Promise(r=>setTimeout(r,15)); assert.equal(sessions,stopped);
});
