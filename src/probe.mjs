import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID, timingSafeEqual } from 'node:crypto';
import { callbackURL, postWebhook, secretKey, signedHeaders } from './webhook.mjs';

export const VERSION = '2026-07-28';
const INFO = { name: 'dot-event-probe', version: '0.1.0' };
const objectSchema = (properties, required = Object.keys(properties)) => ({ type: 'object', properties, required, additionalProperties: false });
const string = { type: 'string', minLength: 1 };
export const EVENT = {
  name: 'probe.message.created',
  description: 'A synthetic message was injected by the local operator into a probe channel. No QQ is connected.',
  delivery: ['webhook'],
  inputSchema: objectSchema({ channel_id: string }),
  payloadSchema: objectSchema({ channel_id: string, message_id: string, text: string })
};
export const TOOLS = [
  { name: 'list_pending_messages', description: 'List message IDs in the specified probe channel that have no recorded successful reply. Read-only: does not mark, consume, delete or acknowledge messages. Call get_message for each returned ID. Can be used after an event wakeup even if the event payload is absent.', inputSchema: objectSchema({ channel_id: string }), annotations: { readOnlyHint: true, openWorldHint: false, destructiveHint: false, idempotentHint: true } },
  { name: 'get_message', description: 'Read a synthetic probe message by its message_id.', inputSchema: objectSchema({ message_id: string }), annotations: { readOnlyHint: true, openWorldHint: false, destructiveHint: false } },
  { name: 'reply_message', description: 'Record one local reply to a probe message. No external message is sent. Repeated identical calls return the original reply; a different reply for the same message is rejected.', inputSchema: objectSchema({ message_id: string, text: string }), annotations: { readOnlyHint: false, openWorldHint: false, destructiveHint: false, idempotentHint: true } }
];
export class RpcError extends Error {
  constructor(code, message, data) { super(message); this.code = code; this.data = data; }
}
const bad = message => { throw new RpcError(-32602, message); };
function fields(obj, names, max = 8192) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj) || Object.keys(obj).some(k => !names.includes(k))) bad('Unexpected arguments');
  for (const name of names) if (typeof obj[name] !== 'string' || !obj[name].trim() || obj[name].length > max) bad(`Invalid ${name}`);
}
const digest = value => createHash('sha256').update(value).digest('hex');
const same = (a, b) => typeof b === 'string' && Buffer.byteLength(a) === Buffer.byteLength(b) && timingSafeEqual(Buffer.from(a), Buffer.from(b));
const complete = result => ({ resultType: 'complete', ...result, _meta: { 'io.modelcontextprotocol/serverInfo': INFO } });
const content = data => complete({ content: [{ type: 'text', text: JSON.stringify(data) }], structuredContent: data });

