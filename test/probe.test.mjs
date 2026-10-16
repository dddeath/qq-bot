import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHmac, randomBytes } from 'node:crypto';
import { Probe, VERSION } from '../src/probe.mjs';
import { startServers } from '../src/server.mjs';
import { signedHeaders, publicIPv4, callbackURL, secretKey, resolvePublicIPv4 } from '../src/webhook.mjs';

const secret = 'whsec_' + Buffer.alloc(32, 7).toString('base64');
const subscription = () => ({ name: 'probe.message.created', arguments: { channel_id: 'phase1' }, delivery: { mode: 'webhook', url: 'https://callback.example.com/events', secret } });
function fixture(t, options = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dot-probe-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const calls = [];
  const send = async (url, body, headers) => {
    const payload = JSON.parse(body);
    const expected = createHmac('sha256', Buffer.alloc(32, 7)).update(`${headers['webhook-id']}.${headers['webhook-timestamp']}.${body}`).digest('base64');
    assert.ok(headers['webhook-signature'].split(' ').includes('v1,' + expected));
    assert.ok(headers['X-MCP-Subscription-Id'].startsWith('sub_'));
    calls.push({ payload, headers });
    return { status: 200, body: JSON.stringify(payload.type === 'verification' ? { challenge: payload.challenge } : {}) };
  };
  return { dir, calls, probe: new Probe(dir, { send, sleep: async () => {}, ...options }) };
}

test('discovery includes MCP2 events and exactly three tools', async t => {
  const { probe } = fixture(t);
  const result = await probe.rpc('server/discover');
  assert.deepEqual(result.supportedVersions, [VERSION]);
  assert.deepEqual(result.capabilities, { tools: {}, events: {} });
  assert.equal((await probe.rpc('events/list')).events[0].name, 'probe.message.created');
  const tools = (await probe.rpc('tools/list')).tools;
  assert.equal(tools.length, 3);
  assert.equal(tools.find(tool => tool.name === 'list_pending_messages').annotations.readOnlyHint, true);
});

test('pending listing is repeatable, channel-filtered and does not mutate business state or payload', async t => {
  const { probe, dir } = fixture(t);
  await probe.rpc('events/subscribe', subscription());
  const other = subscription(); other.arguments.channel_id = 'phase1-fetch';
  await probe.rpc('events/subscribe', other);
  const old = probe.inject({ channel_id: 'phase1', text: 'preserve old message' });
  const fresh = probe.inject({ channel_id: 'phase1-fetch', text: 'new message' });
  await probe.deliver(fresh.message_id);
  const file = path.join(dir, `${fresh.event_id}.payload.json`);
  const wire = fs.readFileSync(file);
  const business = () => JSON.stringify({ subscriptions: probe.state.subscriptions, messages: probe.state.messages, replies: probe.state.replies, deliveries: probe.state.deliveries });
  const before = business();
  const params = { name: 'list_pending_messages', arguments: { channel_id: 'phase1-fetch' } };
  const first = await probe.rpc('tools/call', params);
  assert.deepEqual(first, await probe.rpc('tools/call', params));
  assert.deepEqual(first.structuredContent.messages, [{ message_id: fresh.message_id, channel_id: 'phase1-fetch', created_at: fresh.created_at }]);
  assert.equal(business(), before);
  assert.deepEqual(fs.readFileSync(file), wire);
  const restarted = new Probe(dir);
  assert.deepEqual(await restarted.rpc('tools/call', params), first);
  assert.equal(restarted.state.messages[old.message_id].text, old.text);
});

test('pending IDs remain after a read and disappear only after a successful reply, retaining original message', async t => {
  const { probe, dir } = fixture(t);
  await probe.rpc('events/subscribe', subscription());
  const message = probe.inject({ channel_id: 'phase1', text: 'read then reply' });
  const params = { name: 'list_pending_messages', arguments: { channel_id: 'phase1' } };
  await probe.rpc('tools/call', { name: 'get_message', arguments: { message_id: message.message_id } });
  const failed = await probe.rpc('tools/call', { name: 'reply_message', arguments: { message_id: 'missing', text: 'ACK' } });
  assert.equal(failed.isError, true);
  assert.equal((await probe.rpc('tools/call', params)).structuredContent.messages.length, 1);
  await probe.rpc('tools/call', { name: 'reply_message', arguments: { message_id: message.message_id, text: 'ACK' } });
  assert.deepEqual((await probe.rpc('tools/call', params)).structuredContent.messages, []);
  assert.deepEqual(probe.state.messages[message.message_id], message);
  assert.deepEqual((await new Probe(dir).rpc('tools/call', params)).structuredContent.messages, []);
});

