import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runProbe, connectCredentials, INTENTS, API } from './probe.mjs';

const appId = '123456';
const secret = 'private-test-secret';
const accessToken = 'private-test-access-token';
const expectedText = 'qq-probe-test-nonce';
function fixture({ mode = 'success', tokenData, gatewayData } = {}) {
  const http = [], sent = [];
  const fetchImpl = async (url, options) => {
    http.push({ url, options });
    assert.equal(options.redirect, 'error');
    if (url === API + '/app/getAppAccessToken') {
      assert.equal(options.method, 'POST');
      assert.deepEqual(JSON.parse(options.body), { appId, clientSecret: secret });
      return { ok: true, status: 200, json: async () => tokenData ?? { access_token: accessToken, expires_in: 7200 } };
    }
    assert.equal(url, API + '/gateway');
    assert.equal(options.headers.Authorization, 'QQBot ' + accessToken);
    return { ok: true, status: 200, json: async () => gatewayData ?? { url: 'wss://api.bot.qq.com/websocket/' } };
  };
  let closed = false;
  const socketFactory = url => {
    assert.equal(url, 'wss://api.bot.qq.com/websocket/');
    class Socket extends EventTarget {
      packet(data) { if (!closed) this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(data) })); }
      send(text) {
        const packet = JSON.parse(text); sent.push(packet);
        assert.ok([1, 2].includes(packet.op), 'Only Identify and heartbeat may be sent');
        if (packet.op === 2) {
          assert.equal(packet.d.intents, INTENTS);
          assert.equal(packet.d.token, 'QQBot ' + accessToken);
          assert.deepEqual(packet.d.shard, [0, 1]);
          queueMicrotask(() => {
            if (mode === 'invalid_session') { this.packet({ op: 9 }); return; }
            if (mode === 'reconnect') { this.packet({ op: 7 }); return; }
            this.packet({ op: 0, t: 'READY', s: 1, d: { session_id: 'private-session' } });
          });
        } else if (mode !== 'no_ack') {
          queueMicrotask(() => {
            this.packet({ op: 11 });
            if (mode === 'success') {
              this.packet({ op: 0, t: 'GROUP_AT_MESSAGE_CREATE', s: 2, d: { content: expectedText } });
              this.packet({ op: 0, t: 'C2C_MESSAGE_CREATE', s: 3, d: { id: 'unrelated', content: 'private unrelated text' } });
              this.packet({ op: 0, t: 'C2C_MESSAGE_CREATE', s: 4, d: { id: 'test-message-id', content: expectedText } });
            }
          });
        }
      }
      close() { closed = true; }
    }
    const socket = new Socket();
    queueMicrotask(() => {
      socket.dispatchEvent(new Event('open'));
      if (mode !== 'silent') socket.packet({ op: 10, d: { heartbeat_interval: 30 } });
    });
    return socket;
  };
  return { fetchImpl, socketFactory, http, sent, closed: () => closed };
}
test('receive-only: token, gateway, READY, heartbeat and matching private message; secrets omitted', async () => {
  const f = fixture();
  const result = await runProbe({ appId, secret, expectedText, ...f, timeoutMs: 300 });
  assert.equal(result.success, true);
  assert.equal(result.ready, true); assert.equal(result.heartbeat_ack, true);
  assert.equal(result.matched_message.message_id, 'test-message-id');
  assert.equal(result.c2c_events, 2); assert.equal(result.ignored_events, 1);
  assert.equal(result.qq_messages_sent, 0); assert.equal(result.dot_calls, 0);
  assert.equal(f.http.length, 2); assert.deepEqual(f.sent.map(p => p.op), [2, 1]);
  assert.equal(f.closed(), true);
  for (const value of [secret, accessToken, 'private-session', 'private unrelated text']) assert.ok(!JSON.stringify(result).includes(value));
});
test('HTTP 200 business failure stops before gateway without disclosing remote text', async () => {
  const f = fixture({ tokenData: { code: 100016, message: secret } });
  const result = await runProbe({ appId, secret, expectedText, ...f });
  assert.equal(result.success, false); assert.equal(f.http.length, 1);
  assert.equal(result.records[0].code, 100016);
  assert.ok(!JSON.stringify(result).includes(secret));
});
test('untrusted or non-WSS gateway is rejected before any token-bearing socket', async () => {
  for (const url of ['ws://api.bot.qq.com/', 'wss://evil.example/', 'wss://user:pass@api.bot.qq.com/']) {
    const f = fixture({ gatewayData: { url } });
    await assert.rejects(connectCredentials(appId, secret, f.fetchImpl), e => e.detail.category === 'invalid_gateway');
    assert.equal(f.sent.length, 0);
  }
});
test('READY without a matching private message is not success', async () => {
  const f = fixture({ mode: 'no_message' });
  const result = await runProbe({ appId, secret, expectedText, ...f, timeoutMs: 75 });
  assert.equal(result.ready, true); assert.equal(result.heartbeat_ack, true);
  assert.equal(result.success, false); assert.equal(result.records.at(-1).stage, 'receive_timeout');
});
test('heartbeat without ACK fails instead of staying connected indefinitely', async () => {
  const f = fixture({ mode: 'no_ack' });
  const result = await runProbe({ appId, secret, expectedText, ...f, timeoutMs: 200 });
  assert.equal(result.records.at(-1).stage, 'heartbeat_timeout'); assert.equal(result.success, false);
});
test('authentication failure and server reconnect request end the diagnostic session', async () => {
  for (const [mode, expected] of [['invalid_session', 'invalid_session'], ['reconnect', 'gateway_requested_reconnect']]) {
    const f = fixture({ mode });
    const result = await runProbe({ appId, secret, expectedText, ...f, timeoutMs: 200 });
    assert.equal(result.records.at(-1).stage, expected); assert.equal(result.success, false);
    assert.equal(f.closed(), true);
  }
});
test('cancel closes only this socket and records no receive success', async () => {
  const f = fixture({ mode: 'silent' }); const controller = new AbortController();
  const promise = runProbe({ appId, secret, expectedText, ...f, signal: controller.signal, timeoutMs: 100 });
  setTimeout(() => controller.abort(), 10);
  const result = await promise;
  assert.equal(result.records.at(-1).stage, 'cancelled'); assert.equal(result.success, false); assert.equal(f.closed(), true);
});
test('network error records only error category and code', async () => {
  const result = await runProbe({ appId, secret, expectedText, fetchImpl: async () => { throw Object.assign(new Error(secret), { cause: { code: 'ENOTFOUND' } }); } });
  assert.equal(result.records[0].code, 'ENOTFOUND'); assert.ok(!JSON.stringify(result).includes(secret));
});

test('continuous socket remains open across matching messages and stops on cancellation', async () => {
 const f=fixture(), controller=new AbortController(), received=[];
 const result=await runProbe({appId,secret,expectedText,...f,timeoutMs:300,continuous:true,signal:controller.signal,
  onMessage: d=>{received.push(d.id); if(received.length===2) controller.abort();}});
 assert.equal(received.length,2); assert.equal(result.records.at(-1).stage,'cancelled');
 assert.equal(f.http.length,2); assert.equal(f.closed(),true);
});
