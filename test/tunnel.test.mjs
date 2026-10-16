import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { startServers } from '../src/server.mjs';
import { Probe, VERSION } from '../src/probe.mjs';
import { root } from '../src/config.mjs';

test('official tunnel-client local proxy forwards MCP2 discovery, event subscription and reply', { timeout: 45000 }, async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dot-tunnel-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const probe = new Probe(dir, { send: async (_url, body) => {
    const p = JSON.parse(body);
    return { status: 200, body: JSON.stringify(p.type === 'verification' ? { challenge: p.challenge } : {}) };
  }});
  const config = { dir, mcpPort: 0, adminPort: 0, mcpToken: randomBytes(32).toString('hex'), adminToken: randomBytes(32).toString('hex') };
  const servers = await startServers(config, probe);
  t.after(() => servers.close());
  const connection = path.join(dir, 'connection.json');
  const binary = path.join(root, '.tools', 'tunnel-client', 'tunnel-client.exe');
  assert.ok(fs.existsSync(binary), 'Official tunnel-client binary must be installed for transport test');
  const child = spawn(binary, ['dev', 'proxy', '--mcp-server-url', `http://127.0.0.1:${servers.mcp.address().port}/mcp`, '--url-file', connection, '--duration', '35s'], {
    windowsHide: true, env: { ...process.env, MCP_EXTRA_HEADERS: 'Authorization: env:PROBE_TEST_AUTH', MCP_DISCOVERY_EXTRA_HEADERS: 'Authorization: env:PROBE_TEST_AUTH', PROBE_TEST_AUTH: 'Bearer ' + config.mcpToken }
  });
  let logs = ''; child.stdout.on('data', b => logs += b); child.stderr.on('data', b => logs += b);
  const closed = new Promise(resolve => child.once('close', resolve));
  t.after(async () => { if (child.exitCode === null) child.kill(); await closed; });
  for (let i = 0; i < 150 && !fs.existsSync(connection) && child.exitCode === null; i++) await new Promise(r => setTimeout(r, 100));
  assert.ok(fs.existsSync(connection), 'Local tunnel proxy did not become ready: ' + logs.slice(-2500));
  const info = JSON.parse(fs.readFileSync(connection, 'utf8'));
  assert.ok(info.mcp_url, 'Missing mcp_url in proxy metadata');
  let id = 0;
  async function rpc(method, params = {}) {
    const response = await fetch(info.mcp_url, { method: 'POST', headers: {
      'Content-Type': 'application/json', Accept: 'application/json, text/event-stream',
      'MCP-Protocol-Version': VERSION
    }, body: JSON.stringify({ jsonrpc: '2.0', id: ++id, method,
      params: { _meta: { 'io.modelcontextprotocol/protocolVersion': VERSION }, ...params }
    }), signal: AbortSignal.timeout(10000) });
    const text = await response.text();
    assert.equal(response.status, 200, text);
    const message = JSON.parse(text.startsWith('event:') || text.startsWith('data:') ? text.split('\n').find(l => l.startsWith('data:')).slice(5).trim() : text);
    assert.ok(message.result, JSON.stringify(message));
    return message.result;
  }
  assert.deepEqual((await rpc('server/discover')).supportedVersions, [VERSION]);
  assert.equal((await rpc('events/list')).events[0].name, 'probe.message.created');
  const params = { name: 'probe.message.created', arguments: { channel_id: 'phase1' }, delivery: { mode: 'webhook', url: 'https://callback.example.com/', secret: 'whsec_' + randomBytes(32).toString('base64') } };
  assert.ok((await rpc('events/subscribe', params)).id);
  const message = probe.inject({ channel_id: 'phase1', text: 'local-tunnel-only' });
  await probe.deliver(message.message_id);
  assert.ok((await rpc('tools/list')).tools.some(tool => tool.name === 'list_pending_messages'));
  const pending = await rpc('tools/call', { name: 'list_pending_messages', arguments: { channel_id: 'phase1' } });
  assert.equal(pending.structuredContent.messages[0].message_id, message.message_id);
  assert.equal((await rpc('tools/call', { name: 'get_message', arguments: { message_id: message.message_id } })).structuredContent.text, message.text);
  assert.equal((await rpc('tools/call', { name: 'reply_message', arguments: { message_id: message.message_id, text: 'transport-ok' } })).structuredContent.text, 'transport-ok');
  assert.deepEqual((await rpc('tools/call', { name: 'list_pending_messages', arguments: { channel_id: 'phase1' } })).structuredContent.messages, []);
  await rpc('events/unsubscribe', params);
  assert.equal(probe.status().subscriptions[0].active, false);
  console.log('Local transport verified with official tunnel-client. No hosted OpenAI tunnel or dot was used in this test.');
});