test('pending list accepts only a nonempty channel_id and returns empty for an unmatched channel', async t => {
  const { probe } = fixture(t);
  for (const args of [{}, { channel_id: '' }, { channel_id: ' ' }, { channel_id: 1 }, { channel_id: 'x', consume: true }, { channel_id: 'x'.repeat(129) }]) {
    await assert.rejects(probe.rpc('tools/call', { name: 'list_pending_messages', arguments: args }), e => e.code === -32602);
  }
  assert.deepEqual((await probe.rpc('tools/call', { name: 'list_pending_messages', arguments: { channel_id: 'unknown' } })).structuredContent, { channel_id: 'unknown', messages: [] });
});

test('signed challenge, event delivery, read and idempotent reply', async t => {
  const { probe, calls, dir } = fixture(t);
  const sub = await probe.rpc('events/subscribe', subscription());
  const again = await probe.rpc('events/subscribe', subscription());
  assert.equal(sub.id, again.id);
  assert.equal(calls.length, 1);
  const message = probe.inject({ channel_id: 'phase1', text: 'nonce: test-123' });
  assert.equal((await probe.deliver(message.message_id))[0].accepted, true);
  assert.equal(calls[1].payload.eventId, message.event_id);
  assert.equal(calls[1].headers['webhook-id'], message.event_id);
  const wire = fs.readFileSync(path.join(dir, `${message.event_id}.payload.json`), 'utf8');
  assert.deepEqual(JSON.parse(wire), calls[1].payload);
  assert.equal(JSON.parse(wire).data.message_id, message.message_id);
  const read = await probe.rpc('tools/call', { name: 'get_message', arguments: { message_id: message.message_id } });
  assert.equal(read.structuredContent.text, message.text);
  const args = { name: 'reply_message', arguments: { message_id: message.message_id, text: `ACK:${message.message_id}:${message.text}` } };
  assert.equal((await probe.rpc('tools/call', args)).structuredContent.duplicate, false);
  assert.equal((await probe.rpc('tools/call', args)).structuredContent.duplicate, true);
  args.arguments.text = 'changed';
  assert.equal((await probe.rpc('tools/call', args)).isError, true);
  assert.equal(probe.status().replies.length, 1);
});

test('subscription and replies survive restart; unsubscribe is idempotent', async t => {
  const { dir, probe } = fixture(t);
  await probe.rpc('events/subscribe', subscription());
  const message = probe.inject({ channel_id: 'phase1', text: 'persist' });
  await probe.rpc('tools/call', { name: 'reply_message', arguments: { message_id: message.message_id, text: 'saved' } });
  const restarted = new Probe(dir);
  assert.equal(restarted.status().subscriptions[0].active, true);
  assert.equal(restarted.status().replies[0].text, 'saved');
  const unsub = subscription(); delete unsub.delivery.secret;
  await restarted.rpc('events/unsubscribe', unsub);
  await restarted.rpc('events/unsubscribe', unsub);
  assert.deepEqual(await restarted.deliver(message.message_id), []);
  assert.throws(() => restarted.inject({ channel_id: 'phase1', text: 'after unsubscribe' }), /No active/);
});

test('invalid challenge is rejected and no subscription becomes active', async t => {
  const { probe } = fixture(t, { send: async () => ({ status: 200, body: '{"challenge":"wrong"}' }) });
  await assert.rejects(probe.rpc('events/subscribe', subscription()), e => e.code === -32015);
  assert.equal(probe.status().subscriptions.length, 0);
  assert.equal(probe.status().callback_diagnostics[0].detail, 'challenge_failed');
  assert.ok(!JSON.stringify(probe.status()).includes(secret));
});

