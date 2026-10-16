import fs from 'node:fs';
import path from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
import { loadConfig, root } from '../src/config.mjs';

const config = loadConfig();
const [command = 'status', argument, channel = 'phase1'] = process.argv.slice(2);
async function request(endpoint, data) {
  const response = await fetch(`http://127.0.0.1:${config.adminPort}${endpoint}`, {
    method: data ? 'POST' : 'GET', headers: { Authorization: `Bearer ${config.adminToken}`, 'Content-Type': 'application/json' },
    ...(data ? { body: JSON.stringify(data) } : {}), signal: AbortSignal.timeout(45000)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error ?? `HTTP ${response.status}`);
  return result;
}
try {
  if (command === 'setup') console.log(JSON.stringify({ config: path.join(config.dir, 'config.json'), tunnel_id: config.tunnelId, credentials: 'Local MCP/admin tokens generated; no OpenAI API key stored.' }, null, 2));
  else if (command === 'status') console.log(JSON.stringify(await request('/status'), null, 2));
  else if (command === 'inject') {
    const nonce = randomUUID();
    const message = await request('/inject', { channel_id: channel, text: argument ?? `Probe nonce: ${nonce}` });
    console.log(JSON.stringify({ ...message, expected_reply: `ACK:${message.message_id}:${message.text}` }, null, 2));
  } else if (command === 'redeliver') console.log(JSON.stringify(await request('/redeliver', { message_id: argument }), null, 2));
  else if (command === 'check') {
    const status = await request('/status');
    const message = status.messages.find(m => m.message_id === argument);
    if (!message) throw new Error('Supply an existing message_id');
    const deliveries = status.deliveries.filter(d => d.message_id === argument);
    const replies = status.replies.filter(r => r.message_id === argument);
    const expected = `ACK:${argument}:${message.text}`;
    const payloadFile = path.join(config.dir, `${message.event_id}.payload.json`);
    const payloadBytes = fs.existsSync(payloadFile) ? fs.readFileSync(payloadFile) : null;
    const observed = deliveries.some(d => d.accepted) && replies.length === 1 && replies[0].text === expected;
    const evidence = { observed_at: new Date().toISOString(), message, deliveries, replies, expected_reply: expected,
      ...(payloadBytes ? { sent_payload: JSON.parse(payloadBytes), sent_payload_sha256: createHash('sha256').update(payloadBytes).digest('hex') } : {}),
      server_chain_observed: observed, dot_activity_confirmation: 'PENDING_USER_REVIEW',
      live_e2e: 'PENDING_DOT_ACTIVITY_CONFIRMATION',
      note: 'A local tool call alone does not identify the caller as your dot. Match this message ID to event-triggered dot Activity.' };
    const file = path.join(root, 'evidence', `${argument}.json`);
    fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, JSON.stringify(evidence, null, 2));
    console.log(JSON.stringify({ ...evidence, evidence_file: file }, null, 2));
    if (!observed) process.exitCode = 2;
  } else throw new Error('Commands: setup | status | inject [text] [channel_id=phase1] | redeliver message_id | check message_id');
} catch (error) { console.error(error.message); process.exitCode = 1; }
