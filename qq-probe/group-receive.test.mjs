import { test } from 'node:test';
import assert from 'node:assert/strict';
import { receiveGroup } from './group-receive.mjs';
import { API, INTENTS } from './probe.mjs';

const expectedText = 'unique-group-nonce';
const data = { id: 'message', group_openid: 'test-group', author: { member_openid: 'member' },
  content: expectedText, timestamp: '2026-10-11T12:00:00+08:00' };
async function fixture(events, { ack = true, signal } = {}) {
  const requests = [], sent = []; let closed = false;
  const fetchImpl = async (url, options) => {
    requests.push(url);
    assert.ok([API + '/app/getAppAccessToken', API + '/gateway'].includes(url));
    return { ok: true, json: async () => url.endsWith('/gateway')
      ? { url: 'wss://api.bot.qq.com/' } : { access_token: 'test-secret-token', expires_in: 7200 } };
  };
  const socketFactory = () => {
    class Socket extends EventTarget {
      packet(p) { if (!closed) this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(p) })); }
      send(text) {
        const p = JSON.parse(text); sent.push(p.op);
        assert.ok([1, 2].includes(p.op));
        if (p.op === 2) {
          assert.equal(p.d.intents, INTENTS);
          queueMicrotask(() => this.packet({ op: 0, t: 'READY', d: { session_id: 'test-session' } }));
        } else queueMicrotask(() => {
          if (ack) this.packet({ op: 11 });
          for (const event of events) this.packet(event);
        });
      }
      close() { closed = true; }
    }
    const ws = new Socket();
    queueMicrotask(() => ws.packet({ op: 10, d: { heartbeat_interval: 1000 } }));
    return ws;
  };
  const result = await receiveGroup({ appId: '123', secret: 'test-secret', expectedText, timeoutMs: 80,
    fetchImpl, socketFactory, signal });
  assert.equal(closed, true);
  assert.equal(requests.length, 2);
  assert.deepEqual(sent, [2, 1]);
  assert.equal(result.qq_messages_sent, 0); assert.equal(result.dot_calls, 0);
  assert.ok(!JSON.stringify(result).includes('test-secret'));
  return result;
}
test('group prerequisite: saves only matching ordinary event, with actual received fields', async () => {
  const packet = { op: 0, t: 'GROUP_MESSAGE_CREATE', s: 5, d: { ...data, mentions: [], message_scene: { source: 'fixture' } } };
  const result = await fixture([
    { op: 0, t: 'C2C_MESSAGE_CREATE', d: data },
    { op: 0, t: 'GROUP_AT_MESSAGE_CREATE', d: data },
    { op: 0, t: 'GROUP_MESSAGE_CREATE', d: { ...data, content: 'unrelated' } }, packet]);
  assert.equal(result.success, true); assert.deepEqual(result.matched_event, packet);
  assert.ok(!JSON.stringify(result).includes('unrelated'));
});
test('group prerequisite: private and @ events never qualify', async () => {
  const result = await fixture(['C2C_MESSAGE_CREATE', 'GROUP_AT_MESSAGE_CREATE'].map(t => ({ op: 0, t, d: data })));
  assert.equal(result.success, false); assert.equal(result.matched_event, null);
});
test('group prerequisite: missing group identity or mentions do not verify', async () => {
  for (const d of [{ ...data, group_openid: null }, { ...data, mentions: [{ id: 'bot' }] }]) {
    assert.equal((await fixture([{ op: 0, t: 'GROUP_MESSAGE_CREATE', d }])).success, false);
  }
});
test('group prerequisite: event without heartbeat ACK does not verify', async () => {
  assert.equal((await fixture([{ op: 0, t: 'GROUP_MESSAGE_CREATE', d: data }], { ack: false })).success, false);
});
test('group prerequisite: cancellation closes only its probe connection', async () => {
  const controller = new AbortController();
  setTimeout(() => controller.abort(), 20);
  const result = await fixture([], { signal: controller.signal });
  assert.equal(result.success, false); assert.equal(result.records.at(-1).stage, 'cancelled');
});