test('Fake-IP fallback resolves a real public address without allowing private addresses', async () => {
  const lookup = async () => [{ address: '198.18.0.23', family: 4 }];
  let queries = 0;
  const fetchDNS = async url => {
    queries++;
    assert.equal(new URL(url).hostname, 'cloudflare-dns.com');
    assert.equal(new URL(url).searchParams.get('name'), 'callback.example.com');
    return { ok: true, json: async () => ({ Status: 0, Answer: [{ type: 1, data: '8.8.8.8' }] }) };
  };
  assert.equal(await resolvePublicIPv4('callback.example.com', { lookup, fetchDNS }), '8.8.8.8');
  assert.equal(queries, 1);
  await assert.rejects(resolvePublicIPv4('callback.example.com', { lookup, fetchDNS: async () => ({ ok: true, json: async () => ({ Status: 0, Answer: [{ type: 1, data: '127.0.0.1' }] }) }) }), /non_public/);
  await assert.rejects(resolvePublicIPv4('198.18.0.23', { lookup, fetchDNS }), /non_public/);
  await assert.rejects(resolvePublicIPv4('private.example.com', { lookup: async () => [{ address: '10.0.0.1', family: 4 }], fetchDNS }), /non_public/);
  assert.equal(queries, 1);
});

test('callback failures retain category and status, not callback path or secret', async t => {
  const { probe } = fixture(t, { send: async () => ({ status: 403, body: 'sensitive response' }) });
  await assert.rejects(probe.rpc('events/subscribe', subscription()), e => e.data.reason === 'http_4xx');
  const diagnostic = probe.status().callback_diagnostics[0];
  assert.equal(diagnostic.http_status, 403);
  assert.equal(diagnostic.callback_host, 'callback.example.com');
  assert.ok(!JSON.stringify(diagnostic).includes('sensitive'));
  assert.ok(!JSON.stringify(diagnostic).includes('/events'));
});

test('strict event arguments, secret and HTTPS validation', async t => {
  const { probe } = fixture(t);
  for (const modify of [p => p.name = 'unknown', p => p.arguments.channel_id = 1, p => p.arguments.extra = true,
    p => p.delivery.url = 'http://127.0.0.1/', p => p.delivery.secret = 'whsec_eA==', p => p.ttlMs = -5]) {
    const p = subscription(); modify(p);
    await assert.rejects(probe.rpc('events/subscribe', p), e => e.code === -32602);
  }
});

test('filtering, expiration and refresh are respected', async t => {
  let now = Date.now();
  const { probe } = fixture(t, { now: () => now });
  const p = subscription(); p.ttlMs = 1000;
  const first = await probe.rpc('events/subscribe', p);
  assert.throws(() => probe.inject({ channel_id: 'different', text: 'ignored' }), /No active/);
  now += 1500;
  assert.equal(probe.status().subscriptions[0].active, false);
  assert.throws(() => probe.inject({ channel_id: 'phase1', text: 'expired' }), /No active/);
  const refreshed = await probe.rpc('events/subscribe', p);
  assert.equal(first.id, refreshed.id);
  assert.equal(probe.status().subscriptions[0].active, true);
});

test('retry preserves event ID and stops after success', async t => {
  const { probe } = fixture(t);
  await probe.rpc('events/subscribe', subscription());
  const bodies = [];
  probe.send = async (_url, body) => { bodies.push(JSON.parse(body)); return { status: bodies.length < 3 ? 503 : 202, body: '{}' }; };
  const message = probe.inject({ channel_id: 'phase1', text: 'retry' });
  const result = await probe.deliver(message.message_id);
  assert.deepEqual(result.map(r => r.status), [503, 503, 202]);
  assert.equal(new Set(bodies.map(b => b.eventId)).size, 1);
});

test('410 disables subscription; 413 is not retried; retries are bounded', async t => {
  for (const status of [410, 413, 503]) {
    const { probe } = fixture(t);
    await probe.rpc('events/subscribe', subscription());
    probe.send = async () => ({ status, body: '{}' });
    const message = probe.inject({ channel_id: 'phase1', text: 'delivery status' });
    const result = await probe.deliver(message.message_id);
    assert.equal(result.length, status === 503 ? 3 : 1);
    if (status === 410) assert.equal(probe.status().subscriptions[0].active, false);
  }
});