export class Probe {
  constructor(dir, { send = postWebhook, sleep = ms => new Promise(r => setTimeout(r, ms)), now = () => Date.now(), event = EVENT } = {}) {
    this.event = event;
    this.dir = dir; this.send = send; this.sleep = sleep; this.now = now;
    fs.mkdirSync(dir, { recursive: true });
    this.file = path.join(dir, 'state.json');
    this.state = fs.existsSync(this.file) ? JSON.parse(fs.readFileSync(this.file, 'utf8')) : { subscriptions: {}, messages: {}, replies: {}, deliveries: [], calls: [] };
    this.verifications = new Map();
    this.pending = new Set();
  }
  save() {
    fs.writeFileSync(this.file + '.tmp', JSON.stringify(this.state, null, 2), { mode: 0o600 });
    fs.renameSync(this.file + '.tmp', this.file);
  }
  iso() { return new Date(this.now()).toISOString(); }
  active(sub) { return sub.active && Date.parse(sub.refreshBefore) > this.now(); }
  identity(p) {
    if (p.name !== this.event.name) bad('Unknown event');
    fields(p.arguments, ['channel_id'], 128);
    if (p.delivery?.mode !== 'webhook' || typeof p.delivery?.url !== 'string') bad('Webhook delivery required');
    try { callbackURL(p.delivery.url); } catch { bad('HTTPS callback on port 443 required'); }
    return 'sub_' + digest(JSON.stringify(['local-probe-owner', p.delivery.url, p.name, p.arguments.channel_id])).slice(0,32);
  }
  async subscribe(p) {
    const id = this.identity(p);
    try { secretKey(p.delivery.secret); } catch { bad('whsec_ secret must decode to 24-64 bytes'); }
    if (p.ttlMs !== undefined && p.ttlMs !== null && (!Number.isSafeInteger(p.ttlMs) || p.ttlMs <= 0)) bad('Invalid ttlMs');
    const ttl = Math.min(p.ttlMs ?? 3600000, 3600000);
    const cacheKey = digest(p.delivery.url + p.delivery.secret);
    if ((this.verifications.get(cacheKey) ?? 0) <= this.now()) {
      const challenge = randomUUID(), vid = 'verify_' + randomUUID();
      const body = JSON.stringify({ type: 'verification', challenge });
      let httpStatus = null;
      try {
        const response = await this.send(p.delivery.url, body, signedHeaders(p.delivery.secret, vid, body, id));
        httpStatus = response.status;
        if (response.status < 200 || response.status >= 300) throw new Error('callback_http_error');
        let responseBody;
        try { responseBody = JSON.parse(response.body); } catch { throw new Error('challenge_response_not_json'); }
        if (!same(challenge, responseBody.challenge)) throw new Error('challenge_failed');
      } catch (error) {
        const known = ['non_public_callback', 'dns_lookup_failed', 'callback_timeout', 'callback_http_error', 'challenge_response_not_json', 'challenge_failed'];
        const detail = known.includes(error.message) ? error.message : (/^[A-Z_0-9]+$/.test(error.code ?? '') ? error.code : 'network_error');
        this.state.callbackDiagnostics ??= [];
        this.state.callbackDiagnostics.push({ at: this.iso(), phase: 'verification', callback_host: new URL(p.delivery.url).hostname, detail, http_status: httpStatus });
        this.state.callbackDiagnostics = this.state.callbackDiagnostics.slice(-20); this.save();
        const reason = detail === 'callback_timeout' ? 'timeout' : httpStatus >= 500 ? 'http_5xx' : httpStatus >= 400 ? 'http_4xx' : 'challenge_failed';
        throw new RpcError(-32015, 'CallbackEndpointError', { reason, detail });
      }
      this.verifications.set(cacheKey, this.now() + 60000);
    }
    const previous = this.state.subscriptions[id];
    const sub = { id, name: p.name, arguments: p.arguments, url: p.delivery.url, secret: p.delivery.secret,
      refreshBefore: new Date(this.now() + ttl).toISOString(), active: true, verifiedAt: this.iso() };
    if (previous?.secret && previous.secret !== sub.secret) {
      sub.oldSecret = previous.secret; sub.rotationUntil = this.now() + 60000;
    }
    this.state.subscriptions[id] = sub; this.save();
    return complete({ id, refreshBefore: sub.refreshBefore, cursor: null, truncated: false });
  }
  async rpc(method, p = {}) {
    this.state.calls.push({ at: this.iso(), method, ...(method === 'tools/call' ? { tool: p.name } : {}) });
    this.state.calls = this.state.calls.slice(-200); this.save();
    switch (method) {
      case 'server/discover': return complete({ supportedVersions: [VERSION], capabilities: { tools: {}, events: {} }, instructions: 'Synthetic local event probe only. Read a probe message and record its reply when instructed by the user.' });
      case 'initialize': return { protocolVersion: '2025-06-18', capabilities: { tools: {} }, serverInfo: INFO, instructions: 'Tools-only legacy discovery. Events require MCP 2026-07-28 server/discover.' };
      case 'ping': return complete({});
      case 'tools/list': return complete({ tools: TOOLS });
      case 'events/list': return complete({ events: [this.event] });
      case 'events/subscribe': return this.subscribe(p);
      case 'events/unsubscribe': {
        const id = this.identity(p);
        if (this.state.subscriptions[id]) this.state.subscriptions[id].active = false;
        this.save(); return complete({});
      }
      case 'tools/call': {
        if (!TOOLS.some(t => t.name === p.name)) bad('Unknown tool');
        if (p.name === 'list_pending_messages') {
          fields(p.arguments, ['channel_id'], 128);
          const messages = Object.values(this.state.messages)
            .filter(message => message.channel_id === p.arguments.channel_id && !this.state.replies[message.message_id])
            .map(({ message_id, channel_id, created_at }) => ({ message_id, channel_id, created_at }));
          return content({ channel_id: p.arguments.channel_id, messages });
        }
        fields(p.arguments, p.name === 'get_message' ? ['message_id'] : ['message_id', 'text']);
        const message = this.state.messages[p.arguments.message_id];
        if (!message) return complete({ isError: true, content: [{ type: 'text', text: 'Unknown message_id' }] });
        if (p.name === 'get_message') return content(message);
        const existing = this.state.replies[message.message_id];
        if (existing) {
          if (existing.text !== p.arguments.text) return complete({ isError: true, content: [{ type: 'text', text: 'A different reply already exists for this message.' }] });
          return content({ ...existing, duplicate: true });
        }
        const reply = { message_id: message.message_id, text: p.arguments.text, received_at: this.iso(), source: 'mcp-tool-call' };
        this.state.replies[message.message_id] = reply; this.save();
        return content({ ...reply, duplicate: false });
      }
      default: throw new RpcError(-32601, 'Method not found');
    }
  }
  inject(args) {
    fields(args, ['channel_id', 'text']);
    const targets = Object.values(this.state.subscriptions).filter(s => this.active(s) && s.arguments.channel_id === args.channel_id);
    if (!targets.length) throw new Error('No active matching subscription; subscribe from your dot first.');
    const id = 'msg_' + randomUUID();
    const message = { message_id: id, channel_id: args.channel_id, text: args.text, event_id: 'evt_' + randomUUID(), created_at: this.iso() };
    this.state.messages[id] = message; this.save();
    return message;
  }
  async deliver(id) {
    if (this.pending.has(id)) throw new Error('Delivery already in progress');
    const message = this.state.messages[id];
    if (!message) throw new Error('Unknown message_id');
    this.pending.add(id);
    try {
      const event = { eventId: message.event_id, name: this.event.name, timestamp: message.created_at,
        data: { channel_id: message.channel_id, message_id: id, text: message.text }, cursor: null };
      const body = JSON.stringify(event);
      const payloadFile = path.join(this.dir, `${message.event_id}.payload.json`);
      fs.writeFileSync(payloadFile, body, { mode: 0o600 });
      const results = [];
      for (const sub of Object.values(this.state.subscriptions)) {
        if (!this.active(sub) || sub.arguments.channel_id !== message.channel_id) continue;
        for (let attempt = 1; attempt <= 3; attempt++) {
          if (!this.active(sub)) break;
          const headers = signedHeaders(sub.secret, message.event_id, body, sub.id);
          if (sub.oldSecret && sub.rotationUntil > this.now()) headers['webhook-signature'] += ' ' + signedHeaders(sub.oldSecret, message.event_id, body, sub.id)['webhook-signature'];
          let status = 0;
          const started_at = this.iso();
          try { status = (await this.send(sub.url, body, headers)).status; } catch { /* Redact callback URLs and secrets from evidence. */ }
          const record = { started_at, at: this.iso(), message_id: id, event_id: message.event_id, subscription_id: sub.id, attempt, status, accepted: status >= 200 && status < 300,
            payload_sha256: digest(body), payload_bytes: Buffer.byteLength(body) };
          this.state.deliveries.push(record); this.save(); results.push(record);
          if (status === 410) { sub.active = false; this.save(); }
          if (record.accepted || (status > 0 && status < 500 && status !== 429) || attempt === 3) break;
          await this.sleep(1000 * 2 ** (attempt - 1));
        }
      }
      return results;
    } finally { this.pending.delete(id); }
  }
  status() {
    return {
      server: INFO, scope: 'synthetic-probe-no-qq',
      subscriptions: Object.values(this.state.subscriptions).map(s => ({ id: s.id, channel_id: s.arguments.channel_id, active: this.active(s), refreshBefore: s.refreshBefore })),
      messages: Object.values(this.state.messages), replies: Object.values(this.state.replies),
      deliveries: this.state.deliveries, calls: this.state.calls,
      protocol_errors: this.state.protocolErrors ?? [],
      callback_diagnostics: this.state.callbackDiagnostics ?? [],
      conclusion: 'Server observations only; confirm event-triggered activity in your dot before accepting live E2E.'
    };
  }
}