test('HMAC signature matches independent known-input computation and rejects altered bytes', () => {
  const body = '{"test":"中文"}';
  const headers = signedHeaders(secret, 'evt_test', body, 'sub_test', 1700000000);
  const expected = createHmac('sha256', Buffer.alloc(32, 7)).update('evt_test.1700000000.' + body).digest('base64');
  assert.equal(headers['webhook-signature'], 'v1,' + expected);
  assert.notEqual(headers['webhook-signature'], signedHeaders(secret, 'evt_test', body + ' ', 'sub_test', 1700000000)['webhook-signature']);
  assert.throws(() => secretKey('invalid'));
});

test('callback URL policy blocks local/private/reserved destinations', () => {
  for (const ip of ['127.0.0.1', '10.2.3.4', '169.254.169.254', '192.168.1.1', '100.64.0.1', '::1', '203.0.113.1', '224.0.0.1']) assert.equal(publicIPv4(ip), false);
  assert.equal(publicIPv4('8.8.8.8'), true);
  for (const url of ['http://example.com', 'https://user:pass@example.com', 'https://example.com:444', 'https://example.com/#fragment']) assert.throws(() => callbackURL(url));
});

test('HTTP auth isolation, modern discovery/events and protocol mismatch', async t => {
  const { probe, dir } = fixture(t);
  const config = { dir, mcpPort: 0, adminPort: 0, mcpToken: randomBytes(16).toString('hex'), adminToken: randomBytes(16).toString('hex') };
  const servers = await startServers(config, probe);
  t.after(() => servers.close());
  const mcp = `http://127.0.0.1:${servers.mcp.address().port}/mcp`;
  const admin = `http://127.0.0.1:${servers.admin.address().port}`;
  const rpc = (method, params = {}, extra = {}) => fetch(mcp, {
    method: 'POST', headers: { Authorization: `Bearer ${config.mcpToken}`, 'Content-Type': 'application/json', 'MCP-Protocol-Version': VERSION, ...extra },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params: { _meta: { 'io.modelcontextprotocol/protocolVersion': VERSION }, ...params } })
  });
  assert.equal((await fetch(mcp, { method: 'POST', body: '{}' })).status, 401);
  assert.equal((await fetch(admin + '/status', { headers: { Authorization: `Bearer ${config.mcpToken}` } })).status, 401);
  assert.equal((await rpc('server/discover')).status, 200);
  assert.equal((await (await rpc('events/list')).json()).result.events.length, 1);
  assert.equal((await rpc('events/list', {}, { 'MCP-Protocol-Version': '2025-06-18' })).status, 400);
  assert.equal((await rpc('events/list', {}, { Origin: 'https://untrusted.example' })).status, 403);
  const result = await (await rpc('events/subscribe', subscription())).json();
  assert.ok(result.result.id.startsWith('sub_'));
  const response = await fetch(admin + '/inject', { method: 'POST', headers: { Authorization: `Bearer ${config.adminToken}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ channel_id: 'phase1', text: 'http-test' }) });
  assert.equal(response.status, 202);
  const message = await response.json();
  const reply = await (await rpc('tools/call', { name: 'reply_message', arguments: { message_id: message.message_id, text: 'HTTP ACK' } })).json();
  assert.equal(reply.result.structuredContent.text, 'HTTP ACK');
  const status = await (await fetch(admin + '/status', { headers: { Authorization: `Bearer ${config.adminToken}` } })).text();
  assert.ok(!status.includes(secret));
  assert.ok(!status.includes(subscription().delivery.url));
});

test('secret rotation retains old signature briefly', async t => {
  const { probe } = fixture(t);
  await probe.rpc('events/subscribe', subscription());
  const newSecret = 'whsec_' + Buffer.alloc(32, 9).toString('base64');
  probe.send = async (_url, body, headers) => {
    const p = JSON.parse(body);
    if (p.type === 'verification') return { status: 200, body: JSON.stringify({ challenge: p.challenge }) };
    assert.equal(headers['webhook-signature'].split(' ').length, 2);
    return { status: 200, body: '{}' };
  };
  const refreshed = subscription(); refreshed.delivery.secret = newSecret;
  await probe.rpc('events/subscribe', refreshed);
  const message = probe.inject({ channel_id: 'phase1', text: 'rotation' });
  assert.equal((await probe.deliver(message.message_id))[0].accepted, true);
});
